package com.linwe.gameradar;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;

/**
 * 开机/重启后重新排闹钟。
 * 仅当用户此前开启过对应定时采集（auto_midnight / auto_hourly）才续订，
 * 否则不打扰用户。换手机后首次开机若未开启，则不会自动排。
 */
public class BootReceiver extends BroadcastReceiver {

    @Override
    public void onReceive(Context context, Intent intent) {
        SharedPreferences p = context.getSharedPreferences("radar", Context.MODE_PRIVATE);
        if (p.getBoolean("auto_midnight", false)) {
            AlarmScheduler.schedule(context);
        }
        if (p.getBoolean("auto_hourly", false)) {
            AlarmScheduler.scheduleHourly(context);
        }
    }
}
