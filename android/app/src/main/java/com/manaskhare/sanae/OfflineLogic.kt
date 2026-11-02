package com.manaskhare.sanae

import java.time.DayOfWeek
import java.time.LocalDate
import java.time.LocalDateTime
import java.time.LocalTime
import java.time.Month
import java.time.format.TextStyle
import java.util.Locale

/**
 * Plain logic for working without the laptop (no Android classes, so it's unit-tested on the JVM):
 * a small time parser for reminders / events typed on the phone, and the sync merge rules.
 */

/** When something is: the moment, and whether a time of day was given (no time = all-day event, 9 AM reminder). */
data class When(val at: LocalDateTime, val hasTime: Boolean)

/**
 * "in 20 min", "in 2 hours", "tomorrow 5pm", "tonight", "friday 5:30pm", "next monday",
 * "oct 12 3pm", "12/10", "2026-10-12 14:00", "at 9", "noon"... Returns null for anything it
 * doesn't fully understand (better to ask than to guess). A day without a time = 9 AM.
 * Same habits as the laptop's parser: "next friday" = the coming Friday; a bare "at 5" = 5 PM.
 */
object WhenParser {
    const val DEFAULT_HOUR = 9
    private val UNITS = mapOf("min" to 1L, "mins" to 1L, "minute" to 1L, "minutes" to 1L, "m" to 1L,
                              "hour" to 60L, "hours" to 60L, "hr" to 60L, "hrs" to 60L, "h" to 60L,
                              "day" to 1440L, "days" to 1440L, "week" to 10080L, "weeks" to 10080L)
    private val PARTS = mapOf("morning" to 9, "afternoon" to 14, "evening" to 18, "night" to 21, "tonight" to 20)
    private val MONTHS = Month.values().joinToString("|") { m -> m.getDisplayName(TextStyle.FULL, Locale.US).lowercase() + "|" +
                                                               m.getDisplayName(TextStyle.SHORT, Locale.US).lowercase().removeSuffix(".") }
    // compiled once: the add box parses on every keystroke (up to 14 tries each), and compiling
    // these each time made typing lag
    private val PUNCT = Regex("[,.]")
    private val ISO_T = Regex("(\\d{4}-\\d{1,2}-\\d{1,2})t(\\d)")
    private val SPACES = Regex("\\s+")
    private val IN = Regex(" in (half an hour|an? |\\d+ ?)(min|mins|minute|minutes|m|hour|hours|hr|hrs|h|day|days|week|weeks)? ")
    private val AMPM = Regex(" (?:at )?(\\d{1,2})(?::(\\d{2}))? ?(am|pm|a m|p m) ")
    private val CLOCK24 = Regex(" (?:at )?([01]?\\d|2[0-3]):([0-5]\\d) ")
    private val NOON = Regex(" (?:at )?(noon|midday|midnight) ")
    private val AT_HOUR = Regex(" at (\\d{1,2}) ")
    private val PART = Regex(" (?:this |in the |at )?(morning|afternoon|evening|night|tonight) ")
    private val TODAY = Regex(" (today|tonight) ")
    private val TOMORROW = Regex(" (tomorrow|tmrw|tmr) ")
    private val ISO_DAY = Regex(" (\\d{4})-(\\d{1,2})-(\\d{1,2})(?:t)? ")
    private val SLASH_DAY = Regex(" (?:on )?(\\d{1,2})/(\\d{1,2})(?:/(\\d{2,4}))? ")
    private val MONTH_DAY = Regex(" (?:on )?($MONTHS)\\.? (\\d{1,2})(?:st|nd|rd|th)? ")
    private val DAY_MONTH = Regex(" (?:on )?(\\d{1,2})(?:st|nd|rd|th)? (?:of )?($MONTHS) ")
    private val WEEKDAY = Regex(" (?:on |this |next )?(mon|tue|tues|wed|thu|thur|thurs|fri|sat|sun)(?:day|nesday|sday|urday|rsday)? ")
    private val FILLER = Regex("\\b(on|at|by|the|for)\\b")

