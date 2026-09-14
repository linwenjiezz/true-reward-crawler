package com.linwe.gameradar;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.Service;
import android.content.Context;
import android.content.Intent;
import android.os.Build;
import android.os.IBinder;

import com.chaquo.python.PyObject;
import com.chaquo.python.Python;
import com.chaquo.python.android.AndroidPlatform;

/**
 * 0 点本机采集的前台服务。
 *
 * Android 8+ 后台不允许长任务，必须挂前台通知。采集约 2~5 分钟，
 * 期间锁屏也照常跑（配合 MIDNIGHT 精确闹钟 + 手机不进入深度杀进程状态）。
 * 完成后更新通知并自停。
 */
public class CrawlForegroundService extends Service {

    public static final String ACTION_START = "com.linwe.gameradar.CRAWL_START";
    private static final String CHANNEL_ID = "radar_crawl";
    private static final int NOTIF_ID = 1;

    private volatile boolean running = false;

    @Override
    public void onCreate() {
        super.onCreate();
        createChannel();
    }

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        if (ACTION_START.equals(intent.getAction()) && !running) {
            startForeground(NOTIF_ID, buildNotification("🎮 活动雷达采集中…", "正在抓取 快爆→4399→OPPO"));
            running = true;
            new Thread(new Runnable() {
                @Override public void run() {
                    runCrawl();
                    stopForeground(true);
                    stopSelf();
                }
            }).start();
        }
        // 不被系统拉活：采集任务靠每日闹钟重新触发
        return START_NOT_STICKY;
    }

    private void runCrawl() {
        String filesDir = getFilesDir().getAbsolutePath();
        try {
            if (!Python.isStarted()) {
                Python.start(new AndroidPlatform(this));
            }
            PyObject entry = Python.getInstance().getModule("radar_entry");
            String[] stages = {"hykb", "4399", "oppo", "board"};
            String[] names = {"快爆", "4399", "OPPO", "看板生成"};
            for (int i = 0; i < stages.length; i++) {
                final int n = i + 1;
                updateProgress(n * 25, "阶段 " + n + "/4 · " + names[i] + " 进行中…");
                entry.callAttr("run_stage", stages[i], filesDir);
            }
            updateProgress(100, "✅ 采集完成，看板已生成");
            // 记下最新本地看板路径与时间：App 打开时自动恢复此看板（结果跨重启留存）
            String board = entry.callAttr("board_path").toString();
            getSharedPreferences("radar", Context.MODE_PRIVATE)
                    .edit()
                    .putString("last_board", board)
                    .putLong("last_board_time", System.currentTimeMillis())
                    .apply();
        } catch (Exception e) {
            String msg = e.getMessage() == null ? e.toString() : e.getMessage();
            updateProgress(100, "❌ 采集失败：" + msg);
        }
    }

    private void createChannel() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            NotificationManager nm =
                    (NotificationManager) getSystemService(Context.NOTIFICATION_SERVICE);
            NotificationChannel ch = new NotificationChannel(
                    CHANNEL_ID, "活动雷达采集", NotificationManager.IMPORTANCE_LOW);
            ch.setDescription("本机定时采集三渠道活动（每日0点 / 每小时整点）");
            nm.createNotificationChannel(ch);
        }
    }

    private Notification buildNotification(String title, String text, int pct) {
        Intent i = new Intent(this, MainActivity.class);
        PendingIntent pi = PendingIntent.getActivity(
                this, 0, i, PendingIntent.FLAG_IMMUTABLE);
        Notification.Builder b;
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            b = new Notification.Builder(this, CHANNEL_ID);
        } else {
            b = new Notification.Builder(this);
        }
        b.setContentTitle(title)
         .setContentText(text)
         .setSmallIcon(android.R.drawable.stat_notify_sync)
         .setContentIntent(pi)
         .setOngoing(true)
         .setProgress(100, pct, false);   // 绿色进度条（系统通知样式）
        return b.build();
    }

    private Notification buildNotification(String title, String text) {
        return buildNotification(title, text, 0);
    }

    private void updateProgress(int pct, String text) {
        NotificationManager nm =
                (NotificationManager) getSystemService(Context.NOTIFICATION_SERVICE);
        nm.notify(NOTIF_ID, buildNotification("🎮 活动雷达采集中", text, pct));
    }

    private void updateNotification(String text) {
        NotificationManager nm =
                (NotificationManager) getSystemService(Context.NOTIFICATION_SERVICE);
        nm.notify(NOTIF_ID, buildNotification("🎮 活动雷达", text));
    }

    @Override
    public IBinder onBind(Intent intent) {
        return null;
    }
}
