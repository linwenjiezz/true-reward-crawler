# -*- coding: utf-8 -*-
"""
雷达手机端 Python 入口（Chaquopy 调用）
=======================================
把桌面版的采集管线原样跑在手机本机：快爆 → 4399 → OPPO → 生成看板。
Java 侧分四个阶段调用（run_stage），每完成一阶段 App 更新一次进度文字。

说明：
- 全部纯 Python 标准库，零 pip 依赖，Chaquopy 原生支持
- run_all_channels.py 用了 subprocess（Android 无独立 python 解释器），
  所以这里改为在进程内顺序执行三个采集脚本，两阶段语义不变
- 数据/看板落在 Chaquopy 解包目录（App 私有存储），无需任何权限
"""

import os
import runpy
import sys

HERE = os.path.dirname(os.path.abspath(__file__))

# 手机首次调用时设置一次环境
if not os.environ.get("RADAR_HOME"):
    os.environ["HOME"] = os.environ.get("EXTERNAL_FILES", HERE)
    os.environ["RADAR_HOME"] = os.environ.get("EXTERNAL_FILES", HERE)

STAGES = {
    "hykb":  "hykb_web_sept_crawl_v2.py",
    "4399":  "4399_sept_crawl_v2.py",
    "oppo":  "oppo_sept_crawl_v2.py",
    "board": "radar_board_gen.py",
}


def run_stage(name, external_files=None):
    """执行一个阶段。返回 True=成功；失败抛异常由 Java 侧提示。"""
    if external_files:
        # 每次都刷新（Java 侧可能在 run 之间才拿到 filesDir）
        os.environ["EXTERNAL_FILES"] = str(external_files)
        os.environ["HOME"] = str(external_files)
        os.environ["RADAR_HOME"] = str(external_files)
    os.chdir(HERE)                       # 脚本按 HERE 落表/读表
    sys.path.insert(0, HERE)
    script = STAGES[name]
    runpy.run_path(os.path.join(HERE, script), run_name="__main__")
    return True


def board_path():
    """返回看板 HTML 的绝对路径（供 WebView 加载）。"""
    p = os.path.join(HERE, "radar_board.html")
    return p if os.path.isfile(p) else ""
