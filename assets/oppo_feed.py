# oppo_feed.py — OPPO 游戏中心（OCS 签名）活动采集通道
# R35：PC 直调 api-cn.game.heytapmobi.com，彻底脱离手机/模拟器。
#   签名算法逆向自 libocstool.so + dx3.smali（hook_oppo/ocs.py 24/24 真值验证通过）。
#   响应为 x2-protostuff 二进制 → 内置无 schema 树解析器提取活动卡。
# 纯标准库，无第三方依赖。
import hashlib, json, os, re, time, gzip, html as H, urllib.request, urllib.parse, urllib.error
from datetime import datetime, timezone, timedelta

# ---------------------------------------------------------------- OCS 签名常量
KEY1 = "6486ed42c86ecc09"          # == oak 头
G2 = ["cab2f5d94d4eea71", "3e8d4f1ce5aa6e09", "c5ca81b0391663db",
      "517e95007dd031cb", "f8730121dba1cf23"]
G3 = ["d9275c219e852eb5e60cb5ceccd523b5", "6bf7d491e5ab9da2931f91eb4c9a1640",
      "0ca3e6b70c4e0fc4cf53ead33d158e83", "464c6045b59a38069a3e585d8bfe3b90",
      "f1184b1998cccddd10aa5b8dd039ef8f"]
KEY2 = "6486ed42c86ecc09f81e3e12314dd2953c3e95c524ac6a3a"   # 48B
G_E = ("STORENEWMIICeAIBADANBgkqhkiG9w0BAQEFAASCAmIwggJeAgEAAoGBANYFY/UJGSzhIhpx6YM5KJ9yRHc7YeURxzb9tDvJvMfENHlnP3DtVkOIjERbpsSd76fjtZnMWY60TpGLGyrNkvuV40L15JQhHAo9yURpPQoI0eg3SLFmTEI/MUiPRCwfwYf2deqKKlsmMSysYYHX9JiGzQuWiYZaawxprSuiqDGvAgMBAAECgYEAtQ0QV00gGABISljNMy5aeDBBTSBWG2OjxJhxLRbndZM81OsMFysgC7dq+bUS6ke1YrDWgsoFhRxxTtx/2gDYciGp/c/h0Td5pGw7T9W6zo2xWI5oh1WyTnn0Xj17O9CmOk4fFDpJ6bapL+fyDy7gkEUChJ9+p66WSAlsfUhJ2TECQQD5sFWMGE2IiEuz4fIPaDrNSTHeFQQr/ZpZ7VzB2tcG7GyZRx5YORbZmX1jR7l3H4F98MgqCGs88w6FKnCpxDK3AkEA225CphAcfyiH0ShlZxEXBgIYt3V8nQuc/g2KJtiV6eeFkxmOMHbVTPGkARvt5VoPYEjwPTg43oqTDJVtlWagyQJBAOvEeJLno9aHNExvznyD4/pR4hec6qqLNgMyIYMfHCl6d3UodVvC1HO1/nMPl+4GvuRnxuoBtxj/PTe7AlUbYPMCQQDOkf4sVv58tqslO+I6JNyHy3F5RCELtuMUR6rG5x46FLqqwGQbO8ORq+m5IZHTV/Uhr4h6GXNwDQRh1EpVW0gBAkAp/v3tPI1riz6UuG0I6uf5er26yl5evPyPrjrD299L4Qy/1EIunayC7JYcSGlR01+EDYYgwUkec+QgrRC/NstV")

# 设备/会话常量（手机抓包所得；token 为 JWT 有过期时间，过期后重抓更新 conf/oppo_device.json）
DEVICE_DEFAULT = {
    "id": "2112#ea832cefcd7173c8a3fe8cd5b7b275cf#30de8b87492c6230a35c277b19979f1136eb0c9ba9694e0909445e5ad25df3da",
    "ocs": "Redmi%2F21091116AC%2F31%2F12%2FUNKNOWN%2F1000%2Fevergo-user+12+SP1A.210812.016+V13.0.9.0.SGBCNXM%2F141801",
    "user_agent": "Redmi%2F21091116AC%2F31%2F12%2FUNKNOWN%2F1000%2F2201%2F141801%2F0",
    "token": "TOKEN_eyJhbGciOiJFQ0RTQSIsInYiOiIxIn0.eyJleHAiOjE3OTEyODkyMjc4NzAsImlkIjoiMTMzMDE2MjkzOCIsImlkYyI6InNob3VtaW5nIiwidGlkIjoiWWM3SEF4dmUzcGdFQmhNOHFaUWVqVzJHNG8rc2UvVmxtL1Q2TGxkSDhtWWxIL0RjK1dCK1o4WVZlTVV6S1hFeFVkbllFb1poVDF2d3hXNENiaTQyVUVEUm5TU1M4b0UvRkYrWlJmOVpnbHM9In0.MEQCID_lHFrjHSb1_5s6t5M5qo_WrincP1nYzwAsFvZnN-zbAiBbp87Co0wWR0arWnCS2yMsVNLUUXWdgvLtABOTOo_v7w",
}
ACCEPT = "application/x2-protostuff; charset=UTF-8"
API = "https://api-cn.game.heytapmobi.com"

_DEVICE = dict(DEVICE_DEFAULT)

