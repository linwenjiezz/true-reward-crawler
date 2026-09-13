# 游戏活动雷达 · Android Studio 手机端

一个「打开就能 Run」的标准 Android 工程。App 本体是云端雷达网页的壳
（WebView），数据由 GitHub 服务器每小时自动采集，**手机端不需要也不执行采集**。

## Android Studio 打开步骤

1. 打开 Android Studio → `Open`（或 中文版「打开」）
2. 选择本文件夹：`雷达手机端-AndroidStudio`（注意选**这一层**，里面能看到
   `app`、`build.gradle`、`settings.gradle`）
3. 首次打开右下角会提示 Gradle 同步 / 下载 → 点 **Trust / Trust Project**、
   再点 **Sync Now**，等进度条走完（首次要下载 Gradle 8.2，约 5 分钟）
4. 手机用数据线连电脑 → 手机上开启「开发者选项 → USB 调试」
   → Android Studio 顶部设备框选中你的手机 → 点绿色 ▶ Run
5. App 自动安装并打开，完成 ✅（之后拔线也能用，图标叫「游戏活动雷达」）

> 没开 USB 调试也没关系：Run 一次后，可在 Android Studio 菜单
> Build → Build Bundle(s)/APK(s) → Build APK(s) 生成安装包，
> 把 `app-debug.apk` 传到手机上直接安装。

## 界面说明

| 元素 | 作用 |
|---|---|
| 看板主体 | 云端雷达网页（GitHub 每小时 :01 自动采集 + 0 点蹲守 5 连采） |
| 🔄 刷新 | 重新加载网页 = 看最新数据 |
| ⚡ 手动采集 | 跳转 GitHub Actions 页面 → 点 **Run workflow** → 2~4 分钟后回 App 点刷新，就是刚刚采的新数据（需手机浏览器登录过 GitHub 一次） |

## 常见问题

- **Sync 报 Gradle 版本错误**：选 Android Studio 提示的「Fix / 使用推荐版本」即可
- **Run 时手机提示允许 USB 调试**：勾选「一律允许」→ 确定
- **网页打不开**：确认手机能访问 github.io（个别网络环境需要代理，与 App 无关）
