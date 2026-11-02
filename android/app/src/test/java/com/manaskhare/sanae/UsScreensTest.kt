package com.manaskhare.sanae

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import app.cash.paparazzi.DeviceConfig
import app.cash.paparazzi.Paparazzi
import com.manaskhare.sanae.ui.AppBackground
import com.manaskhare.sanae.ui.Look
import com.manaskhare.sanae.ui.Looks
import com.manaskhare.sanae.ui.SanaeTheme
import com.manaskhare.sanae.ui.NotebookCard
import com.manaskhare.sanae.ui.TogetherCard
import com.manaskhare.sanae.ui.BucketCard
import com.manaskhare.sanae.ui.CookingCard
import com.manaskhare.sanae.ui.GiftsCard
import com.manaskhare.sanae.ui.JapaneseCard
import com.manaskhare.sanae.ui.ScrapbookCard
import com.manaskhare.sanae.ui.SketchbookCard
import com.manaskhare.sanae.ui.StoriesCard
import com.manaskhare.sanae.ui.WatchingCard
import com.manaskhare.sanae.ui.WeekendCard
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Rule
import org.junit.Test

/** The "Us" tab's cards with sample data (the laptop's /api/us shape).
 *  Run: gradlew recordPaparazziDebug  -> app/src/test/snapshots/images */
class UsScreensTest {
    @get:Rule
    val paparazzi = Paparazzi(deviceConfig = DeviceConfig.PIXEL_6.copy(screenHeight = 3200), theme = "android:Theme.Material.NoActionBar")

    private fun shot(content: @Composable () -> Unit) {
        Looks.state.value = Look()
        paparazzi.snapshot { SanaeTheme { AppBackground { Column(Modifier.padding(16.dp)) { content() } } } }
    }

    private fun activity(id: Int, title: String, why: String, how: String?, streak: Int, days: String = "every day", at: String = "") =
        JSONObject().put("id", id).put("title", title).put("why", why).put("how", how ?: JSONObject.NULL).put("streak", streak)
            .put("days_words", days).put("at", at).put("due", true)

    private fun together(items: List<String>, points: Int, droopy: Boolean = false, session: Boolean = false) = JSONObject()
        .put("activities", JSONArray(listOf(
            activity(1, "Read 20 minutes", "I miss getting lost in a story", "tap", 6, at = "21:30"),
            activity(2, "Duolingo", "", null, 12),
            activity(3, "Go for a run", "to feel strong again", "pass", 3, days = "Mon, Wed, Fri"),
            activity(4, "Drink 2 L of water", "", null, 0),
        )))
        .put("room", JSONObject().put("points", points).put("items", JSONArray(items)).put("droopy", droopy)
            .put("next", JSONObject().put("label", "fairy lights").put("in", 3)))
        .put("pass_free", false)
        .put("goals", JSONArray(listOf(JSONObject().put("text", "gym 3 times a week").put("progress", "2 of 3 this week"))))
        .put("session", if (session) JSONObject().put("title", "Duolingo").put("her", "practise drawing hands")
            .put("until", System.currentTimeMillis() / 1000.0 + 14 * 60) else JSONObject.NULL)

    @Test fun brain() = shot {
        val data = JSONObject()
            .put("brain", JSONObject().put("enabled", true).put("available", true).put("calls_today", 4).put("daily_calls", 30).put("error", ""))
            .put("aims", JSONObject().put("aims", JSONArray(listOf(JSONObject().put("aim", "Help them settle into their new job")
                .put("why", "They wrote that their first day of work was good despite the nerves.")
                .put("ways", JSONArray(listOf("Ask how the second and third days felt", "Ask what part of the work they enjoy most")))))))
            .put("lessons", JSONArray(listOf(
                JSONObject().put("id", 1).put("text", "Don't ask about breakfast in the evening.").put("day", "2026-10-27").put("seen", 2),
                JSONObject().put("id", 2).put("text", "When something's unclear, ask instead of guessing.").put("day", "2026-10-27").put("seen", 1))))
            .put("sent", JSONArray(listOf(
                JSONObject().put("t", "2026-10-29T04:31:02").put("task", "reflect")
                    .put("sent", JSONObject().put("prompt", "[19:26] the user: I ate mac n cheese")),
                JSONObject().put("t", "2026-10-28T19:05:10").put("task", "first line"))))
        com.manaskhare.sanae.ui.BrainContent(data, "Sanae", open = 0)
    }

