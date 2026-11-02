package com.manaskhare.sanae.ui

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Close
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.manaskhare.sanae.MainViewModel
import com.manaskhare.sanae.Persona
import com.manaskhare.sanae.objects
import com.manaskhare.sanae.str
import org.json.JSONObject

/** Her brain (cloudbrain.py on the laptop): what Claude taught her, what she's working toward this
 *  week, and every call exactly as it left the laptop. Lessons can be deleted. */
@Composable
internal fun BrainScreen(vm: MainViewModel, onBack: () -> Unit) {
    val name = Persona.name(LocalContext.current)
    var data by remember { mutableStateOf<JSONObject?>(null) }
    var open by remember { mutableStateOf(-1) }
    fun load() = vm.call({ JSONObject(it.raw("GET", "/api/brain")) }) { data = it }
    LaunchedEffect(Unit) { load() }
    LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(start = 16.dp, end = 16.dp, bottom = 24.dp),
               verticalArrangement = Arrangement.spacedBy(14.dp)) {
        item { PageHead("Her brain", onBack) }
        item { BrainContent(data, name, open, onOpen = { open = if (open == it) -1 else it }) { id ->
            vm.call({ it.raw("DELETE", "/api/brain/lessons/$id") }) { load() }
        } }
    }
}

@Composable
internal fun BrainContent(data: JSONObject?, name: String, open: Int = -1, onOpen: (Int) -> Unit = {}, onForget: (Int) -> Unit = {}) {
    Column(verticalArrangement = Arrangement.spacedBy(14.dp)) {
        val b = data?.optJSONObject("brain")
        Card {
            Label("Claude, for the slow thinking", color = Lavender)
            Text(when {
                data == null -> "Loading…"
                b?.optBoolean("enabled") != true -> "Off. Everything stays on the laptop (config.yaml → brain)."
                b.optBoolean("available") -> "On · ${b.optInt("calls_today")} of ${b.optInt("daily_calls")} calls today" +
                                             (b.str("error").let { if (it.isNotBlank()) " · last error: $it" else "" })
                else -> "On, but Claude Code isn't set up on the laptop"
            }, color = Text1, fontSize = 14.sp, modifier = Modifier.padding(top = 6.dp))
            Text("Live chat stays on the laptop's own model. Claude only looks back at your day, sets $name's aims for " +
                 "the week and checks lines before she speaks first. Hard moments, private notebook pages, health and " +
                 "sensitive topics never leave; names are swapped.", color = Text2, fontSize = 12.5.sp,
                 modifier = Modifier.padding(top = 6.dp))
        }
        val aims = data?.optJSONObject("aims")?.optJSONArray("aims")?.objects().orEmpty()
        Card {
            Label("This week she's trying to", color = Mint)
            if (aims.isEmpty()) Text("Decided every Monday, from the week before.", color = Text2, fontSize = 13.sp,
                                     modifier = Modifier.padding(top = 6.dp))
            aims.forEach { a ->
                Text(a.str("aim"), color = Text1, fontSize = 15.sp, fontWeight = FontWeight.Bold, modifier = Modifier.padding(top = 10.dp))
                Text(a.str("why"), color = Text2, fontSize = 12.5.sp)
                a.optJSONArray("ways")?.let { w -> (0 until w.length()).forEach { Text("· " + w.optString(it), color = Text1, fontSize = 13.sp) } }
            }
        }
        val lessons = data?.optJSONArray("lessons")?.objects().orEmpty()
        Card {
            Label("What she's learned", color = Accent0)
            if (lessons.isEmpty()) Text("Every morning she looks back at the day before and keeps up to 3 lessons.",
                                        color = Text2, fontSize = 13.sp, modifier = Modifier.padding(top = 6.dp))
            lessons.forEach { l ->
                Row(Modifier.padding(top = 10.dp), verticalAlignment = Alignment.Top) {
                    Column(Modifier.weight(1f)) {
                        Text(l.str("text"), color = Text1, fontSize = 14.sp)
                        Text("from ${l.str("day")}" + if (l.optInt("seen") > 1) " · seen ${l.optInt("seen")} times" else "",
                             color = Dim, fontSize = 11.5.sp)
                    }
                    Icon(Icons.Filled.Close, "Forget this lesson", tint = Dim,
                         modifier = Modifier.size(20.dp).clickable { onForget(l.optInt("id")) })
                }
            }
        }
        val sent = data?.optJSONArray("sent")?.objects().orEmpty()
        Card {
            Label("What was sent to Claude", color = Butter)
            if (sent.isEmpty()) Text("Nothing yet.", color = Text2, fontSize = 13.sp, modifier = Modifier.padding(top = 6.dp))
            sent.forEachIndexed { i, s ->
                Text("${s.str("t").replace('T', ' ').take(16)} · ${s.str("task")}" + if (open == i) "  ▲" else "  ▼",
                     color = Text1, fontSize = 13.5.sp, modifier = Modifier.padding(top = 10.dp).clickable { onOpen(i) })
                if (open == i) Text(s.optJSONObject("sent")?.str("prompt").orEmpty(), color = Text2, fontSize = 11.5.sp,
                                    fontFamily = FontFamily.Monospace, modifier = Modifier.padding(top = 4.dp))
            }
        }
    }
}
