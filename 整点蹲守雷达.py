#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
整点蹲守雷达（凌晨 0 点特殊 5 连采，秒级盯钟版）
================================================
为什么需要它：GitHub 定时触发只精确到「分钟」且在高负载（尤其午夜）会排队延迟，
靠 cron 不可能卡住 0 点整。本脚本 23:30 被唤醒后**自己在进程里盯钟**，
GitHub 服务器的时钟是 NTP 同步的（毫秒级），从进程内部等待目标秒，
等效于秒级定时任务。唤醒提前到 23:30 是为吸收 GitHub 的排队抖动留缓冲。

5 次采集分配（北京时间）：
  ① 23:58:50  轻量探测（4399 首页 API + OPPO 三个列表接口，约 20 秒）
  ② 23:59:30  轻量探测（第二次）
  ③ 00:00:05  轻量探测（新整点后极限位，卡「整点后10秒」窗口）
  ④ 00:01:00  完整采集 #1（三渠道全量，约 4 分钟）
  ⑤ 00:05:30  完整采集 #2（确认补漏；CDN 缓存延迟的新活动这轮一定抓到）
两次完整采集都会重写全部数据表并重新生成看板，天然合并去重。
部署(job 里的 deploy 步骤)发布的是最后一次的结果。

防拉黑设计：
- 探测阶段只碰 3~4 个列表接口，请求间隔 ≥3 秒，整窗合计约 12 个轻量请求
- 完整采集沿用常规每小时的请求节奏（该节奏已稳定运行无封禁）
- 探测发现新活动不立即加跑，只记录并等 ④ 的完整采集兜住，避免请求风暴

健壮性：
- GitHub 唤醒抖动：若进程 23:58:45 后才启动，自动跳过已过期的探测点，
  直接执行剩余流程；最坏情况退化为「两次完整采集」，不会失败