    @Test fun together_early() = shot {
        TogetherCard(together(listOf("sprout", "rug", "poster", "plant"), 16, session = true), "Sanae")
    }

    @Test fun together_full_room() = shot {
        TogetherCard(together(listOf("sprout", "rug", "poster", "plant", "fairy_lights", "bookshelf", "plant_big", "lamp",
                                     "cat_bed", "flowers", "window_plant", "stars", "beanbag", "cat"), 160), "Sanae")
        Spacer(Modifier.height(12.dp))
        TogetherCard(together(listOf("sprout", "plant"), 14, droopy = true), "Sanae")
    }

    private fun sketches(): List<JSONObject> =
        JSONArray(javaClass.classLoader!!.getResource("sketches.json").readText()).objects()

    @Test fun sketchbook() = shot {
        val s = sketches()
        SketchbookCard(JSONObject().put("drawings", JSONArray(s)).put("learning", "a cat sleeping"), "Sanae")
        Spacer(Modifier.height(12.dp))
        NotebookCard(JSONObject().put("pages", JSONArray(listOf(
            JSONObject().put("id", 3).put("author", "her").put("kind", "page").put("created", "2026-10-20T06:10:00")
                .put("text", "Ramen with Maya after a long wait sounds like the best kind of evening. Mine was quieter: " +
                     "I tried drawing your ramen from what you wrote. What did you order?").put("mood", "").put("private", 0)
                .put("voice", 0).put("drawing", s[2]),
        ))).put("sealed", JSONArray()), "Sanae")
    }

    @Test fun cooking() = shot {
        fun step(t: String, m: Int = 0) = JSONObject().put("text", t).put("minutes", m)
        val now = 1_760_000_000_000L
        CookingCard(JSONObject().put("session", JSONObject().put("title", "Egg fried rice").put("i", 1)
            .put("ingredients", JSONArray(listOf("2 cups cooked rice", "2 eggs", "1 tbsp soy sauce", "1 spring onion")))
            .put("steps", JSONArray(listOf(step("Beat the eggs in a bowl."), step("Scramble the eggs in a hot pan, then set them aside.", 2),
                                            step("Fry the rice until it's a bit crispy.", 5), step("Add the eggs, soy sauce and spring onion, and toss."))))
            .put("timer_until", (now + 95_000) / 1000.0)), "Sanae", now = { now })
    }

    @Test fun watching() = shot {
        fun show(where: String, kind: String, service: String) =
            JSONObject().put("where", where).put("kind", kind).put("service", service).put("last", "2026-10-20T21:31")
        WatchingCard(JSONObject().put("now", "The Bear, season 2 episode 5").put("shows", JSONArray(listOf(
            show("The Bear (up to season 2 episode 4)", "show", "VLC"),
            show("Frieren: Beyond Journey's End (up to season 1 episode 5)", "show", "Crunchyroll"),
            show("Dune: Part Two (a movie)", "movie", "Prime Video")))), "Sanae")
    }

    @Test fun japanese() = shot {
        fun card(w: String, m: String, due: Boolean) = JSONObject().put("word", w).put("meaning", m).put("due", due).put("box", 1)
        JapaneseCard(JSONObject().put("deck", JSONArray(listOf(card("neko", "cat", true), card("ame", "rain", false),
                                                                card("sora", "sky", true))))
            .put("streak", 4).put("corrections", 2).put("her_word", JSONObject().put("word", "hoshi").put("meaning", "star")), "Sanae")
        Spacer(Modifier.height(12.dp))
        JapaneseCard(JSONObject().put("deck", JSONArray()).put("her_word", JSONObject().put("word", "neko").put("meaning", "cat")), "Sanae")
    }

    @Test fun bucket() = shot {
        fun item(id: Int, t: String, who: String = "you", done: String? = null) = JSONObject().put("id", id).put("text", t)
            .put("who", who).put("done_day", done ?: JSONObject.NULL)
        BucketCard(JSONObject().put("items", JSONArray(listOf(
            item(1, "watch the sunrise from a hill"), item(2, "go to a concert"),
            item(3, "send me a photo from somewhere you've never been", who = "her"),
            item(4, "hike up to the hollywood sign", done = "2026-10-18").put("drawing", sketches()[3].put("subject", "mountains"))))), "Sanae")
    }

