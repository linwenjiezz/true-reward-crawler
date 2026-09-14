package com.linwe.gameradar;

import android.app.Activity;
import android.app.AlarmManager;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.pm.PackageManager;
import android.content.res.ColorStateList;
import android.graphics.Color;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.os.PowerManager;
import android.provider.Settings;
import android.view.View;
import android.view.ViewGroup;
import android.webkit.WebResourceError;
import android.webkit.WebResourceRequest;
import android.webkit.WebResourceResponse;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.ProgressBar;
import android.widget.TextView;
import android.widget.Toast;

import com.chaquo.python.PyObject;
import com.chaquo.python.Python;
import com.chaquo.python.android.AndroidPlatform;

import java.util.Locale;

/**
 * 游戏活动雷达 · 手机端 v2
 *
 * 双模式：
 *  ⚡本机采集 —— 采集管线（纯 Python）直接在手机上执行：快爆 → 4399 → OPPO →
 *               生成看板，完成后直接显示本机生成的雷达页面。手机是国内 IP，
 *               抓渠道无风控顾虑；整条流程点一下全自动，与电脑 VS Code 点 Run 等价。
 *  ☁️云端 —— 打开 GitHub Pages 上的公网雷达（GitHub 每小时 :01 自动采集 + 0点蹲守），
 *               手机不干活，纯浏览。公网站点：https://linwenjiezz.github.io/true-reward-crawler/
 *
 *  🌙每日0点（新增）—— 用手机本地 AlarmManager 精确卡 00:00:00 自动本机采集，
 *                不依赖 GitHub 排队。需配合 MIUI/HyperOS 的「自启动 + 电池无限制」
 *                白名单才能在红米锁屏后可靠触发（点「🔧权限」一键跳转设置）。
 *  ⏰整点采集（新增）—— 每小时整点自动本机采集（自动跳过 00:00，避免与每日0点重复）。
 *                同样需要「🔧权限」白名单。适合观察每个整点手机在后台的自动执行。
 *
 *  注意：本机采集运行 2~5 分钟（取决于手机与网络）。手动点时保持亮屏、勿退出 App；
 *        定时（0点/整点）则在后台通过前台服务运行，不会打开 App 主界面，可在通知栏看绿色进度条。
 */
public class MainActivity extends Activity {

    private static final String SITE = "https://linwenjiezz.github.io/true-reward-crawler/";
    private static final String SITE_HOST = "linwenjiezz.github.io";
    private static final String PREFS = "radar";
    private static final String KEY_AUTO = "auto_midnight";
    private static final String KEY_AUTO_HOURLY = "auto_hourly";
    private static final int RC_NOTIF = 1;