def token_status():
    """R46：解析 token（JWT）过期时间，供页面顶部亮红灯。

    token 过期 = OP游戏中心源拉不到数据（其余源不受影响）。
    手机重新抓包后把新 token 写进 conf/oppo_device.json 即恢复。"""
    import base64
    import datetime as _dt
    tk = (_DEVICE.get("token") or "")
    if tk.startswith("TOKEN_"):
        tk = tk[len("TOKEN_"):]
    try:
        payload = tk.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        exp_ms = json.loads(base64.urlsafe_b64decode(payload)).get("exp")
        exp = _dt.datetime.fromtimestamp(exp_ms / 1000,
                                         _dt.timezone(_dt.timedelta(hours=8)))
        now = _dt.datetime.now(_dt.timezone(_dt.timedelta(hours=8)))
        return {"expired": exp <= now, "exp": exp.isoformat(timespec="minutes"),
                "days_left": round((exp - now).total_seconds() / 86400, 1)}
    except Exception:
        return {"expired": False, "exp": "", "days_left": None}


def load_device(cfg=None):
    """conf/oppo_device.json 可覆盖内置设备常量（token 过期后手机重抓一次即可）。"""
    global _DEVICE
    d = dict(DEVICE_DEFAULT)
    try:
        conf = (cfg or {}).get("_conf_dir")
        if not conf:
            home = os.environ.get("RADAR_HOME")
            if home:
                conf = os.path.join(home, "conf")
        if conf:
            p = os.path.join(conf, "oppo_device.json")
            if os.path.exists(p):
                with open(p, "r", encoding="utf-8") as f:
                    d.update(json.load(f))
    except Exception:
        pass
    _DEVICE = d
    return d

# ---------------------------------------------------------------- 签名复刻

def _ocs_d(p1: str, p2: str) -> str:
    total1 = len(p1) + 16 + len(p2)
    d1 = hashlib.md5((p1 + KEY1 + p2 + str(total1)).encode()).digest()
    chk = sum((b if b < 128 else 256 - b) % 10 for b in d1) % 10
    idx = chk % 5
    total2 = len(p1) + len(G2[idx]) + len(G3[idx])
    m2 = p1 + G2[idx] + G3[idx] + str(total2)
    return hashlib.md5(m2.encode()).hexdigest() if chk < 5 else hashlib.sha1(m2.encode()).hexdigest()

def _ocs_c(s: str) -> str:
    blob = KEY2.encode() + s.encode() + str(len(s) + 48).encode() + G_E.encode()
    return hashlib.md5(blob).hexdigest()

def _url_encode(s: str) -> str:
    return urllib.parse.quote(s, safe=".-*_").replace("%20", "+")

def build_headers(url: str, method: str = "get", dev=None) -> dict:
    dev = dev or _DEVICE
    ts = int(time.time() * 1000)
    u = urllib.parse.urlsplit(url)
    sign = _ocs_c(dev["ocs"] + str(ts) + dev["id"] + u.path + urllib.parse.unquote(u.query))  # app 端 sign 用解码后 query（中文参数实锤，见 hook_oppo/capture5.log）
    p1 = (_url_encode(u.path + u.query) + ACCEPT + method.lower() + dev["id"] + str(ts)).lower()
    sg = _ocs_d(p1, sign)
    return {
        "romver": "-1", "minorAgeType": "0", "User-Agent": dev["user_agent"],
        "sign": sign, "sg": sg, "nw": "1", "pid": "1000", "enter-id": "1",
        "snippetVersion": "5", "locale": "zh-CN;CN", "cpuInfo": "",
        "clientSource": "1", "cpuAbilist": "arm64-v8a,armeabi-v7a,armeabi",
        "oak": KEY1, "accid": "", "id": dev["id"], "rcm": "1", "ocs": dev["ocs"],
        "Accept": ACCEPT, "checkSign": "1", "ch": "2201", "saleMode": "0",
        "token": dev["token"], "pkg-ver": "-1", "t": str(ts), "ols": "",
        "minorMode": "0", "compressTool": "zstd-1.5.2-2", "child": "ADULT",
    }

def _get(url, timeout=20):
    req = urllib.request.Request(url, headers=build_headers(url, "get"))
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"HTTP {e.code} {url[:80]}") from None
    if raw[:2] == b"\x1f\x8b":
        try: raw = gzip.decompress(raw)
        except Exception: pass
    return raw

def _post_json(url, obj, timeout=20):
    body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
    h = build_headers(url, "post")
    h["Content-Type"] = "application/json; charset=UTF-8"
    req = urllib.request.Request(url, data=body, headers=h, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"HTTP {e.code} {url[:80]}") from None
    if raw[:2] == b"\x1f\x8b":
        try: raw = gzip.decompress(raw)
        except Exception: pass
    return raw

# ------------------------------------------------------- protostuff 树解析器

class Node:
    __slots__ = ("fields", "type")
    def __init__(self):
        self.fields = {}
        self.type = None
    def vals(self, f, wt=None):
        return [v for w, v in self.fields.get(f, []) if wt is None or w == wt]
    def first(self, f, wt=None, default=None):
        vs = self.vals(f, wt)
        return vs[0] if vs else default
    def all_strs(self, acc=None):
        if acc is None: acc = []
        for f, pairs in self.fields.items():
            for w, v in pairs:
                if w == "str": acc.append((f, v))
                elif w == "msg": v.all_strs(acc)
        return acc
    def all_ints(self, acc=None):
        if acc is None: acc = []
        for f, pairs in self.fields.items():
            for w, v in pairs:
                if w == "int": acc.append((f, v))
                elif w == "msg": v.all_ints(acc)
        return acc

def _varint(buf, i):
    shift = val = 0
    while True:
        b = buf[i]; i += 1
        val |= (b & 0x7F) << shift
        if not (b & 0x80): return val, i
        shift += 7
        if shift > 63: raise ValueError

