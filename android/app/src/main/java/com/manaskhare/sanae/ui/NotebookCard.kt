package com.manaskhare.sanae.ui

import android.Manifest
import android.content.pm.PackageManager
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Mic
import androidx.compose.material.icons.filled.MoreVert
import androidx.compose.material.icons.filled.Stop
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.OutlinedTextFieldDefaults
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
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
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.core.content.ContextCompat
import com.manaskhare.sanae.Recorder
import com.manaskhare.sanae.Us
import com.manaskhare.sanae.objects
import com.manaskhare.sanae.str
import kotlinx.coroutines.launch
import org.json.JSONObject
import java.time.LocalDate
import java.time.LocalDateTime
import java.time.format.DateTimeFormatter

private val MOOD_CHOICES = listOf("😄", "🙂", "😌", "😐", "😴", "😕", "😤", "😢")

/** The exchange diary: you write a page, she writes hers back in the morning. */
@Composable
internal fun NotebookCard(j: JSONObject?, name: String) {
    var writing by remember { mutableStateOf(false) }
    var all by remember { mutableStateOf(false) }
    Card {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Label("Our notebook", modifier = Modifier.weight(1f))
            GhostButton("Write") { writing = true }
        }
        val pages = j?.optJSONArray("pages")?.objects().orEmpty()
        val sealed = j?.optJSONArray("sealed")?.objects().orEmpty()
        if (pages.isEmpty()) {
            Text("An exchange diary, just you two. Write a page tonight; $name's page will be waiting in the morning.",
                 color = Text2, modifier = Modifier.padding(top = 6.dp))
        }
        if (j?.isNull("her_next") == false) {
            Text("Your page is in. $name writes back in the morning.", color = Accent0, fontSize = 13.sp,
                 modifier = Modifier.padding(top = 6.dp))
        }
        if (sealed.isNotEmpty()) {
            val next = sealed.minOf { it.str("deliver_on") }
            Text("✉ ${sealed.size} sealed letter${if (sealed.size > 1) "s" else ""} to future you · next opens ${day(next)}",
                 color = Text2, fontSize = 13.sp, modifier = Modifier.padding(top = 6.dp))
        }
        (if (all) pages else pages.take(4)).forEach { PageView(it, name) }
        if (pages.size > 4) GhostButton(if (all) "Show fewer" else "All ${pages.size} pages", Modifier.padding(top = 8.dp)) { all = !all }
    }
    if (writing) WriteDialog(name) { writing = false }
}

private fun day(iso: String): String = runCatching {
    LocalDate.parse(iso.take(10)).format(DateTimeFormatter.ofPattern("MMM d"))
}.getOrDefault(iso)

private fun stamp(iso: String): String = runCatching {
    LocalDateTime.parse(iso).format(DateTimeFormatter.ofPattern("EEE, MMM d · h:mm a"))
}.getOrDefault(iso)

@Composable
private fun PageView(p: JSONObject, name: String) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    val hers = p.str("author") == "her"
    val letter = p.str("kind") == "letter"
    var menu by remember { mutableStateOf(false) }
    val shape = RoundedCornerShape(topStart = if (hers) 4.dp else 16.dp, topEnd = if (hers) 16.dp else 4.dp, bottomStart = 16.dp, bottomEnd = 16.dp)
    Column(Modifier.padding(top = 12.dp).fillMaxWidth(), horizontalAlignment = if (hers) Alignment.Start else Alignment.End) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            val who = when { letter -> "Letter from past you"; hers -> name; else -> "You" }
            Label("$who · ${stamp(p.str("created"))}" + (if (p.optInt("private") == 1) " · private" else "") +
                  (if (p.optInt("voice") == 1) " · spoken" else ""))
            if (!hers && p.optInt("id") > 0) Box {
                IconButton(onClick = { menu = true }, modifier = Modifier.size(28.dp)) {
                    Icon(Icons.Filled.MoreVert, contentDescription = "More", tint = Dim, modifier = Modifier.size(16.dp))
                }
                DropdownMenu(expanded = menu, onDismissRequest = { menu = false }) {
                    val priv = p.optInt("private") == 1
                    DropdownMenuItem(text = { Text(if (priv) "Let $name bring it up" else "Keep it private (she won't bring it up)") }, onClick = {
                        menu = false; scope.launch { Us.setPrivate(context, p.optInt("id"), !priv) }
                    })
                    DropdownMenuItem(text = { Text("Delete page", color = Red) }, onClick = {
                        menu = false; scope.launch { Us.deletePage(context, p.optInt("id")) }
                    })
                }
            }
        }
        Column(
            Modifier.padding(top = 4.dp).fillMaxWidth(0.92f).clip(shape)
                .background(if (hers) Color(0xFFFFF8E7).copy(alpha = 0.07f) else Accent0.copy(alpha = 0.09f))
                .border(1.dp, if (hers) Color(0xFFFFE6A7).copy(alpha = 0.18f) else Accent0.copy(alpha = 0.22f), shape)
                .padding(14.dp),
        ) {
            if (p.str("mood").isNotBlank()) Text(p.str("mood"), fontSize = 18.sp)
            Text(p.str("text"), color = Text1, fontSize = if (hers) 17.sp else 15.sp, lineHeight = if (hers) 24.sp else 21.sp,
                 fontFamily = if (hers) FontFamily.Cursive else FontFamily.Default)
            p.optJSONObject("drawing")?.let { d ->
                Sketch(d, Modifier.padding(top = 10.dp).size(150.dp))
                Text(d.str("caption"), color = Text2, fontSize = 14.sp, fontFamily = FontFamily.Cursive)
            }
        }
    }
}

