# -*- coding: utf-8 -*-
"""4399游戏盒 九月活动采集/过滤 v2
数据源: mapi.yxhapi.com/android/box/other/v1.0/huodong-all.html（无签名, 原生 stime/etime）
v2 修复点（对应 2026-09-11 晚纰漏诊断）:
  1. 游戏别名最长匹配优先 —— 防《王者荣耀世界》《王者万象棋》标题被误归"王者荣耀"
  2. 输出补「8月开始仍在进行」B组（与快爆表结构对齐, 金铲铲之战不再整组消失）
  3. 奖励判定升级: 标题噪音但含"赢好礼/奖励/礼包"等模糊词的候选, 抓详情页正文复判
  4. reward_classify 按用户2026-09-11重申口径：仅 现金/Q币/实物硬件 三类，京东卡等不扩宽
  5. stime=上架时间≠活动开始时间（CODM崩坏3联动实证08-25上架/09-10开始）：
     候选条目抓详情页以「活动时间」覆写，再按校正后时间分组
用法: python 4399_sept_crawl_v2.py   (刷新数据并生成 _4399_sept_v2.json)
"""
import re, json, sys, gzip
import urllib.request
import concurrent.futures as cf
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone, timedelta

import os
import sys
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _SCRIPT_DIR)  # 依赖模块与本脚本同目录（可移植）
_DATA = os.environ.get("RADAR_DATA", _SCRIPT_DIR)  # 手机端→可写外部存储；桌面→脚本目录
os.makedirs(_DATA, exist_ok=True)
os.chdir(_DATA)  # 输出文件固定落在数据目录
from reward_classify import reward_kind, matched_noise, title_noise

CN = timezone(timedelta(hours=8))
# 无人值守自动化前提：当前时间必须动态获取，不允许写死
NOW = datetime.now(CN).replace(microsecond=0)
# 收录窗口（2026-09-12 用户口径）：活动链接时间范围扩宽到 2026年8月 ~ 今天。
# 判定：已开始（start ≤ 今天）且窗口期内存活（end ≥ 2026-08-01，含已结束的8月活动）。
WIN_START = datetime(2026, 8, 1, tzinfo=CN)
API = "https://mapi.yxhapi.com/android/box/other/v1.0/huodong-all.html"

# 25款腾讯游戏：别名按长度降序匹配（最长优先）
GAMES = {
    "王者荣耀":       ["王者荣耀"],
    "和平精英":       ["和平精英"],
    "使命召唤手游":   ["使命召唤手游", "使命召唤", "CODM"],
    "暗区突围":       ["暗区突围"],
    "三角洲行动":     ["三角洲行动"],
    "无畏契约":       ["无畏契约手游", "无畏契约"],
    "地下城与勇士：起源": ["地下城与勇士", "DNF手游", "DNF"],
    "穿越火线枪战王者": ["穿越火线枪战王者", "穿越火线", "CF手游"],
    "金铲铲之战":     ["金铲铲之战", "金铲铲"],
    "王者万象棋":     ["王者万象棋"],
    "QQ飞车":         ["QQ飞车", "qq飞车"],
    "元梦之星":       ["元梦之星"],
    "妄想山海":       ["妄想山海"],
    "洛克王国：世界": ["洛克王国"],
    "逆战：未来":     ["逆战"],
    "失控进化":       ["失控进化"],
    "部落冲突":       ["部落冲突"],
    "火影忍者手游":   ["火影忍者手游", "火影忍者"],
    "荒野乱斗":       ["荒野乱斗"],
    "天天酷跑":       ["天天酷跑"],
    "卡厄思梦境":     ["卡厄思梦境"],
    "冒险岛：枫之传说": ["冒险岛"],
    "完美世界":       ["完美世界"],
    "天龙八部手游":   ["天龙八部手游"],
    "新天龙八部手游": ["新天龙八部"],
}
ALIAS = sorted(((a, g) for g, als in GAMES.items() for a in als),
               key=lambda t: -len(t[0]))

