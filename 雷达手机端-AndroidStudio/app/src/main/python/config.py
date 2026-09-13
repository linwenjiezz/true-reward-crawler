# -*- coding: utf-8 -*-
"""游戏活动雷达 · 配置层（Android / Chaquopy 版）
================================================
- 复用单文件版的游戏库、福利关键词、MiniSoup 选择器引擎
- 配置改从 assets/conf/{config,sources}.json 读取（radar_main 第一次启动时会
  把 assets/conf 拷到 RADAR_HOME/conf；之后以 RADAR_HOME/conf 为准）
- 仅依赖标准库（配置用内置 json，无需 pyyaml / FastAPI / uvicorn）
- R42：游戏库/关键词按用户 2026-09-10 的最新口径重写：
    * 严格按用户的 25 款腾讯游戏清单抓，其它一律不要；
    * 关键词只认「现实价值」（Q币/耳机/键盘/现金/手办/CDK/周边/京东卡），
      以前混在里面的游戏内行为（签到/皮肤/点券/金币/钻石/...)全部挪到噪声。
"""

import copy
import json
import os
import re
import ssl
import threading
import urllib.parse
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser

# 部分站点证书链不完整，放宽校验（仅用于抓取公开页面）
try:
    ssl._create_default_https_context = ssl._create_unverified_context
except Exception:
    pass

APP_NAME = "游戏活动雷达"
VERSION = "1.0.0"
PORT = 8848
CN_TZ = timezone(timedelta(hours=8))


def now_cn():
    return datetime.now(CN_TZ)


def iso(dt):
    """datetime -> JS 能直接 new Date() 的 ISO 字符串"""
    if not dt:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=CN_TZ)
    return dt.isoformat()


def abs_url(u, base=""):
    """把相对路径/协议相对地址补全成绝对 URL"""
    if not u:
        return ""
    u = u.strip()
    if u.startswith("//"):
        return "https:" + u
    if u.startswith("http://") or u.startswith("https://"):
        return u
    if u.startswith("javascript:") or u.startswith("#"):
        return ""
    if base:
        return urllib.parse.urljoin(base, u)
    return u


# ============================================================================
#  R42：游戏库 —— 只按用户的 25 款腾讯清单抓，其它一律排除
# ============================================================================

# 用户 2026-09-10 给的腾讯游戏清单。顺序与清单原顺序一致。
# 之前内置的 18 个（王者荣耀…黎明觉醒）+ 用户清单里未列（高能英雄/天涯明月刀/...
# 等）全部删除。"王者荣耀"包含王者荣耀 IP 自走棋 = 王者万象棋。
TENCENT_GAMES = [
    "王者荣耀",          # MOBA
    "和平精英",          # 战术竞技
    "使命召唤手游",      # FPS
    "暗区突围",          # 硬核射击
    "三角洲行动",        # 战术射击
    "无畏契约",          # 英雄战术射击
    "地下城与勇士：起源",# 动作格斗（DNF 手游）
    "穿越火线枪战王者",  # FPS
    "金铲铲之战",        # 自走棋
    "王者万象棋",        # 自走棋（王者荣耀 IP 衍生，原清单别名）
    "QQ飞车",            # 竞速赛车
    "元梦之星",          # 休闲派对
    "妄想山海",          # 开放世界
    "洛克王国：世界",    # 开放世界养成
    "逆战：未来",        # 近未来 FPS
    "失控进化",          # 生存对抗（Rust 国服授权）
    "部落冲突",          # 策略塔防
    "火影忍者手游",      # 格斗动作
    "荒野乱斗",          # 多人休闲竞技
    "天天酷跑",          # 休闲跑酷
    "卡厄思梦境",        # Roguelite 卡牌（腾讯代理）
    "冒险岛：枫之传说",  # 横版 MMORPG
    "完美世界",          # 东方玄幻 MMORPG
    "天龙八部手游",      # 武侠 MMORPG
    "新天龙八部手游",    # 武侠 MMORPG（续作）
]