def _plausible_msg(chunk):
    if not chunk: return False
    try:
        i = n = 0
        while i < len(chunk) and n < 6:
            tag, i = _varint(chunk, i)
            f, wt = tag >> 3, tag & 7
            if f == 0 or f > 100000: return False
            if wt == 0: _, i = _varint(chunk, i)
            elif wt == 2:
                ln, i = _varint(chunk, i)
                if ln < 0 or i + ln > len(chunk): return False
                i += ln
            elif wt == 5: i += 4
            elif wt == 1: i += 8
            elif wt == 3: pass
            elif wt == 4: return n > 0
            else: return False
            n += 1
        return n >= 2
    except Exception:
        return False

def _printable(s):
    if not s: return False
    return sum(1 for c in s if c.isprintable() or c in "\n\t") / len(s) > 0.85

def _parse(buf, depth=0):
    node = Node()
    i = 0
    try:
        while i < len(buf):
            tag, i = _varint(buf, i)
            f, wt = tag >> 3, tag & 7
            if f == 0: break
            if wt == 0:
                v, i = _varint(buf, i)
                node.fields.setdefault(f, []).append(("int", v))
            elif wt == 2:
                ln, i = _varint(buf, i)
                if ln < 0 or i + ln > len(buf): break
                chunk = buf[i:i+ln]; i += ln
                # 高可打印率的块优先按字符串（URL/中文标题全是 ASCII+CJK，
                # 若先尝试消息解析，ASCII 字节会被当 varint 啃掉导致丢文本）
                is_text = False
                try:
                    s = chunk.decode("utf-8")
                    if s and sum(1 for c in s if c.isprintable() or c in "\n\t") / len(s) > 0.9:
                        is_text = True
                except UnicodeDecodeError:
                    pass
                if is_text:
                    node.fields.setdefault(f, []).append(("str", s))
                    continue
                if depth < 14 and _plausible_msg(chunk):
                    try:
                        node.fields.setdefault(f, []).append(("msg", _parse(chunk, depth + 1)))
                        continue
                    except Exception:
                        pass
                node.fields.setdefault(f, []).append(("bytes", chunk))
            elif wt == 5: i += 4
            elif wt == 1: i += 8
            else: break
    except Exception:
        pass
    return node

def _iter(n):
    yield n
    for f, pairs in n.fields.items():
        for w, v in pairs:
            if w == "msg":
                yield from _iter(v)

def parse_tree(raw):
    root = _parse(raw)
    for n in _iter(root):
        t = n.first(127, "str") or n.first(253, "str")
        if t and "." in t:
            n.type = t
    return root

# ------------------------------------------------------------ 活动卡提取

_EPOCH_LO, _EPOCH_HI = 1700000000000, 2200000000000   # 2023-11 ~ 2039 (ms)

def _ms_iso(v):
    if _EPOCH_LO <= v <= _EPOCH_HI:
        return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(v / 1000))
    return None

_URL_PAT = re.compile(r"(https?://[!-~]+|oap://[!-~]+)")

def _unwrap_oap(url):
    """oap://gc/web?u=<urlencode> -> 真实 https URL"""
    if url.startswith(("oap://", "oaps://")):
        m = re.search(r"[?&]u=([^&]+)", url)
        if m:
            return urllib.parse.unquote(m.group(1))
        return ""
    return url

_CJK = re.compile(r"[\u4e00-\u9fff]{2,}")

def _card_title(node, game_names):
    """从活动卡节点挑标题：banner 专用字段 > 游戏名 > 日期标签 > 其它中文"""
    for f in (20008,):
        for v in node.vals(f, "str"):
            if v and _CJK.search(v):
                return v.strip()
    if game_names:
        # 游戏名 + 日期标签 组合，方便引擎按游戏名归类
        tag = ""
        for f in (6, 12):
            for v in node.vals(f, "str"):
                if v and _CJK.search(v) and not v.startswith("#"):
                    tag = v.strip(); break
            if tag: break
        g = game_names[0]
        if tag and tag not in g and len(g) + len(tag) < 60:
            return f"{g} {tag}"
        return g
    for f in (6, 12, 7, 4):
        for v in node.vals(f, "str"):
            if v and _CJK.search(v) and "font" not in v and not v.startswith("#"):
                return v.strip()
    # 嵌套里的短中文（事件标签等）
    for f, v in node.all_strs():
        if _CJK.search(v) and 3 < len(v) < 40 and not v.startswith(("http", "oap")) \
                and "com." not in v and "<" not in v:
            return v.strip()
    return (game_names[0] if game_names else "") or ""

