package com.manaskhare.sanae

import org.json.JSONObject
import java.time.LocalDate

/**
 * The "Us" tab as tiles: one line of status per feature (from the laptop's /api/us), a new-dot
 * when she made something you haven't opened yet, and the few things worth a look today.
 */
object UsTiles {
    /** Tile order: daily things first, keepsakes after. Keys are the /api/us sections. */
    val ORDER = listOf("together", "dailyphoto", "groceries", "journal", "voicenotes", "japanese", "weekend", "cooking", "watching",
                       "playlist", "gooddays", "bucket", "scrapbook", "stories", "drawings", "asks", "promises", "weekly", "wrapped")

    val TITLES = mapOf(
        "together" to "Together", "journal" to "Notebook", "voicenotes" to "Voice notes", "japanese" to "Japanese",
        "weekend" to "Weekend", "cooking" to "Kitchen", "watching" to "Watching", "bucket" to "Bucket list",
        "scrapbook" to "Scrapbook", "stories" to "Stories", "drawings" to "Sketchbook", "asks" to "Gifts",
        "promises" to "Promises", "weekly" to "Your week", "groceries" to "Groceries", "playlist" to "Our playlist", "dailyphoto" to "Photo a day",
        "gooddays" to "Good days", "wrapped" to "Your month",
    )

    private fun JSONObject?.list(key: String): List<JSONObject> =
        this?.optJSONArray(key)?.let { a -> (0 until a.length()).mapNotNull { a.optJSONObject(it) } }.orEmpty()

    private fun JSONObject.s(key: String) = if (isNull(key)) "" else optString(key)

    private fun plural(n: Int, one: String, many: String = one + "s") = "$n " + if (n == 1) one else many