    fun parse(input: String, now: LocalDateTime = LocalDateTime.now()): When? {
        var s = " " + input.lowercase(Locale.US).replace(PUNCT, " ")
            .replace(ISO_T, "$1 $2")        // 2026-10-12T14:00
            .replace("sept ", "sep ").replace(SPACES, " ").trim() + " "
        if (s.isBlank()) return null

        // "in 20 minutes", "in an hour", "in half an hour", "in 2 days"
        IN.find(s)?.let { m ->
            val n = m.groupValues[1].trim()
            val minutes = if (n == "half an hour") 30L else {
                val count = if (n == "a" || n == "an") 1L else n.toLongOrNull() ?: return null
                count * (UNITS[m.groupValues[2]] ?: return null)
            }
            if (s.replace(m.value, " ").isNotBlank()) return null
            return When(now.plusMinutes(minutes).withSecond(0).withNano(0), minutes < 1440)
        }

        var time: LocalTime? = null
        fun take(re: Regex, f: (MatchResult) -> Unit) { re.find(s)?.let { f(it); s = s.replace(it.value, " ") } }
        // times: 5pm, 5:30 pm, 17:30, noon, midnight, at 5
        take(AMPM) {
            var h = it.groupValues[1].toInt() % 12
            if (it.groupValues[3].startsWith("p")) h += 12
            val min = it.groupValues[2].ifBlank { "0" }.toInt()
            if (it.groupValues[1].toInt() in 1..12 && min < 60) time = LocalTime.of(h, min)
        }
        if (time == null) take(CLOCK24) {
            time = LocalTime.of(it.groupValues[1].toInt(), it.groupValues[2].toInt())
        }
        if (time == null) take(NOON) {
            time = if (it.groupValues[1] == "midnight") LocalTime.MIDNIGHT else LocalTime.NOON
        }
        if (time == null) take(AT_HOUR) {               // "at 5": 1-7 = afternoon
            val h = it.groupValues[1].toInt()
            if (h in 1..12) time = LocalTime.of(if (h == 12) 12 else if (h < 8) h + 12 else h, 0)
        }
        var partHour: Int? = null
        take(PART) {
            partHour = PARTS[it.groupValues[1]]
            if (it.groupValues[1] == "tonight") s = " today $s"
        }
        if (time == null && partHour != null) time = LocalTime.of(partHour!!, 0)

        // days: today, tomorrow, weekdays, "oct 12", "12 october", "10/12", "2026-10-12"
        val today = now.toLocalDate()
        var day: LocalDate? = null
        take(TODAY) { day = today }
        if (day == null) take(TOMORROW) { day = today.plusDays(1) }
        if (day == null) take(ISO_DAY) {
            day = runCatching { LocalDate.of(it.groupValues[1].toInt(), it.groupValues[2].toInt(), it.groupValues[3].toInt()) }.getOrNull()
        }
        if (day == null) take(SLASH_DAY) {      // US: month/day
            day = date(today, it.groupValues[1].toInt(), it.groupValues[2].toInt(), it.groupValues[3])
        }
        if (day == null) {
            take(MONTH_DAY) {
                day = date(today, month(it.groupValues[1]), it.groupValues[2].toInt(), "")
            }
            if (day == null) take(DAY_MONTH) {
                day = date(today, month(it.groupValues[2]), it.groupValues[1].toInt(), "")
            }
        }
        if (day == null) take(WEEKDAY) {
            val dow = DayOfWeek.values().first { d -> d.name.lowercase().startsWith(it.groupValues[1].take(3)) }
            var ahead = (dow.value - today.dayOfWeek.value + 7) % 7
            if (ahead == 0 && (time == null || !time!!.isAfter(now.toLocalTime()))) ahead = 7
            day = today.plusDays(ahead.toLong())
        }

        if (s.replace(FILLER, " ").isNotBlank()) return null   // words we don't understand
        if (day == null && time == null) return null
        if (day == null) {                                // a time alone: today, or tomorrow if it has passed
            val t = LocalDateTime.of(today, time)
            return When(if (t.isAfter(now)) t else t.plusDays(1), true)
        }
        return When(LocalDateTime.of(day, time ?: LocalTime.of(DEFAULT_HOUR, 0)), time != null)
    }

    private fun month(name: String) = Month.values().first { it.name.lowercase().startsWith(name.take(3)) }.value

    private fun date(today: LocalDate, month: Int, dayOfMonth: Int, year: String): LocalDate? {
        val y = when {
            year.isBlank() -> today.year
            year.length == 2 -> 2000 + year.toInt()
            else -> year.toInt()
        }
        val d = runCatching { LocalDate.of(y, month, dayOfMonth) }.getOrNull() ?: return null
        return if (year.isBlank() && d.isBefore(today)) d.plusYears(1) else d
    }
}

/** Something both sides keep: matched by uid; `status` finished (done / cancelled) or not. */
interface Syncable {
    val uid: String
    val updatedMs: Long
    val finished: Boolean
    val dirty: Boolean       // changed here since the last sync
    val synced: Boolean      // the laptop has seen it
}

/** What to do with the laptop's answer to a sync. */
data class MergePlan<T>(val write: List<T>, val delete: List<String>)

