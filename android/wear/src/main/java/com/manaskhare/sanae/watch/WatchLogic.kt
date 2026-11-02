package com.manaskhare.sanae.watch

import org.json.JSONObject
import java.time.Instant
import java.time.ZoneId
import java.time.format.TextStyle
import java.util.Locale

/** Message paths, the same strings as the phone app's WatchPaths. */
object Paths {
    const val CAPABILITY = "sanae_phone"
    const val VOICE = "/sanae/voice"
    const val REPLY = "/sanae/reply"
    const val SPEECH = "/sanae/speech"
    const val GLANCE = "/sanae/glance"
    const val APPROVAL = "/sanae/approval"
    const val APPROVE = "/sanae/approve"
    const val HR_REQUEST = "/sanae/hr/request"
    const val HR = "/sanae/hr"
    const val HEALTH = "/sanae/health"
}

/**
 * End of speech from 100 ms loudness readings, like the phone's recorder: the first 300 ms is the
 * room's noise, then stop after ~1.2 s of quiet once something was said (or at the time limit).
 */
class Endpoint(private val quietFrames: Int = 12, private val maxFrames: Int = 150) {
    private var noise = 0.0
    private var frames = 0
    private var quiet = 0
    var spoke = false
        private set

    /** Feed one 100 ms frame's RMS (16-bit scale); true = stop recording now. */
    fun feed(rms: Double): Boolean {
        frames++
        if (frames <= 3) { noise = maxOf(noise, rms); return false }
        val loud = rms > maxOf(noise * 2.5, 350.0)
        if (loud) { spoke = true; quiet = 0 } else if (spoke) quiet++
        return (spoke && quiet >= quietFrames) || frames >= maxFrames
    }
}

data class Reply(val heard: String, val reply: String, val emotion: String, val error: String) {
    companion object {
        fun parse(json: String): Reply = runCatching {
            val o = JSONObject(json)
            Reply(o.optString("heard"), o.optString("reply"), o.optString("emotion"), o.optString("error"))
        }.getOrDefault(Reply("", "", "", "Got a reply I couldn't read."))
    }
}

data class Approval(val id: Int, val prompt: String)

data class Item(val title: String, val atMs: Long, val kind: String, val allDay: Boolean)

data class Glance(val items: List<Item>, val approvals: List<Approval>, val online: Boolean, val made: Long) {
    companion object {
        fun parse(json: String): Glance? = runCatching {
            val o = JSONObject(json)
            val items = o.optJSONArray("items")
            val asks = o.optJSONArray("approvals")
            Glance(
                (0 until (items?.length() ?: 0)).map { i ->
                    val it = items!!.getJSONObject(i)
                    Item(it.optString("title"), it.optLong("at"), it.optString("kind"), it.optBoolean("all_day"))
                },
                (0 until (asks?.length() ?: 0)).map { i ->
                    val a = asks!!.getJSONObject(i)
                    Approval(a.optInt("id"), a.optString("prompt"))
                },
                o.optBoolean("online"), o.optLong("made"),
            )
        }.getOrNull()
    }
}

/** Her face on the watch: a ring colour and a little motion for each of the avatar's emotions. */
data class Face(val ring: Long, val bounce: Boolean = false, val tilt: Float = 0f, val dim: Boolean = false)

object Faces {
    const val CYAN = 0xFF22D3EE
    fun of(emotion: String): Face = when (emotion.lowercase()) {
        "happy" -> Face(0xFFF472B6, bounce = true)
        "laugh" -> Face(0xFF4ADE80, bounce = true)
        "shy" -> Face(0xFFFDA4AF, tilt = -8f)
        "surprised" -> Face(0xFFFACC15, bounce = true)
        "thinking" -> Face(0xFFF59E0B, tilt = 8f)
        "sad" -> Face(0xFF60A5FA, dim = true)
        "sleepy" -> Face(0xFFA78BFA, dim = true, tilt = 6f)
        else -> Face(CYAN)
    }
}

/** "2:30 PM", "Tmrw 9 AM", "Sat 11:59 PM", "All day"; due items say "Due ...". */
fun whenLabel(item: Item, nowMs: Long, zone: ZoneId = ZoneId.systemDefault()): String {
    if (item.allDay) return "All day"
    if (item.kind == "todo") return "To do"
    val at = Instant.ofEpochMilli(item.atMs).atZone(zone)
    val today = Instant.ofEpochMilli(nowMs).atZone(zone).toLocalDate()
    val h = at.hour % 12
    val time = (if (h == 0) "12" else "$h") + (if (at.minute == 0) "" else ":%02d".format(at.minute)) +
        if (at.hour < 12) " AM" else " PM"
    val day = when (at.toLocalDate()) {
        today -> ""
        today.plusDays(1) -> "Tmrw "
        else -> at.dayOfWeek.getDisplayName(TextStyle.SHORT, Locale.US) + " "
    }
    return (if (item.kind == "due") "Due " else "") + day + time
}

/** She asked something back: listen again (unless she's waiting for a yes/no tap). */
fun asksBack(reply: Reply, approvalsOpen: Boolean): Boolean =
    !approvalsOpen && reply.error.isBlank() && reply.reply.trim().endsWith("?")
