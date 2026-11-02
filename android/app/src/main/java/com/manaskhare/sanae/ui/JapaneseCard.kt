package com.manaskhare.sanae.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.window.Dialog
import com.manaskhare.sanae.Us
import com.manaskhare.sanae.objects
import com.manaskhare.sanae.str
import kotlinx.coroutines.launch
import org.json.JSONObject

/** Learning Japanese together: her word of the day, your deck, and flashcards that work offline. */
@Composable
internal fun JapaneseCard(j: JSONObject?, name: String) {
    if (j == null) return
    val deck = j.optJSONArray("deck")?.objects().orEmpty()
    val her = j.optJSONObject("her_word")
    var practising by remember { mutableStateOf<List<JSONObject>?>(null) }
    Card {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Label("Japanese together", modifier = Modifier.weight(1f))
            val due = deck.filter { it.optBoolean("due") }
            if (deck.isNotEmpty()) GhostButton(if (due.isNotEmpty()) "Practise (${due.size})" else "Practise") {
                practising = (due.ifEmpty { deck }).shuffled().take(10)
            }
        }
        if (her != null) Row(Modifier.padding(top = 8.dp), verticalAlignment = Alignment.Bottom) {
            Text(her.str("word"), style = DisplayStyle, color = Text1, fontSize = 30.sp)
            Text("  ${her.str("meaning")} · $name's word today", color = Text2, fontSize = 13.sp, modifier = Modifier.padding(bottom = 5.dp))
        }
        val bits = mutableListOf("${deck.size} word${if (deck.size != 1) "s" else ""} in your deck")
        if (j.optInt("streak") > 1) bits += "${j.optInt("streak")} days in a row"
        if (j.optInt("corrections") > 0) bits += "you've corrected $name ${j.optInt("corrections")}×"
        Text(bits.joinToString(" · "), color = Dim, fontSize = 12.sp, modifier = Modifier.padding(top = 4.dp))
        if (deck.isEmpty()) Text("Say “teach me some Japanese” and she'll share her words with you.", color = Text2,
                                 fontSize = 13.sp, modifier = Modifier.padding(top = 6.dp))
    }
    practising?.let { cards -> Flashcards(cards) { practising = null } }
}

@Composable
private fun Flashcards(cards: List<JSONObject>, onDone: () -> Unit) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    var i by remember { mutableIntStateOf(0) }
    var shown by remember { mutableStateOf(false) }
    val results = remember { mutableStateListOf<Pair<String, Boolean>>() }
    fun finish() {
        if (results.isNotEmpty()) scope.launch { Us.reviewJapanese(context, results.toList()) }
        onDone()
    }
    Dialog(onDismissRequest = { finish() }) {
        Column(Modifier.clip(RoundedCornerShape(16.dp)).background(Panel).padding(20.dp), horizontalAlignment = Alignment.CenterHorizontally) {
            if (i >= cards.size) {
                Text("${results.count { it.second }} of ${results.size}", style = DisplayStyle, color = Text1, fontSize = 40.sp)
                Text("Nice. She'll quiz you on the misses.", color = Text2, modifier = Modifier.padding(top = 6.dp))
                Spacer(Modifier.height(14.dp))
                GhostButton("Done") { finish() }
                return@Column
            }
            val c = cards[i]
            Text("${i + 1} / ${cards.size}", color = Dim, fontSize = 12.sp)
            Box(Modifier.fillMaxWidth().height(170.dp).padding(top = 8.dp).clip(RoundedCornerShape(12.dp))
                    .background(Accent0.copy(alpha = 0.08f)).clickable { shown = true }, contentAlignment = Alignment.Center) {
                Column(horizontalAlignment = Alignment.CenterHorizontally) {
                    Text(c.str("word"), style = DisplayStyle, color = Text1, fontSize = 40.sp)
                    Text(if (shown) c.str("meaning") else "tap to see", color = if (shown) Accent0 else Dim,
                         fontSize = if (shown) 20.sp else 13.sp, textAlign = TextAlign.Center)
                }
            }
            Row(Modifier.padding(top = 14.dp), horizontalArrangement = Arrangement.Center) {
                GhostButton("Missed it", color = Red) { results += c.str("word") to false; i++; shown = false }
                Spacer(Modifier.width(12.dp))
                GhostButton("Got it") { results += c.str("word") to true; i++; shown = false }
            }
        }
    }
}
