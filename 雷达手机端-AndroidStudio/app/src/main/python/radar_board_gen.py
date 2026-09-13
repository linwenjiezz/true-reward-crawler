#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
活动雷达看板生成器（R56 双时间分区版）

功能：
- 读取三渠道真奖励活动表，提取 T0（创建/建页/上线）、T1（开始时间）
- 页面三区结构：
  ① 雷达速报：近 7 天内建页（T0）的活动，只显示紫色 T0，按 T0 最新在前；>8 条折叠可展开
  ② 吸顶工具栏：即时搜索 + 渠道 Tab + 只看新捕获 开关
  ③ 游戏分区 ×25：只显示白色 T1；分区/渠道组/活动行均按 T1 最新在前，
     新捕获的活动自动排最前；分区内按渠道分组（发丝线 + 渠道色标）
- 分区默认收起，有近 7 天新 T1 的分区自动展开并置顶（白色「新 T1」徽章）
- T2 结束时间不再上屏（数据保留在记录里）
- 渠道色彩：好游快爆=橙、4399=蓝、OPPO=绿；T0=紫（仅速报区使用）
- T0 铁律：只取各渠道自身源头痕迹，任何校对不改动 T0；T1 校验只作用于 OPPO 模糊开始
- 生成静态 HTML，带复制链接 / 打开按钮
"""

import hashlib
import html
import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

_SCRIPT_DIR = Path(__file__).parent
ROOT = Path(os.environ.get("RADAR_DATA", str(_SCRIPT_DIR)))  # 手机端→可写外部存储；桌面→脚本目录
ANCHOR_MONTH = "2026-09-01"
ANCHOR_DT = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone(timedelta(hours=8)))
NOW = datetime.now(tz=timezone(timedelta(hours=8)))
NEW_TTL_DAYS = 7
STATE_PATH = ROOT / "radar_state.json"

FRESH_DAYS = 7        # 速报窗口：T0 距今 7 天内
FLASH_PREVIEW = 8     # 速报直接显示条数，超出折叠

CHANNEL_COLORS = {
    "好游快爆": "#EF9F27",
    "4399": "#7FB3E8",
    "OPPO": "#3ECF8E",
}
PURPLE = "#B9AAF0"

# 已知 OPPO schema.js 时间与页面“活动时间”不一致时，以页面规则兜底覆盖。
# key: (channel, actId)
TIME_OVERRIDES = {
    ("OPPO", "20230105"): {"start": "2026-09-04T00:00:00+08:00"},
}


def apply_time_overrides(records):
    """对已知时间源头的错误/偏差做兜底覆盖。"""
    for r in records:
        url = r.get("url", "")
        if "actId=" not in url:
            continue
        act_id = url.split("actId=")[-1].split("&")[0]
        key = (r.get("channel"), act_id)
        if key in TIME_OVERRIDES:
            ov = TIME_OVERRIDES[key]
            if "start" in ov:
                r["t1"] = parse_time(ov["start"])
            if "end" in ov:
                r["t_end"] = parse_time(ov["end"])


def parse_hykb_slug_date(url: str):
    """从好游快爆 URL slug 中提取建页日期 T0"""
    # 常见格式：.../hykb_hd/xxxx20260902a437/...
    m = re.search(r"/(?:n/hykb_hd/|hykb/|n/hykb/)(?:[a-z]+)?(\d{4})(\d{2})(\d{2})[a-z]", url)
    if m:
        try:
            return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
        except Exception:
            pass
    # 非补零格式，如 shanhai2026810n420 -> 2026-08-10
    m = re.search(r"/(?:n/hykb_hd/|hykb/|n/hykb/)(?:[a-z]+)?(2026)(\d{1,2})(\d{1,2})[a-z]", url)
    if m:
        try:
            y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
            dt = datetime(y, mo, d, tzinfo=timezone(timedelta(hours=8)))
            return dt.strftime("%Y-%m-%d")
        except Exception:
            pass
    return None


def parse_time(v, default_year=2026):
    """统一解析各渠道时间字符串为带 +8 时区的 datetime"""
    if not v:
        return None
    v = str(v).strip()
    tz = timezone(timedelta(hours=8))
    # ISO 8601 with timezone
    if "T" in v:
        try:
            dt = datetime.fromisoformat(v.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=tz)
            return dt.astimezone(tz)
        except Exception:
            pass
    # "09-10 00:00" or "09-10 00:00:00" (no year, ambiguous, set year explicitly)
    for fmt in ("%m-%d %H:%M:%S", "%m-%d %H:%M"):
        try:
            dt = datetime.strptime(f"{default_year}-{v}", f"%Y-{fmt}")
            dt = dt.replace(tzinfo=tz)
            return dt
        except Exception:
            pass
    # "2026-09-10 00:00:00"
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(v, fmt).replace(tzinfo=tz)
            return dt
        except Exception:
            pass
    return None


def fmt_dt(dt):
    if dt is None:
        return "—"
    return dt.strftime("%m-%d %H:%M")


def fmt_date(dt):
    if dt is None:
        return "—"
    return dt.strftime("%m-%d")


def activity_id(rec):
    """生成活动唯一标识，优先使用 URL"""
    key = rec.get("url") or f"{rec.get('game','')}::{rec.get('channel','')}::{rec.get('title','')}"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]


def load_state():
    """读取新活动追踪状态"""
    if not STATE_PATH.exists():
        return {"version": 1, "activities": {}, "games": {}}
    try:
        data = json.load(open(STATE_PATH, encoding="utf-8"))
        if not isinstance(data, dict):
            return {"version": 1, "activities": {}, "games": {}}
        data.setdefault("activities", {})
        data.setdefault("games", {})
        return data
    except Exception:
        return {"version": 1, "activities": {}, "games": {}}


def save_state(state):
    """保存新活动追踪状态"""
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def load_channel():
    records = []

    # 好游快爆
    hykb = json.load(open(ROOT / "_hykb_table_v3.json", encoding="utf-8"))
    for bucket in ("sept_real", "aug_real_running"):
        for r in hykb.get(bucket, []):
            t0 = parse_hykb_slug_date(r.get("url", ""))
            t1 = parse_time(r.get("start"))
            t_end = parse_time(r.get("end"))
            records.append({
                "game": r.get("game", ""),
                "channel": "好游快爆",
                "title": r.get("title", ""),
                "url": r.get("url", ""),
                "reward": r.get("reward", ""),
                "t0": parse_time(t0) if t0 else None,
                "t0_src": "URL建页期",
                "t1": t1,
                "t_end": t_end,
            })

    # 4399
    t4399 = json.load(open(ROOT / "_4399_table_v3.json", encoding="utf-8"))
    for bucket in ("sept_real", "aug_real_running"):
        for r in t4399.get(bucket, []):
            # T0 = API stime（4399 自身边上线痕迹，绝不受校对影响）。
            # 详情页覆写过时间时 stime 存在 orig_start；未覆写时 start 本身就是 stime。
            t0 = parse_time(r.get("orig_start") or r.get("stime") or r.get("start"))
            t1 = parse_time(r.get("start"))
            t_end = parse_time(r.get("end"))
            records.append({
                "game": r.get("game", ""),
                "channel": "4399",
                "title": r.get("title", ""),
                "url": r.get("url", ""),
                "reward": r.get("reward", ""),
                "t0": t0,
                "t0_src": "API stime",
                "t1": t1,
                "t_end": t_end,
            })

    # OPPO
    oppo = json.load(open(ROOT / "_oppo_table_v3.json", encoding="utf-8"))
    for bucket in ("sept_real", "aug_real_running"):
        for r in oppo.get(bucket, []):
            # T0 取值链：create（提前建页痕迹）> schema_start（schema.js 建页配置时间）> start（旧数据兜底）
            t1 = parse_time(r.get("start"))
            create = r.get("create")
            schema_start = r.get("schema_start")
            if create:
                t0 = parse_time(create)
                t0_src = "schema.js 提前建页"
            elif schema_start:
                t0 = parse_time(schema_start)
                t0_src = "schema.js 建页配置"
            elif r.get("start"):
                t0 = t1
                t0_src = "schema.js 建页配置"
            else:
                t0 = None
                t0_src = "无"
            t_end = parse_time(r.get("end"))
            t1_src = r.get("t1_source", "")
            records.append({
                "game": r.get("game", ""),
                "channel": "OPPO",
                "title": r.get("title", ""),
                "url": r.get("url", ""),
                "reward": r.get("reward", ""),
                "t0": t0,
                "t0_src": t0_src,
                "t1": t1,
                "t1_src": t1_src,
                "t_end": t_end,
            })

    return records


def classify(rec):
    t1 = rec["t1"]
    t_end = rec["t_end"]
    if t1 is None:
        return "unknown", None
    if NOW < t1:
        delta = t1 - NOW
        return "upcoming", delta
    if t_end is None or NOW < t_end:
        return "running", None
    return "ended", None


def apply_new_state(records, state):
    """
    合并持久化状态（保留 first_seen 追踪供数据层使用）。
    页面视觉的「新」判定改用 T0 距今天数（fresh_t0），与 state 解耦。
    """
    activities = state.setdefault("activities", {})
    for r in records:
        aid = activity_id(r)
        r["_id"] = aid
        if aid not in activities:
            activities[aid] = {"first_seen": NOW.isoformat()}
        first_seen = parse_time(activities[aid].get("first_seen"), default_year=NOW.year)
        if first_seen is None:
            first_seen = NOW
            activities[aid]["first_seen"] = NOW.isoformat()
        r["first_seen"] = first_seen
        r["is_new"] = (NOW - first_seen).total_seconds() <= NEW_TTL_DAYS * 86400
    return state


# ---------------- HTML 生成 ----------------

def _ts(r, key, missing):
    dt = r.get(key)
    return int(dt.timestamp() * 1000) if dt else missing


def _row_attrs(r):
    """行级 data 属性：fresh、搜索文本（排序已在 Python 端固定为最新在前）"""
    text = " ".join(filter(None, [r["game"], r["title"], r["reward"], r["channel"]])).lower()
    return (f'data-ch="{html.escape(r["channel"])}" data-fresh="{1 if r["fresh_t0"] else 0}" '
            f'data-title="{html.escape(r["title"])}" data-text="{html.escape(text)}"')


def _row_actions(r):
    url = html.escape(r["url"])
    return (f'<span class="row-act"><button class="mini-copy" data-url="{url}" title="复制链接">⧉</button>'
            f'<a class="mini-open" href="{url}" target="_blank" rel="noopener" title="电脑打开">↗</a></span>')


def _times_html(r):
    """分区行只显示白色 T1（速报区才显示紫色 T0）"""
    t1s = fmt_date(r["t1"]) if r["t1"] else "—"
    return f'<span class="row-times"><span class="t1v">T1 {t1s}</span></span>'


def _flash_row(r, extra):
    c = CHANNEL_COLORS.get(r["channel"], "#9aa0a6")
    cls = " extra hidden" if extra else ""
    return f'''<div class="row flash-row{cls}">
        <span class="ch-dot" style="background:{c}"></span>
        <span class="row-game">{html.escape(r["game"])}</span>
        <span class="row-title"><span class="row-title-text">{html.escape(r["title"])}</span></span>
        <span class="row-times"><span class="t0v">T0 {fmt_date(r["t0"]) if r["t0"] else "—"}</span></span>
        {_row_actions(r)}
    </div>'''


def build_html(records):
    # 过滤：只保留 9 月起仍有效且当前未结束的活动
    filtered = [r for r in records if r["t_end"] and r["t_end"] >= ANCHOR_DT and r["t_end"] >= NOW]
    for r in filtered:
        status, delta = classify(r)
        r["status"] = status
        r["delta"] = delta
        # 速报/分区「新」判定：T0 距今 7 天内（T0 永不受校对影响）
        r["fresh_t0"] = bool(r["t0"] and (NOW - r["t0"]).total_seconds() <= FRESH_DAYS * 86400)

    stats_upcoming = sum(1 for r in filtered if r["status"] == "upcoming")
    stats_running = sum(1 for r in filtered if r["status"] == "running")

    # ---------- ① 速报区：近 7 天新捕获，按 T0 最新在前 ----------
    fresh = sorted([r for r in filtered if r["fresh_t0"]],
                   key=lambda r: -(r["t0"].timestamp()))
    flash_rows = [_flash_row(r, i >= FLASH_PREVIEW) for i, r in enumerate(fresh)]
    flash_extra = max(0, len(fresh) - FLASH_PREVIEW)
    if fresh:
        flash_more = (f'<button id="flash-more">展开其余 {flash_extra} 条 ▾</button>'
                      if flash_extra > 0 else "")
        flash_html = (f'<section id="flash"><p class="flash-title">近 {FRESH_DAYS} 天新捕获 · '
                      f'{len(fresh)} 条</p>{chr(10).join(flash_rows)}{flash_more}</section>')
    else:
        flash_html = (f'<section id="flash"><p class="flash-title flash-empty">'
                      f'近 {FRESH_DAYS} 天无新建页活动</p></section>')

    # ---------- ③ 游戏分区：按最新 T1 降序（新捕获的活动自动排最前） ----------
    BIG = 99999999999999

    def max_t1_ms(rows):
        return max((_ts(r, "t1", 0) for r in rows), default=0)

    games = sorted({r["game"] for r in filtered},
                   key=lambda g: -max_t1_ms([r for r in filtered if r["game"] == g]))

    sections = []
    for g in games:
        rows = [r for r in filtered if r["game"] == g]
        # 「新」判定（分区层）：T1 距今 7 天内 → 自动展开置顶 + 白色「新 T1」徽章
        g_fresh = [r for r in rows if r["t1"] and (NOW - r["t1"]).total_seconds() <= FRESH_DAYS * 86400]
        collapsed = "" if g_fresh else " collapsed"
        new_badge = ""
        if g_fresh:
            latest_t1 = max(r["t1"] for r in g_fresh)
            new_badge = f'<span class="new-t1">新 T1 {fmt_date(latest_t1)}</span>'

        # 渠道分组：按该渠道最新 T1 降序
        ch_names = sorted({r["channel"] for r in rows},
                          key=lambda c: -max_t1_ms([r for r in rows if r["channel"] == c]))
        groups_html = []
        for c in ch_names:
            c_rows = [r for r in rows if r["channel"] == c]
            color = CHANNEL_COLORS.get(c, "#9aa0a6")
            rows_html = []
            for r in sorted(c_rows, key=lambda x: -_ts(x, "t1", 0)):
                rows_html.append(f'''<div class="row" {_row_attrs(r)}>
                    <span class="ch-dot" style="background:{color}"></span>
                    <span class="row-title"><span class="row-title-text">{html.escape(r["title"])}</span></span>
                    {_times_html(r)}
                    {_row_actions(r)}
                </div>''')
            groups_html.append(f'''<div class="ch-group" data-maxt1="{max_t1_ms(c_rows)}">
                <p class="ch-label" style="color:{color}">{c} <span class="ch-cnt">{len(c_rows)}</span></p>
                {chr(10).join(rows_html)}
            </div>''')

        sections.append(f'''<section class="game-sec{collapsed}" data-game="{html.escape(g)}" data-maxt1="{max_t1_ms(rows)}">
            <div class="sec-head">
                <span class="sec-name">{html.escape(g)}</span>
                <span class="sec-cnt">{len(rows)}</span>
                {new_badge}
                <span class="sec-toggle">收起 ▴</span>
            </div>
            <div class="sec-body">{chr(10).join(groups_html)}</div>
        </section>''')

    sections_html = "\n".join(sections)

    # ---------- ② 工具栏：搜索 + 排序 + 渠道 Tab + 只看新T0 ----------
    ch_counts = {c: sum(1 for r in filtered if r["channel"] == c)
                 for c in ("好游快爆", "4399", "OPPO")}
    tabs = [f'<button class="ch-tab active" data-ch="">全部 {len(filtered)}</button>']
    for c in ("好游快爆", "4399", "OPPO"):
        tabs.append(f'<button class="ch-tab" data-ch="{c}" style="color:{CHANNEL_COLORS[c]}">'
                    f'{c} {ch_counts[c]}</button>')
    tabs_html = "\n".join(tabs)

    css = '''
        :root {
            --bg: #0d0f13; --surface: #11141a; --line: #1e222b; --line-2: #171a21;
            --text: #e8eaf0; --text-2: #c9cedb; --text-3: #6b7385; --text-4: #4a5060;
            --border: #2a2f3a; --purple: #B9AAF0;
        }
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "PingFang SC", "Microsoft YaHei", sans-serif;
            background: var(--bg); color: var(--text); line-height: 1.55;
            padding: 20px 16px 60px; min-height: 100vh;
        }
        .wrap { max-width: 880px; margin: 0 auto; }
        .page-head { display:flex; align-items:baseline; gap:10px; }
        h1 { font-size: 1.15rem; font-weight: 600; letter-spacing: 0.01em; }
        .sub { color: var(--text-4); font-size: 0.75rem; margin-left: auto; }
        .hr { height: 1px; background: var(--line); margin: 12px 0 14px; }

        /* ① 速报 */
        .flash-title { color: var(--purple); font-size: 0.8rem; letter-spacing: 2px; margin-bottom: 6px; }
        .flash-title.flash-empty { color: var(--text-4); letter-spacing: 0; }
        #flash-more {
            display:block; width:100%; margin-top:8px; padding:7px 0;
            background:none; border:1px dashed var(--border); border-radius:8px;
            color: var(--text-3); font-size:0.78rem; cursor:pointer;
        }
        #flash-more:hover { color: var(--text-2); border-color: var(--text-4); }

        /* ② 吸顶工具栏 */
        .toolbar {
            position: sticky; top: 0; z-index: 50;
            background: var(--surface); border: 1px solid #22262f; border-radius: 10px;
            padding: 9px 10px; margin: 16px 0 6px;
        }
        .tb-row1 { display:flex; gap:8px; margin-bottom:8px; }
        #q {
            flex:1; background:none; border:1px solid var(--border); border-radius:8px;
            color: var(--text); font-size:0.85rem; padding:7px 12px; outline:none;
        }
        #q:focus { border-color: var(--purple); }
        #q::placeholder { color: var(--text-4); }
        .tb-row2 { display:flex; gap:14px; align-items:center; flex-wrap:wrap; }
        .ch-tab {
            background:none; border:none; cursor:pointer; font-size:0.82rem;
            color: var(--text-3); padding:2px 0 4px; border-bottom:2px solid transparent;
        }
        .ch-tab.active { border-bottom-color: currentColor; }
        .ch-tab:hover { color: var(--text-2); }
        .fresh-toggle { margin-left:auto; display:flex; align-items:center; gap:6px; color:var(--text-3); font-size:0.8rem; cursor:pointer; }
        .fresh-toggle input { accent-color: var(--purple); }

        /* ③ 分区清单 */
        .game-sec { margin-top: 14px; }
        .game-sec.hidden, .ch-group.hidden, .row.hidden { display: none; }
        .sec-head { display:flex; align-items:center; gap:9px; padding:8px 0 6px; cursor:pointer; user-select:none; }
        .sec-name { font-size: 1rem; font-weight: 600; }
        .sec-cnt { color: var(--text-4); font-size: 0.78rem; }
        .new-t1 {
            color: var(--text); font-size: 0.68rem;
            background: rgba(255,255,255,.09); padding: 1px 8px; border-radius: 5px;
        }
        .sec-toggle { margin-left:auto; color: var(--text-4); font-size: 0.72rem; }
        .game-sec.collapsed:not(.search-open) .sec-body { display: none; }
        .game-sec.collapsed .sec-toggle::after { content: ""; }
        .game-sec.collapsed .sec-toggle { color: var(--text-4); }

        .ch-group { border-left: 1px solid var(--line); margin-left: 3px; }
        .ch-label { font-size: 0.75rem; padding: 7px 0 1px 14px; }
        .ch-cnt { color: var(--text-4); font-size: 0.7rem; }

        .row {
            display:flex; align-items:center; gap:10px;
            padding: 8px 0 8px 14px; border-bottom: 1px solid #14161c;
        }
        .flash-row { padding: 8px 0; border-bottom: 1px solid var(--line-2); }
        .ch-dot { width:6px; height:6px; border-radius:50%; flex-shrink:0; }
        .row-game { font-weight:600; font-size:0.88rem; flex-shrink:0; }
        .row-title { flex:1; min-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
        .row-title-text { color: var(--text-2); font-size: 0.86rem; }
        .row-times { flex-shrink:0; font-size:0.8rem; font-variant-numeric: tabular-nums; }
        .t0v { color: var(--purple); }
        .t1v { color: var(--text-2); }
        .sep { color: var(--text-4); margin: 0 4px; }
        .row-act { flex-shrink:0; display:flex; gap:2px; opacity:.5; }
        .row:hover .row-act { opacity:1; }
        .mini-copy, .mini-open {
            background:none; border:none; color:var(--text-3); cursor:pointer;
            font-size:0.85rem; padding:2px 5px; text-decoration:none; border-radius:5px;
        }
        .mini-copy:hover, .mini-open:hover { color:var(--text); background:rgba(255,255,255,.06); }
        mark.hl { background: rgba(185,170,240,.28); color: var(--purple); border-radius:3px; padding:0 2px; }

        .legend {
            margin-top: 30px; padding: 14px 16px;
            border-top: 1px solid var(--line);
            color: var(--text-4); font-size: 0.78rem; line-height: 1.8;
        }
        .legend strong { color: var(--text-2); }
        .toast {
            position: fixed; bottom: 24px; left: 50%;
            transform: translateX(-50%) translateY(100px);
            background: var(--surface); color: var(--purple);
            border: 1px solid rgba(185,170,240,.3);
            padding: 10px 22px; border-radius: 999px; font-weight: 600; font-size: 0.85rem;
            opacity: 0; transition: all .3s; z-index: 100;
        }
        .toast.show { transform: translateX(-50%) translateY(0); opacity: 1; }
        @media (max-width: 560px) {
            .row-game { max-width: 30vw; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
            .row { gap: 7px; padding-left: 10px; }
        }
    '''

    js = '''
        var activeChannel = "";
        function esc(s){return s.replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;");}
        function highlight(row,q){
            var el=row.querySelector(".row-title-text"); if(!el) return;
            var raw=row.dataset.title||"";
            var low=raw.toLowerCase(); var i=low.indexOf(q);
            if(i<0){el.textContent=raw;return;}
            el.innerHTML=esc(raw.slice(0,i))+"<mark class='hl'>"+esc(raw.slice(i,i+q.length))+"</mark>"+esc(raw.slice(i+q.length));
        }
        function unhighlight(row){
            var el=row.querySelector(".row-title-text"); if(!el) return;
            el.textContent=row.dataset.title||"";
        }
        function applyFilters(){
            var q=document.getElementById("q").value.trim().toLowerCase();
            var freshOnly=document.getElementById("freshOnly").checked;
            document.querySelectorAll(".row:not(.flash-row)").forEach(function(row){
                var ok=(!activeChannel||row.dataset.ch===activeChannel)
                    &&(!freshOnly||row.dataset.fresh==="1")
                    &&(!q||row.dataset.text.indexOf(q)>=0);
                row.classList.toggle("hidden",!ok);
                if(ok&&q){highlight(row,q);}else{unhighlight(row);}
            });
            document.querySelectorAll(".ch-group").forEach(function(g){
                g.classList.toggle("hidden",!g.querySelector(".row:not(.hidden)"));
            });
            document.querySelectorAll(".game-sec").forEach(function(s){
                var has=!!s.querySelector(".row:not(.hidden)");
                s.classList.toggle("hidden",!has);
                s.classList.toggle("search-open",!!(q&&has));
            });
        }
        // 排序已在生成时固定：速报按 T0 最新在前、分区按 T1 最新在前
        // 工具栏事件
        document.getElementById("q").addEventListener("input",applyFilters);
        document.getElementById("freshOnly").addEventListener("change",applyFilters);
        document.querySelectorAll(".ch-tab").forEach(function(t){
            t.addEventListener("click",function(){
                document.querySelectorAll(".ch-tab").forEach(function(x){x.classList.remove("active");});
                t.classList.add("active");
                activeChannel=t.dataset.ch;
                applyFilters();
            });
        });
        // 分区收起/展开
        document.querySelectorAll(".sec-head").forEach(function(h){
            h.addEventListener("click",function(){h.closest(".game-sec").classList.toggle("collapsed");});
        });
        // 速报折叠展开
        var fmore=document.getElementById("flash-more");
        if(fmore){
            fmore.addEventListener("click",function(){
                var ex=[].slice.call(document.querySelectorAll("#flash .row.extra"));
                var showing=ex.length&&ex[0].classList.contains("hidden");
                ex.forEach(function(r){r.classList.toggle("hidden",!showing);});
                fmore.textContent=showing?("收起 ▴"):("展开其余 "+ex.length+" 条 ▾");
            });
        }
        // 复制链接
        function fallbackCopy(text){
            var ta=document.createElement("textarea");
            ta.value=text; ta.style.position="fixed"; ta.style.opacity="0";
            document.body.appendChild(ta); ta.select();
            try{document.execCommand("copy");showToast();}catch(err){}
            document.body.removeChild(ta);
        }
        function showToast(){
            var t=document.getElementById("toast");
            t.classList.add("show");
            setTimeout(function(){t.classList.remove("show");},1800);
        }
        document.addEventListener("click",function(e){
            var btn=e.target.closest(".mini-copy");
            if(!btn) return;
            var url=btn.getAttribute("data-url");
            if(!url) return;
            if(navigator.clipboard&&navigator.clipboard.writeText){
                navigator.clipboard.writeText(url).then(showToast).catch(function(){fallbackCopy(url);});
            }else{fallbackCopy(url);}
        });
    '''

    html_content = f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>活动雷达 · 三渠道真奖励</title>
    <style>{css}</style>
</head>
<body>
    <div class="wrap">
        <div class="page-head">
            <h1>游戏活动雷达</h1>
            <span class="sub">{NOW.strftime('%Y-%m-%d %H:%M')} 更新 · {len(filtered)} 活动 · 即将开始 {stats_upcoming} · 进行中 {stats_running}</span>
        </div>
        <div class="hr"></div>

        {flash_html}

        <div class="toolbar">
            <div class="tb-row1">
                <input id="q" type="text" placeholder="搜游戏 / 活动 / 奖励关键词…">
            </div>
            <div class="tb-row2">
                {tabs_html}
                <label class="fresh-toggle"><input type="checkbox" id="freshOnly"> 只看新捕获</label>
            </div>
        </div>

        <main id="sections">
            {sections_html}
        </main>

        <div class="legend">
            <strong>图例说明</strong><br>
            · <span style="color:var(--purple)">紫色 T0</span> 只出现在顶部速报（创建/建页信号，只取各渠道自身源头痕迹，任何校对都不会改动 T0）：好游快爆 URL 建页期 / 4399 API stime / OPPO schema.js 建页配置（早于页面规则时为「提前建页」）<br>
            · 下方游戏分区只显示<span style="color:var(--text-2)">白色 T1</span>（开始时间）；渠道 = 圆点颜色（橙=好游快爆、蓝=4399、绿=OPPO）；T2 结束时间已收进数据不在页面显示<br>
            · 两区排序：速报按 T0 最新在前；分区/渠道组/活动行均按 T1 最新在前，新捕获的活动自动排到最前<br>
            · 分区头「新 T1」徽章 = 该游戏有近 {FRESH_DAYS} 天内开始的活动（自动展开置顶）；其余分区默认收起，点击分区头展开/收起<br>
            · 搜索、渠道 Tab、只看新捕获可叠加使用；悬停行尾 ⧉ 复制链接、↗ 电脑打开<br>
            · 仅 OPPO「即日起」类模糊 T1 会做跨渠道校验（结果记录在数据字段 t1_source 中，页面不显示）
        </div>
    </div>
    <div class="toast" id="toast">链接已复制</div>
    <script>{js}</script>
</body>
</html>
'''
    return html_content


def main():
    records = load_channel()
    apply_time_overrides(records)
    state = load_state()
    state = apply_new_state(records, state)
    save_state(state)
    html_content = build_html(records)
    out_path = ROOT / "radar_board.html"
    out_path.write_text(html_content, encoding="utf-8")
    print(f"已生成看板：{out_path}")
    print(f"当前时间：{NOW.strftime('%Y-%m-%d %H:%M')}")


if __name__ == "__main__":
    main()