    private WebView web;
    private TextView status;
    private ProgressBar progressBar;
    private TextView cdMidnight, cdHourly;   // 两个独立倒计时框（白字）
    private Button localRun, cloudBtn, refresh, autoBtn, autoHourlyBtn, permBtn;
    private volatile boolean crawling = false;
    private long loadedBoardTime = -1;   // 当前页面对应的采集时间（-1=云端页）；用于整点后台采集后切回时自动刷新
    private int pendingMode = 0; // 0 无；1 每日0点；2 整点采集（权限弹窗返回后继续）
    private final android.os.Handler tickHandler = new android.os.Handler(
            android.os.Looper.getMainLooper());
    private Runnable tickRunnable;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);

        // ---- 顶部：标题行 ----
        LinearLayout bar = new LinearLayout(this);
        bar.setOrientation(LinearLayout.VERTICAL);
        bar.setBackgroundColor(Color.rgb(22, 24, 30));
        bar.setPadding(36, 24, 24, 16);

        LinearLayout row1 = new LinearLayout(this);
        row1.setOrientation(LinearLayout.HORIZONTAL);
        row1.setGravity(android.view.Gravity.CENTER_VERTICAL);

        TextView title = new TextView(this);
        title.setText("🎮 游戏活动雷达");
        title.setTextColor(Color.WHITE);
        title.setTextSize(16);
        row1.addView(title, new LinearLayout.LayoutParams(0,
                ViewGroup.LayoutParams.WRAP_CONTENT, 1f));

        cloudBtn = mkBtn("☁️云端");
        cloudBtn.setOnClickListener(new View.OnClickListener() {
            @Override public void onClick(View v) { openCloud(); }
        });
        row1.addView(cloudBtn);

        refresh = mkBtn("🔄刷新");
        LinearLayout.LayoutParams refreshLp = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        refreshLp.leftMargin = 14;
        row1.addView(refresh, refreshLp);
        refresh.setOnClickListener(new View.OnClickListener() {
            @Override public void onClick(View v) { web.reload(); }
        });

        localRun = mkBtn("⚡本机采集");
        LinearLayout.LayoutParams localLp = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        localLp.leftMargin = 14;
        row1.addView(localRun, localLp);

        // ---- 第二行：状态栏 ----
        status = new TextView(this);
        status.setText("打开默认显示云端雷达；点「⚡本机采集」用手机直接抓取最新活动");
        status.setTextColor(Color.rgb(150, 155, 165));
        status.setTextSize(11);
        status.setPadding(0, 10, 0, 0);

        // ---- 绿色进度条（手动本机采集时显示，保留数字加载）----
        // 自绘 Drawable 强制配色：深灰轨道 + 荧光绿填充，不依赖系统 tint（MIUI 上可能不生效）
        progressBar = new ProgressBar(this, null,
                android.R.style.Widget_ProgressBar_Horizontal);
        LinearLayout.LayoutParams pbLp = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, 40);   // 40px≈14dp，肉眼清晰可见
        pbLp.topMargin = 10;
        progressBar.setLayoutParams(pbLp);
        progressBar.setMax(100);
        progressBar.setProgress(0);
        android.graphics.drawable.GradientDrawable track =
                new android.graphics.drawable.GradientDrawable();
        track.setColor(Color.rgb(70, 76, 90));              // 亮灰轨道（深底上明显）
        track.setCornerRadius(9);
        android.graphics.drawable.GradientDrawable fill =
                new android.graphics.drawable.GradientDrawable();
        fill.setColor(Color.parseColor("#00E676"));          // 荧光亮绿填充
        fill.setCornerRadius(9);
        android.graphics.drawable.ClipDrawable clip =
                new android.graphics.drawable.ClipDrawable(fill,
                        android.view.Gravity.START, android.graphics.drawable.ClipDrawable.HORIZONTAL);
        android.graphics.drawable.LayerDrawable layer =
                new android.graphics.drawable.LayerDrawable(
                        new android.graphics.drawable.Drawable[]{track, clip});
        layer.setId(0, android.R.id.background);
        layer.setId(1, android.R.id.progress);
        progressBar.setProgressDrawable(layer);
        progressBar.setVisibility(View.GONE);

        // ---- 第三行：两个定时开关 + 权限引导 ----
        LinearLayout row2 = new LinearLayout(this);
        row2.setOrientation(LinearLayout.HORIZONTAL);
        row2.setPadding(0, 12, 0, 0);

        autoBtn = mkBtn("🌙每日0点：关");
        LinearLayout.LayoutParams autoLp = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        row2.addView(autoBtn, autoLp);

        autoHourlyBtn = mkBtn("⏰整点采集：关");
        LinearLayout.LayoutParams hourlyLp = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        hourlyLp.leftMargin = 14;
        row2.addView(autoHourlyBtn, hourlyLp);

        permBtn = mkBtn("🔧权限");
        LinearLayout.LayoutParams permLp = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        permLp.leftMargin = 14;
        row2.addView(permBtn, permLp);
        permBtn.setOnClickListener(new View.OnClickListener() {
            @Override public void onClick(View v) { openWhitelistGuide(); }
        });

        bar.addView(row1, new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT));
        bar.addView(status, new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT));
        bar.addView(progressBar, pbLp);
        bar.addView(row2, new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT));

        // ---- 两个独立倒计时框（白字，深色背景上清晰可见）----
        LinearLayout.LayoutParams cdLp = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        cdLp.topMargin = 10;
        cdMidnight = new TextView(this);
        cdMidnight.setTextColor(Color.WHITE);
        cdMidnight.setTextSize(12);
        cdMidnight.setPadding(0, 4, 0, 4);
        cdMidnight.setVisibility(View.GONE);
        bar.addView(cdMidnight, cdLp);

        cdHourly = new TextView(this);
        cdHourly.setTextColor(Color.WHITE);
        cdHourly.setTextSize(12);
        cdHourly.setPadding(0, 4, 0, 4);
        cdHourly.setVisibility(View.GONE);
        bar.addView(cdHourly, cdLp);

        // ---- WebView 看板 ----
        web = new WebView(this);
        WebSettings s = web.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);
        s.setAllowFileAccess(true);          // 允许加载本机生成的看板文件
        s.setUseWideViewPort(true);
        s.setLoadWithOverviewMode(true);
        s.setSupportZoom(true);
        s.setBuiltInZoomControls(true);
        s.setDisplayZoomControls(false);
        web.setBackgroundColor(Color.rgb(22, 24, 30));

        web.setWebViewClient(new WebViewClient() {
            @Override
            public boolean shouldOverrideUrlLoading(WebView view, String url) {
                if (url.startsWith("file://")) {
                    return false;            // 本机看板，留在 App 内
                }
                Uri u = Uri.parse(url);
                if (SITE_HOST.equals(u.getHost())) {
                    return false;            // 云端站内
                }
                openBrowser(url);            // 活动链接 → 系统浏览器
                return true;
            }

            @Override
            public void onReceivedError(WebView view, WebResourceRequest req,
                                        WebResourceError err) {
                if (req.isForMainFrame()) fallbackToLocalBoard("云端打不开");
            }

            @Override
            public void onReceivedHttpError(WebView view, WebResourceRequest req,
                                            WebResourceResponse resp) {
                if (req.isForMainFrame() && resp.getStatusCode() >= 400) {
                    fallbackToLocalBoard("云端返回 " + resp.getStatusCode());
                }
            }
        });
        // ---- 启动默认页：优先恢复「上次本机采集」的看板，让采集结果跨重启留存 ----
        // （此前每次冷启动都强制加载云端页，导致清后台重开后看不到上次采集的新活动）
        restoreLastBoardOrCloud();

        localRun.setOnClickListener(new View.OnClickListener() {
            @Override public void onClick(View v) { startLocalCrawl(); }
        });
        autoBtn.setOnClickListener(new View.OnClickListener() {
            @Override public void onClick(View v) { toggleAuto(KEY_AUTO, false); }
        });
        autoHourlyBtn.setOnClickListener(new View.OnClickListener() {
            @Override public void onClick(View v) { toggleAuto(KEY_AUTO_HOURLY, true); }
        });

        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.addView(bar, new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT));
        root.addView(web, new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));
        setContentView(root);

        // ---- 恢复定时开关状态，并校验（换机后权限会重置，这里重新提示）----
        refreshAutoButtons();
        verifyAutoSetup();
        startTicking();   // 每秒刷新两个倒计时框
    }

    @Override
    protected void onDestroy() {
        super.onDestroy();
        tickHandler.removeCallbacks(tickRunnable);
    }

    /** 云端站打不开时，回退到本机最近一次生成的看板（若有）。 */
    private void fallbackToLocalBoard(String reason) {
        String local = prefs().getString("last_board", "");
        if (local != null && !local.isEmpty() && new java.io.File(local).isFile()) {
            web.loadUrl("file://" + local);
            setStatus("⚠ " + reason + "，已显示本机最近一次看板");
        } else {
            setStatus("⚠ " + reason + "，且本机尚无看板，请先点「⚡本机采集」");
        }
    }

    /**
     * 启动默认页策略：本机有上次采集的看板就恢复它（结果跨重启留存）；
     * 没有才回落到云端站。点「☁️云端」随时可切到公网站点。
     */
    private void restoreLastBoardOrCloud() {
        String local = prefs().getString("last_board", "");
        if (local != null && !local.isEmpty() && new java.io.File(local).isFile()) {
            web.loadUrl("file://" + local);
            loadedBoardTime = prefs().getLong("last_board_time", 0);
            String when = loadedBoardTime > 0
                    ? android.text.format.DateFormat.format("MM-dd HH:mm", loadedBoardTime).toString()
                    : "";
            setStatus("已恢复上次本机采集结果" + (when.isEmpty() ? "" : "（" + when + " 采集）")
                    + "；看云端点「☁️云端」，看最新点「⚡本机采集」");
        } else {
            loadedBoardTime = -1;
            web.loadUrl(SITE);
        }
    }

    /**
     * 从后台切回 App 时：若整点/0点在后台又跑了一次采集（last_board_time 变了），
     * 自动刷新为本机最新看板——不用手动点刷新，也不会再误以为"没有变化"。
     */
    @Override
    protected void onResume() {
        super.onResume();
        if (loadedBoardTime < 0) return;   // 当前显示的是云端页，不打扰
        long t = prefs().getLong("last_board_time", 0);
        if (t > loadedBoardTime) {
            String local = prefs().getString("last_board", "");
            if (local != null && !local.isEmpty() && new java.io.File(local).isFile()) {
                loadedBoardTime = t;
                web.loadUrl("file://" + local);
                setStatus("后台整点采集已完成，已自动更新为本机最新看板"
                        + "（" + android.text.format.DateFormat.format("MM-dd HH:mm", t) + " 采集）");
            }
        }
    }

    private void openCloud() {
        setStatus("☁️ 正在打开云端雷达（GitHub Pages 公网站点）…");
        Toast.makeText(this, "打开云端雷达", Toast.LENGTH_SHORT).show();
        web.loadUrl(SITE);
    }

    // ============== 🌙 每日 0 点 / ⏰ 整点 定时开关 ==============

    private void toggleAuto(String key, boolean hourly) {
        if (prefs().getBoolean(key, false)) {
            // 关闭
            if (hourly) AlarmScheduler.cancelHourly(this);
            else AlarmScheduler.cancel(this);
            prefs().edit().putBoolean(key, false).apply();
            refreshAutoButtons();
            setStatus(hourly ? "已关闭整点自动采集" : "已关闭每日0点自动采集");
            Toast.makeText(this, "已关闭", Toast.LENGTH_SHORT).show();
        } else {
            enableAuto(key, hourly);
        }
    }

    private void enableAuto(String key, boolean hourly) {
        // 1) 精确闹钟权限（Android 12+ 需用户授权）
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
            AlarmManager am = (AlarmManager) getSystemService(Context.ALARM_SERVICE);
            if (am != null && !am.canScheduleExactAlarms()) {
                openExactAlarmSettings();
                setStatus("⚠ 请先在设置里「允许精确闹钟/设置闹钟」，再回来点一次启用");
                Toast.makeText(this, "需授权精确闹钟", Toast.LENGTH_LONG).show();
                return;
            }
        }
        // 2) 通知权限（Android 13+ 运行时申请）
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            if (checkSelfPermission(android.Manifest.permission.POST_NOTIFICATIONS)
                    != PackageManager.PERMISSION_GRANTED) {
                pendingMode = hourly ? 2 : 1;
                requestPermissions(
                        new String[]{android.Manifest.permission.POST_NOTIFICATIONS}, RC_NOTIF);
                return; // 授权结果在 onRequestPermissionsResult 里继续
            }
        }
        continueEnable(key, hourly);
    }

    private void continueEnable(String key, boolean hourly) {
        prefs().edit().putBoolean(key, true).apply();
        if (hourly) AlarmScheduler.scheduleHourly(this);
        else AlarmScheduler.schedule(this);
        refreshAutoButtons();
        if (hourly) {
            setStatus("✅ 已启用：每小时整点自动本机采集（跳过 00:00，由每日0点负责）");
            Toast.makeText(this, "已启用整点采集", Toast.LENGTH_SHORT).show();
        } else {
            setStatus("✅ 已启用：每日 00:00 自动本机采集（需完成「🔧权限」白名单才能锁屏触发）");
            Toast.makeText(this, "已启用每日0点采集", Toast.LENGTH_SHORT).show();
        }
        // 顺手把白名单设置推给用户，否则红米锁屏后闹钟可能不触发
        openWhitelistGuide();
    }

    @Override
    public void onRequestPermissionsResult(int requestCode,
                                           String[] permissions, int[] grantResults) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults);
        if (requestCode == RC_NOTIF) {
            if (grantResults.length > 0
                    && grantResults[0] == PackageManager.PERMISSION_GRANTED) {
                // 授权成功，继续启用
            } else {
                setStatus("⚠ 未授予通知权限，定时采集的通知无法显示（功能仍可用）");
            }
            if (pendingMode == 1) continueEnable(KEY_AUTO, false);
            else if (pendingMode == 2) continueEnable(KEY_AUTO_HOURLY, true);
            pendingMode = 0;
        }
    }

    /** 换机/重启后校验：若已开启但权限被重置，重新提示引导；闹钟丢失则自动补排。 */
    private void verifyAutoSetup() {
        boolean m = prefs().getBoolean(KEY_AUTO, false);
        boolean h = prefs().getBoolean(KEY_AUTO_HOURLY, false);
        if (!m && !h) return;
        // App 被更新/强停后系统会清掉已排闹钟：开关仍开启就自动补排
        if (m && !AlarmScheduler.isScheduled(this)) {
            AlarmScheduler.schedule(this);
        }
        if (h && !AlarmScheduler.isHourlyScheduled(this)) {
            AlarmScheduler.scheduleHourly(this);
        }
        StringBuilder sb = new StringBuilder();
        if (!isBatteryExempt()) sb.append("电池优化未关闭；");
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
            AlarmManager am = (AlarmManager) getSystemService(Context.ALARM_SERVICE);
            if (am != null && !am.canScheduleExactAlarms()) sb.append("精确闹钟未授权；");
        }
        if (sb.length() > 0) {
            setStatus("⚠ 定时采集权限未就绪（" + sb
                    + "点「🔧权限」重新设置后才会锁屏触发）");
        }
    }

    private void refreshAutoButtons() {
        boolean m = prefs().getBoolean(KEY_AUTO, false);
        boolean h = prefs().getBoolean(KEY_AUTO_HOURLY, false);
        autoBtn.setText(m ? "🌙每日0点：开" : "🌙每日0点：关");
        autoHourlyBtn.setText(h ? "⏰整点采集：开" : "⏰整点采集：关");
        cdMidnight.setVisibility(m ? View.VISIBLE : View.GONE);
        cdHourly.setVisibility(h ? View.VISIBLE : View.GONE);
        updateCountdowns();
    }

    /** 每秒刷新两个倒计时框（仅当对应开关开启时显示）。 */
    private void startTicking() {
        tickRunnable = new Runnable() {
            @Override public void run() {
                updateCountdowns();
                tickHandler.postDelayed(this, 1000);
            }
        };
        tickHandler.postDelayed(tickRunnable, 1000);
    }

    private void updateCountdowns() {
        long now = System.currentTimeMillis();
        if (cdMidnight.getVisibility() == View.VISIBLE) {
            long ms = AlarmScheduler.nextMidnightMillis() - now;
            cdMidnight.setText("🌙 距 00:00 自动采集还有 " + fmt(ms));
        }
        if (cdHourly.getVisibility() == View.VISIBLE) {
            long ms = AlarmScheduler.nextHourMillis() - now;
            cdHourly.setText("⏰ 距下一整点自动采集还有 " + fmt(ms));
        }
    }

    /** 毫秒 → HH:MM:SS（不足 1 小时也照常显示，便于观察）。 */
    private static String fmt(long ms) {
        if (ms < 0) ms = 0;
        long s = ms / 1000;
        long h = s / 3600;
        long m = (s % 3600) / 60;
        long sec = s % 60;
        return String.format(java.util.Locale.ROOT, "%02d:%02d:%02d", h, m, sec);
    }

    // ============== 🔧 白名单/权限引导（适配小米/红米/POCO，含换机重新适配） ==============

    private void openWhitelistGuide() {
        if (isXiaomi()) {
            new android.app.AlertDialog.Builder(this)
                .setTitle("红米/小米 必要白名单")
                .setMessage("要让 App 在锁屏后于整点/0点自动采集，请完成两步：\n\n"
                        + "① 自启动权限：允许本 App 自启动（否则关机重启/被杀后不触发）\n"
                        + "② 电池无限制：把本 App 设为「无限制/不限制」，否则被省电杀掉\n\n"
                        + "③ 上划多任务 → 长按本 App → 锁定时下拉锁定（防止被清理）\n\n"
                        + "下面会依次弹出对应设置页，按引导打开即可。换手机后需重新设置。")
                .setPositiveButton("去设置", new android.content.DialogInterface.OnClickListener() {
                    @Override public void onClick(android.content.DialogInterface d, int w) {
                        openAutostartSettings();      // 自启动
                        openBatteryExemption();        // 电池豁免
                    }
                })
                .setNegativeButton("稍后", null)
                .show();
        } else {
            // 非小米机型：走标准 Android 电池豁免即可
            openBatteryExemption();
            Toast.makeText(this, "非小米机型：请在设置里关闭本应用电池优化",
                    Toast.LENGTH_LONG).show();
        }
    }

    /** 跳转「忽略电池优化」系统弹窗（所有 Android 通用，含小米）。 */
    private void openBatteryExemption() {
        try {
            Intent i = new Intent(Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS);
            i.setData(Uri.parse("package:" + getPackageName()));
            startActivity(i);
        } catch (Exception e) {
            try {
                startActivity(new Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS)
                        .setData(Uri.parse("package:" + getPackageName())));
            } catch (Exception ignored) { }
        }
    }

    /** 跳转小米「自启动」管理页（不同 MIUI/HyperOS 版本 activity 名不同，逐级兜底）。 */
    private void openAutostartSettings() {
        String pkg = getPackageName();
        String[] actions = {
                "com.miui.securitycenter/com.miui.permcenter.autostart.AutoStartManagementActivity",
                "com.miui.securitycenter/com.miui.permcenter.autostart.AutoStartActivity",
                "com.miui.securitycenter/.permcenter.autostart.AutoStartManagementActivity",
        };
        for (String a : actions) {
            try {
                Intent i = new Intent();
                String[] parts = a.split("/");
                i.setClassName(parts[0], parts[1]);
                startActivity(i);
                return;
            } catch (Exception ignored) { }
        }
        // 兜底：应用详情页，用户手动找自启动
        try {
            startActivity(new Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS)
                    .setData(Uri.parse("package:" + pkg)));
        } catch (Exception ignored) { }
    }

    /** 跳转「精确闹钟」授权页（Android 12+）。 */
    private void openExactAlarmSettings() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
            try {
                startActivity(new Intent(Settings.ACTION_REQUEST_SCHEDULE_EXACT_ALARM)
                        .setData(Uri.parse("package:" + getPackageName())));
            } catch (Exception ignored) { }
        }
    }

    private boolean isBatteryExempt() {
        PowerManager pm = (PowerManager) getSystemService(Context.POWER_SERVICE);
        return pm != null && pm.isIgnoringBatteryOptimizations(getPackageName());
    }

    private boolean isXiaomi() {
        String mf = Build.MANUFACTURER == null ? "" : Build.MANUFACTURER.toLowerCase(Locale.ROOT);
        String br = Build.BRAND == null ? "" : Build.BRAND.toLowerCase(Locale.ROOT);
        return mf.contains("xiaomi") || mf.contains("redmi") || br.contains("xiaomi")
                || br.contains("redmi") || br.contains("poco");
    }

    // ============== ⚡ 本机采集（Python 管线跑在手机上） ==============

    private void startLocalCrawl() {
        if (crawling) return;
        crawling = true;
        localRun.setEnabled(false);
        getWindow().addFlags(WindowManager_FLAG_KEEP_SCREEN_ON());

        if (!Python.isStarted()) {
            Python.start(new AndroidPlatform(this));
        }

        final String filesDirPath = getFilesDir().getAbsolutePath();
        progressBar.setVisibility(View.VISIBLE);
        progressBar.setProgress(0);
        setStatus("①/④ 快爆采集中…（全程约 2~5 分钟，请保持 App 前台）");

        new Thread(new Runnable() {
            @Override public void run() {
                String board = "";
                String err = "";
                try {
                    PyObject entry = Python.getInstance().getModule("radar_entry");
                    String[] stages = {"hykb", "4399", "oppo", "board"};
                    String[] names = {"快爆", "4399", "OPPO", "看板生成"};
                    for (int i = 0; i < stages.length; i++) {
                        final int n = i + 1;
                        runOnUiThread(new Runnable() {
                            @Override public void run() {
                                setStatus("阶段 " + n + "/4 · " + names[n - 1] + " 进行中…");
                            }
                        });
                        entry.callAttr("run_stage", stages[i], filesDirPath);
                        final int pct = n * 25;
                        runOnUiThread(new Runnable() {
                            @Override public void run() { progressBar.setProgress(pct); }
                        });
                    }
                    board = entry.callAttr("board_path").toString();
                } catch (final Exception e) {
                    err = e.getMessage() == null ? e.toString() : e.getMessage();
                }

                final String fBoard = board, fErr = err;
                runOnUiThread(new Runnable() {
                    @Override public void run() {
                        crawling = false;
                        localRun.setEnabled(true);
                        getWindow().clearFlags(WindowManager_FLAG_KEEP_SCREEN_ON());
                        progressBar.setProgress(100);
                        if (fBoard != null && !fBoard.isEmpty()) {
                            // 记录本次采集结果与时间：下次打开 App 自动恢复此看板
                            prefs().edit()
                                    .putString("last_board", fBoard)
                                    .putLong("last_board_time", System.currentTimeMillis())
                                    .apply();
                            setStatus("✅ 本机采集完成，正在打开看板");
                            web.loadUrl("file://" + fBoard);
                            Toast.makeText(MainActivity.this,
                                    "本机采集完成 ✅", Toast.LENGTH_SHORT).show();
                        } else {
                            setStatus("❌ 本机采集失败：" + fErr);
                            Toast.makeText(MainActivity.this,
                                    "采集失败：" + fErr, Toast.LENGTH_LONG).show();
                        }
                    }
                });
            }
        }).start();
    }

    // ============== 工具 ==============

    private SharedPreferences prefs() {
        return getSharedPreferences(PREFS, Context.MODE_PRIVATE);
    }

    private Button mkBtn(String text) {
        Button b = new Button(this);
        b.setText(text);
        b.setTextSize(12);
        b.setAllCaps(false);
        b.setPadding(24, 8, 24, 8);
        return b;
    }

    private static int WindowManager_FLAG_KEEP_SCREEN_ON() {
        return android.view.WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON;
    }

    private void setStatus(final String text) {
        status.setText(text);
    }

    private void openBrowser(String url) {
        try {
            startActivity(new Intent(Intent.ACTION_VIEW, Uri.parse(url)));
        } catch (Exception ignored) {
        }
    }

    @Override
    public void onBackPressed() {
        if (web != null && web.canGoBack()) {
            web.goBack();
        } else {
            super.onBackPressed();
        }
    }
}
