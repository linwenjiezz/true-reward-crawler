# -*- coding: utf-8 -*-
"""生成 三渠道（快爆/4399/OPPO）9月活动对照表 + 三渠道缺陷诊断表"""
import json, os
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
GAMES = [
    "王者荣耀","和平精英","使命召唤手游","暗区突围","三角洲行动","无畏契约",
    "地下城与勇士：起源","穿越火线枪战王者","金铲铲之战","王者万象棋","QQ飞车",
    "元梦之星","妄想山海","洛克王国：世界","逆战：未来","失控进化","部落冲突",
    "火影忍者手游","荒野乱斗","天天酷跑","卡厄思梦境","冒险岛：枫之传说",
    "完美世界","天龙八部手游","新天龙八部手游",
]

def load_json(p):
    return json.load(open(os.path.join(HERE, p), encoding="utf-8"))

def date_fmt(s):
    """统一显示 MM-DD"""
    if not s:
        return "未知"
    s = str(s)
    if "T" in s:
        return s[5:10].replace("-", "-")  # 2026-09-10 -> 09-10
    if s.startswith("2026-"):
        return s[5:10]
    # 09-10 00:00
    return s[:5]

def chan_items(d, key_sept, key_aug):
    """统一读取三个数据文件的 A/B 组条目"""
    sept = d.get(key_sept, [])
    aug = d.get(key_aug, [])
    if not isinstance(sept, list): sept = []
    if not isinstance(aug, list): aug = []
    return sept + aug

# 加载：每个渠道独立输出自己的分组表，最后在此汇总
hykb = load_json("_hykb_table_v3.json")
hykb_items = chan_items(hykb, "sept_real", "aug_real_running")

y4399 = load_json("_4399_table_v3.json")
items_4399 = chan_items(y4399, "sept_real", "aug_real_running")

oppo = load_json("_oppo_table_v3.json")
items_oppo = chan_items(oppo, "sept_real", "aug_real_running")

# 统一行
def row(item, ch):
    return {
        "channel": ch,
        "game": item["game"],
        "title": item["title"],
        "start": date_fmt(item.get("start")),
        "end": date_fmt(item.get("end")),
        "reward": item.get("reward", ""),
        "url": item.get("url", ""),
    }
rows = [row(i, "快爆") for i in hykb_items] + [row(i, "4399") for i in items_4399] + [row(i, "OPPO") for i in items_oppo]

# 覆盖矩阵
matrix = []
for g in GAMES:
    counts = {"快爆":0,"4399":0,"OPPO":0}
    for r in rows:
        if r["game"] == g:
            counts[r["channel"]] += 1
    total = sum(counts.values())
    matrix.append({"game":g, **counts, "total":total})

# 明细按游戏-渠道汇总
by_game = defaultdict(lambda: defaultdict(list))
for r in rows:
    by_game[r["game"]][r["channel"]].append(r)

# 输出 markdown
lines = []
lines.append("# 25腾讯游戏 · 三渠道活动对照表与缺陷诊断（v8）\n")
lines.append("> 口径（2026-09-12 v8）：收录窗口 **2026年8月1日 ~ 今天**（含窗口内已结束活动，供核对优先级）；仅「现金/Q币/实物硬件」三类真奖励。\n")
lines.append("> 判定优先级（用户定版）：**噪音看标题（第一优先级）**——标题命中噪音词直接判噪音，不看规则正文；**真奖励看活动规则/奖池正文（第一优先级）**——标题只用于游戏归属与噪音排除。\n")
lines.append("> OPPO时间口径（仅限OPPO流程）：只以源头出现的时间为第一标准（API卡片时间/schema.js timeRange），不从活动规则正文猜时间；无源头时间进待审。\n")
lines.append("> 采集时间：2026-09-12 12:00；OPPO游戏中心token有效期至2026-10-06。\n")
lines.append("> 数据来源：快爆网页版v2 / 4399 v2 / OPPO游戏中心v2（三渠道各自独立抓取后汇总）\n")

