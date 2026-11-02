package com.manaskhare.sanae.ui

import androidx.activity.compose.BackHandler
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.key
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.drawBehind
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.manaskhare.sanae.objects
import com.manaskhare.sanae.str
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import org.json.JSONArray
import org.json.JSONObject

/** "Your week, by her": the newest recap, and Watch to tap through it like stories. */
@Composable
internal fun WeekCard(w: JSONObject?, name: String) {
    val weeks = w?.optJSONArray("weeks")?.objects().orEmpty()
    if (weeks.isEmpty()) return
    Card {
        Label("Your week, by $name")
        val first = weeks.first()
        val cover = first.optJSONArray("slides")?.objects()?.firstOrNull()
        Row(Modifier.padding(top = 8.dp), verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f)) {
                Text(cover?.str("range").orEmpty(), color = Text1, fontSize = 18.sp)
                if (cover?.str("feel").orEmpty().isNotBlank()) Text(cover!!.str("feel").replaceFirstChar { it.uppercase() }, color = Text2, fontSize = 13.sp)
            }
            GhostButton("Watch") { WeekStories.watching.value = first }
        }
        weeks.drop(1).forEach { wk ->
            val c = wk.optJSONArray("slides")?.objects()?.firstOrNull()
            Text("Rewatch ${c?.str("range").orEmpty()}", color = Accent0, fontSize = 13.sp,
                 modifier = Modifier.padding(top = 8.dp).pointerInput(wk) { detectTapGestures { WeekStories.watching.value = wk } })
        }
    }
}

/** Your month, wrapped: the newest, and the last few to rewatch (same story player as the week). */
@Composable
internal fun WrappedCard(w: JSONObject?, name: String) {
    val months = w?.optJSONArray("months")?.objects().orEmpty()
    Card {
        Label("Your month, by $name")
        if (months.isEmpty()) {
            Text("On the 1st of every month $name wraps up the month before: days you talked, songs on repeat, movies, " +
                 "dishes, your photo streak, your best day.", color = Text2, fontSize = 13.sp, modifier = Modifier.padding(top = 6.dp))
            return@Card
        }
        val first = months.first()
        val cover = first.optJSONArray("slides")?.objects()?.firstOrNull()
        Row(Modifier.padding(top = 8.dp), verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f)) {
                Text(cover?.str("range").orEmpty(), color = Text1, fontSize = 18.sp)
                if (cover != null && cover.optInt("talked") > 0)
                    Text("We talked on ${cover.optInt("talked")} of ${cover.optInt("days")} days", color = Text2, fontSize = 13.sp)
            }
            GhostButton("Watch") { WeekStories.watching.value = first }
        }
        months.drop(1).forEach { m ->
            val c = m.optJSONArray("slides")?.objects()?.firstOrNull()
            Text("Rewatch ${c?.str("range").orEmpty()}", color = Accent0, fontSize = 13.sp,
                 modifier = Modifier.padding(top = 8.dp).pointerInput(m) { detectTapGestures { WeekStories.watching.value = m } })
        }
    }
}

/** The story being watched. It plays over the whole app (WeekStoryHost in MainActivity), not in a
 *  dialog window: the dialog version froze the app on the phone. */
object WeekStories {
    val watching = MutableStateFlow<JSONObject?>(null)
}

@Composable
fun WeekStoryHost(name: String) {
    val week by WeekStories.watching.collectAsState()
    week?.let { w -> key(w) { WeekStory(w, name) { WeekStories.watching.value = null } } }
}

@Composable
fun WeekStory(week: JSONObject, name: String, slideMs: Long = 6500, onClose: () -> Unit) {
    val slides = remember(week) { week.optJSONArray("slides")?.objects().orEmpty() }
    if (slides.isEmpty()) { LaunchedEffect(Unit) { onClose() }; return }
    var i by remember { mutableIntStateOf(0) }
    var t by remember { mutableFloatStateOf(0f) }
    LaunchedEffect(i) {
        t = 0f
        val steps = 60
        repeat(steps) { delay(slideMs / steps); t = (it + 1f) / steps }
        if (i < slides.size - 1) i++ else onClose()
    }
    BackHandler(onBack = onClose)
    StoryPage(slides, i, { t }, name, week.optString("label").ifBlank { "your week" },
              onBack = { if (i > 0) i-- }, onNext = { if (i < slides.size - 1) i++ else onClose() })
}

