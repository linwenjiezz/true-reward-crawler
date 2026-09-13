# -*- coding: utf-8 -*-
"""OPPO游戏中心 9月活动采集 v3
=====================================================
按用户要求：OPPO 单独一条完整流程，源头时间/关键词/奖励提取方法单独适配。

OPPO 源特殊性（与快爆/4399 截然不同）：
  · 活动卡 title 多为 "XX 活动"，desc 是模板/空；
  · 活动详情页 index.html 是 JS 壳，奖励规则写在 js/schema-*.js 里；
  · 同一活动被不同入口（detail_h5 / c=0 / adtag 等）重复返回，必须按 actId/uActId 去重。
  · schema.js timeRange 可能是「提前建页」痕迹；页面规则里的「活动时间」才是真实 T1。

所以 OPPO 流程：
  1) 抓详情页活动卡列表（protostuff 二进制）
  2) 用 schema.js 补时间并与页面规则交叉校验（oppo_feed.enrich_dates_v2）：
     若 schema.js start 明显早于页面规则，则前者归为 create(T0)，后者为 start(T1)；
     若一致或页面规则缺失，则以 schema.js 为 start。
  3) 用 schema.js 提取奖励正文（oppo_feed.enrich_reward_text）
  4) reward_kind 以 schema.js 奖励文本为主、index.html 正文为辅
  5) 按 actId/uActId 去重
  6) R51 跨渠道 T1 校验：对「即日起」等模糊开始的 OPPO 活动，向 4399/快爆 同游戏
     真奖励活动借用/交叉验证 T1（用户2026-09-13 口径：开始时间几乎一致，仅建页期不同）。

输出：
  _oppo_sept_v2.json       原始活动条目
  _oppo_table_v3.json      {sept_real, aug_real_running, sept_noise}
"""
import json, os, re, sys, html as H, urllib.request, gzip
from datetime import datetime, timezone, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # 依赖模块与本脚本同目录（可移植）
os.chdir(os.path.dirname(os.path.abspath(__file__)))  # 输出文件固定落在脚本目录
import config
import oppo_feed
from reward_classify import reward_kind, matched_noise

CN = timezone(timedelta(hours=8))
NOW = datetime.now(CN).replace(microsecond=0)
# 收录窗口（2026-09-12 用户口径）：2026年8月 ~ 今天（含窗口内已结束活动）
WIN_START = datetime(2026, 8, 1, tzinfo=CN)
HERE = os.path.dirname(os.path.abspath(__file__))
APP_IDS_PATH = os.path.join(HERE, "oppo_app_ids.json")

# 25款腾讯游戏规范名（与config一致）
GAMES = list(config.TENCENT_GAMES)

# 游戏别名 -> 规范名，按最长优先
ALIAS = sorted(((a, g) for g, als in config.GAME_ALIASES.items() for a in als),
               key=lambda t: -len(t[0]))
# 排除短语：避免《王者荣耀世界》误归王者荣耀
GAME_EXCLUDE = {"王者荣耀": ["王者荣耀世界"],
                "王者万象棋": []}


def match_game(title):
    for a, g in ALIAS:
        if a in title:
            if any(x in title for x in GAME_EXCLUDE.get(g, ())):
                continue
            return g
    return None


def load_app_ids():
    if os.path.exists(APP_IDS_PATH):
        return json.load(open(APP_IDS_PATH, encoding="utf-8"))
    return {}


def save_app_ids(mapping):
    json.dump(mapping, open(APP_IDS_PATH, "w", encoding="utf-8"), ensure_ascii=False, indent=1)


def resolve_all():
    mapping = load_app_ids()
    for g in GAMES:
        if g in mapping and mapping[g]:
            continue
        try:
            aid = oppo_feed.resolve_app_id(g)
            mapping[g] = aid
            print(f"  resolve {g} -> {aid}")
        except Exception as e:
            print(f"  resolve {g} ERR {e}")
    save_app_ids(mapping)
    return mapping


# ---------- 页面正文提取（OPPO nvwa/staticActivity 页面） ----------
UA = ("Mozilla/5.0 (Linux; Android 13; SM-G991B) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36")

def get_text(url, timeout=12):
    """index.html 可能只有壳；这里仅作辅助，主奖励文本从 schema.js 提取。"""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "text/html,*/*"})
        raw = urllib.request.urlopen(req, timeout=timeout).read()
        if raw[:2] == b"\x1f\x8b":
            try: raw = gzip.decompress(raw)
            except Exception: pass
        s = raw.decode("utf-8", "replace")
        s = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", s, flags=re.S | re.I)
        txt = H.unescape(re.sub(r"<[^>]+>", " ", s))
        return re.sub(r"\s+", " ", txt).strip()[:3000]
    except Exception:
        return ""


