package com.manaskhare.sanae

import android.app.AlarmManager
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import androidx.core.app.NotificationCompat
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withTimeoutOrNull
import java.time.LocalDate
import java.time.LocalDateTime
import java.time.LocalTime
import java.time.ZoneId
import java.time.format.TextStyle
import java.util.Locale

/** The routine's rules (same as the laptop's chores.py; pure, JVM-tested). */
object RoutineLogic {
    fun dueOn(freq: String, day: LocalDate): Boolean {
        if (freq == "daily") return true
        if (freq == "weekdays") return day.dayOfWeek.value <= 5
        val (kind, n) = freq.split(":").let { (it.getOrNull(0) ?: "") to it.getOrNull(1)?.toIntOrNull() }
        return when {
            n == null -> false
            kind == "weekly" -> day.dayOfWeek.value - 1 == n                       // Monday = 0
            kind == "monthly" -> day.dayOfMonth == minOf(n, day.lengthOfMonth())   // the 31st -> a short month's last day
            else -> false
        }
    }

    fun label(freq: String): String {
        if (freq == "daily") return "every day"
        if (freq == "weekdays") return "weekdays"
        val n = freq.substringAfter(":").toIntOrNull() ?: return freq
        return when (freq.substringBefore(":")) {
            "weekly" -> "every " + java.time.DayOfWeek.of(n + 1).getDisplayName(TextStyle.FULL, Locale.US)
            "monthly" -> "monthly on the " + ordinal(n)
            else -> freq
        }
    }

    fun ordinal(n: Int) = "$n" + if (n % 100 in 10..20) "th" else when (n % 10) { 1 -> "st"; 2 -> "nd"; 3 -> "rd"; else -> "th" }

    fun freq(kind: String, weekday: Int, monthDay: Int) = when (kind) {
        "weekly" -> "weekly:$weekday"
        "monthly" -> "monthly:$monthDay"
        else -> kind
    }

    fun done(c: LocalChore, day: LocalDate) = c.doneDay == day.toString()

    /** Today's tasks first (unticked, then ticked), then the rest. */
    fun order(chores: List<LocalChore>, day: LocalDate): List<LocalChore> {
        val today = chores.filter { dueOn(it.freq, day) }
        return today.filter { !done(it, day) } + today.filter { done(it, day) } + chores.filter { !dueOn(it.freq, day) }
    }

    fun forgotten(chores: List<LocalChore>, day: LocalDate) =
        chores.filter { it.status == "active" && dueOn(it.freq, day) && !done(it, day) }

    fun join(items: List<String>) = if (items.size <= 1) items.joinToString() else items.dropLast(1).joinToString(", ") + " and " + items.last()
}

/**
 * The evening check: at `routineCheckAt` (default 9 PM) the phone looks at today's routine and, if
 * anything is still unticked, says so in a notification ("you forgot to water the plants today").
 * Runs on the phone's own copy, so it works with the laptop off; it syncs first when it can, so a
 * tick made on the laptop counts.
 */
object Routine {
    const val NOTIFY_ID = 47_100
    const val ACTION_CHECK = "com.manaskhare.sanae.ROUTINE_CHECK"
    const val ACTION_DONE = "com.manaskhare.sanae.ROUTINE_DONE"

    private fun pi(context: Context) = PendingIntent.getBroadcast(context, NOTIFY_ID,
        Intent(context, RoutineReceiver::class.java).setAction(ACTION_CHECK), PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)

    fun checkTime(context: Context): LocalTime = runCatching { LocalTime.parse(Prefs(context).routineCheckAt) }.getOrDefault(LocalTime.of(21, 0))

    /** Arm the next evening check (or cancel it when turned off). */
    fun arm(context: Context) {
        val prefs = Prefs(context)
        val am = context.getSystemService(AlarmManager::class.java)
        if (!prefs.routineCheckOn) { am.cancel(pi(context)); return }
        var next = LocalDateTime.of(LocalDate.now(), checkTime(context))
        if (!next.isAfter(LocalDateTime.now())) next = next.plusDays(1)
        val ms = next.atZone(ZoneId.systemDefault()).toInstant().toEpochMilli()
        if (Alarms.exact(context)) am.setExactAndAllowWhileIdle(AlarmManager.RTC_WAKEUP, ms, pi(context))
        else am.setAndAllowWhileIdle(AlarmManager.RTC_WAKEUP, ms, pi(context))
    }