def extract_items(raw, game_hint=""):
    """把一份 protostuff 响应解析成活动条目列表。
    叶子优先：倒序遍历（子节点先于父节点），只看本层字符串字段，
    保证 URL/标题取自最小卡片段落而不是整个 feed 根。
    game_hint: 详情页接口场景下已知的游戏名，拼进标题帮助归类。"""
    root = parse_tree(raw)
    out, seen = [], set()
    for node in reversed(list(_iter(root))):
        # 只在「本层」字符串字段里找活动 URL（子节点已被倒序处理过）
        url = ""
        for f, pairs in node.fields.items():
            for w, v in pairs:
                if w == "str" and ("nvwa-static" in v or "actId=" in v
                                   or "activity-cdo" in v or "staticActivity" in v):
                    url = _unwrap_oap(v)
                    break
            if url: break
        if not url or not url.startswith("http"):
            continue
        u = url.split("#")[0]
        if u in seen or len(u) < 20:
            continue
        seen.add(u)
        # 关联本卡嵌套的游戏 ResourceDto（f3=名称 f7=包名）
        game_names, pkgs = [], []
        for sub in _iter(node):
            t = sub.type or ""
            if t.endswith("ResourceDto"):
                n = sub.first(3, "str"); p = sub.first(7, "str")
                if n and n not in game_names: game_names.append(n)
                if p and p not in pkgs: pkgs.append(p)
        title = _card_title(node, game_names)
        if not title and game_hint:
            title = f"{game_hint} 活动"
        if not title:
            continue
        if game_hint and game_hint not in title:
            title = f"{game_hint} {title}"
        # 时间：卡内所有毫秒 epoch。≤now+90d 的最早一个当开始时间，
        # 更远的（一般是一年有效期的卡）当结束时间。
        now_ms = time.time() * 1000
        ep = sorted(v for _, v in node.all_ints() if _EPOCH_LO <= v <= _EPOCH_HI)
        starts = [v for v in ep if v <= now_ms + 90 * 86400_000]
        ends = [v for v in ep if v > now_ms + 90 * 86400_000]
        start_iso = _ms_iso(starts[0]) if starts else None
        end_v = max(ends) if ends else (starts[-1] if len(starts) >= 2 else None)
        end_iso = _ms_iso(end_v) if end_v is not None else None
        # 摘要：游戏名/包名/附加标签
        bits = []
        if game_names and game_names[0] not in title: bits.append(game_names[0])
        extra = [v for f, v in node.all_strs()
                 if f in (12, 8) and _CJK.search(v) and v not in bits and v not in title]
        bits.extend(dict.fromkeys(extra[:3]))
        summary = " · ".join(bits)[:200]
        # actId 作为稳定 key
        m = re.search(r"actId=(\d+)", url)
        key = m.group(1) if m else hashlib.md5(u.encode()).hexdigest()[:16]
        out.append({
            "title": title[:120],
            "url": url,
            "summary": summary,
            "startTime": start_iso,
            "endTime": end_iso,
            "id": key,
            "_pkgs": pkgs,
            "_game": game_hint or (game_names[0] if game_names else ""),
        })
    return out

# ------------------------------------------------------------ 详情页/搜索接口

DETAIL_URL = f"{API}/detail/v5/resource/v2/app"
DETAIL_MODEL_URL = f"{API}/detail/v5/model/app"   # R36: 完整详情页模型（运营位/活动区在此）

def detail_activities(app_id, game_hint=""):
    """游戏详情页活动采集：合并 resource/v2（活动/福利横幅）与 model（完整模型，
    部落冲突等活动只在 model 里出现）。跨接口按 URL 去重。
    R36 已验证 11 款：三角洲31285459/使命召唤3729665/冒险岛31032853/金铲铲30558137/
    无畏契约32963373/暗区突围30594335/部落冲突30619259/皇室战争30619253/
    王者2222071/和平精英3610816/QQ飞车3574547。"""
    out = []
    for url in (DETAIL_URL, DETAIL_MODEL_URL):
        try:
            raw = _post_json(url, {"appId": int(app_id)})
        except Exception:
            continue
        out.extend(extract_items(raw, game_hint=game_hint))
    seen, merged = set(), []
    for it in out:
        if it["url"] in seen:
            continue
        seen.add(it["url"])
        merged.append(it)
    return merged

def resolve_app_id(name):
    """用游戏名搜索接口解析 appId（中文关键词签名已修正验证）。"""
    try:
        q = urllib.parse.quote(name)
        raw = _get(f"{API}/search/v1/mix?size=10&start=0&from=1&keyword={q}&search_type=3&user_input_word=")
        text = raw.decode("latin-1", errors="replace")
        ids = re.findall(r"appId[\"=:]*(\d{6,10})", text)
        return int(ids[0]) if ids else None
    except Exception:
        return None

# ---------------------------------------------------------------- 采集入口

DEFAULT_PAGES = ["50003579"]     # 新游落地页（含 nvwa 活动位）

def collect(cfg, src):
    """engine run_source 的 oppo_ocs 类型入口：返回 engine api 条目格式。"""
    load_device(cfg)
    req_urls = src.get("endpoints") or {}
    urls = []
    # 1) 活动聚合 tab 列表
    urls.append(("tabList", f"{API}/card/game/activity/tabList"))
    # 2) 首页大feed（活动推荐/日历/banner）
    urls.append(("home", f"{API}/card/game/v2/home?size=50&start=0"))
    # 3) 服务端页面（新游落地页等，含 nvwa 活动位）
    for pid in (req_urls.get("pages") or DEFAULT_PAGES):
        urls.append((f"page{pid}", f"{API}/card/game/v1/page/{pid}?size=50&start=0"))
    # 4) struct（tab 模块骨架；页面 id 由此补充发现）
    tab_ids = []
    all_items, page_ids = [], []
    for tag, u in urls:
        try:
            raw = _get(u)
        except Exception:
            continue
        if "struct" in u or "tabList" in u:
            try:
                tree = parse_tree(raw)
                for n in _iter(tree):
                    for f, v in n.all_strs():
                        m = re.search(r"page/(\d{6,})", v)
                        if m: page_ids.append(m.group(1))
            except Exception:
                pass
        try:
            all_items.extend(extract_items(raw))
        except Exception:
            continue
    # struct 里发现的 page 追抓一轮
    for pid in dict.fromkeys(page_ids):
        if pid in [p for _, u in urls for p in [u.rsplit("/", 1)[-1].split("?")[0]]]:
            continue
        try:
            all_items.extend(extract_items(_get(f"{API}/card/game/v1/page/{pid}?size=50&start=0")))
        except Exception:
            continue
    # 5) 游戏详情页活动横幅（新人/回归/版本活动的主要来源）
    #    app_ids: {"三角洲行动": 31285459, ...}；只有名字没有 id 时走搜索解析
    #    R42：填 0 表示「用户清单里有这款游戏但 app_id 暂未确认」，直接跳过不浪费请求
    for name, aid in (req_urls.get("app_ids") or {}).items():
        if not aid or int(aid) <= 0:                       # R42：占位 0 → 跳过
            continue
        try:
            all_items.extend(detail_activities(aid, game_hint=name))
        except Exception:
            continue
    # 去重（actId/url 维度），剥掉内部字段
    merged, seen = [], set()
    enrich_dates_v2(all_items)   # R50: schema.js 与页面规则交叉校验，输出 create/start/end
    for it in all_items:
        k = it["id"] or it["url"]
        if k in seen: continue
        seen.add(k)
        merged.append({
            "title": it["title"], "url": it["url"], "summary": it["summary"],
            "createTime": it.get("createTime"), "startTime": it["startTime"],
            "endTime": it["endTime"], "id": it["id"],
            # 详情页渠道（用户显式跟踪的游戏）打 tracked 标记，引擎侧豁免分区过滤
            "tracked": bool(it.get("_game")),
        })
    return merged


