package com.manaskhare.sanae

import android.content.Context
import org.json.JSONObject

/**
 * Her name and notification lines, from persona.yaml on the laptop (sent with every sync, kept in
 * Prefs so they work offline). Before the first sync: the defaults below.
 */
object Persona {
    const val DEFAULT_NAME = "Sanae"
    private val DEFAULTS = mapOf(
        "reminder" to listOf("Psst, {text}~", "Hey! Don't forget: {text}", "Reminder from me: {text} ♡"),
        "event_soon" to listOf("{text} starts {when}, don't be late!", "Heads up: {text} at {when}~"),
        "notes_ready" to listOf("Your notes for {text} are ready!", "Done! Notes for {text} are waiting for you."),
        "routine_forgot" to listOf("You forgot this today: {text}!", "Hey, still not ticked off today: {text}. There's still time~",
                                   "Today's routine isn't done yet: {text}"),
    )

    @Volatile private var cached: JSONObject? = null

    private fun data(context: Context): JSONObject? =
        cached ?: Prefs(context).personaJson.takeIf { it.isNotBlank() }?.let { runCatching { JSONObject(it) }.getOrNull() }
            ?.also { cached = it }

    fun name(context: Context): String = data(context)?.optString("name")?.takeIf { it.isNotBlank() } ?: DEFAULT_NAME

    /** A line in her voice for `kind` (reminder, event_soon, notes_ready). */
    fun line(context: Context, kind: String, text: String, at: String = ""): String {
        val fromLaptop = data(context)?.optJSONObject("notify")?.optJSONArray(kind)
        val choices = if (fromLaptop != null && fromLaptop.length() > 0) List(fromLaptop.length()) { fromLaptop.getString(it) }
                      else DEFAULTS[kind] ?: listOf("{text}")
        return fill(choices.random(), text, at)
    }

    fun fill(template: String, text: String, at: String) = template.replace("{text}", text).replace("{when}", at)

    /** Store what the laptop sent (the "persona" part of a /api/sync answer). */
    fun save(context: Context, json: JSONObject?) {
        if (json == null) return
        cached = json
        Prefs(context).personaJson = json.toString()
    }
}