    @Test fun scrapbook() = shot {
        fun photo(id: Int, caption: String, drawing: JSONObject? = null) = JSONObject().put("id", id).put("caption", caption)
            .put("day", "2026-10-18").apply { if (drawing != null) put("drawing", drawing) }
        val sk = sketches()
        ScrapbookCard(JSONObject().put("months", JSONArray(listOf(JSONObject().put("label", "October 2026").put("photos", JSONArray(listOf(
            photo(3, "Our first sunrise, and you actually woke up for it"), photo(2, "The ramen that was worth the wait", sk[2]),
            photo(1, "Cat café day. I'm only a little jealous"))))))), "Sanae", image = { null })
    }

    @Test fun stories() = shot {
        fun ch(id: Int, title: String, text: String) = JSONObject().put("id", id).put("n", id).put("title", title).put("text", text)
        StoriesCard(JSONObject().put("place", "a floating library that drifts above a sleepy sea").put("chapters", JSONArray(listOf(
            ch(2, "The Cat Who Rides Bicycles", "The sun dipped low, painting the sky in soft lavender and peach."),
            ch(1, "The Floating Library", "The library floats above the sea like a giant book made of clouds.")))), "Sanae")
        Spacer(Modifier.height(12.dp))
        StoriesCard(JSONObject().put("chapters", JSONArray()), "Sanae")
    }

    @Test fun gifts() = shot {
        fun g(kind: String, text: String, day: String) = JSONObject().put("kind", kind).put("text", text).put("day", day)
        GiftsCard(JSONObject().put("waiting", "sky").put("gifts", JSONArray(listOf(
            g("song", "\"Blinding Lights\" by The Weeknd", "2026-10-20"),
            g("draw", "a cat in a teacup", "2026-10-18").put("drawing", sketches()[1]),
            g("good", "finally got the socket code working", "2026-10-16")))), "Sanae")
    }

    @Test fun weekend() = shot {
        fun plan(id: Int, text: String, day: String, at: String = "", done: Boolean = false) =
            JSONObject().put("id", id).put("text", text).put("day", day).put("at", at).put("done", done)
        WeekendCard(JSONObject().put("label", "Oct 24 – 25").put("plans", JSONArray(listOf(
            plan(1, "go hiking", "sat", "10:00", done = true), plan(2, "dinner with mom", "sat", "19:00"),
            plan(3, "coffee with Maya", "sun", "15:00"), plan(4, "laundry", "")))), "Sanae")
        Spacer(Modifier.height(12.dp))
        WeekendCard(JSONObject().put("label", "Oct 24 – 25").put("plans", JSONArray()), "Sanae")
    }

    @Test fun notebook() = shot {
        fun page(id: Int, author: String, text: String, created: String, mood: String = "", kind: String = "page", private: Int = 0) =
            JSONObject().put("id", id).put("author", author).put("kind", kind).put("text", text).put("mood", mood)
                .put("created", created).put("private", private).put("voice", 0)
        val j = JSONObject()
            .put("pages", JSONArray(listOf(
                page(4, "you", "Couldn't sleep, so I went for a walk by the lake. It was nice actually.", "2026-10-20T23:40:00", "😌", private = 1),
                page(3, "her", "Ramen with Maya after a long wait sounds like the best kind of evening, and the socket bug on " +
                     "top of it? That's a good day. Mine was quieter: hands again, they still look like little rakes. Today's word " +
                     "was sora, sky. What did you order?", "2026-10-20T06:10:00"),
                page(2, "you", "Ramen with Maya tonight at that tiny place by campus. We waited forever but it was worth it. " +
                     "Then I finally fixed the socket bug.", "2026-10-19T22:05:00", "😄"),
            )))
            .put("sealed", JSONArray(listOf(JSONObject().put("id", 1).put("created", "2026-10-19T21:00:00").put("deliver_on", "2027-01-19"))))
            .put("her_next", "2026-10-21T05:00")
        NotebookCard(j, "Sanae")
    }

