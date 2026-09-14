package com.linwe.gameradar;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.os.Build;

/**
 * 接收「整点」精确闹钟广播（每小时一次，跳过 00:00，00:00 由 MidnightAlarmReceiver 负责）：
 *   1) 先排好「下一个整点」的闹钟（精确闹钟是一次性，必须自续）
 *   2) 拉起前台服务跑本机采集管线
 */
public class HourlyAlarmReceiver extends BroadcastReceiver {

    @Override
    public void onReceive(Context context, Intent intent) {
        // 1) 续订下一次整点（保证每小时都有）
        AlarmScheduler.scheduleHourly(context);

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