lines.append("## 一、25游戏覆盖矩阵（真奖励活动数）\n")
lines.append("| 游戏 | 快爆 | 4399 | OPPO | 合计 | 备注 |")
lines.append("|---|---|---|---|---|---|")
for m in matrix:
    note = ""
    if m["total"] == 0:
        note = "三渠道均无真奖励活动"
    elif m["快爆"] == 1 and m["4399"] == 1 and m["OPPO"] == 1:
        note = "三渠道同时覆盖"
    elif m["快爆"] > 0 and m["4399"] == 0 and m["OPPO"] == 0:
        note = "仅快爆"
    elif m["快爆"] == 0 and m["4399"] > 0 and m["OPPO"] == 0:
        note = "仅4399"
    elif m["快爆"] == 0 and m["4399"] == 0 and m["OPPO"] > 0:
        note = "仅OPPO"
    lines.append(f"| {m['game']} | {m['快爆']} | {m['4399']} | {m['OPPO']} | {m['total']} | {note} |")

covered = sum(1 for m in matrix if m["total"]>0)
lines.append(f"\n**覆盖统计**：{covered}/25 款游戏有真奖励活动；快爆 {len(hykb_items)} 条、4399 {len(items_4399)} 条、OPPO {len(items_oppo)} 条。\n")

lines.append("## 二、三渠道真奖励活动明细\n")
for g in GAMES:
    if g not in by_game:
        continue
    lines.append(f"### {g}\n")
    for ch in ["快爆", "4399", "OPPO"]:
        items = by_game[g].get(ch, [])
        if not items:
            lines.append(f"**{ch}**：无\n")
            continue
        lines.append(f"**{ch}**（{len(items)}条）：")
        lines.append("| 时间 | 奖励 | 标题 | 链接 |")
        lines.append("|---|---|---|---|")
        for r in items:
            title_short = r["title"].replace("|", "¦")[:46]
            url_full = r["url"]
            url_display = (url_full[:50] + "...") if len(url_full) > 50 else url_full
            lines.append(f"| {r['start']}~{r['end']} | {r['reward']} | {title_short} | [{url_display}]({url_full}) |")
        lines.append("")