    private fun sampleUs(): JSONObject {
        val sk = sketches()
        fun card(w: String, m: String, due: Boolean) = JSONObject().put("word", w).put("meaning", m).put("due", due)
        val today = java.time.LocalDate.now()
        return JSONObject()
            .put("together", together(listOf("sprout", "rug", "poster", "plant"), 16))
            .put("journal", JSONObject().put("pages", JSONArray(listOf(JSONObject().put("id", 3).put("author", "her").put("kind", "page")
                .put("created", "2026-10-20T06:10:00").put("text", "Ramen with Maya sounds like the best kind of evening.")))).put("sealed", JSONArray()))
            .put("voicenotes", JSONObject().put("notes", JSONArray(listOf(JSONObject().put("id", 4).put("day", today.toString()).put("text", "Morning!").put("seconds", 21.0)))))
            .put("japanese", JSONObject().put("deck", JSONArray(listOf(card("neko", "cat", true), card("sora", "sky", true), card("ame", "rain", false))))
                .put("her_word", JSONObject().put("word", "hoshi").put("meaning", "star")))
            .put("weekend", JSONObject().put("label", "Oct 24 – 25").put("plans", JSONArray(listOf(JSONObject().put("text", "go hiking").put("day", "sat")))))
            .put("cooking", JSONObject())
            .put("watching", JSONObject().put("now", "").put("shows", JSONArray(listOf(JSONObject().put("where", "The Bear"), JSONObject().put("where", "Frieren")))))
            .put("bucket", JSONObject().put("items", JSONArray(listOf(JSONObject().put("text", "sunrise").put("done_day", JSONObject.NULL),
                                                                       JSONObject().put("text", "concert").put("done_day", "2026-10-18")))))
            .put("scrapbook", JSONObject().put("months", JSONArray(listOf(JSONObject().put("photos", JSONArray(listOf(JSONObject().put("id", 1), JSONObject().put("id", 2))))))))
            .put("stories", JSONObject().put("chapters", JSONArray(listOf(JSONObject().put("id", 2).put("n", 2).put("title", "The Cat Who Rides Bicycles")))))
            .put("drawings", JSONObject().put("drawings", JSONArray(sk)).put("learning", "a cat sleeping"))
            .put("asks", JSONObject().put("gifts", JSONArray(listOf(JSONObject().put("kind", "song")))))
            .put("promises", JSONObject().put("open", JSONArray(listOf(JSONObject().put("id", 1)))))
            .put("weekly", JSONObject().put("weeks", JSONArray(listOf(JSONObject().put("week", "2026-W42").put("range", "Oct 12 – 18")))))
    }

    @Test fun us_home() {
        paparazzi.unsafeUpdateConfig(deviceConfig = DeviceConfig.PIXEL_6.copy(screenHeight = 2700))
        Looks.state.value = Look()
        paparazzi.snapshot { SanaeTheme { AppBackground { com.manaskhare.sanae.ui.UsHome(sampleUs(), "Sanae", "happy", setOf("voicenotes", "journal", "drawings")) {} } } }
    }

    @Test fun us_page() {
        paparazzi.unsafeUpdateConfig(deviceConfig = DeviceConfig.PIXEL_6)
        Looks.state.value = Look()
        paparazzi.snapshot { SanaeTheme { AppBackground { com.manaskhare.sanae.ui.UsPage("japanese", sampleUs(), "Sanae") {} } } }
    }

    @Test fun call_screen() {
        CallState.phase.value = CallPhase.SPEAKING
        CallState.startedAt = System.currentTimeMillis() - 192_000
        CallState.heard.value = "I'm walking home, it's so windy"
        CallState.reply.value = "Windy walks are the best kind of dramatic. Did you at least grab a jacket this time?"
        Looks.state.value = Look()
        paparazzi.unsafeUpdateConfig(deviceConfig = DeviceConfig.PIXEL_6)
        paparazzi.snapshot { SanaeTheme { AppBackground { CallScreen("Sanae") {} } } }
    }

    @Test fun week_story() {
        val slides = listOf(
            JSONObject().put("kind", "together").put("done", 23)
                .put("best", JSONObject().put("title", "Read 20 minutes").put("streak", 6).put("unit", "days"))
                .put("room", JSONArray(listOf("fairy lights"))).put("goals", JSONArray(listOf("gym 3 times a week"))),
            JSONObject().put("kind", "proud").put("text", "Six days of reading in a row while fighting that socket bug. I'm really proud of you."),
        )
        Looks.state.value = Look()
        paparazzi.unsafeUpdateConfig(deviceConfig = DeviceConfig.PIXEL_6)
        paparazzi.snapshot { SanaeTheme { androidx.compose.foundation.layout.Row {
            androidx.compose.foundation.layout.Box(Modifier.weight(1f)) { com.manaskhare.sanae.ui.StoryPage(slides, 0, { 0.6f }, "Sanae") }
            androidx.compose.foundation.layout.Box(Modifier.weight(1f)) { com.manaskhare.sanae.ui.StoryPage(slides, 1, { 0.3f }, "Sanae") }
        } } }
    }
}
