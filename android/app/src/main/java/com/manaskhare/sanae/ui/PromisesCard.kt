package com.manaskhare.sanae.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
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
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.manaskhare.sanae.Us
import com.manaskhare.sanae.objects
import com.manaskhare.sanae.str
import kotlinx.coroutines.launch
import org.json.JSONObject
import java.time.LocalDateTime
import java.time.format.DateTimeFormatter

/** Pinky promises, both ways: the open ones, and how many each of you kept. */
@Composable
internal fun PromisesCard(p: JSONObject?, name: String) {
    var adding by remember { mutableStateOf(false) }
    val open = p?.optJSONArray("open")?.objects().orEmpty()
    val kept = p?.optJSONObject("kept")
    Card {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Label("Pinky promises", modifier = Modifier.weight(1f))
            GhostButton("Promise") { adding = true }
        }
        if (open.isEmpty()) Text("No open promises. Make one with $name, or say “I promise I'll…” when you talk.",
                                 color = Text2, fontSize = 13.sp, modifier = Modifier.padding(top = 6.dp))
        val yours = open.filter { it.str("who") == "you" }
        val hers = open.filter { it.str("who") == "her" }
        if (yours.isNotEmpty()) Label("You promised", modifier = Modifier.padding(top = 10.dp), color = Accent0)
        yours.forEach { PromiseRow(it, name) }
        if (hers.isNotEmpty()) Label("$name promised", modifier = Modifier.padding(top = 10.dp), color = Accent0)
        hers.forEach { PromiseRow(it, name) }
        if (kept != null && kept.length() > 0) {
            Text("Kept so far: you ${kept.optInt("you")} · $name ${kept.optInt("her")}", color = Dim, fontSize = 12.sp,
                 modifier = Modifier.padding(top = 10.dp))
        }
    }
    if (adding) PromiseDialog(name) { adding = false }
}

@Composable
private fun PromiseRow(p: JSONObject, name: String) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    var menu by remember { mutableStateOf(false) }
    Row(Modifier.fillMaxWidth().padding(top = 4.dp), verticalAlignment = Alignment.CenterVertically) {
        Text("🤙", fontSize = 16.sp)
        Column(Modifier.weight(1f).padding(start = 10.dp)) {
            Text(p.str("text"), color = Text1, fontSize = 15.sp)
            val due = p.str("due")
            if (due.isNotBlank()) Text("by " + runCatching { LocalDateTime.parse(due).format(DateTimeFormatter.ofPattern("EEE h:mm a")) }.getOrDefault(due),
                                       color = Dim, fontSize = 12.sp)
        }
        if (p.optInt("id") > 0) Box {
            IconButton(onClick = { menu = true }) { Icon(Icons.Filled.MoreVert, contentDescription = "Settle", tint = Dim) }
            DropdownMenu(expanded = menu, onDismissRequest = { menu = false }) {
                val who = if (p.str("who") == "you") "I" else name
                listOf("kept" to "$who kept it", "broken" to "$who broke it", "dropped" to "Never mind").forEach { (status, label) ->
                    DropdownMenuItem(text = { Text(label) }, onClick = {
                        menu = false; scope.launch { Us.settlePromise(context, p.optInt("id"), status) }
                    })
                }
            }
        }
    }
}

@Composable
private fun PromiseDialog(name: String, onDone: () -> Unit) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    var who by remember { mutableStateOf("I promise") }
    var text by remember { mutableStateOf("") }
    var due by remember { mutableStateOf("No deadline") }
    AlertDialog(
        onDismissRequest = onDone,
        containerColor = Panel,
        title = { Text("Pinky promise", color = Text1) },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                Segmented(listOf("I promise", "$name promises"), who, { it }) { who = it }
                OutlinedTextField(text, { text = it }, placeholder = { Text(if (who == "I promise") "to sleep before 1" else "to remind me about the gym tomorrow") },
                    colors = OutlinedTextFieldDefaults.colors(focusedTextColor = Text1, unfocusedTextColor = Text1,
                        focusedBorderColor = Accent0, unfocusedBorderColor = Line, cursorColor = Accent0))
                Segmented(listOf("No deadline", "Tonight", "Tomorrow", "This week"), due, { it }) { due = it }
            }
        },
        confirmButton = {
            TextButton(enabled = text.isNotBlank(), onClick = {
                val words = if (due == "No deadline") "" else due.lowercase()
                scope.launch { Us.makePromise(context, if (who == "I promise") "you" else "her", text.trim(), words) }
                onDone()
            }) { Text("Pinky promise", color = Accent0) }
        },
        dismissButton = { TextButton(onClick = onDone) { Text("Cancel", color = Text2) } },
    )
}