# ---------- 时间解析 ----------
def parse_iso(s):
    if not s: return None
    try:
        return datetime.fromisoformat(s)
    except Exception:
        return None


def parse_start_any(s):
    """统一解析跨渠道 start 字段：ISO（快爆）或 'MM-DD HH:MM'（4399）。
    年份动态推断（跨年活动兜底），返回带 +8 时区的 datetime。"""
    if not s:
        return None
    s = str(s).strip()
    if "T" in s or s[:5].count("-") >= 2:        # ISO（含 2026-09-10T00:00）
        try:
            return datetime.fromisoformat(s).astimezone(CN)
        except Exception:
            pass
    m = re.match(r"(\d{2})-(\d{2})[ T](\d{2}):(\d{2})(?::(\d{2}))?", s)
    if not m:
        return None
    try:
        y = NOW.year
        d = datetime(y, int(m.group(1)), int(m.group(2)),
                     int(m.group(3)), int(m.group(4)),
                     int(m.group(5)) if m.group(5) else 0, tzinfo=CN)
        if (d - NOW).days > 183:                  # 未来超半年 → 上一年
            d = d.replace(year=y - 1)
        return d
    except Exception:
        return None


# ---------------- R51：跨渠道 T1 校验（OPPO「即日起」类模糊开始） ----------------
# 用户2026-09-13 口径：OPPO 大量活动页面规则只写「即日起」，无具体开始日期；
# 但同一游戏在 4399 / 快爆 的真奖励活动开始时间「几乎一致」（仅建页期/提前建页
# 时间不同）。因此以另外两渠道同游戏真奖励活动的 T1 作为交叉校验基准：
#   · 自身无 start（schema.js 也无）→ 借别渠道同游戏最早真奖励 T1（须在过去60天内）
#   · 自身有 start（schema.js）→ 与别渠道比对：±3天内=已交叉验证；差异>3天=未验证（标黄待核）
#   · 纯「即日起」且别渠道也无数据 → 以采集日作为估计（明确标记 now_est）
_CROSS_WINDOW_DAYS = 3          # 跨渠道 T1 可接受的偏差（天）
_BORROW_MAX_AGE_DAYS = 60       # 借用的别渠道 T1 距今天的最大年龄（避免借到过期活动）


def build_cross_channel_ref():
    """从 4399 / 快爆 分组表（real 组）构建「游戏 -> 最早真奖励 T1」基准。
    返回 {game: (start_dt, channel)}。文件缺失则跳过（OPPO 脚本可独立运行）。"""
    ref = {}
    for ch, fn in (("4399", "_4399_table_v3.json"), ("快爆", "_hykb_table_v3.json")):
        p = os.path.join(HERE, fn)
        if not os.path.exists(p):
            continue
        try:
            d = json.load(open(p, encoding="utf-8"))
        except Exception:
            print(f"  cross_ref {fn} 读取失败，跳过")
            continue
        for bucket in ("sept_real", "aug_real_running"):
            for r in d.get(bucket, []) or []:
                s = parse_start_any(r.get("start"))
                if not s:
                    continue
                g = r.get("game")
                if g not in ref or s < ref[g][0]:
                    ref[g] = (s, ch)
    return ref


def apply_cross_channel_t1(rows, ref, now):
    """就地补全 OPPO 模糊开始（_vague_rule=True）活动的 T1，并打 t1_source 标记。
    返回 (rows, stats) —— stats 用于日志汇总。"""
    stats = {"borrowed": 0, "validated": 0, "unverified": 0, "now_est": 0, "schema_only": 0}
    for r in rows:
        if not r.get("_vague_rule"):
            continue
        g = r.get("game")
        own = parse_iso(r.get("start"))
        rec = ref.get(g)
        if own is None:
            # 自身无源头 start → 借别渠道同游戏 T1（须在进行中窗口内）
            if rec and rec[0] <= now and (now - rec[0]).days <= _BORROW_MAX_AGE_DAYS:
                r["start"] = rec[0].isoformat()
                r["t1_source"] = "cross:" + rec[1]
                r["t1_borrowed"] = True
                stats["borrowed"] += 1
            else:
                # 别渠道也无据 → 以采集日作为「即日起」估计（明确标记为估计）
                r["start"] = now.isoformat()
                r["t1_source"] = "now_est"
                r["t1_borrowed"] = True
                stats["now_est"] += 1
        else:
            # 自身有 schema.js start → 与别渠道交叉校验
            if rec:
                diff = abs((own - rec[0]).total_seconds())
                if diff <= _CROSS_WINDOW_DAYS * 86400:
                    r["t1_source"] = "schema+cross_validated"
                    stats["validated"] += 1
                else:
                    r["t1_source"] = "schema_only_unverified"
                    r["t1_conflict"] = rec[0].isoformat() + "/" + rec[1]
                    stats["unverified"] += 1
            else:
                r["t1_source"] = "schema_only"
                stats["schema_only"] += 1
    return rows, stats


