package com.manaskhare.sanae

import android.app.AlarmManager
import android.app.Notification
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.os.Build
import androidx.core.app.NotificationCompat
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withTimeoutOrNull
import org.json.JSONObject
import java.time.LocalDate
import java.time.LocalDateTime
import java.time.LocalTime
import java.time.ZoneId

/**
 * Wind-down at midnight (Settings -> Wind down), done by the phone itself so it works with the
 * laptop off: the phone goes quiet (Do Not Disturb, if you allowed it), she says goodnight (a
 * notification; tap it for your bedtime story), and the morning alarm is set. When the laptop
 * answers it picks the time (before tomorrow's first class) and her line (winddown.py); otherwise
 * your usual wake time and a line from here. The alarm turns Do Not Disturb back off.
 */
object WindDown {
    private const val NIGHT_ID = 7500
    private const val WAKE_ID = 7501
    const val ACTION_NIGHT = "com.manaskhare.sanae.WIND_DOWN"
    const val ACTION_WAKE = "com.manaskhare.sanae.WAKE"
    const val ACTION_STOP = "com.manaskhare.sanae.WAKE_STOP"
    const val ACTION_SNOOZE = "com.manaskhare.sanae.WAKE_SNOOZE"

    private fun ms(at: LocalDateTime) = at.atZone(ZoneId.systemDefault()).toInstant().toEpochMilli()

    private fun pi(context: Context, action: String, code: Int) = PendingIntent.getBroadcast(context, code,
        Intent(context, WindDownReceiver::class.java).setAction(action), PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)

    /** The next wind-down (tonight at `windDownAt`), or cancel it when it's off. */
    fun arm(context: Context) {
        val prefs = Prefs(context)
        val am = context.getSystemService(AlarmManager::class.java)
        val p = pi(context, ACTION_NIGHT, NIGHT_ID)
        if (!prefs.windDownOn) { am.cancel(p); return }
        val at = runCatching { LocalTime.parse(prefs.windDownAt) }.getOrDefault(LocalTime.MIDNIGHT)
        var next = LocalDateTime.of(LocalDate.now(), at)
        if (!next.isAfter(LocalDateTime.now())) next = next.plusDays(1)
        if (Alarms.exact(context)) am.setExactAndAllowWhileIdle(AlarmManager.RTC_WAKEUP, ms(next), p)
        else am.setAndAllowWhileIdle(AlarmManager.RTC_WAKEUP, ms(next), p)
    }

    fun quietAllowed(context: Context) =
        runCatching { context.getSystemService(NotificationManager::class.java).isNotificationPolicyAccessGranted }.getOrDefault(false)