@Composable
private fun WriteDialog(name: String, onDone: () -> Unit) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    var text by remember { mutableStateOf("") }
    var mood by remember { mutableStateOf("") }
    var private by remember { mutableStateOf(false) }
    var kind by remember { mutableStateOf("Page") }
    var recorder by remember { mutableStateOf<Recorder?>(null) }
    var busy by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf("") }
    DisposableEffect(Unit) { onDispose { recorder?.stop() } }
    val fieldColors = OutlinedTextFieldDefaults.colors(focusedTextColor = Text1, unfocusedTextColor = Text1,
        focusedBorderColor = Accent0, unfocusedBorderColor = Line, cursorColor = Accent0)

    fun sendVoice(wav: ByteArray) {
        if (wav.isEmpty()) { error = "That was too short."; return }
        busy = true
        scope.launch {
            val err = Us.voicePage(context, wav, mood, private)
            busy = false
            if (err == null) onDone() else error = err
        }
    }

    AlertDialog(
        onDismissRequest = { if (recorder == null && !busy) onDone() },
        containerColor = Panel,
        title = { Text(if (kind == "Page") "Today's page" else "A letter to future you", color = Text1) },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                Segmented(listOf("Page", "Letter · 3 mo", "Letter · 6 mo"), kind, { it }) { kind = it }
                OutlinedTextField(text, { text = it }, minLines = 6, maxLines = 12, colors = fieldColors,
                    placeholder = { Text(if (kind == "Page") "How was today, really?" else "Dear future me…") },
                    modifier = Modifier.fillMaxWidth())
                if (kind == "Page") {
                    Row(horizontalArrangement = Arrangement.spacedBy(4.dp)) {
                        MOOD_CHOICES.forEach { m ->
                            Text(m, fontSize = 22.sp, modifier = Modifier.clip(CircleShape)
                                .background(if (m == mood) Accent0.copy(alpha = 0.25f) else Color.Transparent)
                                .clickable { mood = if (mood == m) "" else m }.padding(4.dp))
                        }
                    }
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Text("Private: $name reads it but won't bring it up", color = Text2, fontSize = 13.sp, modifier = Modifier.weight(1f))
                        Toggle(private) { private = it }
                    }
                    // say it instead: recorded here, written down by the laptop
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        val rec = recorder
                        IconButton(enabled = !busy, onClick = {
                            if (rec != null) {
                                recorder = null
                                sendVoice(rec.stop())
                            } else if (ContextCompat.checkSelfPermission(context, Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) {
                                error = "Allow the microphone first (tap the mic on the $name tab once)."
                            } else {
                                error = ""
                                recorder = Recorder(onAutoStop = {}, untilSilence = false, maxSeconds = 300).also { r ->
                                    runCatching { r.start() }.onFailure { error = "Mic unavailable: ${it.message}"; recorder = null }
                                }
                            }
                        }) {
                            Icon(if (rec != null) Icons.Filled.Stop else Icons.Filled.Mic, contentDescription = "Say it",
                                 tint = if (rec != null) Red else Accent0)
                        }
                        Text(when { busy -> "Writing it down…"; rec != null -> "Listening… tap to finish (5 min max)"; else -> "Or say it out loud" },
                             color = if (rec != null) Red else Text2, fontSize = 13.sp)
                    }
                }
                if (error.isNotBlank()) Text(error, color = Amber, fontSize = 13.sp)
            }
        },
        confirmButton = {
            TextButton(enabled = text.isNotBlank() && recorder == null && !busy, onClick = {
                val months = when (kind) { "Letter · 3 mo" -> 3; "Letter · 6 mo" -> 6; else -> 0 }
                scope.launch { Us.writePage(context, text.trim(), mood, private, months) }
                onDone()
            }) { Text(if (kind == "Page") "Save page" else "Seal it", color = Accent0, fontWeight = FontWeight.SemiBold) }
        },
        dismissButton = { TextButton(enabled = recorder == null && !busy, onClick = onDone) { Text("Cancel", color = Text2) } },
    )
}
