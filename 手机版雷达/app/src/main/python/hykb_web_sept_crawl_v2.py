# -*- coding: utf-8 -*-
"""快爆网页管线 v2：专区页(全部act链接) + 福利汇总H5(每游戏comm_id) + 修复时间解析
修复点：
  1. 时间解析锚定「活动时间」关键词后的区间，忽略页面隐藏弹窗模板（"已于..结束"）
  2. 采集每游戏的 fulihuizong 福利汇总页（comm_id 从 gameintro CDN 免签名获取）
  3. 专区页收录全部 act/huodong 链接（不只 .lb-warm-li 行）
  4. 标题归属交叉校验（防跨游戏推荐污染）
  5. 详情页失败重试（zone 通用标题活动必须拿到正文）
"""
import sys, re, json, html as H
import concurrent.futures as cf
from datetime import datetime, timezone, timedelta

import os
import sys
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _SCRIPT_DIR)  # 依赖模块与本脚本同目录（可移植）
_DATA = os.environ.get("RADAR_DATA", _SCRIPT_DIR)  # 手机端→可写外部存储；桌面→脚本目录
os.makedirs(_DATA, exist_ok=True)
os.chdir(_DATA)  # 输出文件固定落在数据目录
import config, hykb_feed
from reward_classify import reward_kind

CN = timezone(timedelta(hours=8))
# 无人值守自动化前提：当前时间必须动态获取，不允许写死
NOW = datetime.now(CN).replace(microsecond=0)
# 收录窗口（2026-09-12 用户口径）：2026年8月 ~ 今天（含窗口内已结束活动，供核对优先级）
WIN_START = datetime(2026, 8, 1, tzinfo=CN)

# 25游戏别名表（最长优先），用于校验专区页标题归属，防止跨游戏推荐污染
_HYKB_ALIAS = sorted(((a, g) for g, als in config.GAME_ALIASES.items() for a in als),
                     key=lambda t: -len(t[0]))
_HYKB_EXCLUDE = {"王者荣耀": ["王者荣耀世界"], "王者万象棋": []}

def match_game(title):
    """按标题内容重新匹配归属游戏；标题为空或无法匹配返回 None。
    书名号优先（2026-09-12）：来源标题常把专区游戏名当前缀，如
    "三角洲行动 《王者万象棋》天美联动"——活动本体在《》里，双游戏名时以
    《》内为准，避免平局误归。"""
    if not title:
        return None
    for m in re.finditer(r"《([^》]{1,25})》", title):
        inner = m.group(1)
        for a, g in _HYKB_ALIAS:
            if a in inner:
                if any(x in inner for x in _HYKB_EXCLUDE.get(g, ())):
                    continue
                return g
    for a, g in _HYKB_ALIAS:
        if a in title:
            if any(x in title for x in _HYKB_EXCLUDE.get(g, ())):
                continue
            return g
    return None

ZONE_PAGES = {
    92547: "和平精英", 101225: "使命召唤手游", 151743: "三角洲行动", 63681: "穿越火线枪战王者",
    60881: "王者荣耀", 148499: "王者万象棋", 105882: "洛克王国：世界", 136127: "暗区突围",
    114071: "金铲铲之战", 153460: "元梦之星", 56633: "火影忍者手游", 131733: "无畏契约",
    96012: "部落冲突", 86615: "QQ飞车", 118069: "妄想山海", 96988: "逆战：未来", 176451: "失控进化",
}

# 快爆全站通用绑定弹窗固定文案（2026-09-12 实证：每个 newsign2 页都有）：
# "部分游戏奖励以Q币形式发放，安卓微信区服的玩家也可以在游戏中使用Q币支付获得游戏奖励"
# ——这是绑定QQ弹窗的说明文字，不是活动奖池。不剔除会让所有快爆签到页
# "看起来有Q币"（逆战"首充助力金"误判真奖励的根源，与4399共享领奖弹窗同源）。
_HYKB_BOILER = ("部分游戏奖励以Q币形式发放，安卓微信区服的玩家也可以在游戏中使用Q币支付获得游戏奖励",)

def get(url, timeout=20):
    req = config.urllib.request.Request(url, headers={"User-Agent": hykb_feed.UA_IOS})
    raw = config.urllib.request.urlopen(req, timeout=timeout).read()
    if raw[:2] == b"\x1f\x8b":
        import gzip
        raw = gzip.decompress(raw)
    return raw.decode("utf-8", "replace")

def vis(h):
    h = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", h, flags=re.S | re.I)
    t = H.unescape(re.sub(r"<[^>]+>", " ", h))
    return re.sub(r"\s+", " ", t)