# ---------------- R54：OPPO T1 共识校对（快爆+4399 同 T1 → OPPO 按它们填） ----------------
# 用户2026-09-13 口径：若好游快爆与 4399 对同游戏活动给出**相同的 T1**，
# 则 OPPO 的 T1 也按这个共识时间填（仅当 OPPO 自身 T1 与共识不同才覆写）。
# 铁律：校对只动 T1，T0（create/schema_start）绝不参与、绝不修改。
# 匹配精度：同游戏 + T1 日期一致 = 共识；覆写时要求结束日期也一致（±1天），
# 避免把同游戏另一条活动的开始时间错套过来；结束对不上的只标注不覆写。
_T2_MATCH_DAYS = 1              # 结束日期匹配容差（天）


def build_consensus_ref():
    """从 4399 / 快爆 分组表（real 组）构建「游戏 -> 共识 (T1, T2) 列表」。
    共识定义：同一游戏在两渠道都存在相同 T1 日期的真奖励活动。
    返回 {game: [(t1_dt, end_dt), ...]}，按 T1 去重（同日取 4399 的时间，其次快爆）。"""
    per_game = {}   # game -> {"4399": {date: (t1_dt, end_dt)}, "快爆": {...}}
    for ch, fn in (("4399", "_4399_table_v3.json"), ("快爆", "_hykb_table_v3.json")):
        p = os.path.join(HERE, fn)
        if not os.path.exists(p):
            continue
        try:
            d = json.load(open(p, encoding="utf-8"))
        except Exception:
            continue
        for bucket in ("sept_real", "aug_real_running"):
            for r in d.get(bucket, []) or []:
                s = parse_start_any(r.get("start"))
                if not s:
                    continue
                e = parse_start_any(r.get("end"))
                per_game.setdefault(r.get("game"), {}).setdefault(ch, {})[s.date()] = (s, e)
    cons = {}
    for g, chs in per_game.items():
        if "4399" not in chs or "快爆" not in chs:
            continue
        shared = set(chs["4399"]) & set(chs["快爆"])
        if not shared:
            continue
        cons[g] = [chs["4399"][dt] for dt in sorted(shared)]
    return cons


def apply_consensus_t1(rows, cons):
    """R54 共识校对（就地）：对 OPPO 所有有具体 T1 的活动，
    · 自身 T1 日期 ∈ 共识日期 → t1_source=cross3_validated（三渠道一致，不改值）
    · 自身 T1 不同，但存在共识条目结束日期一致（±1天）→ 覆写为共识 T1，
      原 T1 存 own_start 留档，t1_source=cross_consensus:快爆+4399
    · 其余 → t1_source=own_page_rule（尊重 OPPO 页面规则自身时间）
    返回 stats。"""
    stats = {"cons_validated": 0, "cons_overwritten": 0, "own_rule": 0}
    for r in rows:
        if r.get("_vague_rule"):
            continue          # 模糊开始已由 R51 处理
        g = r.get("game")
        entries = cons.get(g) or []
        own = parse_iso(r.get("start"))
        if own is None:
            continue
        cons_dates = {e[0].date() for e in entries}
        if own.date() in cons_dates:
            r["t1_source"] = "cross3_validated"
            stats["cons_validated"] += 1
            continue
        # 尝试按结束日期配对（同一场活动跨渠道的标志）
        own_end = parse_iso(r.get("end"))
        hit = None
        if own_end is not None:
            for t1, e2 in entries:
                if e2 is not None and abs((e2.date() - own_end.date()).days) <= _T2_MATCH_DAYS:
                    hit = (t1, e2)
                    break
        if hit is not None:
            r["own_start"] = r.get("start", "")      # 原 T1 留档，不丢
            r["start"] = hit[0].isoformat()
            if hit[1] is not None:
                r["end"] = hit[1].isoformat()
            r["t1_source"] = "cross_consensus:快爆+4399"
            stats["cons_overwritten"] += 1
        else:
            r["t1_source"] = "own_page_rule"
            stats["own_rule"] += 1
    return stats


