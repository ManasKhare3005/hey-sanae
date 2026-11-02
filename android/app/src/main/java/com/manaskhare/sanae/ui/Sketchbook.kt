package com.manaskhare.sanae.ui

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.StrokeJoin
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.window.Dialog
import com.manaskhare.sanae.objects
import com.manaskhare.sanae.str
import org.json.JSONObject

val Paper = Color(0xFFF8F1E3)
val Ink = Color(0xFF2B2A3A)

/** One of her sketches: pen strokes from the laptop ({size, strokes: [[x, y, x, y...]...]}) on paper. */
@Composable
fun Sketch(d: JSONObject, modifier: Modifier = Modifier) {
    val strokes = remember(d) {
        val size = d.optDouble("size", 200.0).toFloat()
        val all = d.optJSONArray("strokes") ?: return@remember emptyList<FloatArray>()
        (0 until all.length()).mapNotNull { i ->
            val s = all.optJSONArray(i) ?: return@mapNotNull null
            FloatArray(s.length()) { k -> s.optDouble(k).toFloat() / size }
        }
    }
    Canvas(modifier.clip(RoundedCornerShape(6.dp)).background(Paper)) {
        val pad = this.size.minDimension * 0.06f
        val side = this.size.minDimension - 2 * pad
        val ox = (this.size.width - side) / 2
        val oy = (this.size.height - side) / 2
        val pen = Stroke(width = (side / 200f) * 1.8f, cap = StrokeCap.Round, join = StrokeJoin.Round)
        strokes.forEach { s ->
            if (s.size < 4) return@forEach
            val path = Path()
            path.moveTo(ox + s[0] * side, oy + s[1] * side)
            var k = 2
            while (k + 1 < s.size) { path.lineTo(ox + s[k] * side, oy + s[k + 1] * side); k += 2 }
            drawPath(path, Ink, style = pen)
        }
    }
}

/** Her sketchbook: what she drew lately, newest first; tap one to see it big. */
@Composable
internal fun SketchbookCard(s: JSONObject?, name: String) {
    val drawings = s?.optJSONArray("drawings")?.objects().orEmpty()
    if (drawings.isEmpty()) return
    var open by remember { mutableStateOf<JSONObject?>(null) }
    Card {
        Label("$name's sketchbook")
        val learning = s?.str("learning").orEmpty()
        if (learning.isNotBlank()) Text("Practising: ${learning.substringBefore(" (")}", color = Dim, fontSize = 12.sp)
        LazyRow(Modifier.padding(top = 10.dp), horizontalArrangement = Arrangement.spacedBy(10.dp)) {
            items(drawings) { d ->
                Column(Modifier.width(120.dp).clickable { open = d }) {
                    Sketch(d, Modifier.size(120.dp))
                    Text(d.str("title"), color = Text2, fontSize = 13.sp, fontFamily = FontFamily.Cursive,
                         modifier = Modifier.padding(top = 4.dp), maxLines = 2)
                }
            }
        }
    }
    open?.let { d ->
        Dialog(onDismissRequest = { open = null }) {
            Column(Modifier.clip(RoundedCornerShape(12.dp)).background(Paper).padding(16.dp).clickable { open = null }) {
                Sketch(d, Modifier.fillMaxWidth().aspectRatio(1f))
                Text(d.str("caption"), color = Ink, fontSize = 20.sp, lineHeight = 26.sp, fontFamily = FontFamily.Cursive,
                     textAlign = TextAlign.Center, modifier = Modifier.fillMaxWidth().padding(top = 8.dp))
                Text("— $name", color = Ink.copy(alpha = 0.6f), fontSize = 14.sp, fontFamily = FontFamily.Cursive,
                     textAlign = TextAlign.End, modifier = Modifier.fillMaxWidth())
            }
        }
    }
}
