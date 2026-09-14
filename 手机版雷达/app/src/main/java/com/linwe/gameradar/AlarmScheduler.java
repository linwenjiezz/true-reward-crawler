package com.linwe.gameradar;

import android.app.AlarmManager;
import android.app.PendingIntent;
import android.content.Context;
import android.content.Intent;
import android.os.Build;

import java.util.Calendar;

/**
 * 精确的每日 0 点闹钟（北京时间，由手机本地时区决定）。
 *
 * 关键设计：
 *  - 用 AlarmManager.setExactAndAllowWhileIdle：即使手机锁屏/Doze 休眠也能被唤醒，
 *    不受 GitHub Actions 那种「排队延迟」影响——这是云端方案在午夜失败、手机方案能命中的原因。
 *  - setExactAndAllowWhileIdle 是「一次性」闹钟，所以每次触发后由 MidnightAlarmReceiver 重新排下一次。
 *  - 配合 MIUI/HyperOS 的「自启动 + 电池无限制」白名单（见 MainActivity 权限引导），才能在红米上可靠触发。
 */
public final class AlarmScheduler {

    public static final String ACTION_MIDNIGHT =
            "com.linwe.gameradar.MIDNIGHT_CRAWL";
    public static final String ACTION_HOURLY =
            "com.linwe.gameradar.HOURLY_CRAWL";

    private static final int REQ_CODE = 0x4D49;   // "MI" 每日0点
    private static final int REQ_HOURLY = 0x484F; // "HO" 整点

    /** 排下一次「今天或明天 00:00:00」的精确闹钟。 */
    public static void schedule(Context ctx) {
        AlarmManager am = (AlarmManager) ctx.getSystemService(Context.ALARM_SERVICE);
        if (am == null) return;
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S
                && !am.canScheduleExactAlarms()) {
            return; // 用户尚未授权精确闹钟，引导见 MainActivity.openExactAlarmSettings()
        }
        PendingIntent pi = buildPendingIntent(ctx);
        long trigger = nextMidnightMillis();
        am.setExactAndAllowWhileIdle(AlarmManager.RTC_WAKEUP, trigger, pi);
    }

    /** 取消已排的闹钟。 */
    public static void cancel(Context ctx) {
        AlarmManager am = (AlarmManager) ctx.getSystemService(Context.ALARM_SERVICE);
        if (am == null) return;
        PendingIntent pi = buildPendingIntent(ctx);
        am.cancel(pi);
    }

    /** 是否已存在排好的「每日0点」闹钟（用于 UI 状态恢复）。 */
    public static boolean isScheduled(Context ctx) {
        Intent i = new Intent(ctx, MidnightAlarmReceiver.class);
        i.setAction(ACTION_MIDNIGHT);
        PendingIntent pi = PendingIntent.getBroadcast(ctx, REQ_CODE, i,
                PendingIntent.FLAG_NO_CREATE | PendingIntent.FLAG_IMMUTABLE);
        return pi != null;
    }

    private static PendingIntent buildPendingIntent(Context ctx) {
        Intent i = new Intent(ctx, MidnightAlarmReceiver.class);
        i.setAction(ACTION_MIDNIGHT);
        return PendingIntent.getBroadcast(ctx, REQ_CODE, i,
                PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
    }

    // ============== 整点（每小时，自动跳过 0 点） ==============

    /** 排下一次「下一个整点（且非 00:00）」的精确闹钟。 */
    public static void scheduleHourly(Context ctx) {
        AlarmManager am = (AlarmManager) ctx.getSystemService(Context.ALARM_SERVICE);
        if (am == null) return;
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S
                && !am.canScheduleExactAlarms()) {
            return;
        }
        PendingIntent pi = buildHourlyPendingIntent(ctx);
        long trigger = nextHourMillis();
        am.setExactAndAllowWhileIdle(AlarmManager.RTC_WAKEUP, trigger, pi);
    }

    /** 取消整点闹钟。 */
    public static void cancelHourly(Context ctx) {
        AlarmManager am = (AlarmManager) ctx.getSystemService(Context.ALARM_SERVICE);
        if (am == null) return;
        PendingIntent pi = buildHourlyPendingIntent(ctx);
        am.cancel(pi);
    }

    /** 是否已存在排好的整点闹钟。 */
    public static boolean isHourlyScheduled(Context ctx) {
        Intent i = new Intent(ctx, HourlyAlarmReceiver.class);
        i.setAction(ACTION_HOURLY);
        PendingIntent pi = PendingIntent.getBroadcast(ctx, REQ_HOURLY, i,
                PendingIntent.FLAG_NO_CREATE | PendingIntent.FLAG_IMMUTABLE);
        return pi != null;
    }

    private static PendingIntent buildHourlyPendingIntent(Context ctx) {
        Intent i = new Intent(ctx, HourlyAlarmReceiver.class);
        i.setAction(ACTION_HOURLY);
        return PendingIntent.getBroadcast(ctx, REQ_HOURLY, i,
                PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
    }

    /** 计算下一个整点（01:00~23:00）的毫秒时间戳，刻意跳过 00:00（由每日0点负责）。 */
    static long nextHourMillis() {
        Calendar c = Calendar.getInstance();
        c.set(Calendar.MINUTE, 0);
        c.set(Calendar.SECOND, 0);
        c.set(Calendar.MILLISECOND, 0);
        c.add(Calendar.HOUR_OF_DAY, 1);              // 先推到下一个整点
        if (c.get(Calendar.HOUR_OF_DAY) == 0) {       // 若正好是 00:00，再顺延到 01:00
            c.add(Calendar.HOUR_OF_DAY, 1);
        }
        return c.getTimeInMillis();
    }

    /** 计算下一个 00:00:00 的毫秒时间戳（已过期则顺延到明天）。 */
    static long nextMidnightMillis() {
        Calendar c = Calendar.getInstance();
        c.set(Calendar.HOUR_OF_DAY, 0);
        c.set(Calendar.MINUTE, 0);
        c.set(Calendar.SECOND, 0);
        c.set(Calendar.MILLISECOND, 0);
        long now = System.currentTimeMillis();
        if (c.getTimeInMillis() <= now) {
            c.add(Calendar.DAY_OF_MONTH, 1);
        }
        return c.getTimeInMillis();
    }
}