# ---------------- 时间解析 v2 ----------------
def _mk(y, mo, d, h, mi):
    try:
        y = int(y or 2026); mo = int(mo); d = int(d)
        h = int(h) if h else 0
        mi = int(mi) if mi else 0
        if h >= 24: h, mi = 23, 59
        return datetime(y, mo, d, h, mi, tzinfo=CN)
    except Exception:
        return None

D = r"(?:(20\d{2})\s*年)?\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日(?:\s*(\d{1,2})\s*[点时:：]\s*(\d{1,2})?)?"
RANGE_KW = re.compile(r"(?:活动时间|福利时间|活动起止|参与时间|开奖时间)[^0-9]{0,12}" + D +
                      r"\s*[~—–\-至到]{1,2}\s*" + D)
SINGLE_KW = re.compile(r"(?:活动时间|福利时间|开始时间)[^0-9]{0,12}" + D)
DOT_RANGE = re.compile(r"(20\d{2})[.\-/](\d{1,2})[.\-/](\d{1,2})\s*[~—–\-至]{1,2}\s*(20\d{2})[.\-/](\d{1,2})[.\-/](\d{1,2})")

def parse_times_v2(vis_text, raw_html=""):
    # 0) fulihuizong 点分日期区间（2026.09.10-2026.11.09）
    m = DOT_RANGE.search(vis_text)
    if m:
        s = _mk(m.group(1), m.group(2), m.group(3), None, None)
        e = _mk(m.group(4), m.group(5), m.group(6), None, None)
        if s: return s, e
    # 1) 「活动时间」关键词后紧跟的区间（最可信）
    m = RANGE_KW.search(vis_text)
    if m:
        s = _mk(m.group(1), m.group(2), m.group(3), m.group(4), m.group(5))
        e = _mk(m.group(6), m.group(7), m.group(8), m.group(9), m.group(10))
        if s:
            if e and e < s:
                e = e.replace(year=e.year + 1)
            return s, e
    # 2) 关键词后单日期 = 开始
    m = SINGLE_KW.search(vis_text)
    if m:
        s = _mk(m.group(1), m.group(2), m.group(3), m.group(4), m.group(5))
        if s: return s, None
    # 3) 兜底：页面里的裸区间
    m = re.search(D + r"\s*[~—–\-至到]{1,2}\s*" + D, vis_text)
    if m:
        s = _mk(m.group(1), m.group(2), m.group(3), m.group(4), m.group(5))
        e = _mk(m.group(6), m.group(7), m.group(8), m.group(9), m.group(10))
        if s: return s, e
    return None, None

# ---------------- 采集 ----------------
def game_intro_cid(gid):
    """gameintro CDN -> fulihuizong comm_id"""
    try:
        b = get(f"https://api.3839app.com/cdn/android/gameintro-home-1546-id-{gid}-packag--level-2.htm")
        m = re.search(r'fulihuizong[^"\']{0,60}comm_id=(\d+)', b)
        return m.group(1) if m else None
    except Exception:
        return None

def fuli_items(cid):
    """福利汇总页 -> [{title, desc, time_text, url}]"""
    out = []
    try:
        b = get(f"https://huodong3.3839.com/n/hykb/fulihuizong/index.php?comm_id={cid}&detail=1")
    except Exception:
        return out
    # A) 横幅活动列表（<div class="list-act">：li>a[href] + div.tit标题 + p.info时间）。
    # 2026-09-12 用户实证：王者万象棋 comm_id=400 页头部横幅挂着
    # "抢先下载瓜分50万Q币，前5万名必得6Q币"（osgame页），旧版只解析em礼包
    # 列表导致整条漏抓。
    seen_urls = set()
    for m in re.finditer(
            r'<a href="(https?://(?:act|huodong\d?)\.3839\.com[^"]+)"[^>]*>\s*'
            r'<div class="img">.*?<div class="tit">([^<]+)</div>\s*'
            r'<p class="info">([^<]+)</p>', b, re.S):
        url = m.group(1).strip()
        if url in seen_urls:
            continue
        seen_urls.add(url)
        out.append({"title": H.unescape(m.group(2)).strip(), "desc": "",
                    "time_text": m.group(3).strip(),
                    "url": url, "src": "fulihuizong_act"})
    # B) em 礼包列表。URL 归属修复：旧版取"em块内第一个URL"，但 li 的 <a href>
    # 在 <em> 之前打开，块内第一个URL实际是后续内容（横幅区/下一li）的链接，
    # 会错挂到无关条目上（战令条目挂上6Q币活动链接即此bug）。改为取"上一个em
    # 到当前em之间"最近的 <a href>（= 本 li 自己的锚点），取不到就无URL。
    ems = list(re.finditer(r"<em>", b))
    for i, em in enumerate(ems):
        seg_end = ems[i + 1].start() if i + 1 < len(ems) else len(b)
        ch = b[em.end():seg_end]
        m = re.match(r"([^<]{2,60})</em>\s*<p>([^<]{0,140})", ch)
        if not m:
            continue
        title = H.unescape(m.group(1)).strip()
        desc = H.unescape(m.group(2)).strip()
        seg = vis(ch[:2500])
        prev_pos = ems[i - 1].start() if i > 0 else 0
        anchors = re.findall(
            r'<a href="(https?://(?:act|huodong\d?)\.3839\.com[^"]+)"',
            b[prev_pos:em.start()])
        url = anchors[-1].strip() if anchors else None
        if url in seen_urls:
            url = None
        if url:
            seen_urls.add(url)
        dm = DOT_RANGE.search(seg)
        out.append({"title": title, "desc": desc,
                    "time_text": dm.group(0) if dm else "",
                    "url": url, "src": "fulihuizong"})
    return out

