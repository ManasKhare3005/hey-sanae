package com.manaskhare.sanae

import java.time.Instant
import java.time.LocalDate
import java.time.LocalDateTime
import java.time.OffsetDateTime
import java.time.ZoneId

/** What a timeline row is: each kind gets its own colour and icon on the Today tab. */
enum class EntryKind { CLASS, EVENT, REMINDER, DUE, TODO, ROUTINE }

/** A Canvas class or due date from the laptop's /api/today. */
data class CanvasItem(val title: String, val course: String, val at: LocalDateTime?, val link: String = "")

data class Entry(
    val kind: EntryKind, val id: String, val title: String, val sub: String = "",
    val at: LocalDateTime? = null, val hasTime: Boolean = true, val done: Boolean = false,
    val link: String = "", val dirty: Boolean = false, val end: LocalDateTime? = null,
)

/**
 * The Today tab in one list: today's timed things (classes, events, reminders, due dates) in
 * order, all-day things, the checklist (routine due today + todos) and the next few days.
 */
data class DayPlan(
    val today: List<Entry> = emptyList(),
    val allDay: List<Entry> = emptyList(),
    val checklist: List<Entry> = emptyList(),
    val later: List<Pair<LocalDate, List<Entry>>> = emptyList(),
) {
    val left get() = checklist.count { !it.done }
    val doneCount get() = checklist.count { it.done }
    /** Where the "now" line goes in `today`: before the first thing that hasn't ended yet. */
    fun nowIndex(now: LocalDateTime) = today.indexOfFirst { (it.end ?: it.at ?: now) >= now }.let { if (it < 0) today.size else it }
}

object Timeline {
    private fun local(ms: Long) = Instant.ofEpochMilli(ms).atZone(ZoneId.systemDefault()).toLocalDateTime()

    /** "2026-10-22T23:59:00-07:00" or without the offset -> local time; junk -> null. */
    fun parseIso(s: String): LocalDateTime? = if (s.isBlank()) null else
        runCatching { OffsetDateTime.parse(s).atZoneSameInstant(ZoneId.systemDefault()).toLocalDateTime() }.getOrNull()
            ?: runCatching { LocalDateTime.parse(s) }.getOrNull()
            ?: runCatching { LocalDate.parse(s).atTime(23, 59) }.getOrNull()

    fun build(
        now: LocalDateTime,
        classes: List<CanvasItem> = emptyList(), dueToday: List<CanvasItem> = emptyList(), dueSoon: List<CanvasItem> = emptyList(),
        events: List<LocalEvent> = emptyList(), reminders: List<LocalReminder> = emptyList(),
        todos: List<LocalTodo> = emptyList(), chores: List<LocalChore> = emptyList(), days: Int = 7,
    ): DayPlan {
        val today = now.toLocalDate()
        val all = mutableListOf<Entry>()
        classes.forEach { all += Entry(EntryKind.CLASS, "class:${it.title}:${it.course}:${it.at}", it.title, it.course, it.at ?: today.atStartOfDay(), it.at != null, link = it.link) }
        (dueToday + dueSoon).distinctBy { it.title to it.at }.forEach {
            all += Entry(EntryKind.DUE, "due:${it.title}:${it.course}:${it.at}", it.title, it.course, it.at ?: today.atTime(23, 59), it.at != null, link = it.link)
        }
        events.filter { it.status == "active" }.forEach { e ->
            val start = local(e.startMs)
            all += Entry(EntryKind.EVENT, e.uid, e.title, e.location, start, !e.allDay, dirty = e.dirty, end = local(e.endMs))
        }
        reminders.filter { it.status == "pending" }.forEach { r ->
            val at = local(r.dueMs)
            val missed = at.toLocalDate() < today
            val repeat = if (r.repeat.isBlank()) "" else Repeat.label(r.repeat, at)
            all += Entry(EntryKind.REMINDER, r.uid, r.text, listOf(if (missed) "missed" else "", repeat).filter { it.isNotBlank() }.joinToString(" · "),
                         if (missed) today.atStartOfDay() else at, true, dirty = r.dirty)
        }
        val last = today.plusDays(days.toLong())
        val order = compareBy<Entry>({ if (it.hasTime) 1 else 0 }, { it.at }, { it.kind.ordinal })
        val todayAll = all.filter { e ->
            val d = e.at!!.toLocalDate()
            if (e.kind == EntryKind.EVENT && !e.hasTime) d <= today && (e.end?.toLocalDate() ?: d) > today else d == today
        }
        val later = all.filter { it.at!!.toLocalDate().let { d -> d > today && d <= last } }
            .groupBy { it.at!!.toLocalDate() }.toSortedMap().map { (d, l) -> d to l.sortedWith(order) }
        val checklist = chores.filter { it.status == "active" && RoutineLogic.dueOn(it.freq, today) }.map {
            Entry(EntryKind.ROUTINE, it.uid, it.text, RoutineLogic.label(it.freq), done = RoutineLogic.done(it, today), dirty = it.dirty)
        } + todos.filter { it.status != "deleted" }.map { Entry(EntryKind.TODO, it.uid, it.text, done = it.done, dirty = it.dirty) }
        return DayPlan(
            today = todayAll.filter { it.hasTime }.sortedWith(order),
            allDay = todayAll.filter { !it.hasTime }.sortedWith(order),
            checklist = checklist.sortedBy { it.done },
            later = later,
        )
    }
}

/**
 * The one "+" box: "call mom tomorrow 5pm" -> "call mom" + tomorrow 5 PM; "remind me to stretch
 * in 20 min" -> a reminder. The when-part is the longest run of words at the end (or start)
 * that WhenParser fully understands.
 */
object QuickAdd {
    data class Guess(val title: String, val whenAt: When?, val wantsReminder: Boolean)

    private val REMIND = Regex("^(?:please\\s+)?(?:remind me(?: to)?|reminder(?: to)?)\\s+", RegexOption.IGNORE_CASE)
    private val SPACES = Regex("\\s+")

    fun parse(text: String, now: LocalDateTime = LocalDateTime.now()): Guess {
        var t = text.trim()
        val remind = REMIND.containsMatchIn(t)
        t = t.replace(REMIND, "").trim()
        val words = t.split(SPACES).filter { it.isNotEmpty() }
        for (n in minOf(7, words.size - 1) downTo 1) {
            WhenParser.parse(words.takeLast(n).joinToString(" "), now)?.let { w ->
                return Guess(words.dropLast(n).joinToString(" ").trimEnd(',', ' '), w, remind)
            }
            WhenParser.parse(words.take(n).joinToString(" "), now)?.let { w ->
                return Guess(words.drop(n).joinToString(" ").trimStart(',', ' '), w, remind)
            }
        }
        return Guess(t, null, remind)
    }
}