# 排除短语：标题含这些时不得归入该游戏（如《王者荣耀世界》是另一款游戏）
GAME_EXCLUDE = {"王者荣耀": ["王者荣耀世界"]}

def match_game(title):
    for a, g in ALIAS:          # 最长别名优先
        if a in title:
            if any(x in title for x in GAME_EXCLUDE.get(g, ())):
                continue        # 命中排除短语（王者荣耀世界≠王者荣耀）
            return g
    return None

def get(url, timeout=15):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Linux; Android 13)"})
    raw = urllib.request.urlopen(req, timeout=timeout).read()
    if raw[:2] == b"\x1f\x8b":
        raw = gzip.decompress(raw)
    return raw.decode("utf-8", "replace")

def fetch_one(p):
    d = json.loads(get(f"{API}?p={p}"))
    r = d.get("result") or {}
    return r.get("data") or [], r

def fetch_all():
    """断点续传式游标翻页: 异常时从最后一个成功游标继续, 直到 more=0 走完整链。
    (服务器链是确定性的, 实测372页可走通; 之前丢失74条是链被偶发异常中断所致)"""
    def norm(it):
        u = it.get("url") or it.get("pc_url") or ""
        if not u and it.get("id"):
            u = f"https://a.haohaowan.net/yxh-huodong-id-{it['id']}.html"
        stime = datetime.fromtimestamp(int(it["stime"]), CN).strftime("%m-%d %H:%M:%S") if it.get("stime") else ""
        return {
            "title": it.get("title", ""),
            "desc": it.get("description", "") or it.get("desc", "") or "",
            # stime = API 上架时间（T0 源头痕迹），独立字段落表，任何后续校对不得修改
            "stime": stime,
            "start": stime,
            "end": datetime.fromtimestamp(int(it["etime"]), CN).strftime("%m-%d %H:%M:%S") if it.get("etime") else "",
            "url": u,
        }
    out, seen_ids = [], set()
    cursor, errors, guard = None, 0, 0
    reached_end = False
    import time
    while not reached_end and guard < 1500:
        guard += 1
        qs = f"?startKey={cursor}" if cursor else ""
        try:
            r = json.loads(get(API + qs)).get("result") or {}
            errors = 0
        except Exception:
            errors += 1
            if errors > 8:           # 连续8次失败才放弃
                break
            time.sleep(1.0)
            continue
        data = r.get("data") or []
        for it in data:
            if it.get("stime") and it.get("id") and it["id"] not in seen_ids:
                seen_ids.add(it["id"])
                out.append(it)
        cursor = r.get("startKey")
        if not cursor or not r.get("more") or not data:
            reached_end = True
    print(f"  chain: pages={guard} items={len(out)} reached_end={reached_end}")

    # 快照合并兜底: 服务端游标链有固有的重复页(372页仅297唯一),
    # 且列表按utime动态排序、不同时刻游标链丢失的条目不同 ——
    # 因此与上一份本地快照做并集, 是补全的唯一可靠手段。
    import os
    SNAP = "_4399_sept.json"
    if os.path.exists(SNAP):
        try:
            old = json.load(open(SNAP, encoding="utf-8"))
            have = {x["title"] for x in out}
            back = 0
            for o in old:
                if o["title"] not in have:
                    # 反推 unix -> MM-DD HH:MM 无法逆推id, 直接沿用旧快照字段
                    out.append({"id": None, "title": o["title"],
                                "description": o.get("desc", ""),
                                "stime": None, "etime": None,
                                "_old_start": o["start"], "_old_end": o["end"],
                                "_old_url": o["url"]})
                    have.add(o["title"])
                    back += 1
            print(f"  snapshot merge: +{back}")
        except Exception as e:
            print("  snapshot merge failed:", e)

    def norm(it):
        if it.get("_old_url"):       # 来自旧快照
            return {"title": it["title"], "desc": it.get("description", ""),
                    "stime": it["_old_start"],
                    "start": it["_old_start"], "end": it["_old_end"],
                    "url": it["_old_url"]}
        u = it.get("url") or it.get("pc_url") or ""
        if not u and it.get("id"):
            u = f"https://a.haohaowan.net/yxh-huodong-id-{it['id']}.html"
        stime = datetime.fromtimestamp(int(it["stime"]), CN).strftime("%m-%d %H:%M:%S") if it.get("stime") else ""
        return {
            "title": it.get("title", ""),
            "desc": it.get("description", "") or it.get("desc", "") or "",
            # stime = API 上架时间（T0 源头痕迹），独立字段落表，任何后续校对不得修改
            "stime": stime,
            "start": stime,
            "end": datetime.fromtimestamp(int(it["etime"]), CN).strftime("%m-%d %H:%M:%S") if it.get("etime") else "",
            "url": u,
        }
    rows = [norm(it) for it in out]
    seen, dedup = set(), []
    for x in rows:
        if x["url"] and x["url"] not in seen:
            seen.add(x["url"])
            dedup.append(x)
    return dedup

