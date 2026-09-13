# GitHub 云端方案操作指南（方案 C）

> 目标：GitHub 服务器每小时自动采集一次，生成雷达看板并发布成公网链接，手机/电脑随时打开都是最新数据。电脑关机也照常运行。
>
> ⚠️ 前提提醒：仓库选「公开 Public」才能免费用 Actions + Pages。公开意味着任何人都能看到你的雷达页面（活动数据本身不涉密，一般无所谓）。

## 第 1 步：创建空仓库（约 1 分钟）

1. 打开 https://github.com/new
2. Repository name 填：`game-radar`（可自定义）
3. 选 **Public**，其余全部默认（不要勾选任何初始化文件）
4. 点 **Create repository**，创建后停留在当前页面备用

## 第 2 步：推送项目（在你电脑上执行）

打开命令行（CMD 或 PowerShell），逐行执行（把 `你的用户名` 换成你的 GitHub 用户名）：

```bat
cd /d "C:\Users\linwe\Desktop\无敌大成APP\true-reward-crawler\true-reward-crawler"

git init
git add -A
git commit -m "活动雷达完整版 9月13日"
git branch -M main
git remote add origin https://github.com/你的用户名/game-radar.git
git push -u origin main
```

> 第一次推送会弹出 GitHub 登录窗口，用浏览器授权即可。
> 如果提示 git 不是内部命令：去 https://git-scm.com/download/win 安装，一路下一步装完重开命令行。

## 第 3 步：开启 Pages（约 30 秒）

1. 打开你的仓库页面 → **Settings** → 左侧 **Pages**
2. **Build and deployment → Source** 选择：**GitHub Actions**
3. 完成。

## 第 4 步：验证

1. 仓库页面 → **Actions** 标签 → 左侧「活动雷达定时采集」
2. 点右边 **Run workflow → Run workflow** 手动触发第一次
3. 等 2~3 分钟，变绿 ✅ 后，打开：
   `https://你的用户名.github.io/game-radar/`
   能看到雷达页面 = 成功。之后每小时第 23 分钟（UTC）自动采集刷新。

## 海外网络测试点（第一次运行重点看）

第一次运行 = 对「GitHub 海外服务器能否抓到三个国内渠道」的实测：

- **快爆 / 4399**：普通网页接口，大概率没问题
- **OPPO**：签名接口，最可能被风控——如果 Actions 日志里 OPPO 报错或数据为 0，说明该渠道拒绝海外 IP
- 看日志：仓库 → Actions → 点开那次运行 → 点 crawl 任务，就能看到和我们本地一样的采集输出

**如果 OPPO 被墙**：不影响另外两渠道正常出海展示；可以退回「本机任务计划（方案A）为主 + GitHub 展示两渠道」或混合方案，到时候再调。

## 日常使用

- 什么都不用做：每小时自动采集 + 自动发版
- 想立即刷新：仓库 → Actions → Run workflow
- 想停掉：仓库 → Actions → 「活动雷达定时采集」→ ⋯ → Disable workflow
- 想改频率：编辑 `.github/workflows/radar.yml` 里的 cron（注释里已说明格式）
