package com.manaskhare.sanae.ui

import android.content.Intent
import android.net.Uri
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Close
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.manaskhare.sanae.Us
import com.manaskhare.sanae.objects
import com.manaskhare.sanae.str
import kotlinx.coroutines.launch
import org.json.JSONObject

/**
 * Songs that became "ours" (on repeat for days, or added by hand), each with why. Links open in
 * whichever app handles youtube.com (YouTube, or YouTube ReVanced once it's set to open those links).
 */
@Composable
internal fun PlaylistCard(p: JSONObject?, name: String) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    val songs = p?.optJSONArray("songs")?.objects().orEmpty()
    val playAll = p?.str("play_url").orEmpty().takeIf { it.isNotBlank() && it != "null" }
    fun open(url: String) = runCatching {
        context.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(url)).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
    }
    Card {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Label(if (songs.isEmpty()) "Our playlist" else "Our playlist · ${songs.size}", modifier = Modifier.weight(1f))
            if (playAll != null) GhostButton("▶ Play all", color = Lavender) { open(playAll) }
        }
        p?.optJSONObject("week_song")?.let { w ->
            Column(Modifier.padding(top = 10.dp).fillMaxWidth().clip(RoundedCornerShape(16.dp))
                       .background(Lavender.copy(alpha = 0.12f)).clickable { open(w.str("url")) }.padding(12.dp)) {
                Text("Song of the week", color = Lavender, fontSize = 12.sp)
                Text("▶ " + w.str("title") + if (w.str("artist").isNotBlank()) " · ${w.str("artist")}" else "",
                     style = DisplayStyle, color = Text1, fontSize = 20.sp, maxLines = 1, overflow = TextOverflow.Ellipsis)
                Text("$name picked it because ${w.str("why")}.", color = Text2, fontSize = 13.sp)
            }
        }
        if (songs.isEmpty()) Text("A song you keep playing (3 different days) ends up here on its own, or tell $name " +
                                  "\"add this song to our playlist\" while it plays. YouTube / ReVanced, Spotify and " +
                                  "YouTube Music all count.", color = Text2, fontSize = 13.sp, modifier = Modifier.padding(top = 6.dp))
        songs.forEach { s ->
            Row(Modifier.fillMaxWidth().heightIn(min = 52.dp).clickable { open(s.str("url")) }.padding(top = 6.dp),
                verticalAlignment = Alignment.CenterVertically) {
                Text("♪", color = Lavender, fontSize = 18.sp, modifier = Modifier.padding(end = 12.dp))
                Column(Modifier.weight(1f)) {
                    Text(s.str("title") + if (s.str("artist").isNotBlank()) " · ${s.str("artist")}" else "",
                         color = Text1, fontSize = 15.sp, maxLines = 1, overflow = TextOverflow.Ellipsis)
                    Text(s.str("why"), color = Dim, fontSize = 12.sp)
                }
                Box(Modifier.size(40.dp).clip(CircleShape).clickable { scope.launch { Us.removeSong(context, s.optInt("id")) } },
                    contentAlignment = Alignment.Center) {
                    Icon(Icons.Filled.Close, contentDescription = "Take it off", tint = Dim, modifier = Modifier.size(16.dp))
                }
            }
        }
        Text("Tip: to open these in YouTube ReVanced, go to Android Settings → Apps → YouTube ReVanced → Open by default, " +
             "and turn on its youtube.com links.", color = Dim, fontSize = 11.sp, modifier = Modifier.padding(top = 10.dp))
    }
}