def activity_key(url):
    """OPPO 去重键：nvwa站点ID > uActId > actId > url。
    2026-09-12 用户实证：火影忍者两条重复（同站点 gBVsse8K4rsLmFIFBu4XV5tK，
    一条无actId一条带actId=20229941）——旧键序里无actId的条目退到整条URL，
    query入口参数不同就判成两条。一个nvwa站点=一个活动落地页，query
    （at/ta/ht/ts/pageStyle/actId等）只是入口/渠道参数，故站点ID优先。"""
    m = re.search(r"/nvwa-static/sites/([A-Za-z0-9]+)/", url or "")
    if m: return "nvwaSite:" + m.group(1)
    m = re.search(r"[?&]uActId=(\d+)", url or "")
    if m: return "uActId:" + m.group(1)
    m = re.search(r"[?&]actId=(\d+)", url or "")
    if m: return "actId:" + m.group(1)
    return url


def fetch_one_game(args):
    name, aid = args
    try:
        items = oppo_feed.detail_activities(aid, game_hint=name)
    except Exception as e:
        print(f"  detail {name} ERR {e}")
        return []

    # OPPO 页面是 JS 单页：index.html 是壳，奖励规则在 schema.js / 组件配置里。
    # 1) 先补时间（含 schema.js 与页面规则交叉校验 -> create/start 双字段）
    # 2) 再从 schema.js 提取奖励正文，拼到 summary 给 reward_kind 复判。
    try: oppo_feed.enrich_dates_v2(items)
    except Exception: pass
    try: oppo_feed.enrich_reward_text(items)
    except Exception: pass

    out = []
    for it in items:
        txt = get_text(it["url"]) or ""
        schema_txt = it.get("summary") or ""
        full_txt = (txt + " " + schema_txt).strip()
        # 游戏归属先按【原标题】匹配（2026-09-12 实证：详情页推《王者万象棋》
        # 礼包时，加了"三角洲行动"前缀的标题会被错归到三角洲名下）
        raw_title = it["title"] or ""
        game = match_game(raw_title)
        if game:
            title = raw_title          # 标题明确属于某游戏 → 归该游戏，不加来源游戏前缀
        else:
            game = name
            title = raw_title or f"{name} 活动"
            if name not in title:
                title = f"{name} {title}"
        kind, label = reward_kind(title, full_txt)
        s = parse_iso(it.get("startTime"))
        e = parse_iso(it.get("endTime"))
        out.append({
            "game": game, "title": title, "desc": full_txt[:500],
            "create": it.get("createTime") or "",
            "schema_start": it.get("schemaStart") or "",
            "start": s.isoformat() if s else "",
            "end": e.isoformat() if e else "",
            "url": it["url"], "id": it["id"],
            "kind": kind, "reward": label,
            "noise_hint": matched_noise(title, full_txt)[:3],
            "_vague_rule": bool(it.get("_vague_rule")),
        })
    return out


def fetch_all():
    mapping = resolve_all()
    out = []
    # 通用 feed（首页/活动聚合/新游落地页）可能包含目标游戏的跨厂活动
    try:
        common = oppo_feed.collect({}, {"endpoints": {"pages": ["50003579"]}})
        for it in common:
            txt = get_text(it["url"]) or ""
            schema_txt = it.get("summary") or ""
            full_txt = (txt + " " + schema_txt).strip()
            title = it["title"] or "活动"
            game = match_game(title)
            if not game:
                continue
            kind, label = reward_kind(title, full_txt)
            s = parse_iso(it.get("startTime"))
            e = parse_iso(it.get("endTime"))
            out.append({
                "game": game, "title": title, "desc": full_txt[:500],
                "create": it.get("createTime") or "",
                "schema_start": it.get("schemaStart") or "",
                "start": s.isoformat() if s else "",
                "end": e.isoformat() if e else "",
                "url": it["url"], "id": it["id"],
                "kind": kind, "reward": label,
                "noise_hint": matched_noise(title, full_txt)[:3],
                "_vague_rule": bool(it.get("_vague_rule")),
            })
    except Exception as e:
        print(f"  common feed ERR {e}")

    with ThreadPoolExecutor(max_workers=6) as ex:
        futs = [ex.submit(fetch_one_game, (g, mapping.get(g))) for g in GAMES if mapping.get(g)]
        for f in as_completed(futs):
            out.extend(f.result())

    # OPPO 去重：同一活动不同入口 query 不同，按 actId/uActId 去重，保留描述更丰富的
    seen, dedup = {}, []
    for x in out:
        k = activity_key(x["url"])
        if k not in seen:
            seen[k] = len(dedup)
            dedup.append(x)
        else:
            idx = seen[k]
            if len(x["desc"]) > len(dedup[idx]["desc"]):
                # 保留 create / schema_start 字段，避免被覆盖条目清空
                old_create = dedup[idx].get("create")
                old_schema = dedup[idx].get("schema_start")
                dedup[idx] = x
                if old_create and not dedup[idx].get("create"):
                    dedup[idx]["create"] = old_create
                if old_schema and not dedup[idx].get("schema_start"):
                    dedup[idx]["schema_start"] = old_schema
    return dedup


