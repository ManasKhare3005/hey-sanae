package com.manaskhare.sanae.ui

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.Star
import androidx.compose.material.icons.filled.StarBorder
import androidx.compose.material3.Icon
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.OutlinedTextFieldDefaults
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.manaskhare.sanae.Us
import com.manaskhare.sanae.objects
import com.manaskhare.sanae.str
import kotlinx.coroutines.launch
import org.json.JSONObject
import java.time.LocalDate
import java.time.LocalDateTime
import java.time.temporal.ChronoUnit

/** Shows and movies you watched on the laptop with her keeping you company, and where you're at. */
@Composable
internal fun WatchingCard(w: JSONObject?, name: String) {
    val shows = w?.optJSONArray("shows")?.objects().orEmpty()
    val now = w?.str("now").orEmpty().takeIf { it.isNotBlank() && it != "null" }
    MovieNightCard(w, name)
    MovieLogCard(w, name)
    if (shows.isEmpty() && now == null) return
    Card(Modifier.padding(top = 12.dp)) {
        Label("Watched together")
        if (now != null) Text("Watching now: $now · $name's quiet till it's over", color = Accent0, fontSize = 13.sp,
                              modifier = Modifier.padding(top = 4.dp))
        shows.forEach { s ->
            Row(Modifier.fillMaxWidth().padding(top = 8.dp), verticalAlignment = Alignment.CenterVertically) {
                Text(when (s.str("kind")) { "movie" -> "🎬"; "video" -> "▶"; else -> "📺" }, fontSize = 16.sp)
                Column(Modifier.weight(1f).padding(start = 10.dp)) {
                    Text(s.str("where"), color = Text1, fontSize = 15.sp)
                    Text(listOf(s.str("service"), ago(s.str("last"))).filter { it.isNotBlank() }.joinToString(" · "),
                         color = Dim, fontSize = 12.sp)
                }
            }
        }
    }
}

/** Every movie you two watched: your stars, your words, and her take. */
@Composable
private fun MovieLogCard(w: JSONObject?, name: String) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    val log = w?.optJSONArray("log")?.objects().orEmpty()
    if (log.isEmpty()) return
    Card(Modifier.padding(top = 12.dp)) {
        Label("Our movie log · ${log.size}")
        log.forEach { m ->
            val id = m.optInt("id")
            Column(Modifier.fillMaxWidth().padding(top = 12.dp)) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text("🎬 " + m.str("title"), color = Text1, fontSize = 16.sp, modifier = Modifier.weight(1f))
                    Text(ago(m.str("day") + "T12:00"), color = Dim, fontSize = 12.sp)
                    Box(Modifier.size(36.dp).clip(CircleShape).clickable { scope.launch { Us.removeMovie(context, id) } },
                        contentAlignment = Alignment.Center) {
                        Icon(Icons.Filled.Close, contentDescription = "Take it out", tint = Dim, modifier = Modifier.size(14.dp))
                    }
                }
                Row {
                    (1..5).forEach { n ->
                        Icon(if (n <= m.optInt("stars")) Icons.Filled.Star else Icons.Filled.StarBorder,
                             contentDescription = "$n stars", tint = Butter,
                             modifier = Modifier.size(28.dp).clickable { scope.launch { Us.rateMovie(context, id, n) } }.padding(3.dp))
                    }
                }
                if (m.str("your_take").isNotBlank()) Text("You: “${m.str("your_take")}”", color = Text2, fontSize = 13.sp)
                if (m.str("her_take").isNotBlank()) Text("$name: ${m.str("her_take")}", color = Lavender, fontSize = 15.sp,
                                                         fontFamily = FontFamily.Cursive, modifier = Modifier.padding(top = 2.dp))
            }
        }
    }
}

/** Tonight's pick (worked out on the laptop from time till bed + the day's mood) and the watchlist. */
@Composable
private fun MovieNightCard(w: JSONObject?, name: String) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    val list = w?.optJSONArray("watchlist")?.objects().orEmpty()
    val tonight = w?.optJSONObject("tonight")
    var text by remember { mutableStateOf("") }
    val send = { if (text.isNotBlank()) { val t = text.trim(); text = ""; scope.launch { Us.addWatch(context, t) } } }
    Card {
        Label("Movie night")
        tonight?.str("pick")?.takeIf { it.isNotBlank() && it != "null" }?.let { pick ->
            Text("$name's pick for tonight", color = Dim, fontSize = 12.sp, modifier = Modifier.padding(top = 6.dp))
            Text(pick, color = Text1, fontSize = 18.sp)
            Text(tonight.str("why"), color = Text2, fontSize = 13.sp)
        }
        Row(Modifier.fillMaxWidth().padding(top = 10.dp), verticalAlignment = Alignment.CenterVertically) {
            OutlinedTextField(
                text, { text = it }, singleLine = true, modifier = Modifier.weight(1f),
                placeholder = { Text("Add to the watchlist", color = Dim) }, shape = RoundedCornerShape(14.dp),
                keyboardOptions = KeyboardOptions(imeAction = ImeAction.Done), keyboardActions = KeyboardActions(onDone = { send() }),
                colors = OutlinedTextFieldDefaults.colors(focusedTextColor = Text1, unfocusedTextColor = Text1,
                    focusedBorderColor = Accent0, unfocusedBorderColor = Line, cursorColor = Accent0),
            )
            Box(Modifier.padding(start = 8.dp).size(48.dp).clip(CircleShape).clickable { send() }, contentAlignment = Alignment.Center) {
                Icon(Icons.Filled.Add, contentDescription = "Add", tint = Accent0)
            }
        }
        if (list.isEmpty()) Text("Movies and shows you want to see together. Ask $name \"what should we watch?\" and she " +
                                 "picks by how long till bed and how your day went.", color = Text2, fontSize = 13.sp,
                                 modifier = Modifier.padding(top = 8.dp))
        list.forEach { item ->
            Row(Modifier.fillMaxWidth().padding(top = 6.dp), verticalAlignment = Alignment.CenterVertically) {
                Text(if (item.str("kind") == "show") "📺" else "🎬", fontSize = 15.sp)
                Text(item.str("title"), color = Text1, fontSize = 15.sp, modifier = Modifier.weight(1f).padding(start = 10.dp))
                Box(Modifier.size(40.dp).clip(CircleShape).clickable { scope.launch { Us.removeWatch(context, item.optInt("id")) } },
                    contentAlignment = Alignment.Center) {
                    Icon(Icons.Filled.Close, contentDescription = "Remove", tint = Dim, modifier = Modifier.size(16.dp))
                }
            }
        }
    }
}

private fun ago(iso: String): String = runCatching {
    val d = LocalDateTime.parse(iso).toLocalDate()
    val n = ChronoUnit.DAYS.between(d, LocalDate.now()).toInt()
    when { n <= 0 -> "today"; n == 1 -> "yesterday"; else -> "$n days ago" }
}.getOrDefault("")
