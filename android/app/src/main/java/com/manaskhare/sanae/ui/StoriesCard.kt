package com.manaskhare.sanae.ui

import android.media.MediaPlayer
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
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
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.window.Dialog
import com.manaskhare.sanae.Prefs
import com.manaskhare.sanae.SanaeApi
import com.manaskhare.sanae.objects
import com.manaskhare.sanae.str
import kotlinx.coroutines.launch
import org.json.JSONObject
import java.io.File

/** Our bedtime story: every chapter so far, to read or to hear again in her voice. */
@Composable
internal fun StoriesCard(s: JSONObject?, name: String) {
    val chapters = s?.optJSONArray("chapters")?.objects().orEmpty()
    var open by remember { mutableStateOf<JSONObject?>(null) }
    Card {
        Label("Our bedtime story")
        if (chapters.isEmpty()) {
            Text("Say “tell me a bedtime story” and $name starts one. It carries on every night you ask.",
                 color = Text2, fontSize = 13.sp, modifier = Modifier.padding(top = 6.dp))
            return@Card
        }
        s?.str("place")?.takeIf { it.isNotBlank() && it != "null" }?.let {
            Text(it.replaceFirstChar { c -> c.uppercase() }, color = Dim, fontSize = 12.sp, fontFamily = FontFamily.Cursive)
        }
        chapters.take(6).forEach { c ->
            Row(Modifier.fillMaxWidth().padding(top = 8.dp).clickable { open = c }, verticalAlignment = Alignment.CenterVertically) {
                Text("${c.optInt("n")}", color = Accent0, fontSize = 15.sp, modifier = Modifier.width(26.dp))
                Column(Modifier.weight(1f)) {
                    Text(c.str("title"), color = Text1, fontSize = 15.sp)
                    Text(c.str("text").take(70) + "…", color = Dim, fontSize = 12.sp, maxLines = 1)
                }
            }
        }
    }
    open?.let { c -> ChapterDialog(c) { open = null } }
}

@Composable
private fun ChapterDialog(c: JSONObject, onDone: () -> Unit) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    var player by remember { mutableStateOf<MediaPlayer?>(null) }
    var status by remember { mutableStateOf("") }
    DisposableEffect(Unit) { onDispose { player?.runCatching { stop(); release() } } }
    fun play() {
        if (player != null) { player?.runCatching { stop(); release() }; player = null; status = ""; return }
        val id = c.optInt("id")
        val f = File(File(context.cacheDir, "stories").apply { mkdirs() }, "$id.wav")
        scope.launch {
            if (!f.exists() || f.length() < 44) {
                status = "Getting her voice…"
                val api = SanaeApi.from(Prefs(context))
                if (api == null || runCatching { api.download("/api/stories/$id.wav", f) }.isFailure) {
                    f.delete(); status = "Can't reach the laptop for her voice."; return@launch
                }
            }
            player = runCatching { MediaPlayer().apply { setDataSource(f.path); setOnCompletionListener { status = "" }; prepare(); start() } }.getOrNull()
            status = if (player != null) "Playing…" else "Couldn't play it."
        }
    }
    Dialog(onDismissRequest = onDone) {
        Column(Modifier.clip(RoundedCornerShape(14.dp)).background(Paper).padding(18.dp)) {
            Text("Chapter ${c.optInt("n")}", color = Ink.copy(alpha = 0.6f), fontSize = 12.sp)
            Text(c.str("title"), color = Ink, fontSize = 24.sp, fontFamily = FontFamily.Cursive)
            Column(Modifier.heightIn(max = 420.dp).verticalScroll(rememberScrollState()).padding(top = 8.dp)) {
                Text(c.str("text"), color = Ink, fontSize = 16.sp, lineHeight = 24.sp)
            }
            Row(Modifier.padding(top = 10.dp), verticalAlignment = Alignment.CenterVertically) {
                GhostButton(if (player != null) "Stop" else "Listen", color = Ink) { play() }
                Text(status, color = Ink.copy(alpha = 0.6f), fontSize = 12.sp, modifier = Modifier.padding(start = 10.dp))
            }
        }
    }
}
