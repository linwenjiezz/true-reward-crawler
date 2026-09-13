# -*- coding: utf-8 -*-
"""三渠道独立采集 + 汇总入口
=================================
用户要求：每个渠道单独写完整抓取流程（抓取+筛选），互不干扰，最后汇集显示。

本脚本按以下顺序执行：
  1. 快爆网页版：hykb_web_sept_crawl_v2.py
  2. 4399 游戏盒：4399_sept_crawl_v2.py
  3. OPPO 游戏中心：oppo_sept_crawl_v2.py
  4. 汇总生成对照表：gen_three_channel.py

每个脚本独立输出自己的分组表（_hykb_table_v3.json / _4399_table_v3.json / _oppo_table_v3.json），
最后由 gen_three_channel.py 读取三个分组表并生成《25腾讯游戏_三渠道9月对照表与缺陷诊断.md》。
"""
import os, subprocess, sys
from concurrent.futures import ThreadPoolExecutor, as_completed

HERE = os.path.dirname(os.path.abspath(__file__))
PYTHON = sys.executable

# 两阶段执行：先把 4399 与 快爆 跑完（并行），再跑 OPPO。
# 原因：oppo_sept_crawl_v2 的 R51 跨渠道 T1 校验需要读取另外两渠道的分组表
# （_4399_table_v3.json / _hykb_table_v3.json）作为同游戏 T1 基准，必须先就绪。
PHASE1 = [                       # 无相互依赖，可并行
    ("快爆", "hykb_web_sept_crawl_v2.py"),
    ("4399", "4399_sept_crawl_v2.py"),
]
PHASE2 = [                       # 依赖 PHASE1 的分组表
    ("OPPO", "oppo_sept_crawl_v2.py"),
]

def run_one(name, script):
    print(f"\n▶ 开始采集：{name}")
    proc = subprocess.run(
        [PYTHON, script],
        cwd=HERE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    print(proc.stdout)
    if proc.returncode != 0:
        print(f"❌ {name} 采集失败（exit={proc.returncode}）")
    else:
        print(f"✅ {name} 采集完成")
    return name, proc.returncode

def main():
    print("=" * 50)
    print("三渠道独立采集流程启动（两阶段：先快爆+4399，后OPPO）")
    print("=" * 50)

    # 阶段一：快爆 + 4399 并行
    with ThreadPoolExecutor(max_workers=2) as ex:
        futs = {ex.submit(run_one, name, script): name for name, script in PHASE1}
        for f in as_completed(futs):
            name, code = f.result()
            if code != 0:
                print(f"⚠️ {name} 返回非零，后续汇总可能缺失该渠道数据")

    # 阶段二：OPPO（依赖阶段一的分组表做跨渠道 T1 校验）
    for name, script in PHASE2:
        run_one(name, script)

    print("\n" + "=" * 50)
    print("三渠道采集结束，开始汇总生成对照表")
    print("=" * 50)
    proc = subprocess.run(
        [PYTHON, "gen_three_channel.py"],
        cwd=HERE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    print(proc.stdout)
    if proc.returncode != 0:
        print("❌ 汇总生成失败")
        return 1
    print("✅ 汇总完成：25腾讯游戏_三渠道9月对照表与缺陷诊断.md")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