/** One page of the story (progress bars, her name, the slide); taps on the left third go back. */
@Composable
internal fun StoryPage(slides: List<JSONObject>, i: Int, t: () -> Float, name: String, label: String = "your week",
                       onBack: () -> Unit = {}, onNext: () -> Unit = {}) {
    run {
        val hue = listOf(Color(0xFF1B1035), Color(0xFF0E2A3A), Color(0xFF2A1426), Color(0xFF13261C), Color(0xFF2B2110), Color(0xFF1A1A3A), Color(0xFF0F2530))
        Box(Modifier.fillMaxSize()
            .background(Brush.verticalGradient(listOf(hue[i % hue.size], Color(0xFF07080C))))
            .pointerInput(slides.size) {
                detectTapGestures { pos -> if (pos.x < size.width / 3f) onBack() else onNext() }
            }) {
            Column(Modifier.fillMaxSize().statusBarsPadding().navigationBarsPadding().padding(20.dp)) {
                Row(horizontalArrangement = Arrangement.spacedBy(4.dp)) {
                    slides.indices.forEach { k ->
                        Box(Modifier.weight(1f).height(3.dp).clip(RoundedCornerShape(2.dp)).background(Color.White.copy(alpha = 0.25f))
                                .drawBehind {
                                    val f = when { k < i -> 1f; k == i -> t().coerceIn(0f, 1f); else -> 0f }
                                    drawRect(Color.White, size = size.copy(width = size.width * f))
                                })
                    }
                }
                Text("$name · $label", color = Color.White.copy(alpha = 0.7f), fontSize = 12.sp, modifier = Modifier.padding(top = 10.dp))
                Box(Modifier.weight(1f).fillMaxWidth(), contentAlignment = Alignment.Center) { Slide(slides[i], name) }
            }
        }
    }
}

@Composable
private fun Big(text: String, size: Int = 34) =
    Text(text, style = DisplayStyle, color = Color.White, fontSize = size.sp, lineHeight = (size * 1.15).sp, textAlign = TextAlign.Center)

@Composable
private fun Small(text: String, alpha: Float = 0.8f) =
    Text(text, color = Color.White.copy(alpha = alpha), fontSize = 17.sp, lineHeight = 24.sp, textAlign = TextAlign.Center)

private fun JSONArray?.strings(): List<String> = this?.let { a -> (0 until a.length()).map { a.optString(it) } }.orEmpty()