    /** One short status line for a tile. */
    fun line(key: String, o: JSONObject?, name: String, today: LocalDate = LocalDate.now()): String {
        if (o == null || o.has("error")) return "Opens after the first sync"
        return when (key) {
            "together" -> {
                val s = o.optJSONObject("session")
                val due = o.list("activities").filter { it.optBoolean("due", true) || !it.isNull("how") }
                when {
                    s != null -> "Doing ${s.s("title")} with $name"
                    due.isEmpty() -> "Pick something to do every day"
                    due.all { !it.isNull("how") } -> "All done today"
                    else -> "${due.count { !it.isNull("how") }} of ${due.size} done today"
                }
            }
            "journal" -> o.list("pages").firstOrNull().let { p ->
                when {
                    p == null -> "Write the first page"
                    p.s("author") == "her" -> "$name wrote back"
                    else -> "$name writes back in the morning"
                }
            }
            "voicenotes" -> o.list("notes").let { n ->
                when {
                    n.isEmpty() -> "$name leaves one some mornings"
                    n.first().s("day") == today.toString() -> "A new one from this morning"
                    else -> plural(n.size, "note") + " from $name"
                }
            }
            "japanese" -> {
                val due = o.list("deck").count { it.optBoolean("due") }
                val word = o.optJSONObject("her_word")
                when {
                    due > 0 -> plural(due, "card") + " to review"
                    word != null -> "Today: ${word.s("word")} (${word.s("meaning")})"
                    else -> "Words you learn together"
                }
            }
            "weekend" -> o.list("plans").let { p -> if (p.isEmpty()) "Plan ${o.s("label").ifBlank { "the weekend" }}" else plural(p.size, "plan") + " · " + o.s("label") }
            "cooking" -> o.optJSONObject("session")?.let { s ->
                "${s.s("title")} · step ${s.optInt("i") + 1} of ${s.optJSONArray("steps")?.length() ?: 0}"
            } ?: o.list("recipes").let { r ->
                if (r.isEmpty()) "Send a fridge photo to cook together"
                else plural(r.size, "recipe") + (r.maxByOrNull { it.optInt("stars") }?.takeIf { it.optInt("stars") >= 4 }
                    ?.let { " · ★ ${it.s("title")}" } ?: "")
            }
            "watching" -> o.s("now").takeIf { it.isNotBlank() }?.let { "Now: $it" }
                ?: o.optJSONObject("tonight")?.s("pick")?.takeIf { it.isNotBlank() }?.let { "Tonight: $it" }
                ?: o.list("shows").let { if (it.isEmpty()) "Shows you watch show up here" else plural(it.size, "show") + " going" }
            "bucket" -> o.list("items").let { i ->
                val done = i.count { !it.isNull("done_day") && it.s("done_day").isNotBlank() }
                if (i.isEmpty()) "Dreams for someday" else plural(i.size - done, "dream") + if (done > 0) " · $done done" else ""
            }
            "dailyphoto" -> {
                val t = o.optJSONObject("today")
                val streak = o.optInt("streak")
                val fire = if (streak > 0) " · 🔥 $streak" else ""
                when (t?.s("status")) {
                    null -> "A small challenge every day"
                    "done" -> "Done today$fire"
                    "open" -> t.s("challenge").replaceFirstChar { it.uppercase() } + fire
                    else -> "Skipped today$fire"
                }
            }
            "playlist" -> o.list("songs").let { s ->
                val week = o.optJSONObject("week_song")
                when {
                    s.isEmpty() -> "Songs on repeat end up here"
                    week != null -> "Song of the week: ${week.s("title")}"
                    else -> plural(s.size, "song") + " · ${s.first().s("title")}"
                }
            }
            "gooddays" -> o.list("patterns").firstOrNull()?.let { p -> p.s("label") + if (p.optBoolean("better")) " helps" else " is rough on you" }
                ?: if (o.optInt("days") < o.optInt("need", 8)) "${o.optInt("days")} of ${o.optInt("need", 8)} days so far" else "No clear pattern yet"
            "groceries" -> o.list("items").let { i ->
                val left = i.count { !it.optBoolean("done") }
                when {
                    i.isEmpty() -> "What you need from the store"
                    left == 0 -> "Everything's in the cart"
                    else -> plural(left, "thing") + " to get" + if (left < i.size) " · ${i.size - left} in the cart" else ""
                }
            }
            "scrapbook" -> o.list("months").sumOf { it.list("photos").size }.let { if (it == 0) "Photos you keep with her" else plural(it, "photo") + " kept" }
            "stories" -> o.list("chapters").firstOrNull()?.let { "Ch. ${it.optInt("n")}: ${it.s("title")}" } ?: "A bedtime story, one chapter at a time"
            "drawings" -> o.s("learning").takeIf { it.isNotBlank() }?.let { "Learning: $it" }
                ?: o.list("drawings").let { if (it.isEmpty()) "Her sketches" else plural(it.size, "sketch", "sketches") }
            "asks" -> o.list("gifts").let { if (it.isEmpty()) "Little things you give her" else plural(it.size, "gift") }
            "promises" -> o.list("open").let { if (it.isEmpty()) "Nothing open" else plural(it.size, "open promise") }
            "weekly" -> o.list("weeks").firstOrNull()?.let { "The week of ${it.s("range").ifBlank { it.s("week") }}" } ?: "Every Sunday evening"
            "wrapped" -> o.list("months").firstOrNull()?.let { it.s("label").replaceFirstChar { c -> c.uppercase() } + ", wrapped" }
                ?: "On the 1st of every month"
            else -> ""
        }
    }

    /** What changes when she makes something new ("" = this tile never gets a dot). */
    fun signature(key: String, o: JSONObject?): String {
        if (o == null) return ""
        return when (key) {
            "journal" -> o.list("pages").filter { it.s("author") == "her" || it.s("kind") == "letter" }.maxOfOrNull { it.optInt("id") }?.toString()
            "voicenotes" -> o.list("notes").maxOfOrNull { it.optInt("id") }?.toString()
            "stories" -> o.list("chapters").maxOfOrNull { it.optInt("id") }?.toString()
            "drawings" -> o.list("drawings").size.takeIf { it > 0 }?.toString()
            "scrapbook" -> o.list("months").flatMap { it.list("photos") }.maxOfOrNull { it.optInt("id") }?.toString()
            "asks" -> o.list("gifts").size.takeIf { it > 0 }?.toString()
            "playlist" -> o.list("songs").maxOfOrNull { it.optInt("id") }?.let { "$it" + (o.optJSONObject("week_song")?.let { w -> " " + w.s("week") } ?: "") }
            "weekly" -> o.list("weeks").firstOrNull()?.s("week")
            "wrapped" -> o.list("months").firstOrNull()?.s("month")
            "japanese" -> o.optJSONObject("her_word")?.s("word")
            "gooddays" -> o.list("patterns").joinToString(",") { it.s("key") + if (it.optBoolean("better")) "+" else "-" }
            else -> null
        }.orEmpty()
    }

