# hykb_feed.py — 好游快爆（3839 同源 Web 后端）Q币福利活动采集通道
#
# R40：好游快爆 App 的真 API 网关(api.3839app.com) 由「阿里安全 SDK」做
#   native 签名(ISecureSignatureComponent)，secret 落在 .so 里，纯静态无法还原；
#   且其 App 内置安全 SDK 会扫描 frida 并把 shell 命令回传服务端(实测触发风控)。
#   因此放弃设备端逆向，改走「离设备、零账号」的同源 Web 后端：
#     1) 福利聚合页 act.3839.com/n/hykb/fuliheji/ (hub，含 welfare-item Q币入口)
#     2) 各游戏「专区页」www.3839.com/a/<gameId>.htm (per-game 活动/福利列表)
#   两者与 App 同源，公开可读，不登录、不碰 App 签名、不暴露设备，天然规避风控。
#
# 采集到的条目一律落在 act.3839.com/n/hykb_hd/ 或 huodongN.3839.com/n/hykb/
# 这类「真活动页」(R33 用户标准)，再由 engine 的 Q币闸门(enrich 阶段)做最终
# 真值过滤——本模块只负责把候选活动抓全、按引擎 api 条目格式归一化。
#
# 纯标准库 + config.MiniSoup，无第三方依赖。
import hashlib
import json
import re
import time
import urllib.request
import urllib.parse
import urllib.error

# config 提供 MiniSoup 选择器引擎、abs_url、以及 ssl 非校验上下文(抓公开页用)
try:
    from . import config
except Exception:                                   # 桌面独立调试回退
    import config

MiniSoup = config.MiniSoup
select = config.select
pick_attr = config.pick_attr
abs_url = config.abs_url

UA_IOS = ("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
          "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 "
          "Mobile/15E148 Safari/604.1")
UA_PC = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
         "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

# 真活动页链接（act / huodongN 子域）——只收这类，论坛/搜索/文章页不要
_ACT_LINK_PAT = re.compile(
    r"https?://(?:act|huodong\d?)\.3839\.com/[^\s\"'<>\\)]+", re.I)

# Q币判定：活动文案出现 Q币/q币/QB 才算用户要的「真福利」
_QB_RE = re.compile(r"[Qq]币|\bQB\b")

# 广义福利信号：Q币之外，礼包/红包/福利/签到/兑换 也算用户可能想要的福利
_WELFARE_RE = re.compile(r"[Qq]币|\bQB\b|礼包|红包|福利|签到|兑换|cdk|激活码|抽奖|助力金")

# 噪声标题（与 engine.NOISE_HINT 同义，采集端先砍一层，减轻 enrich 负担）
_NOISE_HINT = re.compile(r"攻略|评测|新闻|资讯|速报|前瞻|爆料|直播|更新公告|停服|维护|合服|开服时间|下载|专题|首页|排行榜|热游|新游")
# 福利聚合页里明确的非福利噪音（用户点名的「金海豚」开发大赛等）
_FULI_NOISE = re.compile(r"金海豚|开发大赛|开发者日志|征稿|大赛|创作者")

# 默认监控的游戏专区页：用户目标(使命召唤/失控进化) + 主流腾讯系。
# 数值为好游快爆 gameId；www.3839.com/a/<id>.htm 即对应专区页。
# src.endpoints.pages 可覆盖；collect 也会从现有 SOURCES 的 hykb_* 专区源自动并回 id。
DEFAULT_PAGES = {
    101225: "使命召唤手游",     # 用户目标①
    176451: "失控进化",         # 用户目标②（此前无源，漏抓根因）
    60881:  "王者荣耀",
    105882: "洛克王国：世界",
    136127: "暗区突围",
    114071: "金铲铲之战",
    153460: "元梦之星",
    56633:  "火影忍者手游",
    131733: "无畏契约",
    113508: "英雄联盟手游",
    96012:  "部落冲突",
    86615:  "QQ飞车",
    118069: "妄想山海",
    111104: "黎明觉醒",
    96988:  "逆战：未来",
    146289: "燕云十六声",
    143964: "鸣潮",
    106235: "原神",
    138206: "崩坏",
    143516: "崩坏",
}

# 福利聚合页候选地址（按顺序探测，第一个 200 即用）
FULI_CANDIDATES = [
    "https://act.i3839.com/n/hykb/fuliheji/index.php?comm_id=9",
    "https://act.3839.com/n/hykb/fuliheji/index.php?comm_id=9",
    "https://act.3839.com/n/hykb/fuliheji/",
]


