package com.linwe.gameradar;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.os.Build;

/**
 * 接收 0 点精确闹钟广播：
 *   1) 先排好「明天」的闹钟（精确闹钟是一次性，必须自续）
 *   2) 拉起前台服务跑本机采集管线
 */
public class MidnightAlarmReceiver extends BroadcastReceiver {

    @Override
    public void onReceive(Context context, Intent intent) {
        // 1) 续订下一次（保证每天都有）
        AlarmScheduler.schedule(context);

        // 2) 启动前台采集服务
        Intent svc = new Intent(context, CrawlForegroundService.class);
        svc.setAction(CrawlForegroundService.ACTION_START);
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            context.startForegroundService(svc);
        } else {
            context.startService(svc);
        }
    }
}