def pt(s):
    """统一时间解析（管线级，双渠道通用）：
    '09-11 09:00' -> 当年年9月11日；ISO '2026-09-11T09:00' -> 原样。
    年份动态推断：MM-DD超过当前月6个月以上视为上一年（跨年活动兜底）。"""
    if not s:
        return None
    try:
        if "T" in s or "-" in s[:5]:        # ISO 格式（快爆侧）
            return datetime.fromisoformat(s).replace(tzinfo=CN)
    except Exception:
        pass
    m = re.match(r"(\d{2})-(\d{2}) (\d{2}):(\d{2})", s)
    if not m:
        return None
    try:
        y = datetime.now(CN).year
        d = datetime(y, int(m.group(1)), int(m.group(2)),
                     int(m.group(3)), int(m.group(4)), tzinfo=CN)
        if (d - datetime.now(CN)).days > 183:      # 未来超半年 -> 上一年
            d = d.replace(year=y - 1)
        return d
    except Exception:
        return None

VAGUE = ("赢好礼", "赢奖励", "赢大奖", "拿奖励", "领好礼", "有礼", "好礼")

# —— 4399 模板噪音剔除（2026-09-12 实证）——
# 4399 活动详情页模板自带两块与【本活动奖池】无关的 Q币 文本：
#   1) 获奖留言墙：`boxer_xx 2026-04-30 16:13:08 江苏省 获得 6Q币 感谢盒子`（历史留言）
#   2) 共享抽奖模块计数文案：`目前累计暴击奖励 0 Q币 / 抽奖次数+1 / 已领取 / 我要拿奖…`
# 它们让几乎所有4399页面正文都“看起来有Q币”，是把《三角洲行动》福利中心、
# 《王者万象棋》福利中心这类活动误判成真奖励的根源（用户反馈“里面不是我想要的”）。
_WALL_TS = re.compile(r"20\d{2}-\d{2}-\d{2} \d{1,2}:\d{2}(:\d{2})?")
_LOTTERY_BOILER = ("抽奖次数+1", "每日首次浏览", "每日首次访问", "去逛逛", "继续逛逛",
                   "已领取", "我要拿奖", "开启挑战", "目前累计暴击奖励", "已累计",
                   "请先登录，再参与活动", "篇幅所限")
# 共享领奖弹窗模板句（j-get_prize/j-get_qq 等模板，所有4399活动页都有）：
# "恭喜你获得了“ ”，现金奖励需前往微信【服务号】…领取现金红包。"
# "Q币奖励后续将直接发放至对应账号中"——给每个页面注入假"现金/Q币"证据
# （无畏契约"赢枪皮喷漆"被误标现金的根源），整句剔除。
_BOILER_SENT = re.compile(
    r"恭喜[你您]获得了[^。~]{0,80}[~。]?"
    r"|现金奖励[^。]{0,60}(?:微信|钱包)[^。]*。?"
    r"|很遗憾，还差一点就中奖[^。]*。?")