# 全量识别库（detect_game 按最长别名优先匹配）。
# 覆盖：王者荣耀 IP 全家桶 / 使命召唤跨厂联动 / 部落冲突英文 / 冒险岛英文 /
# DNF 中英文 / 王者万象棋与王者荣耀共存时的优先级。
GAME_ALIASES = {
    "王者荣耀":              ["王者荣耀", "国服王者"],
    "和平精英":              ["和平精英", "pubgm", "pubg mobile"],
    "使命召唤手游":          ["使命召唤手游", "使命召唤", "codm", "cod mobile",
                             "call of duty mobile", "call of duty"],
    "暗区突围":              ["暗区突围", "暗区", "arena breakout"],
    "三角洲行动":            ["三角洲行动", "三角洲", "delta force"],
    "无畏契约":              ["无畏契约", "无畏契约手游", "valorant", "瓦罗兰特"],
    "地下城与勇士：起源":    ["地下城与勇士：起源", "地下城与勇士", "地下城与勇士手游",
                             "dnf手游", "dnf", "dnf origin"],
    "穿越火线枪战王者":      ["穿越火线枪战王者", "穿越火线手游", "穿越火线",
                             "cf手游", "cfm", "crossfire mobile"],
    "金铲铲之战":            ["金铲铲之战", "金铲铲", "tft"],
    "王者万象棋":            ["王者万象棋", "王者自走棋"],   # 用户原清单的"王者万象棋"
    "QQ飞车":                ["QQ飞车", "qq飞车", "qq飞车手游", "飞车手游"],
    "元梦之星":              ["元梦之星", "元梦"],
    "妄想山海":              ["妄想山海"],
    "洛克王国：世界":        ["洛克王国：世界", "洛克王国", "洛克王国手游"],
    "逆战：未来":            ["逆战：未来", "逆战未来", "逆战"],
    "失控进化":              ["失控进化", "rust"],   # Rust 国服授权
    "部落冲突":              ["部落冲突", "clash of clans", "coc"],
    "火影忍者手游":          ["火影忍者手游", "火影忍者", "火影", "naruto"],
    "荒野乱斗":              ["荒野乱斗", "brawl stars", "荒野乱斗手游"],
    "天天酷跑":              ["天天酷跑"],
    "卡厄思梦境":            ["卡厄思梦境", "卡厄思"],
    "冒险岛：枫之传说":      ["冒险岛：枫之传说", "枫之传说", "冒险岛",
                             "冒险岛手游", "maplestory"],
    "完美世界":              ["完美世界", "完美世界手游"],
    "天龙八部手游":          ["天龙八部手游", "天龙八部"],
    "新天龙八部手游":        ["新天龙八部手游", "新天龙八部"],
}

# R42：废弃「其它游戏」分区 —— 用户 2026-09-10 明确指示"只按清单抓"，
# 任何非清单里的活动一律过滤，不再给 OTHER_GAMES 兜底。
OTHER_GAMES = {}
NON_TENCENT_GAMES = OTHER_GAMES   # 兼容旧名字（engine 里 historical 引用）

# ----------------------------------------------------------------------------
# R42：奖励 / 福利关键词 —— 严格按用户口径
#   · **只保留**「现实价值」关键词（Q币 / 现金 / 耳机 / 键盘 / 手办 / 周边 /
#     京东卡 / CDK / 兑换码 / 激活码 / 话费 / 购物卡 / 红包 / 提现）。
#   · 之前混进来的「签到 / 预约 / 上线 / 公测 / 皮肤 / 点券 / 头像框 / 礼包 / 助力金」等
#     游戏内行为全部删除 → 它们从这一刻起就是「噪声」。
# ----------------------------------------------------------------------------
WELFARE_KW = [
    "q币", "Q币", "QB",                  # 现金等价物
    "现金", "红包", "微信红包", "提现", "现金红包",  # 真金白银
    "京东卡", "购物卡", "e卡", "话费",      # 通用购物/通信
    "周边", "手办", "公仔", "玩偶",          # 实物周边
    "耳机", "键盘", "鼠标",                 # 数码外设
    "兑换码", "激活码", "cdk", "CDK",      # 兑换凭证
    "奖池",                                # 奖池 = 有现实奖励活动的强信号
    "白嫖",                                # 用户自描述用语
]

REWARD_KW = list(WELFARE_KW) + [
    "限量", "限定",                         # 限量实体
    "周边", "手办", "公仔",                  # 重复保险
    "首充返现", "现金红包",                  # 现金类
]