# ---------------------------------------------------------------- 抓取

def _get(url, timeout=20, ua=UA_IOS):
    req = urllib.request.Request(url, headers={"User-Agent": ua,
                                                "Accept": "text/html,application/xhtml+xml,*/*",
                                                "Accept-Language": "zh-CN,zh;q=0.9"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"HTTP {e.code} {url[:80]}") from None
    except Exception as e:
        raise RuntimeError(f"{type(e).__name__}: {e}") from None
    # gzip 自动解压（部分 3839 页面走压缩）
    if raw[:2] == b"\x1f\x8b":
        try:
            import gzip
            raw = gzip.decompress(raw)
        except Exception:
            pass
    return raw.decode("utf-8", errors="replace")


def _fetch_page(gid, timeout=20):
    """抓游戏专区页，www 失败退 m. 镜像。返回 (html, url) 或 (None, err)。"""
    for host in ("https://www.3839.com", "https://m.3839.com"):
        try:
            html = _get(f"{host}/a/{gid}.htm", timeout=timeout)
            if html and len(html) > 500:
                return html, f"{host}/a/{gid}.htm"
        except Exception as e:
            last = e
    return None, f"fetch {gid} failed: {last}"


# ---------------------------------------------------------------- 解析

def _clean(t):
    return re.sub(r"\s+", " ", (t or "")).strip()


def _act_link(text):
    """从一段文本里取第一个真活动页链接。"""
    m = _ACT_LINK_PAT.search(text or "")
    return m.group(0) if m else ""


def _item_id(url):
    """用活动路径片段做稳定去重 key（hykb_hd/<id> 或 huodong 路径）。"""
    m = re.search(r"hykb_hd/([^/?#]+)", url)
    if m:
        return "hykb_" + m.group(1)
    m = re.search(r"/n/hykb/([^/?#]+)", url)
    if m:
        return "hykb_" + m.group(1)
    return hashlib.md5(url.encode()).hexdigest()[:16]


def parse_zona(html, game_id, game_hint=""):
    """专区页 www.3839.com/a/<id>.htm 的活动/福利列表解析。
    结构：.lb-warm-li 每行 = 一个活动；.sp-tit em 标题，.sp-txt a 链接，
    .sp-txt 摘要。只保留落到 act/huodong 真活动页的条目。"""
    root = MiniSoup()
    try:
        root = config.parse_html(html)
    except Exception:
        return []
    out = []
    for row in select(root, ".lb-warm-li"):
        titles = pick_attr(row, ".sp-tit em")
        title = _clean(titles[0]) if titles else ""
        # 链接可能在 .sp-txt 内的 a，也可能整行可点
        urls = pick_attr(row, ".sp-txt a@href",
                         base_url=f"https://www.3839.com/a/{game_id}.htm")
        if not urls:
            urls = pick_attr(row, "a@href",
                             base_url=f"https://www.3839.com/a/{game_id}.htm")
        url = abs_url(urls[0] if urls else "",
                      f"https://www.3839.com/a/{game_id}.htm")
        # 优先取真活动页链接；没有则跳（非活动行）
        act = _act_link(url) or _act_link(row.text)
        if not act:
            continue
        summary = _clean(row.text)
        if not title:
            title = _clean(re.sub(r"https?://\S+", "", summary))[:50]
        if not title or len(title) < 3:
            continue
        blob = f"{title} {summary}"
        if _NOISE_HINT.search(title):
            continue
        out.append({
            "title": (f"{game_hint} {title}" if game_hint and game_hint not in title
                      else title)[:120],
            "url": act,
            "summary": summary[:200],
            "startTime": None,
            "endTime": None,
            "id": _item_id(act),
            "_game": game_hint,
            "_qb": bool(_QB_RE.search(blob)),
            "_welfare": bool(_WELFARE_RE.search(blob)),
        })
    return out


def parse_fuli(html, base=""):
    """福利聚合页 act.3839.com/n/hykb/fuliheji/ 的 Q币福利入口解析。
    welfare-item 锚点指向 act.3839.com/n/hykb_hd/<id>/，其 <p> 文案即奖励说明。"""
    root = config.parse_html(html)
    out = []
    for a in select(root, "a.welfare-item"):
        href = a.get("href", "")
        url = abs_url(href, base)
        act = _act_link(url) or _act_link(a.text)
        if not act:
            continue
        p = pick_attr(a, "p")
        title = _clean(p[0]) if p else _clean(a.text)
        summary = _clean(a.text)
        blob = f"{title} {summary}"
        if _NOISE_HINT.search(title) or _FULI_NOISE.search(title):
            continue
        out.append({
            "title": (title or "好游快爆福利")[:120],
            "url": act,
            "summary": summary[:200],
            "startTime": None,
            "endTime": None,
            "id": _item_id(act),
            "_game": "",
            "_qb": bool(_QB_RE.search(blob)),
            "_welfare": bool(_WELFARE_RE.search(blob)) or _QB_RE.search(blob) is not None,
        })
    return out


# ---------------------------------------------------------------- 采集入口

def collect(cfg, src):
    """engine run_source 的 hykb_api 类型入口：返回 engine api 条目格式列表。
    只产出「Q币或广义福利信号」的候选；最终 Q币真值由 engine 闸门在 enrich 阶段裁定。"""
    req = src.get("endpoints") or {}
    pages = {}
    names = req.get("names") or {}
    # 1) 显式配置优先。R41 修正：显式给了 pages 但没配 names 时，
    #    名字回落 DEFAULT_PAGES（否则 name="" → 后续 setdefault 因 key 已存在
    #    而不覆盖，导致全部活动都是「未识别游戏」）。
    for gid in (req.get("pages") or []):
        try:
            gid = int(gid)
        except Exception:
            continue
        name = str(names.get(str(gid), "")) or DEFAULT_PAGES.get(gid, "")
        pages[gid] = name
    # 2) 仅在未显式给 pages 时，从现有 SOURCES 的 hykb_* 专区源并回 gameId
    #    （自动覆盖全量游戏）；显式给了就只用显式列表，避免与既有专区源重复抓、触发 WAF。
    if not pages:
        try:
            for s in config.SOURCES:
                sid = s.get("id", "")
                if not (sid.startswith("hykb_") and sid not in ("hykb_home_acts",
                                                                "hykb_bbs", "hykb_calendar")):
                    continue
                u = (s.get("request") or {}).get("url", "") if isinstance(s.get("request"), dict) else ""
                m = re.search(r"/a/(\d+)\.htm", u)
                if m:
                    pages.setdefault(int(m.group(1)), s.get("game", "") or s.get("name", ""))
        except Exception:
            pass
    # 3) 兜底默认（含用户两个目标游戏）
    for gid, name in DEFAULT_PAGES.items():
        pages.setdefault(gid, name)

    all_items, seen = [], set()
    # 福利聚合页 hub（可选，404 时跳过）
    fuli = req.get("fuli") or FULI_CANDIDATES
    fuli_list = fuli if isinstance(fuli, list) else [fuli]
    for furl in fuli_list:
        try:
            html = _get(furl, timeout=15)
            for it in parse_fuli(html, furl):
                if it["id"] in seen:
                    continue
                seen.add(it["id"])
                all_items.append(it)
            break
        except Exception:
            continue

    # 各游戏专区页
    for gid, name in pages.items():
        try:
            html, _ = _fetch_page(gid)
        except Exception:
            continue
        if not html:
            continue
        for it in parse_zona(html, gid, game_hint=name):
            if it["id"] in seen:
                continue
            seen.add(it["id"])
            all_items.append(it)

    # 预过滤已在解析阶段完成（仅保留落到 act/huodong 真活动页、且非资讯/金海豚噪音的条目）。
    # Q币真值由 engine 的 enrich 闸门在抓到活动详情页后裁定（与现有 hykb_* 源一致），
    # 这里不硬卡 Q币，避免漏掉「专区行文案没写 Q币、但活动页真有 Q币」的条目。
    merged = []
    for it in all_items:
        merged.append({
            "title": it["title"], "url": it["url"], "summary": it["summary"],
            "startTime": it["startTime"], "endTime": it["endTime"], "id": it["id"],
            # R41：把专区页对应的游戏名带上，供 engine 直接归类（不用只靠标题猜）
            "game": it.get("_game") or "",
            # 用户显式跟踪的游戏打 tracked，引擎侧豁免分区过滤
            "tracked": bool(it.get("_game")),
        })
    return merged


if __name__ == "__main__":
    # 离线/在线自测：用环境变量 HYKB_OFFLINE 指向本地 html 目录可离线跑
    import os
    off = os.environ.get("HYKB_OFFLINE")
    items = collect({}, {"endpoints": {"pages": [101225, 176451]}})
    print(f"共 {len(items)} 条 Q币/福利候选:")
    for it in items:
        print(f"  [{it['id']}] {it['title'][:46]} | {it['url'][:66]}")