# 共享QQ领奖弹窗/到账说明的精确变体（洛克王国33170/33048实证）。
# ⚠️ 不用通用模式 r"Q币奖励…"——会把真奖池句"可获得限定Q币奖励"一起删掉
# （三角洲33271误伤实证），必须逐句枚举。
_BOILER_PHRASES = ("Q币奖励后续将直接发放至对应账号中",
                   "Q币奖励需在活动期间内，自行前往微信小程序内兑换领取",
                   "Q币奖励需在活动期间内前往小程序兑换领取",
                   "Q币奖励在领取后，需在活动期间内，前往小程序登录QQ号兑换领取",
                   "4399专属Q币奖励将以直充的形式发放到账",
                   "Q币奖励不可重复获得，请悉知",
                   "重复领取的Q币奖励不会到账",
                   "请确认您提交的领奖QQ号信息是否准确无误",
                   "Q直充到账，请务必填写正确",
                   "奖励性质相对特殊，请您仔细核对信息",
                   "领奖QQ账号一")
# 页脚标记：可见文本出现这些即进入页脚推荐区（"更多好玩活动"链接标题是
# 别家活动的标题，会把 CODM"6元红包"之类记到本游戏头上），先截断再拼模板。
_FOOTER_MARKERS = ("更多好玩活动", "游戏实用工具", "四三九九网络")

def scope_body(txt):
    """剔除留言墙、共享抽奖/领奖弹窗模板句，只留活动自身规则/奖池文本。
    （页脚推荐区在 detail_text 内可见文本阶段先截断，模板按文档序拼在其后，
    规则模板在前、留言墙模板在后，时间戳截断依然安全。）"""
    if not txt:
        return txt
    m = _WALL_TS.search(txt)
    if m:                    # 从第一处留言墙时间戳起截断（其后全是历史留言/页脚）
        txt = txt[:m.start()]
    txt = _BOILER_SENT.sub(" ", txt)
    for w in _BOILER_PHRASES + _LOTTERY_BOILER:
        txt = txt.replace(w, " ")
    return txt

# 详情页「活动时间」区间（2026年9月10日-2026年11月9日）
PAGE_TIME = re.compile(
    r"活动时间[^0-9]{0,12}(?:(20\d{2})\s*年)?\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日"
    r"(?:\s*[-~—–至]{1,3}\s*(?:(20\d{2})\s*年)?\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日)?")
# 「即日起-2026年9月16日」型：只有结束日，不能把结束日误当开始日
PAGE_UNTIL = re.compile(
    r"活动时间\s*即\s*日起?\s*[-~—–至]{0,3}\s*(?:(20\d{2})\s*年)?\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日")

def parse_page_times(txt):
    """详情页正文 -> ("range", start, end) | ("until", end) | ("since_today", None) | (None, None)
    纯函数（可回归测试）。优先级：即日起 > 明确区间。"""
    m = PAGE_UNTIL.search(txt)
    if m:
        ne = f"{int(m.group(2)):02d}-{int(m.group(3)):02d} 23:59"
        return ("until", ne)
    if re.search(r"活动时间[^0-9]{0,6}即\s*日起", txt):
        return ("since_today", None)
    m = PAGE_TIME.search(txt)
    if m:
        ns = f"{int(m.group(2)):02d}-{int(m.group(3)):02d} 00:00"
        ne = f"{int(m.group(5)):02d}-{int(m.group(6)):02d} 23:59" if m.group(4) else None
        return ("range", ns, ne)
    return (None, None)

