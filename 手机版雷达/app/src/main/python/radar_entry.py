# -*- coding: utf-8 -*-
"""
雷达手机端 Python 入口（Chaquopy 调用）
=======================================
把桌面版的采集管线跑在手机本机：快爆 → 4399 → OPPO → 生成看板。
Java 侧分四个阶段调用（run_stage），每完成一阶段 App 更新一次进度文字。

Chaquopy 注意点（与桌面 subprocess 方案的关键差异）：
- APK 里只有 .pyc，磁盘上不存在 .py 源文件，因此不能用 runpy.run_path 去
  “执行某个脚本文件”——会 FileNotFoundError。改为 importlib 导入模块后调用 main()。
- 各采集脚本按 __file__ 目录落表/读表，而 Chaquopy 下 __file__ 指向虚拟路径、
  对应目录并不真实存在。所以数据一律改写到 RADAR_DATA（手机端由 Java 传入的
  getFilesDir，真实可写；桌面未设置时回退到脚本目录，行为不变）。
- 全部纯 Python 标准库，零 pip 依赖，Chaquopy 原生支持。
"""

import importlib
import os

# 手机首次调用时设置一次环境（Java 每次都会把 filesDir 传进来覆盖）
if not os.environ.get("RADAR_HOME"):
    _fallback = os.getcwd()
    os.environ.setdefault("HOME", _fallback)
    os.environ.setdefault("RADAR_HOME", _fallback)
    os.environ.setdefault("RADAR_DATA", _fallback)

# 平铺后的模块名（与桌面 assets/ 布局一致，确保被打进 APK）
STAGES = {
    "hykb":  "hykb_web_sept_crawl_v2",
    "4399":  "4399_sept_crawl_v2",
    "oppo":  "oppo_sept_crawl_v2",
    "board": "radar_board_gen",
}


def _ensure_env(external_files):
    """把数据落点固定到真实可写的外部存储目录。"""
    if external_files:
        p = str(external_files)
        os.environ["EXTERNAL_FILES"] = p
        os.environ["RADAR_DATA"] = p
        os.environ["HOME"] = p
        os.environ["RADAR_HOME"] = p


def run_stage(name, external_files=None):
    """执行一个阶段。成功后返回 True；失败抛异常由 Java 侧提示。"""
    _ensure_env(external_files)
    mod = importlib.import_module(STAGES[name])
    mod.main()
    return True


def board_path():
    """返回看板 HTML 的绝对路径（供 WebView 加载）。"""
    base = os.environ.get("RADAR_DATA") or os.getcwd()
    p = os.path.join(base, "radar_board.html")
    return p if os.path.isfile(p) else ""
