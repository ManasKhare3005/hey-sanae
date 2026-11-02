package com.manaskhare.sanae.ui

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.manaskhare.sanae.objects
import com.manaskhare.sanae.str
import org.json.JSONObject

/** The little things you gave her when she asked: a song, the sky, what to draw, a good thing, a word. */
@Composable
internal fun GiftsCard(a: JSONObject?, name: String) {
    val gifts = a?.optJSONArray("gifts")?.objects().orEmpty()
    val waiting = a?.str("waiting").orEmpty().takeIf { it.isNotBlank() && it != "null" }
    if (gifts.isEmpty() && waiting == null) return
    Card {
        Label("From you to $name")
        if (waiting != null) Text(when (waiting) {
            "sky" -> "She asked for a photo of your sky. Send her one?"
            "song" -> "She asked you to pick her a song."
            "draw" -> "She asked what she should draw next."
            "good" -> "She asked for one good thing from your day."
            else -> "She asked you to teach her a word."
        }, color = Accent0, fontSize = 13.sp, modifier = Modifier.padding(top = 4.dp))
        gifts.take(8).forEach { g ->
            Row(Modifier.fillMaxWidth().padding(top = 8.dp), verticalAlignment = Alignment.CenterVertically) {
                Text(when (g.str("kind")) { "sky" -> "☁"; "song" -> "♪"; "draw" -> "✎"; "good" -> "☀"; else -> "Aa" },
                     color = Accent0, fontSize = 16.sp, modifier = Modifier.width(28.dp))
                Column(Modifier.weight(1f)) {
                    Text(g.str("text"), color = Text1, fontSize = 14.sp, maxLines = 2)
                    Text(g.str("day"), color = Dim, fontSize = 11.sp)
                }
                g.optJSONObject("drawing")?.let { Sketch(it, Modifier.size(40.dp)) }
            }
        }
    }
}
