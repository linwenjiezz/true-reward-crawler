package com.linwe.gameradar;

import android.app.Activity;
import android.content.Intent;
import android.graphics.Color;
import android.net.Uri;
import android.os.Bundle;
import android.view.View;
import android.view.ViewGroup;
import android.view.Window;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.TextView;
import android.widget.Toast;

import com.chaquo.python.PyObject;
import com.chaquo.python.Python;
import com.chaquo.python.android.AndroidPlatform;

/**
 * 游戏活动雷达 · 手机端 v2
 *
 * 双模式：
 *  ⚡本机采集 —— 采集管线（纯 Python）直接在手机上执行：快爆 → 4399 → OPPO →
 *               生成看板，完成后直接显示本机生成的雷达页面。手机是国内 IP，
 *               抓渠道无风控顾虑；整条流程点一下全自动，与电脑 VS Code 点 Run 等价。
 *  ☁️云端网页 —— GitHub Pages 上的雷达（GitHub 服务器每小时自动采集 + 0点蹲守），
 *               手机不干活，纯浏览。
 *
 * 注意：本机采集运行 2~5 分钟（取决于手机与网络），期间保持亮屏、勿退出 App。
 */
public class MainActivity extends Activity {

    private static final String SITE = "https://linwenjiezz.github.io/true-reward-crawler/";
    private static final String SITE_HOST = "linwenjiezz.github.io";

    private WebView web;
    private TextView status;
    private Button localRun, cloudBtn, refresh;
    private volatile boolean crawling = false;

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
            @Override public void onClick(View v) { web.loadUrl(SITE); }
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

        bar.addView(row1, new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT));
        bar.addView(status, new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT));

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
        });
        web.loadUrl(SITE);

        localRun.setOnClickListener(new View.OnClickListener() {
            @Override public void onClick(View v) { startLocalCrawl(); }
        });

        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.addView(bar, new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT));
        root.addView(web, new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));
        setContentView(root);
    }

    private Button mkBtn(String text) {
        Button b = new Button(this);
        b.setText(text);
        b.setTextSize(12);
        b.setAllCaps(false);
        b.setPadding(24, 8, 24, 8);
        return b;
    }

    // ---------------- ⚡ 本机采集（Python 管线跑在手机上） ----------------

    private void startLocalCrawl() {
        if (crawling) return;
        crawling = true;
        localRun.setEnabled(false);
        getWindow().addFlags(WindowManager_FLAG_KEEP_SCREEN_ON());

        if (!Python.isStarted()) {
            Python.start(new AndroidPlatform(this));
        }

        final String filesDirPath = getFilesDir().getAbsolutePath();
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
                                setStatus("阶段 " + n + "/4 · " + stagesName(n) + "进行中…");
                            }
                        });
                        entry.callAttr("run_stage", stages[i], filesDirPath);
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
                        if (fBoard != null && !fBoard.isEmpty()) {
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

            private String stagesName(int n) {
                return new String[]{"快爆", "4399", "OPPO", "看板生成"}[n - 1];
            }
        }).start();
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
