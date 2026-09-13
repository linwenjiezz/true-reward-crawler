#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
一键RUN雷达（唯一入口）
========================
在 VS Code 中打开本文件，直接点击「运行」即可完成全流程：

  1. 三渠道采集（两阶段：快爆+4399 并行 → OPPO，含跨渠道 T1 共识校验）
  2. 生成活动雷达看板 radar_board.html（速报只显示紫色 T0、分区只显示白色 T1）
  3. 自动用默认浏览器打开雷达页面

无需安装任何第三方库（纯 Python 标准库 + urllib）。
所有采集脚本和输出文件都固定在本目录的 assets/ 文件夹内。
"""

import os
import subprocess
import sys
import webbrowser

HERE = os.path.dirname(os.path.abspath(__file__))
ASSETS = os.path.join(HERE, "assets")
PYTHON = sys.executable


def run_step(name, script):
    print("\n" + "=" * 54)
    print(f"▶ {name}")
    print("=" * 54)
    proc = subprocess.run([PYTHON, script], cwd=ASSETS)
    if proc.returncode != 0:
        print(f"\n❌ [{name}] 失败（exit={proc.returncode}），流程中止。")
        raise SystemExit(proc.returncode)
    print(f"✅ [{name}] 完成")


def main():
    print("╔" + "═" * 52 + "╗")
    print("║   游戏活动雷达 · 一键采集 + 生成 + 打开                ║")
    print("╚" + "═" * 52 + "╝")
    print(f"项目目录：{HERE}")

    if not os.path.isdir(ASSETS):
        print(f"❌ 找不到 assets 目录：{ASSETS}")
        raise SystemExit(1)

    # 1) 三渠道采集（内部已按 两阶段 排序：先快爆+4399，后 OPPO）
    run_step("阶段一：三渠道采集（快爆 ∥ 4399 → OPPO）", "run_all_channels.py")

    # 2) 生成雷达看板
    run_step("阶段二：生成雷达看板 radar_board.html", "radar_board_gen.py")

    # 3) 自动打开
    board = os.path.join(ASSETS, "radar_board.html")
    print("\n▶ 打开雷达页面：" + board)
    webbrowser.open("file:///" + board.replace("\\", "/"))
    print("\n🎉 全部完成！下次想刷新数据，重新运行本文件即可。")


if __name__ == "__main__":
    main()
