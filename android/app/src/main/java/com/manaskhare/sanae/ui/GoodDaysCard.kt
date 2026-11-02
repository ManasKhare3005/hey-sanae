package com.manaskhare.sanae.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.manaskhare.sanae.objects
import com.manaskhare.sanae.str
import org.json.JSONObject

/** What makes your good days: patterns she found between how your days felt and what you did,
 *  each with the real counts (good days with it vs without). */
@Composable
internal fun GoodDaysCard(g: JSONObject?, name: String) {
    val patterns = g?.optJSONArray("patterns")?.objects().orEmpty()
    val days = g?.optInt("days") ?: 0
    Card {
        Label("What makes your good days", color = Butter)
        if (patterns.isEmpty()) {
            Text(if (days < (g?.optInt("need", 8) ?: 8))
                     "$name needs a few more weeks of your days (how they felt, from your chats) to see a pattern. $days so far."
                 else "No clear pattern yet across $days days. $name keeps looking.",
                 color = Text2, fontSize = 13.sp, modifier = Modifier.padding(top = 6.dp))
            return@Card
        }
        Text("From $days days: ${g?.optInt("good")} good, ${g?.optInt("rough")} rough.", color = Dim, fontSize = 12.sp,
             modifier = Modifier.padding(top = 2.dp))
        patterns.forEach { p ->
            val better = p.optBoolean("better")
            Column(Modifier.padding(top = 14.dp)) {
                Text((if (better) "☀  " else "☁  ") + p.str("label"), color = if (better) Butter else Lavender,
                     fontSize = 16.sp, fontWeight = FontWeight.Bold)
                Text(p.str("text"), color = Text2, fontSize = 13.sp, lineHeight = 18.sp, modifier = Modifier.padding(top = 2.dp))
                val with = p.optJSONObject("with") ?: JSONObject()
                val without = p.optJSONObject("without") ?: JSONObject()
                val key = p.str("metric").ifBlank { "good" }
                Bar("With", with.optInt(key), with.optInt("days"), if (better) Mint else Peach)
                Bar("Without", without.optInt(key), without.optInt("days"), Dim)
            }
        }
    }
}

@Composable
private fun Bar(label: String, n: Int, of: Int, color: Color) {
    val f = if (of > 0) n.toFloat() / of else 0f
    Row(Modifier.padding(top = 6.dp), verticalAlignment = Alignment.CenterVertically) {
        Text(label, color = Dim, fontSize = 11.sp, modifier = Modifier.width(56.dp))
        Box(Modifier.weight(1f).height(8.dp).clip(RoundedCornerShape(4.dp)).background(Color.White.copy(alpha = 0.07f))) {
            Box(Modifier.fillMaxWidth(f.coerceIn(0.02f, 1f)).height(8.dp).clip(RoundedCornerShape(4.dp)).background(color))
        }
        Text("$n/$of", color = Dim, fontSize = 11.sp, modifier = Modifier.padding(start = 8.dp))
    }
}
