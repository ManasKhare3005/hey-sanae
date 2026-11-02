package com.manaskhare.sanae

import android.content.Context
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.launch
import java.time.LocalDateTime
import java.time.ZoneId

/**
 * Reminders, events and todos made or removed on the phone: saved here right away (alarm armed, Sanae
 * calendar updated), then sent to the laptop by Sync whenever it can be reached.
 */
object Offline {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)

    fun ms(t: LocalDateTime): Long = t.atZone(ZoneId.systemDefault()).toInstant().toEpochMilli()

    private fun after(context: Context, calendar: Boolean) {
        val app = context.applicationContext
        scope.launch {
            runCatching { Alarms.armAll(app) }
            if (calendar) runCatching { SanaeCalendar.mirror(app) }
        }
        Sync.trigger(app)
        TodayWidget.refresh(app)
    }

    fun addReminder(context: Context, text: String, at: LocalDateTime): LocalReminder {
        val r = LocalReminder(LocalDb.newUid(), text.trim(), ms(at))
        LocalDb.get(context).put(r)
        after(context, calendar = false)
        return r
    }

    fun cancelReminder(context: Context, uid: String) {
        val db = LocalDb.get(context)
        val r = db.reminder(uid) ?: return
        db.put(r.copy(status = "cancelled", updatedMs = System.currentTimeMillis(), dirty = true))
        Alarms.cancel(context, uid)
        after(context, calendar = false)
    }

    /** An event; no time of day = all day. */
    fun addEvent(context: Context, title: String, w: When, minutes: Int = 60, location: String = ""): LocalEvent {
        val start = if (w.hasTime) w.at else w.at.toLocalDate().atStartOfDay()
        val end = if (w.hasTime) start.plusMinutes(minutes.toLong()) else start.plusDays(1)
        val e = LocalEvent(LocalDb.newUid(), title.trim(), ms(start), ms(end), allDay = !w.hasTime, location = location.trim())
        LocalDb.get(context).put(e)
        after(context, calendar = true)
        return e
    }

    fun cancelEvent(context: Context, uid: String) {
        val db = LocalDb.get(context)
        val e = db.event(uid) ?: return
        db.put(e.copy(status = "cancelled", updatedMs = System.currentTimeMillis(), dirty = true))
        after(context, calendar = true)
    }

    /** "milk, eggs and bread" -> three todos (TodoText.split). */
    fun addTodos(context: Context, text: String): List<LocalTodo> {
        val db = LocalDb.get(context)
        val created = LocalDateTime.now().withNano(0).toString()
        val added = TodoText.split(text).map { LocalTodo(LocalDb.newUid(), it, created = created) }
        added.forEach { db.put(it) }
        if (added.isNotEmpty()) after(context, calendar = false)
        return added
    }

    fun tickTodo(context: Context, uid: String, done: Boolean) {
        val db = LocalDb.get(context)
        val t = db.todo(uid) ?: return
        db.put(t.copy(status = if (done) "done" else "open", updatedMs = System.currentTimeMillis(), dirty = true))
        after(context, calendar = false)
    }

    fun deleteTodo(context: Context, uid: String) {
        val db = LocalDb.get(context)
        val t = db.todo(uid) ?: return
        db.put(t.copy(status = "deleted", updatedMs = System.currentTimeMillis(), dirty = true))
        after(context, calendar = false)
    }

    fun clearDoneTodos(context: Context) {
        val db = LocalDb.get(context)
        val now = System.currentTimeMillis()
        db.todos("status = 'done'").forEach { db.put(it.copy(status = "deleted", updatedMs = now, dirty = true)) }
        after(context, calendar = false)
    }
}
