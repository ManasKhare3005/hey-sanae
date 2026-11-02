package com.manaskhare.sanae

import android.app.AlarmManager
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Build
import androidx.core.app.NotificationCompat
import java.time.Instant
import java.time.LocalDateTime
import java.time.ZoneId

/**
 * Reminders fire on the phone itself: an exact alarm per pending reminder, so the notification
 * comes on time with the laptop off, no internet, or the app closed. (USE_EXACT_ALARM is granted
 * to this app automatically; without exact alarms Android may deliver a few minutes late.)
 * Alarms are re-armed after every sync and after a reboot.
 */
object Alarms {
    private fun intent(context: Context, uid: String) = PendingIntent.getBroadcast(
        context, uid.hashCode(),
        Intent(context, ReminderAlarmReceiver::class.java).setData(Uri.parse("max://reminder/$uid")).putExtra("uid", uid),
        PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)

    fun exact(context: Context): Boolean {
        val am = context.getSystemService(AlarmManager::class.java) ?: return false
        return Build.VERSION.SDK_INT < Build.VERSION_CODES.S || am.canScheduleExactAlarms()
    }

    /** Arm every pending reminder (an alarm already in the past goes off right away). */
    fun armAll(context: Context) {
        val am = context.getSystemService(AlarmManager::class.java)
        for (r in LocalDb.get(context).reminders()) {
            if (r.status != "pending") { am.cancel(intent(context, r.uid)); continue }
            val pi = intent(context, r.uid)
            if (exact(context)) am.setExactAndAllowWhileIdle(AlarmManager.RTC_WAKEUP, r.dueMs, pi)
            else am.setAndAllowWhileIdle(AlarmManager.RTC_WAKEUP, r.dueMs, pi)
        }
    }

    fun cancel(context: Context, uid: String) =
        context.getSystemService(AlarmManager::class.java).cancel(intent(context, uid))

    fun notificationId(uid: String) = 20_000 + (uid.hashCode() and 0xffff)

    /** A reminder went off: a one-time one is done; a repeating one moves on to its next occurrence. */
    fun afterFiring(r: LocalReminder, dirty: Boolean = true): LocalReminder {
        val zone = ZoneId.systemDefault()
        val toTime = { ms: Long -> LocalDateTime.ofInstant(Instant.ofEpochMilli(ms), zone) }
        val next = if (r.repeat.isBlank()) null
                   else Repeat.next(toTime(r.dueMs), r.repeat, toTime(maxOf(r.dueMs, System.currentTimeMillis())))
        val stamp = if (dirty) System.currentTimeMillis() else r.updatedMs
        return if (next == null) r.copy(status = "done", updatedMs = stamp, dirty = dirty)
               else r.copy(dueMs = next.atZone(zone).toInstant().toEpochMilli(), updatedMs = stamp, dirty = dirty)
    }

    /** Show a reminder (once: whichever comes first, this phone's alarm or the laptop's event). */
    fun show(context: Context, uid: String, text: String) {
        val line = Persona.line(context, "reminder", text)
        val nm = context.getSystemService(NotificationManager::class.java)
        val open = PendingIntent.getActivity(context, 0,
            Intent(context, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
        nm.notify(notificationId(uid), NotificationCompat.Builder(context, SanaeApp.CH_REMINDER)
            .setSmallIcon(R.drawable.ic_stat_sanae)
            .setContentTitle("⏰ " + Persona.name(context))
            .setContentText(line)
            .setStyle(NotificationCompat.BigTextStyle().bigText(line))
            .setPriority(NotificationCompat.PRIORITY_HIGH)
            .setCategory(NotificationCompat.CATEGORY_REMINDER)
            .setAutoCancel(true)
            .setContentIntent(open)
            .build())
    }
}

/** A reminder's alarm went off: notify, mark it done here (a repeating one: move it to the next
 *  time and arm that), tell the laptop when it can be reached. */
class ReminderAlarmReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        val uid = intent.getStringExtra("uid") ?: return
        val db = LocalDb.get(context)
        val r = db.reminder(uid) ?: return
        if (r.status != "pending") return                   // the laptop's event got here first, or cancelled
        Alarms.show(context, uid, r.text)
        db.put(Alarms.afterFiring(r))
        if (r.repeat.isNotBlank()) Alarms.armAll(context)
        Sync.trigger(context)
    }
}
