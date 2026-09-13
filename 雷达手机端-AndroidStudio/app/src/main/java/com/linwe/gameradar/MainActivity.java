package com.linwe.gameradar;

import android.app.Activity;
import android.content.Intent;
import android.graphics.Color;
import android.net.Uri;
import android.os.Bundle;
import android.view.View;
import android.view.ViewGroup;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.TextView;

/**
 * 游戏活动雷达 · 手机端
 * 内核 = 云端雷达网页（GitHub Pages，数据由 GitHub 每小时自动采集更新）。
 * - 打开即最新看板；「🔄 刷新」重新加载网页
 * - 「⚡ 手动采集」跳转 GitHub Actions 页面，点 Run workflow 立即触发一次云端采集
 *   （需在浏览器里登录过 GitHub；触发后 2~4 分钟数据上线）
 * - 看板里的活动链接自动跳转系统浏览器打开，不劫持 WebView
 */
public class MainActivity extends Activity {

    private static final String SITE = "https://linwenjiezz.github.io/true-reward-crawler/";
    private static final String SITE_HOST = "linwenjiezz.github.io";
    private static final String ACTIONS = "https://github.com/linwenjiezz/true-reward-crawler/actions";

    private WebView web;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);

        // ---- 顶部工具条 ----
        LinearLayout bar = new LinearLayout(this);
        bar.setOrientation(LinearLayout.HORIZONTAL);
        bar.setGravity(android.view.Gravity.CENTER_VERTICAL);
        bar.setBackgroundColor(Color.rgb(22, 24, 30));
        bar.setPadding(36, 24, 24, 24);

        TextView title = new TextView(this);
        title.setText("🎮 游戏活动雷达");
        title.setTextColor(Color.WHITE);
        title.setTextSize(16);
        LinearLayout.LayoutParams titleLp =
                new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f);
        bar.addView(title, titleLp);

        Button manual = new Button(this);
        manual.setText("⚡手动采集");
        manual.setTextSize(12);
        manual.setAllCaps(false);
        manual.setOnClickListener(new View.OnClickListener() {
            @Override public void onClick(View v) {
                openBrowser(ACTIONS);
            }
        });
        bar.addView(manual);

        Button refresh = new Button(this);
        refresh.setText("🔄刷新");
        refresh.setTextSize(12);
        refresh.setAllCaps(false);
        LinearLayout.LayoutParams refreshLp =
                new LinearLayout.LayoutParams(ViewGroup.LayoutParams.WRAP_CONTENT,
                        ViewGroup.LayoutParams.WRAP_CONTENT);
        refreshLp.leftMargin = 16;
        bar.addView(refresh, refreshLp);

        // ---- WebView 看板 ----
        web = new WebView(this);
        WebSettings s = web.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);
        s.setUseWideViewPort(true);
        s.setLoadWithOverviewMode(true);
        s.setSupportZoom(true);
        s.setBuiltInZoomControls(true);
        s.setDisplayZoomControls(false);
        web.setBackgroundColor(Color.rgb(22, 24, 30));

        web.setWebViewClient(new WebViewClient() {
            @Override
            public boolean shouldOverrideUrlLoading(WebView view, String url) {
                Uri u = Uri.parse(url);
                // 站内（GitHub Pages）留在 App 里；活动链接等站外地址交给系统浏览器
                if (SITE_HOST.equals(u.getHost())) {
                    return false;
                }
                openBrowser(url);
                return true;
            }
        });
        web.loadUrl(SITE);

        refresh.setOnClickListener(new View.OnClickListener() {
            @Override public void onClick(View v) {
                web.reload();
            }
        });

        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.addView(bar, new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT));
        root.addView(web, new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));
        setContentView(root);
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
