package com.manaskhare.sanae

import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.time.LocalDate

class UsLogicTest {
    private val sat = LocalDate.of(2026, 10, 24)

    private fun act(title: String, how: String?) = JSONObject().put("title", title).put("due", true).put("how", how ?: JSONObject.NULL)

    fun us(herPage: Int = 3, note: Int = 5) = JSONObject()
        .put("together", JSONObject().put("activities", JSONArray(listOf(act("Read", "tap"), act("Duolingo", null), act("Run", null)))))
        .put("journal", JSONObject().put("pages", JSONArray(listOf(JSONObject().put("id", herPage).put("author", "her"),
                                                                     JSONObject().put("id", 2).put("author", "you")))))
        .put("voicenotes", JSONObject().put("notes", JSONArray(listOf(JSONObject().put("id", note).put("day", sat.toString())))))
        .put("japanese", JSONObject().put("deck", JSONArray(listOf(JSONObject().put("due", true), JSONObject().put("due", false))))
            .put("her_word", JSONObject().put("word", "hoshi").put("meaning", "star")))
        .put("weekend", JSONObject().put("label", "Oct 24 – 25").put("plans", JSONArray(listOf(
            JSONObject().put("text", "go hiking").put("day", "sat").put("done", false)))))
        .put("promises", JSONObject().put("open", JSONArray()))
        .put("stories", JSONObject().put("error", "boom"))

    @Test fun lines() {
        val u = us()
        assertEquals("1 of 3 done today", UsTiles.line("together", u.optJSONObject("together"), "Sanae", sat))
        assertEquals("Sanae wrote back", UsTiles.line("journal", u.optJSONObject("journal"), "Sanae", sat))
        assertEquals("A new one from this morning", UsTiles.line("voicenotes", u.optJSONObject("voicenotes"), "Sanae", sat))
        assertEquals("1 card to review", UsTiles.line("japanese", u.optJSONObject("japanese"), "Sanae", sat))
        assertEquals("1 plan · Oct 24 – 25", UsTiles.line("weekend", u.optJSONObject("weekend"), "Sanae", sat))
        assertEquals("Nothing open", UsTiles.line("promises", u.optJSONObject("promises"), "Sanae", sat))
        assertEquals("Opens after the first sync", UsTiles.line("stories", u.optJSONObject("stories"), "Sanae", sat))
        assertEquals("Opens after the first sync", UsTiles.line("bucket", null, "Sanae", sat))
        fun item(done: Boolean) = JSONObject().put("item", "milk").put("done", done)
        val g = JSONObject().put("items", JSONArray(listOf(item(false), item(false), item(true))))
        assertEquals("2 things to get · 1 in the cart", UsTiles.line("groceries", g, "Sanae", sat))
        assertEquals("What you need from the store", UsTiles.line("groceries", JSONObject().put("items", JSONArray()), "Sanae", sat))
        fun recipe(t: String, stars: Int) = JSONObject().put("title", t).put("stars", stars)
        val box = JSONObject().put("session", JSONObject.NULL).put("recipes", JSONArray(listOf(recipe("Egg fried rice", 5), recipe("Pancakes", 3))))
        assertEquals("2 recipes · ★ Egg fried rice", UsTiles.line("cooking", box, "Sanae", sat))
        val songs = JSONObject().put("songs", JSONArray(listOf(JSONObject().put("id", 2).put("title", "Espresso"))))
        assertEquals("1 song · Espresso", UsTiles.line("playlist", songs, "Sanae", sat))
        assertEquals("2", UsTiles.signature("playlist", songs))
        songs.put("week_song", JSONObject().put("title", "Espresso").put("week", "2026-W43"))
        assertEquals("Song of the week: Espresso", UsTiles.line("playlist", songs, "Sanae", sat))
        assertEquals("2 2026-W43", UsTiles.signature("playlist", songs))
        val daily = JSONObject().put("streak", 4).put("today", JSONObject().put("status", "open").put("challenge", "your shadow, outside"))
        assertEquals("Your shadow, outside · 🔥 4", UsTiles.line("dailyphoto", daily, "Sanae", sat))
        val walk = JSONObject().put("key", "walked").put("label", "Walking 6k+ steps").put("better", true)
        val good = JSONObject().put("days", 20).put("need", 8).put("patterns", JSONArray(listOf(walk)))
        assertEquals("Walking 6k+ steps helps", UsTiles.line("gooddays", good, "Sanae", sat))
        assertEquals("walked+", UsTiles.signature("gooddays", good))
        val wrapped = JSONObject().put("months", JSONArray(listOf(JSONObject().put("month", "2026-10").put("label", "your October"))))
        assertEquals("Your October, wrapped", UsTiles.line("wrapped", wrapped, "Sanae", sat))
        assertEquals("2026-10", UsTiles.signature("wrapped", wrapped))
        assertEquals("On the 1st of every month", UsTiles.line("wrapped", JSONObject().put("months", JSONArray()), "Sanae", sat))
        assertEquals("3 of 8 days so far", UsTiles.line("gooddays", JSONObject().put("days", 3).put("need", 8).put("patterns", JSONArray()), "Sanae", sat))
    }

    @Test fun dotsOnlyForNewThingsAfterTheFirstSync() {
        val first = UsTiles.firstSeen(us(), emptyMap())
        assertTrue(UsTiles.fresh(us(), first).isEmpty())
        val later = us(herPage = 7, note = 6)
        assertEquals(setOf("journal", "voicenotes"), UsTiles.fresh(later, first))
        val opened = first + ("journal" to UsTiles.signature("journal", later.optJSONObject("journal")))
        assertEquals(setOf("voicenotes"), UsTiles.fresh(later, opened))
        assertEquals(opened, UsTiles.seenFromJson(UsTiles.seenToJson(opened)))
    }

    @Test fun todayWithHer() {
        val later = us(herPage = 7)
        val h = UsTiles.today(later, setOf("journal"), "Sanae", sat)
        assertEquals(listOf("together", "journal", "japanese", "weekend"), h.map { it.key })
        assertEquals("2 things to do together", h[0].text)
        assertEquals("Go hiking", h[3].text)
    }
}