# ---------------- R38：活动页 schema.js 时间富化 ----------------
_SCHEMA_CACHE = {}   # siteId -> (start_iso, end_iso) 或 None

def site_dates(url, timeout=12):
    """从活动站点静态 schema-*.js 提取活动起止时间（免登录免签名）。
    nvwa 站点: index.html 引用 js/schema-<hash>.js，其中 timeRange:["起","止"]。
    staticActivity 站点: 纯静态 HTML，活动时间直接写在页面里（源头时间）。
    返回 (start_iso, end_iso) 或 (None, None)。"""
    sk = _static_page_key(url)
    if sk:
        _, s, e = static_page_info(url, timeout=timeout)
        return s, e
    m = re.search(r"/nvwa-static/sites/([A-Za-z0-9]+)/static/index\.html", url)
    if not m:
        return None, None
    sid = m.group(1)
    if sid in _SCHEMA_CACHE:
        return _SCHEMA_CACHE[sid]
    start = end = None
    try:
        base = url.split("/static/index.html")[0] + "/static/"
        html = _get(base + "index.html", timeout=timeout).decode("utf-8", errors="replace")
        mj = re.search(r'(?:src="|")\./?(js/schema-[A-Za-z0-9_-]+\.js)', html) or              re.search(r'(js/schema-[A-Za-z0-9_-]+\.js)', html)
        if mj:
            schema = _get(base + mj.group(1), timeout=timeout).decode("utf-8", errors="replace")
            mt = re.search(r'timeRange:\["(20\d{2}-\d{2}-\d{2}[ T][\d:]{8})","(20\d{2}-\d{2}-\d{2}[ T][\d:]{8})"\]', schema)
            if mt:
                start = mt.group(1).replace(" ", "T") + "+08:00" if "T" not in mt.group(1) else mt.group(1)
                end = mt.group(2).replace(" ", "T") + "+08:00" if "T" not in mt.group(2) else mt.group(2)
            else:
                # 兜底：逐组件配置里的 actBeginTime/actEndTime（或任意日期对），取最早/最晚
                ds = sorted(set(re.findall(r"20\d{2}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}", schema)))
                if ds:
                    start, end = ds[0], ds[-1]
                # 归一为 ISO（2026-08-26 00:00:00 -> 2026-08-26T00:00:00+08:00）
                start = re.sub(r"^(\d{4}-\d{2}-\d{2}) (\d{2}:\d{2}:\d{2})$", r"\1T\2+08:00", start or "")
                end = re.sub(r"^(\d{4}-\d{2}-\d{2}) (\d{2}:\d{2}:\d{2})$", r"\1T\2+08:00", end or "")
                start = start or None; end = end or None
        # 2026-09-12 用户口径（仅限 OPPO 流程）：时间只以【源头出现的时间】为第一
        # 标准（API 卡片毫秒时间 / schema.js timeRange 等数据层字段）。
        # 不再从活动规则可见文本里解析时间——那正是“活动规则频繁读取不出真正
        # 时间”的根源。源头没有结构化时间的条目保持为空，进待审桶，绝不猜。
    except Exception:
        pass
    _SCHEMA_CACHE[sid] = (start, end)
    return start, end

def enrich_dates(items):
    """给缺时间的条目补 schema.js 日期（就地修改，带内存缓存）。"""
    for it in items:
        if it.get("startTime") or it.get("endTime"):
            continue
        st, en = site_dates(it.get("url", ""))
        if st: it["startTime"] = st
        if en: it["endTime"] = en
    return items


# ---------------- R47：活动页 schema.js 奖励正文提取 ----------------
_REWARD_TEXT_CACHE = {}   # siteId -> text

# nvwa 活动引擎共享任务组件的通用UI文案（2026-09-12 实证：用该组件的每个站点
# schema.js 都带）——"新注册用户/回流用户/注册 Q币/回流礼包/任务抽奖/我的奖品…"
# 是组件模板字样，不是活动真实奖池。天龙八部(旧)/新天龙3周年/天美家族大礼包
# 三站被判Q币的根源，与4399留言墙、快爆获奖记录墙同属"全站共享模板污染"。
_OPPO_ENGINE_BOILER = (
    "恭喜您获得礼包", "请前往游戏内查看吧", "恭喜您获得", "请前往页面",
    "我的奖品", "前往领取吧", "任务抽奖", "抽奖积分", "新注册用户",
    "回流用户", "回流礼包", "回流登录礼包", "每日登录游戏",
    "请在游戏内查收奖励", "小时内发放到", "暂无任何奖励",
    # nvwa 共享组件库的组件名/通用UI（2026-09-12 下午补充实证）
    "领奖组件", "奖品列表组件", "跳转奖品列表组件", "查询领奖记录",
    "查询领取记录", "热区组件", "轮播图", "富文本", "查看详情",
    "绑定账号", "账号绑定", "当前活动积分", "中奖后请尽快填写收货地址",
    "逾期无法补发哦", "标题文案", "副标题描述文案", "互娱游戏中心",
    "深圳市腾讯计算机系统有限公司", "去完成", "已完成",
)