    /** Tiles with something new. `seen` = the signatures when each was last opened; a tile never
     *  seen before isn't new (the first sync shouldn't light everything up). */
    fun fresh(us: JSONObject?, seen: Map<String, String>): Set<String> =
        ORDER.filter { k -> signature(k, us?.optJSONObject(k)).let { it.isNotBlank() && k in seen && seen[k] != it } }.toSet()

    /** The first sync: everything there now counts as seen. */
    fun firstSeen(us: JSONObject?, seen: Map<String, String>): Map<String, String> =
        seen + ORDER.filter { it !in seen }.mapNotNull { k -> signature(k, us?.optJSONObject(k)).takeIf { it.isNotBlank() }?.let { k to it } }

    data class Highlight(val key: String, val text: String)

    /** "Today with her": what's worth a tap right now, most pressing first (at most 4). */
    fun today(us: JSONObject?, fresh: Set<String>, name: String, today: LocalDate = LocalDate.now()): List<Highlight> {
        if (us == null) return emptyList()
        val out = mutableListOf<Highlight>()
        us.optJSONObject("cooking")?.optJSONObject("session")?.let { out += Highlight("cooking", "Cooking ${it.s("title")}") }
        us.optJSONObject("together")?.let { t ->
            val s = t.optJSONObject("session")
            if (s != null) out += Highlight("together", "${s.s("title")} with $name")
            else {
                val left = t.list("activities").filter { it.optBoolean("due", true) && it.isNull("how") }
                if (left.isNotEmpty()) out += Highlight("together", if (left.size == 1) left[0].s("title") + " together" else "${left.size} things to do together")
            }
        }
        us.optJSONObject("dailyphoto")?.optJSONObject("today")?.takeIf { it.s("status") == "open" }?.let {
            out += Highlight("dailyphoto", "📸 " + it.s("challenge").replaceFirstChar { c -> c.uppercase() })
        }
        if ("voicenotes" in fresh) out += Highlight("voicenotes", "A voice note from $name")
        if ("journal" in fresh) out += Highlight("journal", "$name wrote in your notebook")
        if ("wrapped" in fresh) out += Highlight("wrapped", us.optJSONObject("wrapped")?.list("months")?.firstOrNull()
            ?.s("label")?.replaceFirstChar { it.uppercase() }?.let { "$it, wrapped 🎁" } ?: "Your month, wrapped 🎁")
        if ("weekly" in fresh) out += Highlight("weekly", "Your week in review")
        us.optJSONObject("japanese")?.list("deck")?.count { it.optBoolean("due") }?.takeIf { it > 0 }?.let {
            out += Highlight("japanese", if (it == 1) "1 Japanese card" else "$it Japanese cards")
        }
        val dow = today.dayOfWeek.name.take(3).lowercase()
        us.optJSONObject("weekend")?.list("plans")?.filter { it.s("day") == dow && !it.optBoolean("done") }?.firstOrNull()?.let {
            out += Highlight("weekend", it.s("text").replaceFirstChar { c -> c.uppercase() })
        }
        if ("stories" in fresh) out += Highlight("stories", "A new chapter")
        if ("drawings" in fresh) out += Highlight("drawings", "$name drew something")
        return out.distinctBy { it.key }.take(4)
    }

    fun seenToJson(seen: Map<String, String>): String = JSONObject(seen as Map<*, *>).toString()
    fun seenFromJson(s: String): Map<String, String> = runCatching {
        val o = JSONObject(s); o.keys().asSequence().associateWith { o.optString(it) }
    }.getOrDefault(emptyMap())
}
