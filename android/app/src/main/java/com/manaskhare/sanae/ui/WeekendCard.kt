package com.manaskhare.sanae.ui

import androidx.compose.foundation.border
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Check
import androidx.compose.material.icons.filled.MoreVert
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
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.style.TextDecoration
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.manaskhare.sanae.Us
import com.manaskhare.sanae.objects
import com.manaskhare.sanae.str
import kotlinx.coroutines.launch
import org.json.JSONObject

/** This weekend's plans, made together: Saturday, Sunday and "sometime". Tap the circle when it happened. */
@Composable
internal fun WeekendCard(w: JSONObject?, name: String) {
    var adding by remember { mutableStateOf(false) }
    val plans = w?.optJSONArray("plans")?.objects().orEmpty()
    Card {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f)) {
                Label("This weekend")
                if (w != null) Text(w.str("label"), color = Dim, fontSize = 12.sp)
            }
            GhostButton("Add") { adding = true }
        }
        if (plans.isEmpty()) Text("Nothing planned yet. Plan it with $name: say “let's plan the weekend”, or add something here.",
                                  color = Text2, fontSize = 13.sp, modifier = Modifier.padding(top = 6.dp))
        listOf("sat" to "Saturday", "sun" to "Sunday", "" to "Sometime this weekend").forEach { (day, label) ->
            val those = plans.filter { it.str("day") == day }
            if (those.isNotEmpty()) {
                Label(label, modifier = Modifier.padding(top = 10.dp), color = Accent0)
                those.forEach { PlanRow(it) }
            }
        }
    }
    if (adding) PlanDialog { adding = false }
}

@Composable
private fun PlanRow(p: JSONObject) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    var menu by remember { mutableStateOf(false) }
    val done = p.optBoolean("done")
    val id = p.optInt("id")
    Row(Modifier.fillMaxWidth().padding(top = 4.dp), verticalAlignment = Alignment.CenterVertically) {
        Box(Modifier.size(24.dp).clip(CircleShape)
            .then(if (done) Modifier.background(Accent0) else Modifier.border(1.5.dp, Line, CircleShape))
            .clickable(enabled = id > 0) { scope.launch { Us.planDone(context, id, !done) } },
            contentAlignment = Alignment.Center) {
            if (done) Icon(Icons.Filled.Check, contentDescription = "Done", tint = Panel, modifier = Modifier.size(16.dp))
        }
        Column(Modifier.weight(1f).padding(start = 12.dp)) {
            Text(p.str("text").replaceFirstChar { it.uppercase() }, color = if (done) Text2 else Text1, fontSize = 15.sp,
                 textDecoration = if (done) TextDecoration.LineThrough else null)
            val at = p.str("at")
            if (at.isNotBlank()) Text(clock(at), color = Dim, fontSize = 12.sp)
        }
        if (id > 0) Box {
            IconButton(onClick = { menu = true }) { Icon(Icons.Filled.MoreVert, contentDescription = "More", tint = Dim) }
            DropdownMenu(expanded = menu, onDismissRequest = { menu = false }) {
                DropdownMenuItem(text = { Text("Remove") }, onClick = { menu = false; scope.launch { Us.removePlan(context, id) } })
            }
        }
    }
}

private fun clock(hm: String): String = runCatching {
    val (h, m) = hm.split(":").map { it.toInt() }
    "${if (h % 12 == 0) 12 else h % 12}${if (m > 0) ":%02d".format(m) else ""} ${if (h < 12) "AM" else "PM"}"
}.getOrDefault(hm)

@Composable
private fun PlanDialog(onDone: () -> Unit) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    var text by remember { mutableStateOf("") }
    var day by remember { mutableStateOf("Saturday") }
    var time by remember { mutableStateOf("Any time") }
    val times = mapOf("Any time" to "", "Morning" to "10:00", "Afternoon" to "14:00", "Evening" to "18:00")
    AlertDialog(
        onDismissRequest = onDone,
        containerColor = Panel,
        title = { Text("Weekend plan", color = Text1) },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                OutlinedTextField(text, { text = it }, placeholder = { Text("go hiking") },
                    colors = OutlinedTextFieldDefaults.colors(focusedTextColor = Text1, unfocusedTextColor = Text1,
                        focusedBorderColor = Accent0, unfocusedBorderColor = Line, cursorColor = Accent0))
                Segmented(listOf("Saturday", "Sunday", "Either"), day, { it }) { day = it }
                Segmented(times.keys.toList(), time, { it }) { time = it }
            }
        },
        confirmButton = {
            TextButton(enabled = text.isNotBlank(), onClick = {
                val d = when (day) { "Saturday" -> "sat"; "Sunday" -> "sun"; else -> "" }
                scope.launch { Us.addPlan(context, text.trim(), d, times[time].orEmpty()) }
                onDone()
            }) { Text("Add", color = Accent0) }
        },
        dismissButton = { TextButton(onClick = onDone) { Text("Cancel", color = Text2) } },
    )
}
