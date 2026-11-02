package com.manaskhare.sanae.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
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
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.manaskhare.sanae.Us
import com.manaskhare.sanae.objects
import com.manaskhare.sanae.str
import kotlinx.coroutines.launch
import org.json.JSONObject

/** The shared bucket list: open ones first, done ones with the day and her little sketch of it. */
@Composable
internal fun BucketCard(b: JSONObject?, name: String) {
    var adding by remember { mutableStateOf(false) }
    val items = b?.optJSONArray("items")?.objects().orEmpty()
    val open = items.filter { it.isNull("done_day") || it.str("done_day").isBlank() }
    val done = items - open.toSet()
    Card {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Label("Our bucket list", modifier = Modifier.weight(1f))
            GhostButton("Add") { adding = true }
        }
        if (items.isEmpty()) Text("Things you two want to try someday. $name will bring one up when your weekend is free.",
                                  color = Text2, fontSize = 13.sp, modifier = Modifier.padding(top = 6.dp))
        open.forEach { BucketRow(it, name) }
        if (done.isNotEmpty()) Label("Done ✓ ${done.size}", modifier = Modifier.padding(top = 12.dp), color = Accent0)
        done.forEach { BucketRow(it, name) }
    }
    if (adding) BucketDialog { adding = false }
}

@Composable
private fun BucketRow(item: JSONObject, name: String) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    var menu by remember { mutableStateOf(false) }
    val id = item.optInt("id")
    val done = !item.isNull("done_day") && item.str("done_day").isNotBlank()
    Row(Modifier.fillMaxWidth().padding(top = 6.dp), verticalAlignment = Alignment.CenterVertically) {
        Box(Modifier.size(24.dp).clip(CircleShape)
            .then(if (done) Modifier.background(Accent0) else Modifier.border(1.5.dp, Line, CircleShape))
            .clickable(enabled = id > 0) { scope.launch { Us.bucketDone(context, id, !done) } },
            contentAlignment = Alignment.Center) {
            if (done) Icon(Icons.Filled.Check, contentDescription = "Done", tint = Panel, modifier = Modifier.size(16.dp))
        }
        Column(Modifier.weight(1f).padding(start = 12.dp)) {
            Text(item.str("text").replaceFirstChar { it.uppercase() }, color = if (done) Text2 else Text1, fontSize = 15.sp)
            val bits = listOfNotNull(if (item.str("who") == "her") "♡ $name's idea" else null, if (done) "did it ${item.str("done_day")}" else null)
            if (bits.isNotEmpty()) Text(bits.joinToString(" · "), color = Dim, fontSize = 12.sp)
        }
        item.optJSONObject("drawing")?.let { Sketch(it, Modifier.size(48.dp)) }
        if (id > 0) Box {
            IconButton(onClick = { menu = true }) { Icon(Icons.Filled.MoreVert, contentDescription = "More", tint = Dim) }
            DropdownMenu(expanded = menu, onDismissRequest = { menu = false }) {
                DropdownMenuItem(text = { Text("Remove") }, onClick = { menu = false; scope.launch { Us.removeBucket(context, id) } })
            }
        }
    }
}

@Composable
private fun BucketDialog(onDone: () -> Unit) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    var text by remember { mutableStateOf("") }
    AlertDialog(
        onDismissRequest = onDone,
        containerColor = Panel,
        title = { Text("Bucket list", color = Text1) },
        text = {
            OutlinedTextField(text, { text = it }, placeholder = { Text("watch the sunrise from a hill") },
                colors = OutlinedTextFieldDefaults.colors(focusedTextColor = Text1, unfocusedTextColor = Text1,
                    focusedBorderColor = Accent0, unfocusedBorderColor = Line, cursorColor = Accent0))
        },
        confirmButton = {
            TextButton(enabled = text.isNotBlank(), onClick = { scope.launch { Us.addBucket(context, text.trim()) }; onDone() }) {
                Text("Add", color = Accent0)
            }
        },
        dismissButton = { TextButton(onClick = onDone) { Text("Cancel", color = Text2) } },
    )
}