def site_reward_text(url, timeout=12):
    """从活动页提取奖励相关文本。
    nvwa 站点: index.html 是壳，奖励规则、任务名、奖品都写在 schema-*.js 里。
    staticActivity 站点: 纯静态 HTML，规则/奖池直接在页面正文里。
    返回可打印文本（去重后拼接），供给 reward_classify 判定。"""
    sk = _static_page_key(url)
    if sk:
        return static_page_info(url, timeout=timeout)[0]
    m = re.search(r"/nvwa-static/sites/([A-Za-z0-9]+)/static/index\.html", url)
    if not m:
        return ""
    sid = m.group(1)
    if sid in _REWARD_TEXT_CACHE:
        return _REWARD_TEXT_CACHE[sid]
    parts = []
    try:
        base = url.split("/static/index.html")[0] + "/static/"
        html = _get(base + "index.html", timeout=timeout).decode("utf-8", errors="replace")
        # index.html 里的内联 <script>/<style>（引擎配置/CSS）必须先剥掉，
        # 否则这些无意义文本会占满 4000 字预算，schema 正文进不来（2026-09-12 实证：
        # 新天龙3周年/天美家族两站证据被"window.nvwa_engine…"垃圾填满）。
        html = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html, flags=re.S | re.I)
        parts.append(re.sub(r"\s+", " ", H.unescape(re.sub(r"<[^>]+>", " ", html))))
        mj = re.search(r'(?:src="|"|href=")\./?(js/schema-[A-Za-z0-9_-]+\.js)', html) or \
             re.search(r'(js/schema-[A-Za-z0-9_-]+\.js)', html)
        if mj:
            schema = _get(base + mj.group(1), timeout=timeout).decode("utf-8", errors="replace")
            # schema.js 里奖品/任务/规则文本多为 JSON 字符串。⚠️ 提取必须保留
            # 「Q币/QB」等含拉丁字母的奖励词 —— 旧版纯中文正则会把"拉新3Q币积分"
            # 切成"拉新"+"币积分"，Q币证据被销毁导致真奖励全判噪音（2026-09-12实证）。
            txt = " ".join(re.findall(r"[\u4e00-\u9fa5]{2,30}|[Qq]币|[Qq][Bb]", schema))
            # 独立"qb/QB"token 是 nvwa 组件库的组件名标签（如"查询领奖记录 qb 查询"），
            # 不是奖励词，整token丢弃；真实Q币要么写作"Q币"，要么在整句token里
            # （如"注册送QB"）不会单独成token。
            txt = " ".join(t for t in txt.split() if t.lower() != "qb")
            # 剔除 nvwa 引擎共享任务组件的通用UI文案：每个用该组件的站点 schema.js
            # 都带"注册 Q币""回流礼包"等模板字样，会给页面注入假Q币证据——
            # 天龙八部/新天龙3周年被判Q币的根源（活动真实奖池=游戏礼包，2026-09-12实证）。
            # 真活动的规则是整句token（如"新用户注册送Q币"），不会拆成独立token对，
            # 因此只删 token 级的模板组合与下列通用UI词，不伤真实奖池句。
            for w in _OPPO_ENGINE_BOILER:
                txt = txt.replace(w, " ")
            txt = re.sub(r"积分\s*[QqＱ]币", " ", txt)   # 任务组件模板："…积分 Q币 奖励将在…"
            txt = re.sub(r"(?:新)?注册\s*[QqＱ]币", " ", txt)
            txt = re.sub(r"回流\s*[QqＱ]币", " ", txt)
            parts.append(txt[:3000])
    except Exception:
        pass
    text = " ".join(dict.fromkeys(" ".join(parts).split()))
    # 引擎组件模板剔除对【合并后全文】统一执行：模板字样不仅出现在 schema.js，
    # 也出现在 index.html 的服务端渲染可见区（天龙八部旧站实证："注册礼包 领取
    # 成功 积分 Q币 奖励将在"就在 index 部分）。真活动规则是整句token，不受影响。
    text = " ".join(t for t in text.split() if t.lower() != "qb")
    for w in _OPPO_ENGINE_BOILER:
        text = text.replace(w, " ")
    text = re.sub(r"积分\s*[QqＱ]币", " ", text)   # 任务组件模板："…积分 Q币 奖励将在…"
    text = re.sub(r"(?:新)?注册\s*[QqＱ]币", " ", text)
    text = re.sub(r"回流\s*[QqＱ]币", " ", text)
    text = text[:4000]
    _REWARD_TEXT_CACHE[sid] = text
    return text

def enrich_reward_text(items):
    """给条目补 schema.js 奖励正文（就地修改）。"""
    for it in items:
        rt = site_reward_text(it.get("url", ""))
        if rt:
            it["summary"] = (it.get("summary") or "") + " " + rt
    return items


# ---------------- R50：nvwa 页面规则「活动时间」提取（与 schema.js 交叉校验） ----------------
_PAGE_RULE_CACHE = {}   # siteId -> {"start":..., "end":..., "text":...}

_VAGUE_START_MARKERS = ("即日起", "即时起", "长期有效", "活动时间：长期", "永久有效")