lines.append("## 三、三渠道缺陷诊断表\n")
lines.append("| 渠道 | 缺陷 | 根因 | 实例 | 当前影响 | 修复状态/解法 |")
lines.append("|---|---|---|---|---|---|")
lines.append("| 快爆 | 网页版无原生时间字段 | H5详情页只输出中文日期文本，无 stime/etime 结构化字段 | 失控进化“本活动已于X日结束”模板带偏解析 | 需多正则锚定，仍有少量解析失败 | ✅ 已缓解：锚定「活动时间」区间+隐藏弹窗剥离；天花板级问题无法根除 |")
lines.append("| 快爆 | 专区页只渲染部分活动 | 游戏专区H5懒加载/分页，首屏只出1~2条 | 使命召唤手游专区页仅1条 | 真源在福利汇总H5（comm_id） | ✅ 已修复：补抓 comm_id 对应的 fulihuizong H5 |")
lines.append("| 快爆 | 全站模板句污染 | “恭喜你获得现金*1元”等模板句被误当真奖励 | 全渠道普遍存在 | 假阳性混入真奖励 | ✅ 已修复：精确子串剥离（不按句切） |")
lines.append("| 快爆 | 日期解析天花板 | 中文日期格式不统一，部分页面无明确起止 | “即日起/长期有效”等 | 时间残缺条目进U1待审 | ⚠️ 缓解：进待审桶人工补时间 |")
lines.append("| 快爆 | 签到类活动误判真奖励 | 标题含“签到X天礼包”被 desc/正文中的“Q币”等词带偏 | 王者荣耀每日签到福利、暗区突围签到30天礼包等 | 无Q币的签到礼包被当Q币活动 | ✅ 已修复：标题含“签到”直接归为噪音（用户2026-09-12明确口径） |")
lines.append("| 快爆 | zone通用标题活动详情页失败/超时 | “快爆专属福利”类标题依赖详情页正文，并发请求偶发超时导致判noise | 穿越火线/王者荣耀 zone活动页实际有Q币，却显示无 | ✅ 已修复：enrich 加3次失败重试+1秒退避 |")
lines.append("| 快爆 | 分类写错行（rows[-1]错位） | add()按URL去重跳过后 enrich 仍写 rows[-1]，并发下分类写到别的活动行 | “答疑赢Q币好礼”“新人注册领Q币”标题含Q币却被判noise | 真奖励被错标成噪音 | ✅ 已修复：add()返回自己的行，分类写回该行（2026-09-12） |")
lines.append("| 快爆 | 专区页跨游戏推荐污染 | 王者荣耀专区页推王者万象棋/天美家族礼包，按专区gid硬归属会错配 | 王者荣耀明细出现“抢先下载《王者万象棋》” | ✅ 已修复：zone标题用25游戏别名表重新匹配归属 |")
lines.append("| 4399 | stime=上架时间≠活动开始 | 接口字段语义不可信 | CODM×崩坏3联动：stime=08-25，实际09-10开始 | 误把A组活动分到B组 | ✅ 已修复：详情页「活动时间」覆写接口时间 |")
lines.append("| 4399 | 游标链固有重复页 | 服务端 startKey 分页链在不同请求会丢失/重复条目 | 372页只返回297个唯一条目 | 单次抓取必丢活动 | ✅ 已修复：断点续传翻页+本地快照并集 |")
lines.append("| 4399 | 英文缩写别名缺失 | 4399标题用《CODM》而非“使命召唤手游” | CODM崩坏3联动整条漏抓 | 关键词匹配失败 | ✅ 已修复：别名表加CODM+最长优先匹配 |")
lines.append("| 4399 | 标题含模糊词“赢好礼” | desc字段无用，正文才能判断奖励 | 和平精英/金铲铲等多条“赢京东卡/好礼” | 噪音/真奖励难辨 | ✅ 已修复：抓详情页正文复判 |")
lines.append("| 4399 | 正文复判只对“模糊词标题”触发 | 旧逻辑标题含“赢好礼/有礼”才抓详情页，“福利中心/新赛季”等标题直接漏 | 三角洲福利中心标题无Q币、规则正文有“540Q币助力金”被漏 | 标题筛奖漏真奖励 | ✅ 已修复（2026-09-12）：去掉模糊词门槛，所有命中游戏且进行中的候选一律并行抓详情页正文复判 |")
lines.append("| 4399 | 表格结构缺B组 | 早期只列出9月开始活动 | 金铲铲/使命召唤8月起活动“整组消失” | 用户误以为漏抓 | ✅ 已修复：补8月起仍进行B组 |")
lines.append("| OPPO | 活动卡标题高度模板化 | protostuff活动卡title多为“XX 活动”，desc常为模板 | 使命召唤“活动”、暗区“活动”等大量条目 | 标题本身无法判定奖励 | ⚠️ 缓解：用 schema.js 正文补充后已能判Q币/现金 |")
lines.append("| OPPO | 页面正文提取困难 | nvwa站点为JS单页，index.html仅壳，规则/奖励在js/schema.js | CODM×崩坏3联动OPPO也有，但标题只写“领好礼” | 真奖励漏判为噪音 | ✅ 已修复：oppo_feed 新增 enrich_reward_text，从 schema.js 提取奖励文本 |")
lines.append("| OPPO | 时间字段缺失率高 | 大量 staticActivity 卡片无 startTime/endTime | 许多历史活动无时间 | 无法判定运行中 | ✅ 已修复（2026-09-12）：staticActivity 是纯静态HTML，直接抓页面并解析「活动时间：X月X日至X月X日」——按源头活动时间显示，不依赖API字段 |")
lines.append("| OPPO | staticActivity 页面正文从未提取 | site_reward_text/site_dates 只认 nvwa-static，staticActivity 直接返回空 | 三角洲/暗区/QQ飞车 staticActivity 条目全部判噪音 | 源头有真奖励但整页漏 | ✅ 已修复（2026-09-12）：新增 static_page_info，抓静态页正文（奖池/规则）+ 页面自标注时间 |")
lines.append("| OPPO | desc 残留“>”符号 | get_text 正则少写闭合尖括号 `<[^>]+`，标签剥离不干净 | OPPO条目desc全是“>>>>>” | 对照表观感差、正文证据被污染 | ✅ 已修复：正则改为 `<[^>]+>` |")
lines.append("| OPPO | 重复条目多 | 同一活动通过不同query参数/渠道返回多次（actId相同，入口参数不同） | 暗区突围“活动”和“S19赛季”两条同actId | 去重前同一活动多条 | ✅ 已修复：按 actId/uActId 去重，保留描述更丰富的 |")
lines.append("| OPPO | 跨游戏推荐污染 | 王者万象棋上线活动被推送到三角洲行动/王者荣耀等详情页 | 三角洲行动出现“王者万象棋已上线” | 误归属 | ✅ 已修复：标题+desc重新匹配25游戏别名，非目标游戏剔除 |")
lines.append("| 工程层 | 报告链接被截断失效 | gen_three_channel 生成 markdown 时把 URL 截到90字符，OPPO长链被截成 `/static/i` | 和平精英OPPO链接点击后报 NoSuchKey | 用户误以为OPPO接口抓错/乱码 | ✅ 已修复：显示可截断，但 href 必须保留完整URL |")