# 活动类型关键词（用于 UI 分类标签，不影响噪声判定 —— R42）
TYPE_KW = {
    "新赛季": ["赛季", "s\\d{1,2}赛季"],
    "联动":   ["联动"],
    "新版本": ["新版本", "更新"],
    "上线":   ["上线", "首发", "发布"],
    "回归":   ["回归", "召回"],
    "新用户": ["新用户", "新人", "注册"],
    "红包":   ["红包", "现金红包", "微信红包", "压岁红包", "红包雨"],
    "礼包":   ["礼包", "礼包码", "cdk", "激活码", "兑换码", "礼包兑换"],
    "福利":   ["福利", "白嫖", "免费领", "免费送", "0元", "返利", "满减",
               "代金券", "兑换", "充值返利"],
}

DEFAULT_CONFIG = {
    "general": {
        "timezone": "Asia/Shanghai",
        "poll_interval": 600,
        "min_push_score": 45,
        "push_non_target": False,
        "quiet_hours": [[1, 7]],
        "reminders": [1440, 120, 10],
        "max_push_per_run": 8,
        "enrich_detail": True,
        "enrich_limit": 50,
    },
    "watch": {"games": list(TENCENT_GAMES) + list(OTHER_GAMES),
              "channels": [], "keywords_extra": []},
    "notify": {
        "bark": {"enabled": False, "key": "", "server": "https://api.day.app",
                 "level": "timeSensitive", "sound": "alarm", "group": "游戏活动雷达"},
        "wecom": {"enabled": False, "webhook": ""},
        "ntfy": {"enabled": False, "server": "https://ntfy.sh", "topic": "", "priority": "high"},
        "serverchan": {"enabled": False, "sendkey": ""},
        "pushplus": {"enabled": False, "token": "", "topic": ""},
        "telegram": {"enabled": False, "bot_token": "", "chat_id": ""},
        "dingtalk": {"enabled": False, "webhook": ""},
        "webhook": {"enabled": False, "url": "", "headers": {}},
    },
}

UA_MAP = {
    "ios": ("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 "
            "(KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"),
    "android": ("Mozilla/5.0 (Linux; Android 13; SM-G991B) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36"),
    "pc": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
           "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"),
}


# ============================================================================
#  2. MiniSoup —— 够用的 HTML 解析 + CSS 选择器子集
# ============================================================================
# 支持： tag / .class / #id / 后代空格 / 逗号分组 / a@href 取属性
# 不支持：子元素 >、伪类、属性选择器（本项目用不到，保持精简可靠）

VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input",
             "link", "meta", "param", "source", "track", "wbr"}


class El:
    __slots__ = ("tag", "attrs", "children", "parent")

    def __init__(self, tag, attrs=None, parent=None):
        self.tag = tag
        self.attrs = attrs or {}
        self.children = []
        self.parent = parent

    def get(self, key, default=None):
        return self.attrs.get(key, default)

    def cls(self):
        return (self.attrs.get("class") or "").split()

    @property
    def text(self):
        out = []
        _collect_text(self, out)
        return "".join(out)

    def iter_el(self):
        for c in self.children:
            if isinstance(c, El):
                yield c
                yield from c.iter_el()


def _collect_text(el, out):
    for c in el.children:
        if isinstance(c, str):
            out.append(c)
        else:
            if c.tag == "br":
                out.append("\n")
            _collect_text(c, out)


class MiniSoup(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = El("[document]")
        self.stack = [self.root]

    def handle_starttag(self, tag, attrs):
        el = El(tag, {k: (v or "") for k, v in attrs}, self.stack[-1])
        self.stack[-1].children.append(el)
        if tag not in VOID_TAGS:
            self.stack.append(el)

    def handle_startendtag(self, tag, attrs):
        el = El(tag, {k: (v or "") for k, v in attrs}, self.stack[-1])
        self.stack[-1].children.append(el)

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, 0, -1):
            if self.stack[i].tag == tag:
                del self.stack[i:]
                return

    def handle_data(self, data):
        if not data:
            return
        if data.strip():
            self.stack[-1].children.append(data)
        elif "\n" in data or "\r" in data:
            # 标签之间的换行要保留：好游快爆的活动块就靠它分隔
            self.stack[-1].children.append("\n")


