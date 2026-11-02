package com.manaskhare.sanae.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.Check
import androidx.compose.material.icons.filled.Close
import androidx.compose.material3.Icon
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.OutlinedTextFieldDefaults
import androidx.compose.material3.Text
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
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.style.TextDecoration
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.manaskhare.sanae.Us
import com.manaskhare.sanae.objects
import com.manaskhare.sanae.str
import kotlinx.coroutines.launch
import org.json.JSONObject

/**
 * The grocery list, made for the shop: what's left grouped by aisle with big tick circles, what's
 * already in the cart below, and her ideas ("you usually get coffee every 7 days") to add with a tap.
 */
@Composable
internal fun GroceryCard(g: JSONObject?, name: String) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    val items = g?.optJSONArray("items")?.objects().orEmpty()
    val open = items.filter { !it.optBoolean("done") }
    val cart = items.filter { it.optBoolean("done") }
    val sections = g?.optJSONArray("sections")?.let { a -> (0 until a.length()).map { a.optString(it) } }.orEmpty()
    val ideas = g?.optJSONArray("ideas")?.objects().orEmpty()
    val goingOff = g?.optJSONArray("going_off")?.objects().orEmpty()
    if (goingOff.isNotEmpty()) Card(Modifier.padding(bottom = 12.dp)) {
        Label("Use these soon", color = Peach)
        goingOff.forEach { f ->
            val item = f.str("item")
            val age = f.optInt("age")
            Row(Modifier.fillMaxWidth().heightIn(min = 44.dp), verticalAlignment = Alignment.CenterVertically) {
                Column(Modifier.weight(1f)) {
                    Text(item.replaceFirstChar { it.uppercase() }, color = Text1, fontSize = 15.sp)
                    Text(if (age > f.optInt("life")) "bought $age days ago, might be past it" else "bought $age days ago",
                         color = Dim, fontSize = 12.sp)
                }
                GhostButton("Used it", color = Mint) { scope.launch { Us.groceryUsed(context, item) } }
            }
        }
    }
    Card {
        Label(if (open.isEmpty()) "Grocery list" else "Grocery list · ${open.size} to get")
        GroceryAdd { text -> scope.launch { Us.addGroceries(context, text) } }
        if (items.isEmpty()) Text("Add what you need, or tell $name \"we're out of milk\". Say \"I'm going grocery shopping\" " +
                                  "and she'll read it by aisle and ask what else you might need.",
                                  color = Text2, fontSize = 13.sp, modifier = Modifier.padding(top = 8.dp))
        val bySection = open.groupBy { it.str("section").ifBlank { "Other" } }
        (sections + bySection.keys.filter { it !in sections }).forEach { section ->
            val here = bySection[section] ?: return@forEach
            Label(section, modifier = Modifier.padding(top = 14.dp), color = Accent0)
            here.forEach { GroceryRow(it) }
        }
        if (cart.isNotEmpty()) {
            Row(Modifier.fillMaxWidth().padding(top = 16.dp), verticalAlignment = Alignment.CenterVertically) {
                Label("In the cart ✓ ${cart.size}", modifier = Modifier.weight(1f), color = Mint)
                GhostButton("Clear", color = Text2) { scope.launch { Us.clearGroceries(context, "done") } }
            }
            cart.forEach { GroceryRow(it) }
        }
    }
    if (ideas.isNotEmpty()) Card(Modifier.padding(top = 12.dp)) {
        Label("$name thinks you might need")
        IdeaChips(ideas, onAdd = { scope.launch { Us.addGroceries(context, it) } },
                  onSkip = { scope.launch { Us.skipGroceryIdea(context, it) } })
    }
}

/** The add box keeps its own text, so typing only redraws the box. */
@Composable
private fun GroceryAdd(onAdd: (String) -> Unit) {
    var text by remember { mutableStateOf("") }
    val send = { if (text.isNotBlank()) { onAdd(text.trim()); text = "" } }
    Row(Modifier.fillMaxWidth().padding(top = 10.dp), verticalAlignment = Alignment.CenterVertically) {
        OutlinedTextField(
            text, { text = it }, singleLine = true, modifier = Modifier.weight(1f),
            placeholder = { Text("milk, 2 eggs, bread", color = Dim) },
            shape = RoundedCornerShape(14.dp),
            keyboardOptions = KeyboardOptions(imeAction = ImeAction.Done), keyboardActions = KeyboardActions(onDone = { send() }),
            colors = OutlinedTextFieldDefaults.colors(focusedTextColor = Text1, unfocusedTextColor = Text1,
                focusedBorderColor = Accent0, unfocusedBorderColor = Line, cursorColor = Accent0),
        )
        Box(Modifier.padding(start = 8.dp).size(48.dp).clip(CircleShape).background(Accent0.copy(alpha = 0.18f))
                .clickable { send() }, contentAlignment = Alignment.Center) {
            Icon(Icons.Filled.Add, contentDescription = "Add", tint = Accent0)
        }
    }
}

@Composable
private fun GroceryRow(item: JSONObject) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    val id = item.optInt("id")
    val done = item.optBoolean("done")
    Row(Modifier.fillMaxWidth().heightIn(min = 48.dp).clickable(enabled = id > 0) { scope.launch { Us.groceryDone(context, id, !done) } },
        verticalAlignment = Alignment.CenterVertically) {
        Box(Modifier.size(28.dp).clip(CircleShape)
            .then(if (done) Modifier.background(Mint) else Modifier.border(1.5.dp, Line, CircleShape)),
            contentAlignment = Alignment.Center) {
            if (done) Icon(Icons.Filled.Check, contentDescription = "In the cart", tint = Panel, modifier = Modifier.size(18.dp))
        }
        Text(item.str("item").replaceFirstChar { it.uppercase() }, color = if (done) Dim else Text1, fontSize = 16.sp,
             textDecoration = if (done) TextDecoration.LineThrough else null,
             modifier = Modifier.weight(1f).padding(start = 14.dp))
        if (item.str("qty").isNotBlank()) Text(item.str("qty"), color = Text2, fontSize = 14.sp, modifier = Modifier.padding(end = 4.dp))
        if (id > 0) Box(Modifier.size(40.dp).clip(CircleShape).clickable { scope.launch { Us.removeGrocery(context, id) } },
                        contentAlignment = Alignment.Center) {
            Icon(Icons.Filled.Close, contentDescription = "Remove", tint = Dim, modifier = Modifier.size(18.dp))
        }
    }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun IdeaChips(ideas: List<JSONObject>, onAdd: (String) -> Unit, onSkip: (String) -> Unit) {
    FlowRow(Modifier.padding(top = 10.dp), horizontalArrangement = Arrangement.spacedBy(8.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp)) {
        ideas.forEach { idea ->
            val item = idea.str("item")
            Row(Modifier.clip(RoundedCornerShape(16.dp)).background(Butter.copy(alpha = 0.12f))
                    .border(1.dp, Butter.copy(alpha = 0.35f), RoundedCornerShape(16.dp)),
                verticalAlignment = Alignment.CenterVertically) {
                Column(Modifier.clickable { onAdd(item) }.padding(start = 12.dp, top = 6.dp, bottom = 6.dp, end = 4.dp)) {
                    Text("+ $item", color = Text1, fontSize = 14.sp)
                    Text(idea.str("why"), color = Dim, fontSize = 11.sp)
                }
                Box(Modifier.size(36.dp).clickable { onSkip(item) }, contentAlignment = Alignment.Center) {
                    Icon(Icons.Filled.Close, contentDescription = "Don't need it", tint = Dim, modifier = Modifier.size(14.dp))
                }
            }
        }
    }
}