def verify_start(rows):
    """4399接口的 stime 是【上架时间】不是活动开始时间（CODM崩坏3联动实证：
    stime=08-25，详情页写明活动9月10日开始）。对进入候选的条目抓详情页，
    以页面「活动时间」为准覆写起止时间。"""
    fixed = 0
    for r in rows:
        try:
            txt = detail_text(r["url"])
        except Exception:
            continue
        res = parse_page_times(txt)
        if res[0] == "until":
            r["start_note"] = "即日起（页面未写明确开始，仍取接口stime）"
            if res[1] != r["end"]:
                r["orig_end"] = r["end"]
                r["end"] = res[1]
                r["time_corrected"] = True
                fixed += 1
        elif res[0] == "since_today":
            r["start_note"] = "即日起（页面未写明确开始，仍取接口stime）"
        elif res[0] == "range":
            ns, ne = res[1], (res[2] or r["end"])
            if ns != r["start"] or ne != r["end"]:
                r["orig_start"], r["orig_end"] = r["start"], r["end"]
                r["start"], r["end"] = ns, ne
                r["time_corrected"] = True
                fixed += 1
    print(f"  详情页时间校正: {fixed} 条（stime=上架时间≠活动开始）")
    return rows

def detail_text(url):
    """详情页正文 = 可见文本 + <script type="text/html"> 模板文本。
    ⚠️ 2026-09-12 实证（三角洲 id-33271）：4399 活动页的【活动规则/奖池】整块写在
    `<script type="text/html" id="j-rule-tmpl">` 前端模板里（15处Q币全在其中），
    可见文本只有任务按钮区（0处Q币）。旧版把所有 <script> 一律剥掉，等于把
    活动规则正文删了——这正是"规则里明明有Q币却判噪音"的最后一块拼图。
    text/html 模板是 HTML 片段不是 JS 代码，剥标签取文本即可；JS 代码仍剥掉。
    模板按文档序拼接，规则模板在前、留言墙模板(j-yxh_prize-tmpl)在后，
    因此 scope_body 的"第一处时间戳截断"依然安全。"""
    try:
        h = get(url, timeout=12)
        import html as H
        tmpls = re.findall(r'<script[^>]*type="text/html"[^>]*>(.*?)</script>',
                           h, flags=re.S | re.I)
        h = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", h, flags=re.S | re.I)
        txt = re.sub(r"\s+", " ", H.unescape(re.sub(r"<[^>]+>", " ", h)))
        # 页脚"更多好玩活动"是别家活动的推荐链接（CODM"6元红包"会记到本游戏头上），
        # 在可见文本阶段先截断，模板文本按文档序拼在其后不受影响
        for mk in _FOOTER_MARKERS:
            i = txt.find(mk)
            if i >= 0:
                txt = txt[:i]
        if tmpls:
            tj = " ".join(re.sub(r"\s+", " ", H.unescape(re.sub(r"<[^>]+>", " ", t)))
                          for t in tmpls)
            txt = (txt + " " + tj)
        return txt[:9000]
    except Exception:
        return ""