def main():
    rows, seen = [], set()

    def add(game, title, url, desc, s, e, src):
        """追加一行并返回该行 dict —— 分类必须写回自己的行。
        旧版：URL 重复时 add() 静默跳过，但 enrich 仍写 rows[-1]，把分类
        写到别的活动行上（并发下进一步错位），导致"标题含Q币却判noise"。
        """
        if not url or url in seen:
            return None
        seen.add(url)
        row = {"game": game, "title": title[:80], "url": url,
               "desc": desc[:200], "src": src,
               "start": s.isoformat() if s else None,
               "end": e.isoformat() if e else None}
        rows.append(row)
        return row

    def enrich(game, title, url, desc, src, inline_time=""):
        # 归属校验：标题能明确匹配某款游戏时以标题为准（防 fuli/zone 把
        # 跨游戏推荐活动记到专区游戏名下，如"《王者万象棋》天美联动"挂在三角洲）
        mg = match_game(title or "")
        if mg:
            game = mg
        # 快爆详情页可能超时或 5xx，重试 2 次（zone 通用标题活动尤其依赖详情页正文）
        v = ""
        for attempt in range(3):
            try:
                raw = get(url, timeout=20)
                v = vis(raw)
                break
            except Exception:
                if attempt == 2:
                    v = ""
                else:
                    import time
                    time.sleep(1.0)
        # 列表页结构化时间（如横幅 p.info "2026.09.09-2026.10.10"）优先：
        # 详情页正文的时间语句更杂（如"Q币发放：10.10 23:59"单边日期），
        # 会把结束日误当开始日——抢先下载50万Q币条目 start=10-10 被窗口
        # 过滤丢弃即此bug（2026-09-12 实证）。
        mi = DOT_RANGE.search(inline_time or "")
        if mi:
            s = _mk(mi.group(1), mi.group(2), mi.group(3), None, None)
            e = _mk(mi.group(4), mi.group(5), mi.group(6), None, None)
            if not s:
                s = e = None
        else:
            s, e = parse_times_v2(v + (" " + inline_time if inline_time else ""))
            if not s and inline_time:
                s, e = parse_times_v2(inline_time)
        # 标题兜底：详情页 <title>
        if (not title or len(title.strip()) < 4) and v:
            try:
                raw = get(url, timeout=15)
                m = re.search(r'<title[^>]*>([^<]+)</title>', raw, re.I | re.S)
                if m:
                    title = H.unescape(re.sub(r'\s+', ' ', m.group(1))).strip()[:80]
            except Exception:
                pass
        # 标题兜底/丰富后再归游戏一次：列表页横幅标题常无游戏名（如"抢先下载
        # 瓜分50万Q币"挂在王者荣耀名下），详情页<title>才含《王者万象棋》
        mg = match_game(title or "")
        if mg:
            game = mg
        # 分类证据 = 活动规则/奖池正文为主（4000字），标题仅兜底；
        # 先剔除快爆全站弹窗模板句（见 _HYKB_BOILER 注释）
        v_cls = v
        for w in _HYKB_BOILER:
            v_cls = v_cls.replace(w, " ")
        # 剔除快爆全站「获奖记录」历史留言墙：领奖记录组件会把历史中奖条目
        # （如"获奖记录 Q币 2024-06-28 18:30 去领取"）混进可见文本，给页面
        # 注入假Q币证据——天美联动页被误判真奖励的根源（与4399获奖留言墙同源）。
        # 注意"查看活动获奖记录"按钮也含该词，因此只删后面真跟时间戳的墙条目，
        # 且只删片段不截断其后正文（页面隐藏弹窗与规则交错，不能一刀切）。
        while True:
            mw = None
            for mm in re.finditer(r"获奖记录", v_cls):
                if re.search(r"20\d{2}-\d{2}-\d{2}", v_cls[mm.end():mm.end() + 200]):
                    mw = mm
                    break
            if mw is None:
                break
            seg_end = v_cls.find("去领取", mw.start())
            if seg_end == -1 or seg_end - mw.start() > 300:
                seg_end = mw.end() + 200
            v_cls = v_cls[:mw.start()] + " " + v_cls[seg_end + 3:]
        kind, label = reward_kind(title, desc + " " + v_cls[:4000])
        row = add(game, title, url, desc, s, e, src)
        if row is not None:
            row["kind"], row["reward"] = kind, label

    # 1) 专区页
    def zone_job(args):
        gid, game = args
        out = []
        try:
            html = get(f"https://www.3839.com/a/{gid}.htm")
        except Exception:
            return out
        # 全部 act 链接
        urls = sorted(set(re.findall(r'https?://(?:act|huodong\d?)\.3839\.com[^\s"\'<>\\)]+', html)))
        # parse_zona 提供标题
        titled = {r["url"]: r["title"] for r in hykb_feed.parse_zona(html, gid, game)}
        for u in urls:
            if re.search(r"jinhaitun|dsvote|indiegamepd|kbgameChannel", u):  # 平台级噪音
                continue
            t = titled.get(u, "")
            # 专区页常有跨游戏推荐广告（如王者荣耀页推王者万象棋），按标题重新归游戏
            mg = match_game(t) if t else None
            out.append((gid, mg or game, t, u))
        return out

    zone_tasks = []
    with cf.ThreadPoolExecutor(6) as ex:
        for res in ex.map(zone_job, list(ZONE_PAGES.items())):
            zone_tasks.extend(res)

    # 2) 福利汇总页
    fuli_tasks = []
    with cf.ThreadPoolExecutor(6) as ex:
        cid_map = dict(zip([g for g, _ in ZONE_PAGES.items()],
                           list(ex.map(lambda kv: game_intro_cid(kv[0]), ZONE_PAGES.items()))))
    for gid, cid in cid_map.items():
        game = ZONE_PAGES[gid]
        if not cid: continue
        for it in fuli_items(cid):
            if it["url"] and "sqly" in it["url"]:  # 授权页噪音
                it["url"] = None
            fuli_tasks.append((gid, game, it))

    # 3) 合并任务并并发详情解析
    # fuli 任务必须先于 zone：同一活动 URL 两边都有时，先到先得（add 按 URL
    # 去重）。fuli 横幅带结构化时间（"2026.09.09-2026.10.10"），zone 只有无
    # 时间的裸链接——fuli 先入队才不会输给 zone 后被详情页杂乱时间语句误解析
    # （抢先下载50万Q币 start 被解析成结束日 10-10 而遭窗口过滤，即此bug）。
    jobs = []
    for gid, game, it in fuli_tasks:
        jobs.append((game, it["title"], it["url"], it["desc"], "fuli", it["time_text"]))
    for gid, game, title, u in zone_tasks:
        jobs.append((game, title or "", u, "", "zone", ""))

    with cf.ThreadPoolExecutor(8) as ex:
        futs = [ex.submit(enrich, *j) for j in jobs if j[2]]
        for f in futs: f.result()

    json.dump(rows, open("hykb_web_sept_v2.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    ok = [r for r in rows if r["start"]]
    print(f"total={len(rows)} with_time={len(ok)}")
    for r in rows:
        if r["start"]:
            print(f'  {r["game"]:<9} {r["src"]:<5} {(r["start"] or "?")[:16]}~{(r["end"] or "未写")[:16]} {r["reward"] or "noise"} | {r["title"][:36]}')

    # 输出渠道分组表，与4399/OPPO格式一致
    # 窗口口径（2026-09-12）：2026-08-01 ~ 今天；已开始 + 窗口期内存活（含已结束）
    sept_real, aug_real_running, sept_noise = [], [], []
    for r in rows:
        s = parse_iso(r.get("start"))
        e = parse_iso(r.get("end"))
        if not s or s > NOW:
            continue
        if e and e < WIN_START:
            continue
        if r.get("kind") == "real":
            if s.month >= 9:
                sept_real.append(r)
            else:
                aug_real_running.append(r)
        else:
            sept_noise.append(r)
    json.dump({"sept_real": sept_real, "aug_real_running": aug_real_running,
               "sept_noise": sept_noise},
              open("_hykb_table_v3.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print(f"_hykb_table_v3.json -> A={len(sept_real)} B={len(aug_real_running)} noise={len(sept_noise)}")


def parse_iso(s):
    if not s: return None
    try:
        return datetime.fromisoformat(s)
    except Exception:
        return None

if __name__ == "__main__":
    main()