def _parse_iso(s):
    if not s:
        return None
    try:
        return datetime.fromisoformat(s)
    except Exception:
        return None


def _normalize_date_text(t):
    """把 HTML span 拆分产生的空格归一化，便于 _cn_time_range 解析。"""
    if not t:
        return ""
    t = t.replace("：", ":")
    t = re.sub(r"(\d)\s*([年月日号点时分])", r"\1\2", t)
    t = re.sub(r"([年月日号点时分])\s*(\d)", r"\1\2", t)
    # HTML span 拆分会把 "日00:00" 切成 "日0 0:00"，需合并相邻数字间空格
    t = re.sub(r"(\d)\s+(?=\d)", r"\1", t)
    t = re.sub(r"(\d)\s*[:点]\s*(\d)", r"\1:\2", t)
    return re.sub(r"\s+", " ", t).strip()


def _nvwa_page_rule_time(url, timeout=12):
    """从 nvwa schema.js 的富文本/规则字段里提取页面可见「活动时间」。
    返回 (start_iso, end_iso, plain_text)。只处理 nvwa 站点。"""
    m = re.search(r"/nvwa-static/sites/([A-Za-z0-9]+)/static/index\.html", url)
    if not m:
        return None, None, ""
    sid = m.group(1)
    if sid in _PAGE_RULE_CACHE:
        c = _PAGE_RULE_CACHE[sid]
        return c.get("start"), c.get("end"), c.get("text", "")
    start = end = None
    plain = ""
    try:
        base = url.split("/static/index.html")[0] + "/static/"
        html = _get(base + "index.html", timeout=timeout).decode("utf-8", errors="replace")
        mj = re.search(r'(?:src="|"|href=")\./?(js/schema-[A-Za-z0-9_-]+\.js)', html) or \
             re.search(r'(js/schema-[A-Za-z0-9_-]+\.js)', html)
        if not mj:
            _PAGE_RULE_CACHE[sid] = {"start": None, "end": None, "text": ""}
            return None, None, ""
        schema = _get(base + mj.group(1), timeout=timeout).decode("utf-8", errors="replace")

        # 1) 提取常见规则/富文本字段（JSON/JS 字符串，内部含 \" 等转义）
        chunks = []
        for key in ("actRule", "text", "content", "desc"):
            # "key":"value" 形式
            chunks.extend(re.findall(r'(?:^|[,;{}\s])"' + key + r'"\s*:\s*"(.{50,12000})"', schema, re.DOTALL))
            # key:"value" 形式
            chunks.extend(re.findall(key + r'[:=]"(.{50,12000})"', schema, re.DOTALL))

        # 2) 去重并做 JS 字符串转义还原 + HTML 标签剥离 + 日期空格归一
        seen = set()
        norm_parts = []
        for raw in chunks:
            if raw in seen:
                continue
            seen.add(raw)
            # 文件里是 \\" 表示实际内容中的 \"，逐层还原
            s = raw.replace("\\\\", "\\").replace('\\"', '"')
            s = H.unescape(re.sub(r"<[^>]+>", " ", s))
            s = re.sub(r"\\[ntr]", " ", s)
            s = _normalize_date_text(s)
            if s:
                norm_parts.append(s)
        plain = " ".join(dict.fromkeys(norm_parts))

        # 3) 优先在活动规则附近解析
        start, end = _cn_time_range(plain)
        # 4) 兜底：对整个 schema.js 清理后解析
        if not start:
            s = schema.replace("\\\\", "\\").replace('\\"', '"')
            s = H.unescape(re.sub(r"<[^>]+>", " ", s))
            s = _normalize_date_text(s)
            start, end = _cn_time_range(s)
    except Exception:
        pass
    _PAGE_RULE_CACHE[sid] = {"start": start, "end": end, "text": plain[:2000]}
    return start, end, plain[:2000]


def _is_vague_rule(text):
    """判断页面规则是否含「即日起」等无法确定具体日期的描述。"""
    if not text:
        return True
    t = text.lower()
    return any(m in t for m in _VAGUE_START_MARKERS)


def site_dates_v2(url, timeout=12):
    """返回 (create, start, end, is_vague, schema_start)。
    - create：schema.js timeRange.start 中明显早于页面规则的「提前建页/预览」痕迹（T0）。
    - start/end：优先取页面规则真实活动时间；缺失或模糊则回退 schema.js。
    - is_vague：页面规则为「即日起」等无法确定具体日期的描述。
    - schema_start：schema.js timeRange.start 原值（建页配置时间），无论是否提前建页都透传，
      供展示层作为 T0 的兜底（页面建得越早，这个时间越早）。
    staticActivity 纯静态页：页面规则即源头，无 create/schema 概念，is_vague=False。
    """
    # staticActivity：页面规则即源头
    sk = _static_page_key(url)
    if sk:
        _, s, e = static_page_info(url, timeout=timeout)
        return None, s, e, False, None

    # nvwa 站点
    schema_start, schema_end = site_dates(url, timeout=timeout)
    page_start, page_end, page_text = _nvwa_page_rule_time(url, timeout=timeout)
    create = start = end = None

    # 结束时间：页面规则优先
    end = page_end or schema_end

    # 页面规则含「即日起」等视为模糊开始
    vague = _is_vague_rule(page_text) and page_start is None

    if page_start and not vague:
        if schema_start:
            s_schema = _parse_iso(schema_start)
            s_page = _parse_iso(page_start)
            # 页面规则明显晚于 schema.js（>=1天）=> schema.js 为提前建页痕迹（T0）
            if s_schema and s_page and (s_page - s_schema).total_seconds() >= 86400:
                create = schema_start
                start = page_start
            else:
                # 两者一致或接近：无提前建页，以页面规则为准
                start = page_start
        else:
            start = page_start
    elif schema_start:
        # 无页面规则/规则模糊：回退 schema.js 源头时间
        start = schema_start

    return create, start, end, vague, schema_start