- 手动 dispatch 不经过本脚本（云采集雷达.py 仅在 schedule+23 点时切入）
"""

import importlib.util
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
ASSETS = os.path.join(HERE, "assets")
sys.path.insert(0, ASSETS)
PYTHON = sys.executable
CN = timezone(timedelta(hours=8))          # 北京时间

LOG = os.path.join(ASSETS, "_midnight_probe.log")


def now_cn():
    return datetime.now(CN)


def sleep_until(target):
    """睡到目标时刻（北京时间 datetime），期间每 20 秒报一次状态。"""
    while True:
        remain = (target - now_cn()).total_seconds()
        if remain <= 0:
            return
        print(f"    …等待中，距目标 {target:%H:%M:%S} 还有 {remain:.0f} 秒", flush=True)
        time.sleep(min(remain, 20))


def run_script(script, label):
    print(f"\n▶ {label}", flush=True)
    t0 = time.time()
    proc = subprocess.run([PYTHON, script], cwd=ASSETS)
    dt = time.time() - t0
    if proc.returncode != 0:
        print(f"❌ [{label}] 失败（exit={proc.returncode}，用时 {dt:.0f}s）", flush=True)
        return False
    print(f"✅ [{label}] 完成，用时 {dt:.0f} 秒", flush=True)
    return True


def _load_mod(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _baseline(key_field, *files):
    """已入库活动的 id/url 集合，作为「新活动」判别基线。"""
    base = set()
    for f in files:
        p = os.path.join(ASSETS, f)
        if not os.path.isfile(p):
            continue
        try:
            data = json.load(open(p, encoding="utf-8"))
        except Exception:
            continue
        for bucket in data.values() if isinstance(data, dict) else []:
            if not isinstance(bucket, list):
                continue
            for r in bucket:
                for k in (key_field, "url", "id"):
                    v = r.get(k)
                    if v:
                        base.add(str(v))
    return base


def probe(tag):
    """轻量探测：4399 第一页 + OPPO 三个列表接口。返回新增条目列表。"""
    import urllib.request, gzip
    print(f"  [探测{tag}] 开始 {now_cn():%H:%M:%S}", flush=True)
    new_hits = []

    # ---- 4399：首页 API 一个请求 ----
    try:
        m4399 = _load_mod("m4399_guard", os.path.join(ASSETS, "4399_sept_crawl_v2.py"))
        items, _ = m4399.fetch_one(1)
        base = _baseline("url", "_4399_table_v3.json", "_4399_sept_v2.json")
        for it in items:
            u = it.get("url") or it.get("pc_url") or ""
            key = str(it.get("id") or u)
            if key and key not in base and u not in base:
                new_hits.append(("4399", it.get("title", "")[:40]))
    except Exception as e:
        print(f"    [探测{tag}] 4399 探测异常（忽略）：{e}", flush=True)

    time.sleep(3)   # 请求间隔，防拉黑

    # ---- OPPO：tabList + home feed + 一个 page，共 3 个签名请求 ----
    try:
        import oppo_feed
        oppo_feed.load_device({})
        oppo_base = _baseline("id", "_oppo_table_v3.json", "_oppo_sept_v2.json")
        urls = [
            f"{oppo_feed.API}/card/game/activity/tabList",
            f"{oppo_feed.API}/card/game/v2/home?size=50&start=0",
            f"{oppo_feed.API}/card/game/v1/page/50003579?size=50&start=0",
        ]
        for u in urls:
            try:
                raw = oppo_feed._get(u)
                for it in oppo_feed.extract_items(raw):
                    k = str(it.get("id") or it.get("url") or "")
                    if k and k not in oppo_base:
                        new_hits.append(("OPPO", it.get("title", "")[:40]))
            except Exception as e:
                print(f"    [探测{tag}] OPPO {u.rsplit('/',1)[-1][:20]} 异常（忽略）：{e}", flush=True)
            time.sleep(3)
    except Exception as e:
        print(f"    [探测{tag}] OPPO 探测异常（忽略）：{e}", flush=True)

    line = f"{now_cn():%Y-%m-%d %H:%M:%S} [探测{tag}] 新增候选 {len(new_hits)} 条"
    if new_hits:
        for ch, t in new_hits:
            line += f"\n    · [{ch}] {t}"
    print(line, flush=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")
    return new_hits


def main():
    start = now_cn()
    print("=" * 58, flush=True)
    print(f"🌙 0 点蹲守启动（北京时间 {start:%m-%d %H:%M:%S}）", flush=True)
    print("=" * 58, flush=True)

    # ---- 目标时刻表（基于今天 23:58 之后的窗口）----
    base = start.replace(hour=23, minute=58, second=50, microsecond=0)
    if base < start:
        # GitHub 唤醒晚于窗口起点（极端抖动）：以当前时刻为基准顺延，保证流程仍能跑完（降级）
        base = start
        print("  ⚠️ 唤醒晚于 23:58:50，已降级为「立即顺延执行」", flush=True)
    t_probe1 = base
    t_probe2 = base + timedelta(seconds=40)            # 23:59:30
    t_probe3 = base + timedelta(seconds=75)            # 00:00:05
    t_full1 = base + timedelta(seconds=130)            # 00:01:00
    t_full2 = base + timedelta(seconds=400)            # 00:05:30

    # ---- ①②③ 极限窗口三次轻量探测（过期的自动跳过，并记录实际命中偏差）----
    for i, t in enumerate((t_probe1, t_probe2, t_probe3), 1):
        if (t - now_cn()).total_seconds() > 0:
            sleep_until(t)
        drift = (now_cn() - t).total_seconds()
        print(f"  [探测{i}] 实际命中 {now_cn():%H:%M:%S}（目标 {t:%H:%M:%S}，偏差 {drift:+.1f}s）", flush=True)
        if drift <= 60:
            probe(i)
        else:
            print(f"  [探测{i}] 偏差>60s，跳过探测", flush=True)

    # ---- ④ 完整采集 #1 ----
    if (t_full1 - now_cn()).total_seconds() > 0:
        sleep_until(t_full1)
    print(f"  [完整#1] 实际命中 {now_cn():%H:%M:%S}（目标 {t_full1:%H:%M:%S}）", flush=True)
    run_script("run_all_channels.py", "完整采集 #1（00:01 三渠道全量）")
    run_script("radar_board_gen.py", "看板生成 #1")

    # ---- ⑤ 完整采集 #2（确认补漏）----
    if (t_full2 - now_cn()).total_seconds() > 0:
        sleep_until(t_full2)
    print(f"  [完整#2] 实际命中 {now_cn():%H:%M:%S}（目标 {t_full2:%H:%M:%S}）", flush=True)
    run_script("run_all_channels.py", "完整采集 #2（00:05 确认补漏）")
    run_script("radar_board_gen.py", "看板生成 #2（最终版）")

    board = os.path.join(ASSETS, "radar_board.html")
    size = os.path.getsize(board) // 1024 if os.path.isfile(board) else 0
    print(f"\n🌙 蹲守结束（{now_cn():%H:%M:%S}）：最终看板 {size} KB", flush=True)


if __name__ == "__main__":
    main()