lines.append("\n## 四、本次用户反馈对应的三渠道修复点\n")
lines.append("| 问题 | 渠道 | 根因 | 修复 | 验证结果 |")
lines.append("|---|---|---|---|---|")
lines.append("| 王者荣耀出现“签到15天礼包” | 快爆 | 旧表数据未重跑 / 脚本早期去重未覆盖 | 已重新运行，签到标题直接判noise | 最新快爆A组无签到条目 |")
lines.append("| OPPO同一链接出现两条不同标题 | OPPO | 去重按完整URL，同一actId不同入口参数被当两条 | 改为按 actId/uActId 去重 | 暗区突围只剩1条 |")
lines.append("| 穿越火线只有4399抓到 | 三渠道各自原因 | 快爆：zone通用标题详情页超时；OPPO：index.html壳无正文；4399：本身正常 | 快爆加enrich重试；OPPO从schema.js提取奖励 | 穿越火线三渠道均现真奖励 |")
lines.append("| 关键词被拆成三份 | 工程层 | 三脚本各自内联别名/时间逻辑，维护困难 | 统一用 config.GAME_ALIASES + reward_classify，但每个渠道保留自己的源头适配层 | 口径统一，渠道特有逻辑独立 |")
lines.append("")
lines.append("### 2026-09-12 11:00 用户复核反馈（打勾缺口）定位与修复")
lines.append("| 打勾缺口 | 源头证据 | 根因 | 修复 |")
lines.append("|---|---|---|---|")
lines.append("| 暗区突围·快爆=0 | 快爆源有“新赛季福利活动”(zone) | 通用标题无奖励词，正文证据被 rows[-1] 错位bug污染 | 修错位bug+正文4000字判定 |")
lines.append("| 三角洲行动·4399=0 | 4399源《三角洲福利中心》规则正文有“540Q币助力金”，标题无 | 正文复判只对“赢好礼”模糊词标题触发 | 去掉门槛，全量候选并行抓正文复判 |")
lines.append("| 三角洲行动·OPPO=0 | OPPO源多条 staticActivity/uActId 条目 summary 全空 | 静态页正文从未提取，永远判噪音 | static_page_info 抓静态页正文+源头时间 |")
lines.append("| 王者万象棋·快爆=0 | 快爆源“参与互助答疑赢Q币好礼”标题含Q币却被判noise | rows[-1] 错位竞态bug（add()去重跳过后写错行） | add()返回自己的行，分类写回该行 |")
lines.append("| QQ飞车·快爆=0 / OPPO=0 | 快爆源“年中盛典”(zone)；OPPO源 staticActivity | 同上两类根因 | 同上两项修复 |")
lines.append("| 用户判断“关键词筛在标题而非规则奖池” | 三渠道实证全部命中 | 标题筛奖是系统性根因 | 三渠道统一改为：规则/奖池正文为主证据，标题只做归属+噪音排除 |")