def main():
    rows = fetch_all()

    # R51：跨渠道 T1 校验（仅对「即日起」等模糊开始的 OPPO 活动生效）。
    # 依赖 4399 / 快爆 分组表已存在（run_all_channels.py 已改为先跑这两渠道再跑 OPPO）。
    ref = build_cross_channel_ref()
    if ref:
        rows, cc_stats = apply_cross_channel_t1(rows, ref, NOW)
        print(f"  跨渠道 T1 校验：借用 {cc_stats['borrowed']} / 已验证 {cc_stats['validated']} "
              f"/ 未验证(>3天差) {cc_stats['unverified']} / 仅schema {cc_stats['schema_only']} "
              f"/ 即日起估计 {cc_stats['now_est']}")
    else:
        print("  跨渠道 T1 校验：未找到 4399/快爆 分组表，跳过（OPPO 独立运行模式）")

    # R54：OPPO T1 共识校对（快爆+4399 同游戏同 T1 → OPPO 按共识填；只动 T1 不动 T0）。
    cons = build_consensus_ref()
    if cons:
        c_stats = apply_consensus_t1(rows, cons)
        print(f"  T1 共识校对：三渠道一致 {c_stats['cons_validated']} / 按共识覆写 {c_stats['cons_overwritten']} "
              f"/ 尊重OPPO页面规则 {c_stats['own_rule']}")
    else:
        print("  T1 共识校对：无快爆+4399 共同 T1 基准，跳过")

    json.dump(rows, open("_oppo_sept_v2.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print(f"raw={len(rows)}")

    real = []
    for r in rows:
        if r["kind"] != "real":
            continue
        s, e = parse_iso(r["start"]), parse_iso(r["end"])
        # 时间口径（2026-09-13 更新）：OPPO 流程已支持 schema.js 与页面规则
        # 交叉校验。start 优先取页面规则真实活动时间；页面规则缺失/模糊则回退
        # schema.js timeRange。create 字段保留 schema.js 中早于页面规则的
        # 「提前建页」痕迹（T0），无提前建页则不输出 create。
        if not s or s > NOW:          # 无源头时间 / 未开始
            continue
        if e and e < WIN_START:       # 2026-08-01 前已结束
            continue
        r["group"] = "A组9月起" if s.month >= 9 else "B组8月起"
        real.append(r)

    sept = [r for r in real if parse_iso(r["start"]).month >= 9]
    aug = [r for r in real if parse_iso(r["start"]).month < 9]
    noise = [r for r in rows if r["kind"] != "real"]

    json.dump({"sept_real": sept, "aug_real_running": aug, "sept_noise": noise},
              open("_oppo_table_v3.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)

    print(f"\n=== A组 9月开始·进行中·真奖励 ({len(sept)}条) ===")
    for r in sorted(sept, key=lambda x: x["game"]):
        print(f'{r["game"]:<10} {r["start"][:16]}~{r["end"][:16]} [{r["reward"]}] {r["title"][:44]}')
    print(f"\n=== B组 8月及更早开始·仍在进行·真奖励 ({len(aug)}条) ===")
    for r in sorted(aug, key=lambda x: x["game"]):
        print(f'{r["game"]:<10} {r["start"][:16]}~{r["end"][:16]} [{r["reward"]}] {r["title"][:44]}')
    print(f"\n=== 9月开始但按分类计噪音（留档） ({len(noise)}条） ===")
    for r in sorted(noise, key=lambda x: x["game"])[:8]:
        print(f'{r["game"]:<10} {r["start"][:16]}~{r["end"][:16]} 噪音{r["noise_hint"][:3]} {r["title"][:44]}')


if __name__ == "__main__":
    main()