class SimpleSel:
    """一个复合选择器片段，如 div.item.hot 或 a@href"""

    _TOKEN = re.compile(r"([a-zA-Z][\w-]*)|#([\w-]+)|\.([\w-]+)")

    def __init__(self, raw):
        self.attr = None
        s = raw.strip()
        if "@" in s:
            s, self.attr = s.split("@", 1)
        self.tag = None
        self.id = None
        self.classes = []
        for m in self._TOKEN.finditer(s):
            if m.group(1):
                self.tag = m.group(1).lower()
            elif m.group(2):
                self.id = m.group(2)
            elif m.group(3):
                self.classes.append(m.group(3))

    def match(self, el):
        if self.tag and el.tag != self.tag:
            return False
        if self.id and el.get("id") != self.id:
            return False
        cl = el.cls()
        for c in self.classes:
            if c not in cl:
                return False
        return bool(self.tag or self.id or self.classes)


def parse_html(html):
    s = MiniSoup()
    try:
        s.feed(html)
        s.close()
    except Exception:
        pass
    return s.root


def select(root, selector):
    """支持逗号分组的后代选择器，返回去重节点列表"""
    out, seen = [], set()
    for group in (selector or "").split(","):
        group = group.strip()
        if not group:
            continue
        seq = [SimpleSel(p) for p in group.split() if p.strip()]
        if not seq:
            continue
        for el in _descendants_match(root, seq):
            if id(el) not in seen:
                seen.add(id(el))
                out.append(el)
    return out


def _descendants_match(root, seq):
    out = []
    for el in root.iter_el():
        if seq[0].match(el):
            if len(seq) == 1:
                out.append(el)
            else:
                out.extend(_descendants_match(el, seq[1:]))
    return out


def pick_attr(el, selector, base_url=""):
    """按选择器取属性列表（最后一段支持 @attr）"""
    last = SimpleSel(selector.split()[-1])
    nodes = select(el, selector)
    if last.attr:
        vals = [abs_url(n.get(last.attr, ""), base_url) for n in nodes]
        return [v for v in vals if v]
    return [re.sub(r"\s+", " ", n.text).strip() for n in nodes if n.text.strip()]


# ============================================================================
#  3. 配置加载：JSON（config.json + sources.json）
# ============================================================================

# 运行期由 radar_main 通过环境变量注入；桌面调试时回退到 assets/conf
DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data")
DB_PATH = os.path.join(DATA_DIR, "radar.db")
CONFIG = copy.deepcopy(DEFAULT_CONFIG)
# SOURCES 始终是被「原地修改」的同一个列表对象：
#   engine.py 在导入时执行 `SOURCES = config.SOURCES` 拿到同一个对象引用，
#   之后任何 `load_config()` / 保存用户源 都必须用 `SOURCES[:] = ...` 原地改，
#   不能重新赋值，否则 engine 里的引用会过期。
BASE_SOURCES = []     # 来自 sources.yaml（打包内置）
USER_SOURCES = []     # 来自 user_sources.yaml（用户抓包导入）
SOURCES = []          # 合并后供引擎使用
_CONF_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "assets", "conf")


def _deep_merge(dst, src):
    for k, v in src.items():
        if isinstance(v, dict) and isinstance(dst.get(k), dict):
            _deep_merge(dst[k], v)
        else:
            dst[k] = v


def load_config(home=None):
    """根据 RADAR_HOME（或显式 home）加载 conf 目录下的 YAML。

    返回 conf 目录路径，供保存配置时使用。
    """
    global CONFIG, SOURCES, DATA_DIR, DB_PATH, _CONF_DIR
    home = home or os.environ.get("RADAR_HOME")
    if home:
        DATA_DIR = os.path.join(home, "data")
        DB_PATH = os.environ.get("RADAR_DB") or os.path.join(DATA_DIR, "radar.db")
        _CONF_DIR = os.path.join(home, "conf")
    # 兜底：home/conf 不存在时，回退到打包的 assets/conf
    # （桌面调试或设备端 assets 拷贝失败，都能用内置配置跑起来）
    if not os.path.isdir(_CONF_DIR):
        _bundled = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               "..", "assets", "conf")
        if os.path.isdir(_bundled):
            _CONF_DIR = _bundled
    os.makedirs(DATA_DIR, exist_ok=True)

    # --- config.yaml ---
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    cp = os.path.join(_CONF_DIR, "config.json")
    if os.path.exists(cp):
        try:
            with open(cp, "r", encoding="utf-8") as f:
                user = json.load(f) or {}
            for k, v in (user or {}).items():
                if isinstance(v, dict) and isinstance(cfg.get(k), dict):
                    _deep_merge(cfg[k], v)
                else:
                    cfg[k] = v
        except Exception:
            pass
    CONFIG = cfg

    # --- sources.yaml（内置/打包） ---
    sp = os.path.join(_CONF_DIR, "sources.json")
    BASE_SOURCES[:] = []
    if os.path.exists(sp):
        try:
            with open(sp, "r", encoding="utf-8") as f:
                sd = json.load(f) or {}
            BASE_SOURCES[:] = sd.get("sources") or []
        except Exception:
            BASE_SOURCES[:] = []

    # --- user_sources.yaml（用户抓包导入） ---
    _load_user_sources()

    # 合并（原地修改，保持列表对象引用不变）
    SOURCES[:] = list(BASE_SOURCES) + list(USER_SOURCES)

    CONFIG["_conf_dir"] = _CONF_DIR
    return _CONF_DIR