object SyncRules {
    /** The laptop's rule (sync.py): finished beats open, otherwise the later edit; a tie keeps ours. */
    fun wins(incomingFinished: Boolean, incomingUpdated: Long, currentFinished: Boolean, currentUpdated: Long): Boolean =
        if (incomingFinished != currentFinished) incomingFinished else incomingUpdated > currentUpdated

    /**
     * The laptop answered with its list after merging what we `sent` (uid -> updatedMs as sent).
     * Its version replaces ours, except rows changed here while the request was out (kept, still
     * dirty). Rows it no longer lists are dropped (deleted on the laptop, or old and finished),
     * except new ones made during the request.
     */
    fun <T : Syncable> plan(local: List<T>, server: List<T>, sent: Map<String, Long>): MergePlan<T> {
        val mine = local.associateBy { it.uid }
        val changedSince = { l: T -> l.dirty && sent[l.uid] != l.updatedMs }
        val write = server.filter { s -> val l = mine[s.uid]; l == null || !changedSince(l) }
        val listed = server.map { it.uid }.toSet()
        val delete = local.filter { it.uid !in listed && !(it.dirty && it.uid !in sent) && !changedSince(it) }.map { it.uid }
        return MergePlan(write, delete)
    }
}

/**
 * Repeating reminders, same rules as the laptop (reminders.py next_due): "daily", "weekdays", "weekly",
 * "monthly:<day>" (a shorter month uses its last day), "yearly:<month>-<day>". When one goes off it
 * moves on to its next occurrence instead of being marked done.
 */
object Repeat {
    /** The first occurrence later than `after` (skips any that were missed); null for an unknown rule. */
    fun next(due: LocalDateTime, rule: String, after: LocalDateTime): LocalDateTime? {
        val kind = rule.substringBefore(":")
        val anchor = rule.substringAfter(":", "")
        var t = due
        repeat(5000) {
            if (t.isAfter(after)) return t
            t = when (kind) {
                "daily" -> t.plusDays(1)
                "weekdays" -> t.plusDays(when (t.dayOfWeek) { DayOfWeek.FRIDAY -> 3; DayOfWeek.SATURDAY -> 2; else -> 1 })
                "weekly" -> t.plusWeeks(1)
                "monthly" -> {
                    val m = t.toLocalDate().withDayOfMonth(1).plusMonths(1)
                    val day = anchor.toIntOrNull() ?: t.dayOfMonth
                    LocalDateTime.of(m.withDayOfMonth(minOf(day, m.lengthOfMonth())), t.toLocalTime())
                }
                "yearly" -> {
                    val (mo, d) = anchor.split("-").mapNotNull { it.toIntOrNull() }.takeIf { it.size == 2 }
                        ?: listOf(t.monthValue, t.dayOfMonth)
                    val first = LocalDate.of(t.year + 1, mo, 1)
                    LocalDateTime.of(first.withDayOfMonth(minOf(d, first.lengthOfMonth())), t.toLocalTime())
                }
                else -> return null
            }
        }
        return null
    }

    /** "every day", "every Monday", "5th of every month", "every year on Mar 3" (for labels). */
    fun label(rule: String, due: LocalDateTime): String {
        val anchor = rule.substringAfter(":", "")
        fun nth(n: Int) = "$n" + if (n % 100 in 10..20) "th" else when (n % 10) { 1 -> "st"; 2 -> "nd"; 3 -> "rd"; else -> "th" }
        return when (rule.substringBefore(":")) {
            "daily" -> "every day"
            "weekdays" -> "every weekday"
            "weekly" -> "every " + due.dayOfWeek.getDisplayName(TextStyle.FULL, Locale.US)
            "monthly" -> nth(anchor.toIntOrNull() ?: due.dayOfMonth) + " of every month"
            "yearly" -> {
                val p = anchor.split("-").mapNotNull { it.toIntOrNull() }
                val (mo, d) = if (p.size == 2) p else listOf(due.monthValue, due.dayOfMonth)
                "every year on " + Month.of(mo).getDisplayName(TextStyle.SHORT, Locale.US) + " $d"
            }
            else -> ""
        }
    }
}

/** Todo text as typed or said: "milk, eggs and bread" -> three items; "call mom and dad" stays one
 *  (no comma). Same rule as the laptop (todos.split_items). */
object TodoText {
    fun split(text: String): List<String> {
        val t = text.replace(Regex("\\s+"), " ").trim().trim('.', ' ')
        if (t.isEmpty()) return emptyList()
        if (!t.contains(',') && !t.contains(';')) return listOf(t)
        return t.split(Regex("\\s*[,;]\\s*(?:and\\s+)?|\\s+and\\s+(?=[^,;]*$)"))
            .map { it.trim().trim('.', ' ') }.filter { it.isNotEmpty() }
    }
}
