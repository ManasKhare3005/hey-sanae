package com.manaskhare.sanae.ui

import android.media.MediaPlayer
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Pause
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontStyle
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.manaskhare.sanae.VoiceNotes
import com.manaskhare.sanae.objects
import com.manaskhare.sanae.str
import kotlinx.coroutines.delay
import org.json.JSONObject
import java.time.LocalDate
import java.time.format.DateTimeFormatter

/** Her morning voice messages: the newest big, a few older ones small. Played from the phone's copy. */
@Composable
internal fun VoiceNotesCard(v: JSONObject?, name: String) {
    val notes = v?.optJSONArray("notes")?.objects().orEmpty()
    if (notes.isEmpty()) return
    val context = LocalContext.current
    var playing by remember { mutableIntStateOf(-1) }
    var progress by remember { mutableFloatStateOf(0f) }
    val player = remember { mutableStateOf<MediaPlayer?>(null) }
    fun stop() { player.value?.runCatching { stop(); release() }; player.value = null; playing = -1; progress = 0f }
    fun play(id: Int) {
        stop()
        val f = VoiceNotes.file(context, id)
        if (!f.exists()) return
        player.value = runCatching {
            MediaPlayer().apply { setDataSource(f.path); setOnCompletionListener { stop() }; prepare(); start() }
        }.getOrNull()
        if (player.value != null) playing = id
    }
    DisposableEffect(Unit) { onDispose { stop() } }
    LaunchedEffect(playing) {
        while (playing >= 0) {
            player.value?.let { p -> runCatching { progress = p.currentPosition.toFloat() / p.duration.coerceAtLeast(1) } }
            delay(100)
        }
    }
    var showText by remember { mutableStateOf(false) }
    Card {
        Label("Voice notes from $name")
        val first = notes.first()
        Row(Modifier.padding(top = 10.dp), verticalAlignment = Alignment.CenterVertically) {
            val id = first.optInt("id")
            val ready = VoiceNotes.has(context, id)
            Box(Modifier.size(56.dp).clip(CircleShape).background(if (ready) Accent0 else Accent0.copy(alpha = 0.2f))
                .clickable(enabled = ready) { if (playing == id) stop() else play(id) }, contentAlignment = Alignment.Center) {
                Icon(if (playing == id) Icons.Filled.Pause else Icons.Filled.PlayArrow, contentDescription = "Play", tint = Navy,
                     modifier = Modifier.size(30.dp))
            }
            Column(Modifier.weight(1f).padding(start = 14.dp)) {
                Text(when (first.str("day")) { LocalDate.now().toString() -> "This morning"; else -> day(first.str("day")) },
                     color = Text1, fontSize = 15.sp)
                Box(Modifier.padding(top = 8.dp).fillMaxWidth().height(4.dp).clip(RoundedCornerShape(2.dp)).background(Line)) {
                    Box(Modifier.fillMaxWidth(if (playing == id) progress else 0f).height(4.dp).background(Accent0))
                }
                Text(if (ready) "%d sec".format(first.optDouble("seconds").toInt()) else "Downloading…", color = Dim, fontSize = 12.sp,
                     modifier = Modifier.padding(top = 4.dp))
            }
        }
        Text(if (showText) first.str("text") else "Show what she said", color = if (showText) Text2 else Accent0, fontSize = 13.sp,
             fontStyle = if (showText) FontStyle.Italic else FontStyle.Normal,
             modifier = Modifier.padding(top = 10.dp).clickable { showText = !showText })
        notes.drop(1).take(4).forEach { n ->
            val id = n.optInt("id")
            Row(Modifier.padding(top = 10.dp).fillMaxWidth().clickable(enabled = VoiceNotes.has(context, id)) { if (playing == id) stop() else play(id) },
                verticalAlignment = Alignment.CenterVertically) {
                Icon(if (playing == id) Icons.Filled.Pause else Icons.Filled.PlayArrow, contentDescription = "Play", tint = Accent0,
                     modifier = Modifier.size(20.dp))
                Text(day(n.str("day")), color = Text2, fontSize = 13.sp, modifier = Modifier.padding(start = 10.dp).width(90.dp))
                Text(n.str("text"), color = Dim, fontSize = 12.sp, maxLines = 1, modifier = Modifier.weight(1f))
            }
        }
    }
}

private fun day(iso: String): String = runCatching {
    LocalDate.parse(iso).format(DateTimeFormatter.ofPattern("EEE, MMM d"))
}.getOrDefault(iso)