def _user_sources_path():
    return os.path.join(_CONF_DIR, "user_sources.json")


def _load_user_sources():
    """从 user_sources.yaml 读取用户抓包导入的源（原地修改 USER_SOURCES）。"""
    USER_SOURCES[:] = []
    p = _user_sources_path()
    if os.path.exists(p):
        try:
            with open(p, "r", encoding="utf-8") as f:
                ud = json.load(f) or {}
            USER_SOURCES[:] = ud.get("sources") or []
        except Exception:
            USER_SOURCES[:] = []


def save_user_sources():
    """把 USER_SOURCES 写回 user_sources.yaml。"""
    p = _user_sources_path()
    try:
        with open(p, "w", encoding="utf-8") as f:
            json.dump({"sources": USER_SOURCES}, f,
                      ensure_ascii=False, indent=2)
        return True
    except Exception:
        return False


def reload_sources():
    """改动源之后刷新 SOURCES（原地修改，保持引用不变）。"""
    SOURCES[:] = list(BASE_SOURCES) + list(USER_SOURCES)


def upsert_user_source(src):
    """新增或更新一个用户源（按 id 去重），写盘并刷新。返回是否成功。"""
    if not isinstance(src, dict) or not src.get("id"):
        return False
    for i, s in enumerate(USER_SOURCES):
        if s.get("id") == src["id"]:
            USER_SOURCES[i] = src
            break
    else:
        USER_SOURCES.append(src)
    ok = save_user_sources()
    reload_sources()
    return ok


def delete_user_source(sid):
    """删除一个用户源（仅限 user_sources 里的，不会动内置源）。返回是否成功。"""
    global USER_SOURCES
    before = len(USER_SOURCES)
    USER_SOURCES[:] = [s for s in USER_SOURCES if s.get("id") != sid]
    if len(USER_SOURCES) == before:
        return False
    ok = save_user_sources()
    reload_sources()
    return ok


def is_user_source(sid):
    return any(s.get("id") == sid for s in USER_SOURCES)


def conf_dir():
    return _CONF_DIR


def save_config():
    """把当前 CONFIG 写回 config.yaml（保留 sources.yaml 独立）。"""
    cp = os.path.join(_CONF_DIR, "config.json")
    payload = {k: v for k, v in CONFIG.items() if not k.startswith("_")}
    try:
        with open(cp, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        return True
    except Exception:
        return False


def load_user_games():
    """把 RADAR_HOME/conf/user_games.json 里的游戏名合并进 OTHER_GAMES。

    用户在前端「添加游戏」后，名字持久化到该文件；重启后端时这里把它加载回来，
    让手动新增的游戏在重启后依然保留在分区列表里。
    """
    try:
        gp = os.path.join(_CONF_DIR, "user_games.json")
        if not os.path.exists(gp):
            return
        with open(gp, "r", encoding="utf-8") as f:
            ud = json.load(f) or {}
        for name in (ud.get("games") or []):
            if name and name not in OTHER_GAMES and name not in TENCENT_GAMES:
                OTHER_GAMES[name] = [name]
    except Exception:
        pass


# 模块导入即加载一次（radar_main 已先设好环境变量）
try:
    load_config()
    load_user_games()
except Exception:
    pass
