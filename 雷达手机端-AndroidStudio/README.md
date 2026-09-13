# 游戏活动雷达 · Android Studio 手机端 v2

**采集管线直接跑在手机上**——点「⚡本机采集」，Python 采集代码在手机本机执行
（快爆 → 4399 → OPPO → 生成看板，全程纯 Python 标准库，经 Chaquopy 内嵌运行），
完成后直接显示手机刚抓出来的雷达页面。与电脑 VS Code 点 Run 完全等价。

## Android Studio 打开步骤

1. 打开 Android Studio → `Open` → 选 `雷达手机端-AndroidStudio` 这一层
   （里面能看到 `app`、`build.gradle`、`settings.gradle`）
2. 提示 Trust / Sync 一路确认。**首次同步会下载 Gradle 8.2 + Chaquopy + 内嵌
   Python 运行时（约 200MB）**，耐心等进度条走完，之后不再下载
3. 手机连电脑、开启「开发者选项 → USB 调试」→ 顶部选中设备 → 点绿色 ▶ Run
4. App 自动安装并打开 ✅（之后拔线照常用；也可 Build → Build APK(s) 生成安装包传手机装）

## 界面说明

| 元素 | 作用 |
|---|---|
| **⚡本机采集** | 手机本机执行完整采集（2~5 分钟，保持 App 前台），完成后显示本机刚抓的看板。**国内 IP 直抓渠道，无风控顾虑** |
| **☁️云端** | 切回 GitHub Pages 云端雷达（GitHub 每小时 :01 自动采集 + 0 点蹲守 5 连采） |
| **🔄刷新** | 重新加载当前页面 |

- 看板里的活动链接自动交给系统浏览器打开
- 本机采集期间自动保持亮屏，按钮防重复点击

## 常见问题

- **Sync 时 Chaquopy 下载慢/失败**：网络原因，开代理重试；或点 Android Studio 提示的「Fix / 推荐版本」
- **本机采集中断网/失败**：看状态栏红色错误文字；换 Wi-Fi/流量再点一次即可，不影响 App 其他功能
- **OPPO 显示需要设备 token**：oppo_feed.py 内置默认设备常量，正常无需配置；如长期失效，把新抓的 `conf/oppo_device.json` 放进手机 `Android/data/com.linwe.gameradar/files/conf/` 即可覆盖
