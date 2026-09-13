#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
云采集雷达（GitHub Actions 专用入口）
====================================
与本地「一键RUN雷达.py」的区别：
- 不打开浏览器（云端无人值守，没有显示器）
- 流程相同：三渠道采集（两阶段）→ 生成 radar_board.html
生成结果由 GitHub Actions 工作流负责：提交回仓库 + 发布到 GitHub Pages。
零第三方依赖（纯 Python 标准库）。
"""

import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ASSETS = os.path.join(HERE, "assets")
PYTHON = sys.executable


def run_step(name, script):
    print("\n" + "=" * 54)
    print(f"▶ {name}")
    print("=" * 54, flush=True)
    proc = subprocess.run([PYTHON, script], cwd=ASSETS)
    if proc.returncode != 0:
        print(f"\n❌ [{name}] 失败（exit={proc.returncode}）")
        raise SystemExit(proc.returncode)
    print(f"✅ [{name}] 完成", flush=True)


def main():
    auto = "--auto" in sys.argv

    # --auto 模式：北京时间 23 点被唤醒 → 切入 0 点蹲守（5 连采，秒级盯钟）
    if auto:
        from datetime import datetime, timedelta, timezone
        bj = datetime.now(timezone(timedelta(hours=8)))
        print(f"[auto] 当前北京时间 {bj:%H:%M}，仓库分支判定…", flush=True)
        if bj.hour == 23:
            print("[auto] 命中 23 点 → 进入 0 点蹲守模式\n", flush=True)
            run_step("阶段零：0 点蹲守（3 探测 + 2 完整采集）", "../整点蹲守雷达.py")
            board = os.path.join(ASSETS, "radar_board.html")
            size = os.path.getsize(board) if os.path.isfile(board) else 0
            print(f"\n🎉 蹲守采集完成：radar_board.html {size // 1024} KB")
            return
        print("[auto] 非 23 点 → 常规每小时巡逻\n", flush=True)

    print("=" * 54)
    print("云采集：三渠道 → 雷达看板（GitHub Actions）")
    print("=" * 54, flush=True)

    if not os.path.isdir(ASSETS):
        print(f"❌ 找不到 assets 目录：{ASSETS}")
        raise SystemExit(1)

    run_step("阶段一：三渠道采集（快爆 ∥ 4399 → OPPO）", "run_all_channels.py")
    run_step("阶段二：生成雷达看板 radar_board.html", "radar_board_gen.py")

    board = os.path.join(ASSETS, "radar_board.html")
    size = os.path.getsize(board) if os.path.isfile(board) else 0
    print(f"\n🎉 云采集完成：radar_board.html {size // 1024} KB")


if __name__ == "__main__":
    main()