    suspend fun night(context: Context) {
        val prefs = Prefs(context)
        var wake = runCatching { LocalTime.parse(prefs.wakeAt) }.getOrDefault(LocalTime.of(8, 30))
        var line = ""
        val api = SanaeApi.from(prefs)
        if (api != null) withTimeoutOrNull(8_000) {
            runCatching { JSONObject(api.raw("GET", "/api/winddown?wake=${prefs.wakeAt}", JSONObject())) }.getOrNull()
        }?.let { plan ->
            runCatching { wake = LocalTime.parse(plan.optString("wake")) }
            line = plan.optString("line")
        }
        val name = Persona.name(context)
        if (line.isBlank()) line = "It's midnight. Your phone's going quiet now." +
            (if (prefs.windDownAlarm) " Alarm's set for ${clock(wake)}." else "") + " Sleep well."
        val nm = context.getSystemService(NotificationManager::class.java)
        if (prefs.windDownQuiet && nm.isNotificationPolicyAccessGranted) {
            runCatching { nm.setInterruptionFilter(NotificationManager.INTERRUPTION_FILTER_PRIORITY) }
            prefs.windDownQuieted = true
        }
        val open = PendingIntent.getActivity(context, NIGHT_ID,
            Intent(context, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP).putExtra(MainActivity.EXTRA_TAB, MainActivity.TAB_US),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
        nm.notify(NIGHT_ID, NotificationCompat.Builder(context, SanaeApp.CH_CHAT)
            .setSmallIcon(R.drawable.ic_stat_sanae)
            .setContentTitle("Goodnight from $name")
            .setContentText(line)
            .setStyle(NotificationCompat.BigTextStyle().bigText(line + "\nTap for our bedtime story."))
            .setAutoCancel(true)
            .setContentIntent(open)
            .build())
        if (prefs.windDownAlarm) {
            var at = LocalDateTime.of(LocalDate.now(), wake)
            if (!at.isAfter(LocalDateTime.now())) at = at.plusDays(1)
            setAlarm(context, ms(at))
        }
        arm(context)                                      // tomorrow night
    }

    private fun setAlarm(context: Context, atMs: Long) {
        val am = context.getSystemService(AlarmManager::class.java)
        val show = PendingIntent.getActivity(context, WAKE_ID, Intent(context, MainActivity::class.java), PendingIntent.FLAG_IMMUTABLE)
        runCatching { am.setAlarmClock(AlarmManager.AlarmClockInfo(atMs, show), pi(context, ACTION_WAKE, WAKE_ID)) }
            .onFailure { am.setAndAllowWhileIdle(AlarmManager.RTC_WAKEUP, atMs, pi(context, ACTION_WAKE, WAKE_ID)) }
        Prefs(context).windDownAlarmAt = atMs
    }

    fun wake(context: Context) {
        val prefs = Prefs(context)
        val nm = context.getSystemService(NotificationManager::class.java)
        if (prefs.windDownQuieted && nm.isNotificationPolicyAccessGranted) {
            runCatching { nm.setInterruptionFilter(NotificationManager.INTERRUPTION_FILTER_ALL) }
        }
        prefs.windDownQuieted = false
        prefs.windDownAlarmAt = 0L
        val name = Persona.name(context)
        val n = NotificationCompat.Builder(context, SanaeApp.CH_ALARM)
            .setSmallIcon(R.drawable.ic_stat_sanae)
            .setContentTitle("Good morning! ☀")
            .setContentText("$name's alarm. Time to get up.")
            .setCategory(NotificationCompat.CATEGORY_ALARM)
            .setPriority(NotificationCompat.PRIORITY_MAX)
            .setOngoing(true)
            .setContentIntent(PendingIntent.getActivity(context, WAKE_ID,
                Intent(context, MainActivity::class.java).putExtra(MainActivity.EXTRA_TAB, MainActivity.TAB_US),
                PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT))
            .addAction(0, "Snooze 10 min", pi(context, ACTION_SNOOZE, WAKE_ID + 1))
            .addAction(0, "I'm up", pi(context, ACTION_STOP, WAKE_ID + 2))
            .build()
        n.flags = n.flags or Notification.FLAG_INSISTENT           // keeps ringing until you answer it
        nm.notify(WAKE_ID, n)
    }

    fun stop(context: Context) = context.getSystemService(NotificationManager::class.java).cancel(WAKE_ID)

    fun snooze(context: Context) {
        stop(context)
        setAlarm(context, System.currentTimeMillis() + 10 * 60_000L)
    }

    fun clock(t: LocalTime) = "${if (t.hour % 12 == 0) 12 else t.hour % 12}${if (t.minute > 0) ":%02d".format(t.minute) else ""} ${if (t.hour < 12) "AM" else "PM"}"
}

class WindDownReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        when (intent.action) {
            WindDown.ACTION_NIGHT -> {
                val done = goAsync()
                CoroutineScope(Dispatchers.IO).launch {
                    try { WindDown.night(context.applicationContext) } finally { done.finish() }
                }
            }
            WindDown.ACTION_WAKE -> WindDown.wake(context)
            WindDown.ACTION_STOP -> WindDown.stop(context)
            WindDown.ACTION_SNOOZE -> WindDown.snooze(context)
        }
    }
}
