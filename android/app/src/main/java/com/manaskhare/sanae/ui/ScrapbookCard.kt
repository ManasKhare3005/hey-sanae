package com.manaskhare.sanae.ui

import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.rotate
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.ImageBitmap
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.window.Dialog
import com.manaskhare.sanae.Scrapbook
import com.manaskhare.sanae.Us
import com.manaskhare.sanae.objects
import com.manaskhare.sanae.str
import kotlinx.coroutines.launch
import org.json.JSONObject

/** Our scrapbook: a paper page per month, photos like polaroids with her caption (and her sketch). */
@Composable
internal fun ScrapbookCard(s: JSONObject?, name: String, image: (Int) -> ImageBitmap? = rememberScrapbookImages()) {
    val months = s?.optJSONArray("months")?.objects().orEmpty().filter { (it.optJSONArray("photos")?.length() ?: 0) > 0 }
    if (months.isEmpty()) return
    var page by remember(months.size) { mutableIntStateOf(0) }
    var open by remember { mutableStateOf<JSONObject?>(null) }
    val m = months[page.coerceIn(0, months.size - 1)]
    Card {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Label("Our scrapbook", modifier = Modifier.weight(1f))
            if (page < months.size - 1) GhostButton("‹ older") { page++ }
            if (page > 0) { Spacer(Modifier.size(6.dp)); GhostButton("newer ›") { page-- } }
        }
        Column(Modifier.padding(top = 10.dp).fillMaxWidth().clip(RoundedCornerShape(10.dp)).background(Paper).padding(12.dp)) {
            Text(m.str("label"), color = Ink, fontSize = 22.sp, fontFamily = FontFamily.Cursive)
            val photos = m.optJSONArray("photos")?.objects().orEmpty()
            photos.chunked(2).forEachIndexed { row, pair ->
                Row(Modifier.padding(top = 10.dp), horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                    pair.forEachIndexed { k, p ->
                        Polaroid(p, image(p.optInt("id")), tilt = if ((row + k) % 2 == 0) -2f else 2f,
                                 modifier = Modifier.weight(1f).clickable { open = p })
                    }
                    if (pair.size == 1) Spacer(Modifier.weight(1f))
                }
            }
        }
    }
    open?.let { p -> PhotoDialog(p, image(p.optInt("id")), name) { open = null } }
}

@Composable
fun rememberScrapbookImages(): (Int) -> ImageBitmap? {
    val context = LocalContext.current
    val version by Scrapbook.version.collectAsState()
    val cache = remember(version) { mutableMapOf<Int, ImageBitmap?>() }
    return { id -> cache.getOrPut(id) { Scrapbook.image(context, id) } }
}

@Composable
private fun Polaroid(p: JSONObject, img: ImageBitmap?, tilt: Float, modifier: Modifier = Modifier) {
    Column(modifier.rotate(tilt).background(Color.White).padding(6.dp)) {
        Box(Modifier.fillMaxWidth().aspectRatio(1f).background(Color(0xFFE8E2D6))) {
            if (img != null) Image(img, contentDescription = p.str("caption"), contentScale = ContentScale.Crop, modifier = Modifier.fillMaxWidth().aspectRatio(1f))
            p.optJSONObject("drawing")?.let { d -> Sketch(d, Modifier.align(Alignment.BottomEnd).padding(4.dp).size(40.dp)) }
        }
        Text(p.str("caption"), color = Ink, fontSize = 13.sp, lineHeight = 16.sp, fontFamily = FontFamily.Cursive,
             textAlign = TextAlign.Center, maxLines = 3, modifier = Modifier.fillMaxWidth().padding(top = 4.dp))
    }
}

@Composable
private fun PhotoDialog(p: JSONObject, img: ImageBitmap?, name: String, onDone: () -> Unit) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    var sure by remember { mutableStateOf(false) }
    Dialog(onDismissRequest = onDone) {
        Column(Modifier.clip(RoundedCornerShape(10.dp)).background(Color.White).padding(12.dp)) {
            if (img != null) Image(img, contentDescription = p.str("caption"), contentScale = ContentScale.Fit, modifier = Modifier.fillMaxWidth())
            Text(p.str("caption"), color = Ink, fontSize = 20.sp, lineHeight = 26.sp, fontFamily = FontFamily.Cursive,
                 textAlign = TextAlign.Center, modifier = Modifier.fillMaxWidth().padding(top = 8.dp))
            Text("— $name · ${p.str("day")}", color = Ink.copy(alpha = 0.6f), fontSize = 13.sp, textAlign = TextAlign.End,
                 modifier = Modifier.fillMaxWidth())
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.End) {
                TextButton(onClick = {
                    if (!sure) sure = true else { scope.launch { Us.deletePhoto(context, p.optInt("id")) }; onDone() }
                }) { Text(if (sure) "Delete for good?" else "Remove from scrapbook", color = Red) }
            }
        }
    }
}