def enrich_dates_v2(items):
    """给条目补 create/start/end/schemaStart/_vague_rule（就地修改），支持 nvwa 页面规则交叉校验。"""
    for it in items:
        create, start, end, vague, schema_start = site_dates_v2(it.get("url", ""))
        if create:
            it["createTime"] = create
        if start:
            it["startTime"] = start
        if end:
            it["endTime"] = end
        if schema_start:
            it["schemaStart"] = schema_start
        it["_vague_rule"] = vague
    return items


# ---------------- R48：staticActivity 静态页 正文 + 源头时间 ----------------
# staticActivity 页面是纯静态 HTML（非 nvwa JS 壳），活动规则/奖池与
# 「活动时间：X月X日至X月X日」都直接写在页面里 —— 源头时间以页面自标注为准。
_STATIC_CACHE = {}   # pageKey -> {"text":…, "start":…, "end":…}

def _static_page_key(url):
    m = re.search(r"/staticActivity/([A-Za-z0-9]+)/htmls/", url or "")
    return ("static:" + m.group(1)) if m else None

def _get_plain(url, timeout=15):
    req = urllib.request.Request(url, headers={
        "User-Agent": ("Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/120.0 Mobile Safari/537.36")})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read()
    if raw[:2] == b"\x1f\x8b":
        try: raw = gzip.decompress(raw)
        except Exception: pass
    return raw.decode("utf-8", errors="replace")

def _cn_dt(y, mo, d, h, mi):
    import datetime as _dt
    try:
        y = int(y) if y else _dt.datetime.now().year
        mo, d = int(mo), int(d)
        h = int(h) if h not in (None, "") else 0
        mi = int(mi) if mi not in (None, "") else 0
        if h >= 24: h, mi = 23, 59
        return "%04d-%02d-%02dT%02d:%02d:00+08:00" % (int(y), mo, d, h, mi)
    except Exception:
        return None

_CD = r"(?:(20\d{2})\s*年)?\s*(\d{1,2})\s*月\s*(\d{1,2})\s*[日号]?(?:\s*(\d{1,2})\s*[点时:：]\s*(\d{1,2})?)?"
_CN_RANGE = re.compile(_CD + r"\s*[~—–\-至到]{1,2}\s*" + _CD)
_CN_KW = re.compile(r"(?:活动时间|福利时间|参与时间|起止时间)[^0-9]{0,12}")
_CN_DOT = re.compile(r"(20\d{2})[.\-/](\d{1,2})[.\-/](\d{1,2})\s*[~—–\-至]{1,2}\s*(?:(20\d{2})[.\-/])?(\d{1,2})[.\-/](\d{1,2})")

def _cn_time_range(text):
    """静态页正文 -> (start_iso, end_iso)。优先「活动时间」关键词后的区间。"""
    if not text:
        return None, None
    for kw in _CN_KW.finditer(text):
        seg = text[kw.end():kw.end() + 80]
        m = _CN_RANGE.search(seg)
        if m:
            s = _cn_dt(*m.group(1, 2, 3, 4, 5))
            e = _cn_dt(*m.group(6, 7, 8, 9, 10))
            if s:
                return s, e
    m = _CN_RANGE.search(text[:6000])
    if m:
        s = _cn_dt(*m.group(1, 2, 3, 4, 5))
        e = _cn_dt(*m.group(6, 7, 8, 9, 10))
        if s:
            return s, e
    m = _CN_DOT.search(text[:6000])
    if m:
        y1, mo1, d1, y2, mo2, d2 = m.group(1, 2, 3, 4, 5, 6)
        s = _cn_dt(y1, mo1, d1, None, None)
        e = _cn_dt(y2 or y1, mo2, d2, None, None)
        if s:
            return s, e
    return None, None

def static_page_info(url, timeout=15):
    """staticActivity 静态页 -> (奖励正文, start_iso, end_iso)。带缓存。"""
    key = _static_page_key(url)
    if not key:
        return "", None, None
    hit = _STATIC_CACHE.get(key)
    if hit:
        return hit["text"], hit["start"], hit["end"]
    text, start, end = "", None, None
    try:
        html = _get_plain(url.split("?")[0], timeout=timeout)
        body = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html, flags=re.S | re.I)
        vis = re.sub(r"\s+", " ", H.unescape(re.sub(r"<[^>]+>", " ", body)))
        # staticActivity 的标题/规则常内嵌在 <script> 里（页面可见文本为空），
        # 需从原始 HTML 再提取一遍中文与 Q币 词，作为奖池证据
        emb = " ".join(re.findall(r"[\u4e00-\u9fa5]{2,30}|[Qq]币|[Qq][Bb]", html))
        text = (vis + " " + " ".join(dict.fromkeys(emb.split()))).strip()
        start, end = _cn_time_range(vis)
        if not start:
            start, end = _cn_time_range(text)
    except Exception:
        pass
    text = text[:4000]
    _STATIC_CACHE[key] = {"text": text, "start": start, "end": end}
    return text, start, end

if __name__ == "__main__":
    load_device()
    items = collect({}, {"endpoints": {"pages": DEFAULT_PAGES}})
    print(f"共 {len(items)} 条:")
    for it in items[:30]:
        print(f"  [{it['id']}] {it['title'][:40]} | start={it['startTime']} end={it['endTime']}")
        print(f"       {it['url'][:110]}")
        if it["summary"]: print(f"       sum: {it['summary'][:80]}")
