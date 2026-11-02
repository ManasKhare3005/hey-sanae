package com.manaskhare.sanae.ui

import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.ImageBitmap
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.manaskhare.sanae.Us
import com.manaskhare.sanae.objects
import com.manaskhare.sanae.str
import kotlinx.coroutines.launch
import org.json.JSONObject
import java.time.LocalDate

/** Photo a day: today's challenge, the streak, and this month as a grid of the photos you sent. */
@Composable
internal fun DailyPhotoCard(d: JSONObject?, name: String, image: (Int) -> ImageBitmap? = rememberScrapbookImages()) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    val today = d?.optJSONObject("today")
    val status = today?.str("status").orEmpty()
    val streak = d?.optInt("streak") ?: 0
    Card {
        Label(if (status == "done") "Today's photo ✓" else "Today's challenge", color = Peach)
        Text(today?.str("challenge").orEmpty().replaceFirstChar { it.uppercase() }, style = DisplayStyle, color = Text1,
             fontSize = 24.sp, lineHeight = 29.sp, modifier = Modifier.padding(top = 4.dp))
        Text(when (status) {
            "done" -> "Sent. It's in your scrapbook."
            "skipped" -> "Skipped today (your free skip this week)."
            "missed" -> "Skipped today."
            else -> "Go get it, then send it to $name with the camera button on Home."
        }, color = Text2, fontSize = 13.sp, modifier = Modifier.padding(top = 6.dp))
        today?.optJSONObject("hers")?.let { hers ->
            Row(Modifier.padding(top = 12.dp), horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                Column(Modifier.weight(1f)) {
                    Label("Yours")
                    val img = today.optInt("scrapbook_id").takeIf { it > 0 }?.let(image)
                    Box(Modifier.padding(top = 4.dp).fillMaxWidth().aspectRatio(1f).clip(RoundedCornerShape(6.dp)).background(Panel),
                        contentAlignment = Alignment.Center) {
                        if (img != null) Image(img, contentDescription = "Your photo", contentScale = ContentScale.Crop,
                                               modifier = Modifier.fillMaxWidth().aspectRatio(1f))
                        else Text(if (status == "done") "📷" else "Your turn!", color = Dim, fontSize = 13.sp)
                    }
                }
                Column(Modifier.weight(1f)) {
                    Label("$name's")
                    Sketch(hers, Modifier.padding(top = 4.dp).fillMaxWidth().aspectRatio(1f))
                }
            }
            Text(hers.str("caption"), color = Text2, fontSize = 15.sp, fontFamily = FontFamily.Cursive, modifier = Modifier.padding(top = 6.dp))
        }
        Row(Modifier.padding(top = 10.dp), verticalAlignment = Alignment.CenterVertically) {
            Text(if (streak > 0) "🔥 $streak day${if (streak == 1) "" else "s"}" else "Start a streak today", color = Butter, fontSize = 15.sp)
            if ((d?.optInt("best") ?: 0) > streak) Text(" · best ${d?.optInt("best")}", color = Dim, fontSize = 13.sp)
            Spacer(Modifier.weight(1f))
            if (status == "open") {
                GhostButton("Swap", color = Text2) { scope.launch { Us.dailyPhoto(context, "reroll") } }
                Spacer(Modifier.width(6.dp))
                GhostButton("Skip today", color = Text2) { scope.launch { Us.dailyPhoto(context, "skip") } }
            }
        }
    }
    val month = d?.optJSONArray("month")?.objects().orEmpty()
    if (month.isNotEmpty()) Card(Modifier.padding(top = 12.dp)) {
        Label(d?.str("month_label").orEmpty())
        MonthGrid(month, image)
    }
}

@Composable
private fun MonthGrid(month: List<JSONObject>, image: (Int) -> ImageBitmap?) {
    val byDay = month.associateBy { it.str("day") }
    val first = runCatching { LocalDate.parse(month.first().str("day")).withDayOfMonth(1) }.getOrNull() ?: return
    val lead = first.dayOfWeek.value - 1                       // Monday first
    val cells = List(lead) { null } + (1..first.lengthOfMonth()).map { first.withDayOfMonth(it) }
    Column(Modifier.padding(top = 8.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
        Row { listOf("M", "T", "W", "T", "F", "S", "S").forEach { Text(it, color = Dim, fontSize = 11.sp, modifier = Modifier.weight(1f)) } }
        cells.chunked(7).forEach { week ->
            Row(horizontalArrangement = Arrangement.spacedBy(4.dp)) {
                (0 until 7).forEach { i ->
                    val day = week.getOrNull(i)
                    Box(Modifier.weight(1f).aspectRatio(1f).clip(RoundedCornerShape(6.dp))
                            .background(if (day == null) Panel.copy(alpha = 0f) else Panel), contentAlignment = Alignment.Center) {
                        if (day != null) {
                            val row = byDay[day.toString()]
                            val img = row?.optInt("scrapbook_id")?.takeIf { it > 0 }?.let(image)
                            if (img != null) Image(img, contentDescription = row.str("challenge"), contentScale = ContentScale.Crop,
                                                   modifier = Modifier.fillMaxWidth().aspectRatio(1f))
                            else Text("${day.dayOfMonth}", fontSize = 11.sp, color = when (row?.str("status")) {
                                "done" -> Mint; "skipped" -> Butter; else -> Dim
                            })
                        }
                    }
                }
            }
        }
    }
}