lines.append("\n### 2026-09-12 12:00 用户第二轮反馈：噪音优先级定版 + 窗口扩宽")
lines.append("| 问题 | 渠道 | 根因 | 修复 |")
lines.append("|---|---|---|---|")
lines.append("| 三角洲·4399 抓错活动（福利中心送干员外观） | 4399 | 页面Q币证据全部来自4399模板共享的【获奖留言墙】（“获得6Q币 感谢盒子”，2024年历史留言）与【共享抽奖模块】（“目前累计暴击奖励0 Q币”），并非该活动自身奖池 | scope_body：从第一处留言墙时间戳截断+剥离抽奖模块文案；福利中心型集散页按新口径归噪音 |")
lines.append("| 万象棋·4399“福利中心送棋盘&皮肤”误判Q币 | 4399 | 同上：棋盘&皮肤是活动真实奖池（游戏内道具），Q币来自共享留言墙 | 同上；标题“福利中心”加入标题噪音词 |")
lines.append("| 金铲铲·OPPO“进群交流阵容拿奖励”未判噪音 | OPPO | 噪音词表缺“进群/交流群” | TITLE_NOISE_FIRST 增加 进群/交流群/加群/畅聊/开服话题/福利信息站/福利中心 |")
lines.append("| 万象棋·4399“开服话题热聊！发帖赢周边、Q币”未判噪音 | 4399/快爆 | 标题里同时有噪音词和Q币时，Q币抢了优先级 | 定版：**噪音看标题（第一优先级）**——标题命中噪音词直接终判，不看规则正文，哪怕标题带“赢Q币” |")
lines.append("| 收录时间范围太窄 | 三渠道 | 只收录9月起的活动 | 窗口扩宽为 **2026-08-01 ~ 今天**（含窗口内已结束活动），三渠道统一 |")
lines.append("| OPPO时间依赖活动规则文本 | OPPO | 之前 schema 无日期时会从页面规则文本解析时间兜底 | 仅限OPPO：时间只认源头出现的时间（API卡片/schema.js timeRange/staticActivity页面标注），不再解析规则正文，无源头时间进待审 |")

lines.append("\n## 五、核心结论\n")
lines.append("1. **三渠道独立流程已落地**：`run_all_channels.py` 分别跑快爆/4399/OPPO各自脚本，互不干扰，最后汇总。\n")
lines.append("2. **穿越火线枪战王者已三渠道覆盖**：快爆（十元助力金=Q币）、4399（388Q币）、OPPO（CFM嘉年华现金/Q币）。\n")
lines.append("3. **判定优先级定版（用户2026-09-12）**：噪音看标题（第一优先级，命中即终判不看正文）；真奖励看活动规则/奖池正文（第一优先级）。三渠道正文来源：快爆=详情页H5正文、4399=详情页正文（已剔留言墙/共享抽奖模块）、OPPO=nvwa schema.js + staticActivity 静态页正文。\n")
lines.append("4. **OPPO源头时间（仅限OPPO流程）**：只以源头出现的时间为第一标准（API卡片毫秒时间 / schema.js timeRange / staticActivity 页面标注），不从活动规则正文猜时间；无源头时间进待审。\n")

open(os.path.join(HERE, "25腾讯游戏_三渠道9月对照表与缺陷诊断.md"), "w", encoding="utf-8").write("\n".join(lines))
print("written 25腾讯游戏_三渠道9月对照表与缺陷诊断.md")
print(f"rows total: {len(rows)}; coverage {covered}/25")
