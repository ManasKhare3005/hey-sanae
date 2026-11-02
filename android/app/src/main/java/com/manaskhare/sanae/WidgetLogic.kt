package com.manaskhare.sanae

import java.time.Instant
import java.time.LocalDateTime
import java.time.ZoneId
import java.time.format.DateTimeFormatter

/** The home-screen widget's words and order (pure, JVM-tested). */
object WidgetLogic {
    private val CLOCK = DateTimeFormatter.ofPattern("h:mm a")
    private val DAY = DateTimeFormatter.ofPattern("EEE")

    fun greeting(hour: Int): String = when (hour) {
        in 5..11 -> "Good morning"
        in 12..16 -> "Good afternoon"
        in 17..21 -> "Good evening"
        else -> "Up late"
    }

    /** "3:30 PM" today, "Tmrw 9:00 AM", "Thu 2:00 PM"; all-day ones just say so. */
    fun timeLabel(item: GlanceItem, now: LocalDateTime, zone: ZoneId = ZoneId.systemDefault()): String {
        val at = Instant.ofEpochMilli(item.atMs).atZone(zone).toLocalDateTime()
        val day = when (at.toLocalDate()) {
            now.toLocalDate() -> ""
            now.toLocalDate().plusDays(1) -> "Tmrw "
            else -> DAY.format(at) + " "
        }
        if (item.allDay) return if (day.isEmpty()) "All day" else day.trim()
        val prefix = if (item.kind == "due") "Due " else ""
        return prefix + day + CLOCK.format(at).replace(":00", "")
    }

    /** Starting within the hour (or already due): drawn brighter. */
    fun soon(item: GlanceItem, nowMs: Long) = !item.allDay && item.atMs - nowMs in -15 * 60_000L..60 * 60_000L

    /** Open first (oldest first, as added), then ticked ones; how many are left; done share 0-1. */
    fun todoOrder(todos: List<LocalTodo>): List<LocalTodo> =
        todos.filter { it.status == "open" } + todos.filter { it.status == "done" }

    fun todoHeader(todos: List<LocalTodo>): String {
        val open = todos.count { it.status == "open" }
        val done = todos.count { it.status == "done" }
        return when {
            open == 0 && done == 0 -> "To do"
            open == 0 -> "To do · all done"
            else -> "To do · $open left"
        }
    }

    fun progress(todos: List<LocalTodo>): Float {
        val shown = todos.filter { it.status == "open" || it.status == "done" }
        return if (shown.isEmpty()) 0f else shown.count { it.status == "done" }.toFloat() / shown.size
    }

    /** "Routine · 2 left today" / "Routine · all done today". */
    fun routineHeader(due: List<LocalChore>, day: java.time.LocalDate): String {
        val left = due.count { !RoutineLogic.done(it, day) }
        return if (left == 0) "Routine · all done today" else "Routine · $left left today"
    }

    /** "synced 3 min ago" under the list, so a stale widget is obvious. */
    fun syncedLabel(lastMs: Long, nowMs: Long): String {
        if (lastMs <= 0) return "not synced yet · tap to sync"
        val min = (nowMs - lastMs) / 60_000
        val ago = when {
            min < 1 -> "just now"
            min < 60 -> "$min min ago"
            min < 24 * 60 -> "${min / 60} h ago"
            else -> "${min / (24 * 60)} d ago"
        }
        return "synced $ago · tap to sync"
    }
}