    // ----- ticking from the app / the notification -----
    fun add(context: Context, text: String, freq: String): LocalChore {
        val c = LocalChore(LocalDb.newUid(), text.trim(), freq, created = LocalDateTime.now().withNano(0).toString())
        LocalDb.get(context).put(c)
        after(context)
        return c
    }

    fun tick(context: Context, uid: String, done: Boolean) {
        val db = LocalDb.get(context)
        val c = db.chore(uid) ?: return
        db.put(c.copy(doneDay = if (done) LocalDate.now().toString() else "", updatedMs = System.currentTimeMillis(), dirty = true))
        after(context)
    }

    fun delete(context: Context, uid: String) {
        val db = LocalDb.get(context)
        val c = db.chore(uid) ?: return
        db.put(c.copy(status = "deleted", updatedMs = System.currentTimeMillis(), dirty = true))
        after(context)
    }

    private fun after(context: Context) {
        Sync.trigger(context.applicationContext)
        TodayWidget.refresh(context.applicationContext)
    }

    /** The evening check itself. */
    suspend fun check(context: Context, sync: Boolean = true) {
        // pick up ticks made on the laptop (short: a broadcast only gets a few seconds)
        if (sync) withTimeoutOrNull(7_000) { runCatching { Sync.run(context) } }
        val today = LocalDate.now()
        val left = RoutineLogic.forgotten(LocalDb.get(context).chores("status = 'active'"), today)
        val nm = context.getSystemService(NotificationManager::class.java)
        if (left.isEmpty()) { nm.cancel(NOTIFY_ID); return }
        val what = RoutineLogic.join(left.map { it.text })
        val line = Persona.line(context, "routine_forgot", what)
        val open = PendingIntent.getActivity(context, NOTIFY_ID,
            Intent(context, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP)
                .putExtra(MainActivity.EXTRA_TAB, MainActivity.TAB_TODAY),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
        val b = NotificationCompat.Builder(context, SanaeApp.CH_REMINDER)
            .setSmallIcon(R.drawable.ic_stat_sanae)
            .setContentTitle(Persona.name(context))
            .setContentText(line)
            .setStyle(NotificationCompat.BigTextStyle().bigText(line))
            .setPriority(NotificationCompat.PRIORITY_HIGH)
            .setCategory(NotificationCompat.CATEGORY_REMINDER)
            .setAutoCancel(true)
            .setContentIntent(open)
        // a "Did it" button per task (Android shows up to three)
        left.take(3).forEachIndexed { i, c ->
            val done = PendingIntent.getBroadcast(context, NOTIFY_ID + 1 + i,
                Intent(context, RoutineReceiver::class.java).setAction(ACTION_DONE).putExtra("uid", c.uid),
                PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
            b.addAction(0, if (left.size == 1) "Did it ✓" else "✓ ${c.text.take(18)}", done)
        }
        nm.notify(NOTIFY_ID, b.build())
    }

    /** "Did it" on the notification: tick it; show what's still left (or clear it). */
    suspend fun doneFromNotification(context: Context, uid: String) {
        tick(context, uid, true)
        val left = RoutineLogic.forgotten(LocalDb.get(context).chores("status = 'active'"), LocalDate.now())
        if (left.isEmpty()) context.getSystemService(NotificationManager::class.java).cancel(NOTIFY_ID)
        else check(context, sync = false)
    }
}

class RoutineReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        val app = context.applicationContext
        val pending = goAsync()
        CoroutineScope(Dispatchers.IO).launch {
            try {
                when (intent.action) {
                    Routine.ACTION_CHECK -> { Routine.check(app); Routine.arm(app) }
                    Routine.ACTION_DONE -> intent.getStringExtra("uid")?.let { Routine.doneFromNotification(app, it) }
                }
            } finally {
                pending.finish()
            }
        }
    }
}
