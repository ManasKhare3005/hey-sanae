package com.manaskhare.sanae

import org.json.JSONArray
import org.json.JSONObject
import java.time.Instant
import java.time.LocalDateTime
import java.time.OffsetDateTime
import java.time.ZoneId

/** Message paths between the phone and the watch (Wear OS Data Layer). Same strings in the watch app. */
object WatchPaths {
    const val VOICE = "/sanae/voice"          // channel watch -> phone: a WAV; "/sanae/voice/speak" = also send her voice back
    const val REPLY = "/sanae/reply"          // phone -> watch: {heard, reply, emotion, error}
    const val SPEECH = "/sanae/speech"        // channel phone -> watch: her reply as WAV
    const val GLANCE = "/sanae/glance"        // watch -> phone: asks; phone -> watch: {items, approvals, online, made}
    const val APPROVAL = "/sanae/approval"    // phone -> watch: {id, prompt} (empty prompt = settled)
    const val APPROVE = "/sanae/approve"      // watch -> phone: {id, approved}
    const val HR_REQUEST = "/sanae/hr/request" // phone -> watch: measure the heart rate now
    const val HR = "/sanae/hr"                // watch -> phone: {bpm} or {error}
    const val HEALTH = "/sanae/health"        // phone -> watch: {on} (health sharing turned on / off)
}

/** One line on the watch's Today tile. kind: reminder, event, due, class, todo (no time). */
data class GlanceItem(val title: String, val atMs: Long, val kind: String, val allDay: Boolean = false) {
    fun toJson(): JSONObject = JSONObject().put("title", title).put("at", atMs).put("kind", kind).put("all_day", allDay)
}

/**
 * What's next, for the watch: the phone's own reminders and Sanae-calendar events (so it works
 * with the laptop off) plus Canvas due items and classes from the last Today page the laptop sent.
 */
object Glance {
    private const val HOUR = 3_600_000L

    fun build(today: JSONObject?, reminders: List<LocalReminder>, events: List<LocalEvent>,
              nowMs: Long, zone: ZoneId = ZoneId.systemDefault(), limit: Int = 4,
              todos: List<LocalTodo> = emptyList()): List<GlanceItem> {
        val day = Instant.ofEpochMilli(nowMs).atZone(zone).toLocalDate()
        val items = mutableListOf<GlanceItem>()
        reminders.filter { !it.finished && it.dueMs >= nowMs - 10 * 60_000 && it.dueMs <= nowMs + 24 * HOUR }
            .mapTo(items) { GlanceItem(it.text, it.dueMs, "reminder") }
        for (e in events.filter { !it.finished }) {
            if (e.allDay) {
                // all-day events are stored at UTC midnight (SanaeCalendar)
                val d = Instant.ofEpochMilli(e.startMs).atZone(ZoneId.of("UTC")).toLocalDate()
                if (d == day) items += GlanceItem(e.title, e.startMs, "event", allDay = true)
            } else if (e.endMs > nowMs && e.startMs <= nowMs + 24 * HOUR) {
                items += GlanceItem(e.title, e.startMs, "event")
            }
        }
        if (today != null) {
            fun take(key: String, kind: String, ahead: Long) {
                val list = today.optJSONArray(key) ?: return
                for (i in 0 until list.length()) {
                    val o = list.optJSONObject(i) ?: continue
                    val at = parse(o.optString("due"), zone) ?: continue
                    val end = if (kind == "class") at + HOUR else at
                    if (end >= nowMs && at <= nowMs + ahead) items += GlanceItem(o.optString("title"), at, kind)
                }
            }
            take("due_today", "due", 24 * HOUR)
            take("due_soon", "due", 72 * HOUR)
            take("classes", "class", 24 * HOUR)
        }
        val seen = HashSet<String>()
        return items
            .sortedWith(compareBy<GlanceItem>({ !it.allDay }, { it.atMs }))
            .filter { it.title.isNotBlank() && seen.add(it.title.lowercase().trim() + "|" + it.atMs / 60_000) }
            .take(limit)
            .let { timed -> timed + todos.filter { it.status == "open" }.take(limit - timed.size).map { GlanceItem(it.text, 0, "todo") } }
    }

    /** The laptop's ISO times: "2026-10-16T14:00:00" (local) or with an offset. */
    fun parse(iso: String, zone: ZoneId = ZoneId.systemDefault()): Long? {
        if (iso.isBlank()) return null
        runCatching { return OffsetDateTime.parse(iso).toInstant().toEpochMilli() }
        return runCatching { LocalDateTime.parse(iso).atZone(zone).toInstant().toEpochMilli() }.getOrNull()
    }

    fun payload(items: List<GlanceItem>, approvals: List<PendingApproval>, online: Boolean, nowMs: Long): JSONObject =
        JSONObject()
            .put("items", JSONArray().apply { items.forEach { put(it.toJson()) } })
            .put("approvals", JSONArray().apply { approvals.forEach { put(JSONObject().put("id", it.id).put("prompt", it.prompt)) } })
            .put("online", online)
            .put("made", nowMs)
}