def main():
    items = fetch_all()
    json.dump(items, open("_4399_sept_v2.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print(f"raw={len(items)}")

    # 候选：游戏命中 + 收录窗口内（2026-08 ~ 今天：已开始、窗口期内未结束/已结束均可）
    cands = []
    for x in items:
        g = match_game(x["title"])
        if not g:
            continue
        s, e = pt(x["start"]), pt(x["end"])
        if not s or not e:
            continue
        if s > NOW:                      # 未开始（未来排期）
            continue
        if e < WIN_START:                # 8月1日前已结束
            continue
        x["_game"] = g
        cands.append(x)

    # 判定优先级（2026-09-12 用户口径）：
    #   噪音看标题（第一优先级）：标题命中噪音词 → 终判噪音，【不抓规则正文】；
    #   真奖励看规则正文（第一优先级）：标题干净 → 抓详情页，用奖池正文判定。
    need = [i for i, x in enumerate(cands) if not title_noise(x["title"])]

    # 并行预取详情页正文（仅标题干净的候选）：奖励复判 + 源头时间校正共用同一份正文
    def _body(x):
        try:
            return detail_text(x["url"])
        except Exception:
            return ""

    bodies = [""] * len(cands)
    if need:
        with ThreadPoolExecutor(8) as ex:
            got = list(ex.map(_body, [cands[i] for i in need]))
        for i, b in zip(need, got):
            bodies[i] = b

    rows = []
    for x, txt in zip(cands, bodies):
        g = x["_game"]
        tn = title_noise(x["title"])
        if tn:
            # 标题噪音 → 终判，不用正文复判（正文仅可做时间参考，这里直接跳过）
            rows.append({**x, "game": g, "kind": "noise", "reward": None,
                         "detail_checked": False,
                         "noise_hint": [tn]})
            continue
        kind, label = reward_kind(x["title"], x["desc"])
        upgraded = False
        # 剔除4399模板噪音（留言墙+共享抽奖模块）后再判定
        scoped = scope_body(txt)
        if scoped:
            kind2, label2 = reward_kind(x["title"], scoped)
            if kind2 == "real" and kind != "real":
                kind, label, upgraded = kind2, label2, True
            if not x["desc"]:
                x["desc"] = scoped[:120]
        # stime=上架时间≠活动开始时间 -> 详情页「活动时间」覆写（CODM实证）
        res = parse_page_times(txt)
        if res[0] == "until":
            if res[1] != x["end"]:
                x["orig_end"] = x["end"]
                x["end"] = res[1]
        elif res[0] == "range":
            ns, ne = res[1], (res[2] or x["end"])
            if ns != x["start"] or ne != x["end"]:
                x["orig_start"], x["orig_end"] = x["start"], x["end"]
                x["start"], x["end"] = ns, ne
        rows.append({**x, "game": g, "kind": kind, "reward": label,
                     "detail_checked": upgraded,
                     "noise_hint": matched_noise(x["title"], "")})

    sept = [r for r in rows if r["start"] >= "09-01"]
    aug = [r for r in rows if r["start"] < "09-01"]
    real_sept = [r for r in sept if r["kind"] == "real"]
    real_aug = [r for r in aug if r["kind"] == "real"]
    noise_sept = [r for r in sept if r["kind"] != "real"]

    # 输出链接域名改写（2026-09-12 用户反馈）：a.haohaowan.net 用户打不开，
    # a.4399.cn 短域名可直接打开。抓取全程仍用 haohaowan 全文源（a.4399.cn
    # 只返回跳转壳，不能用于抓规则正文），仅在最终落库/展示时改写域名。
    for _grp in (real_sept, real_aug, noise_sept):
        for _r in _grp:
            if _r.get("url"):
                _r["url"] = _r["url"].replace("a.haohaowan.net", "a.4399.cn")

    json.dump({"sept_real": real_sept, "aug_real_running": real_aug,
               "sept_noise": noise_sept},
              open("_4399_table_v3.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)

    print(f"\n=== A组 9月开始·真奖励（窗口2026-08~今天，含已结束） ({len(real_sept)}条) ===")
    for r in sorted(real_sept, key=lambda r: r["game"]):
        print(f'{r["game"]:<9} {r["start"]}~{r["end"]} [{r["reward"]}{"↑详情页复判" if r["detail_checked"] else ""}] {r["title"][:40]}')
    print(f'\n=== B组 8月及更早开始·仍在进行·真奖励 ({len(real_aug)}条) ===')
    for r in sorted(real_aug, key=lambda r: r["game"]):
        print(f'{r["game"]:<9} {r["start"]}~{r["end"]} [{r["reward"]}] {r["title"][:40]}')
    print(f'\n=== 9月开始但按分类计噪音 ({len(noise_sept)}条, 留档供查验) ===')
    for r in noise_sept:
        print(f'{r["game"]:<9} {r["start"]}~{r["end"]} 噪音{r["noise_hint"][:3]} {r["title"][:36]}')

if __name__ == "__main__":
    main()