@Composable
private fun Slide(s: JSONObject, name: String) {
    Column(horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.spacedBy(14.dp),
           modifier = Modifier.padding(horizontal = 8.dp)) {
        when (s.str("kind")) {
            "cover" -> {
                Small(s.str("range"), 0.7f)
                Big(s.str("title").ifBlank { "Your week" }, 48)
                if (s.str("feel").isNotBlank()) Small(s.str("feel").replaceFirstChar { it.uppercase() })
                if (s.optInt("talked") > 0) Small("We talked on ${s.optInt("talked")} of ${s.optInt("days", 7)} days", 0.6f)
                if (s.has("good") && s.optInt("good") + s.optInt("rough") > 0)
                    Small("☀ ${s.optInt("good")} good days · ☁ ${s.optInt("rough")} rough ones", 0.8f)
            }
            "songs" -> {
                Small("On repeat", 0.7f)
                s.optJSONArray("top")?.objects().orEmpty().forEachIndexed { k, t ->
                    Big("${k + 1}. ${t.str("title")}", if (k == 0) 30 else 22)
                    Small(listOf(t.str("artist"), "${t.optInt("days")} days").filter { it.isNotBlank() }.joinToString(" · "), 0.6f)
                }
                val added = s.optJSONArray("added").strings()
                if (added.isNotEmpty()) Small("New on our playlist: ${added.joinToString()}", 0.7f)
            }
            "screen" -> {
                Small("On screen", 0.7f)
                if (s.str("hours").isNotBlank()) Big(s.str("hours") + " watched together")
                if (s.str("top_show").isNotBlank()) Small("You were into ${s.str("top_show")}")
                s.optJSONArray("movies")?.objects().orEmpty().forEach { m ->
                    Small("🎬 ${m.str("title")}" + if (m.optInt("stars") > 0) "  " + "★".repeat(m.optInt("stars")) else "")
                }
            }
            "kitchen" -> {
                Small("In the kitchen", 0.7f)
                Big(if (s.optInt("cooked") > 0) "${s.optInt("cooked")} dish${if (s.optInt("cooked") != 1) "es" else ""} cooked"
                    else "${s.optInt("new")} new recipe${if (s.optInt("new") != 1) "s" else ""}")
                s.optJSONObject("best")?.let { b -> Small("Best: ${b.str("title")} ${"★".repeat(b.optInt("stars"))}") }
                val re = s.optJSONArray("recreated").strings()
                if (re.isNotEmpty()) Small("Made at home from a photo: ${re.joinToString()}", 0.7f)
            }
            "photo_a_day" -> {
                Small("Photo a day", 0.7f)
                Big("${s.optInt("done")} photos")
                Small("🔥 Best streak: ${s.optInt("best")} days")
                PhotoRow(s.optJSONArray("items")?.objects().orEmpty())
            }
            "together_month" -> {
                Small("Doing it together", 0.7f)
                if (s.optInt("done") > 0) Big("${s.optInt("done")} things done")
                s.optJSONObject("top")?.let { t -> Small("${t.str("title")} × ${t.optInt("times")}") }
                if (s.optInt("pages") > 0) Small("${s.optInt("pages")} page${if (s.optInt("pages") != 1) "s" else ""} in our notebook")
            }
            "pattern" -> {
                Small("What makes your good days", 0.7f)
                Big((if (s.optBoolean("better")) "☀ " else "☁ ") + s.str("label"), 28)
                Small(s.str("text"))
            }
            "bestday" -> {
                Small("Best day of the month", 0.7f)
                Big(s.str("day"), 26)
                Text("“${s.str("text")}”", color = Color.White, fontSize = 20.sp, lineHeight = 28.sp,
                     fontFamily = FontFamily.Cursive, textAlign = TextAlign.Center)
            }
            "together" -> {
                Small("Doing it together", 0.7f)
                Big("${s.optInt("done")} things done")
                s.optJSONObject("best")?.let { b -> Small("🔥 ${b.optInt("streak")} ${b.str("unit")} of ${b.str("title")} in a row") }
                val room = s.optJSONArray("room").strings()
                if (room.isNotEmpty()) Small("New in our room: ${room.joinToString()}", 0.7f)
                s.optJSONArray("goals").strings().forEach { Small("✓ $it") }
            }
            "wins" -> {
                Small("Wins I noticed", 0.7f)
                s.optJSONArray("items").strings().forEach { Big(it, 22) }
            }
            "notebook" -> {
                Small("Our notebook", 0.7f)
                if (s.optInt("pages") > 0) Big("${s.optInt("pages")} page${if (s.optInt("pages") != 1) "s" else ""}")
                val moods = s.optJSONArray("moods").strings()
                if (moods.isNotEmpty()) Text(moods.joinToString(" "), fontSize = 30.sp)
                if (s.str("highlight").isNotBlank()) Text("“${s.str("highlight")}”", color = Color.White, fontSize = 20.sp, lineHeight = 28.sp,
                                                          fontFamily = FontFamily.Cursive, textAlign = TextAlign.Center)
            }
            "moment" -> {
                Small(when (s.str("type")) { "joke" -> "Running joke of the week"; "nickname" -> "New nickname"; else -> "Remember this?" }, 0.7f)
                Big(s.str("text"), 30)
            }
            "photos" -> {
                Small("Our scrapbook this week", 0.7f)
                PhotoRow(s.optJSONArray("items")?.objects().orEmpty())
            }
            "proud" -> {
                Small("What I'm proudest of", 0.7f)
                Text(s.str("text"), color = Color.White, fontSize = 24.sp, lineHeight = 32.sp, fontFamily = FontFamily.Cursive, textAlign = TextAlign.Center)
                Small("— $name", 0.6f)
            }
            "next" -> {
                Small("Next week", 0.7f)
                s.optJSONArray("items").strings().forEach { Big(it, 22) }
                Spacer(Modifier.height(8.dp))
                Small("We've got this.", 0.6f)
            }
            else -> Big(s.str("text").ifBlank { "…" })
        }
    }
}

@Composable
private fun PhotoRow(items: List<JSONObject>) {
    val image = rememberScrapbookImages()
    Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
        items.chunked(2).forEach { pair ->
            Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                pair.forEach { p ->
                    Column(Modifier.weight(1f).background(Color.White).padding(5.dp)) {
                        val img = image(p.optInt("id"))
                        if (img != null) androidx.compose.foundation.Image(img, contentDescription = p.str("caption"),
                            contentScale = androidx.compose.ui.layout.ContentScale.Crop,
                            modifier = Modifier.fillMaxWidth().aspectRatio(1f))
                        else Box(Modifier.fillMaxWidth().aspectRatio(1f).background(Color(0xFFE8E2D6)))
                        Text(p.str("caption"), color = Ink, fontSize = 12.sp, lineHeight = 15.sp, fontFamily = FontFamily.Cursive,
                             textAlign = TextAlign.Center, maxLines = 2, modifier = Modifier.fillMaxWidth())
                    }
                }
                if (pair.size == 1) Spacer(Modifier.weight(1f))
            }
        }
    }
}
