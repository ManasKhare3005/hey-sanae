package com.manaskhare.sanae.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.Star
import androidx.compose.material.icons.filled.StarBorder
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableLongStateOf
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
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import org.json.JSONObject

/** The kitchen: the recipe you're cooking (if one is on), this week's dinners, then our recipe box. */
@Composable
internal fun KitchenPage(c: JSONObject?, meals: JSONObject?, name: String) {
    Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
        CookingCard(c, name)
        MealsCard(meals, name)
        RecipeBoxCard(c, name)
    }
}

/** The week's dinners: plan them, swap one, and send what's missing to the grocery list. */
@Composable
internal fun MealsCard(m: JSONObject?, name: String) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    val days = m?.optJSONArray("days")?.objects().orEmpty().filter { !it.optBoolean("past") }
    val missing = m?.optJSONArray("missing")?.let { a -> (0 until a.length()).map { a.optString(it) } }.orEmpty()
    var busy by remember { mutableStateOf(false) }
    var offline by remember { mutableStateOf(false) }
    fun laptop(block: suspend () -> Boolean) = scope.launch { busy = true; offline = !block(); busy = false }
    Card {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Label("Dinners this week", modifier = Modifier.weight(1f))
            GhostButton(if (busy) "Planning…" else if (days.isEmpty()) "Plan 5" else "Replan", color = Peach) {
                if (!busy) laptop { Us.planMeals(context, 5) }
            }
        }
        if (days.isEmpty()) Text("$name picks dinners from your recipe box plus a few new ones, then puts what you're " +
                                 "missing on the grocery list.", color = Text2, fontSize = 13.sp, modifier = Modifier.padding(top = 6.dp))
        days.forEach { d ->
            val id = d.optInt("id")
            Row(Modifier.fillMaxWidth().padding(top = 8.dp), verticalAlignment = Alignment.CenterVertically) {
                Text(d.str("label").replaceFirstChar { it.uppercase() }, color = if (d.str("label") == "tonight") Accent0 else Dim,
                     fontSize = 13.sp, modifier = Modifier.width(78.dp))
                Column(Modifier.weight(1f)) {
                    Text(d.str("title"), color = if (d.optBoolean("cooked")) Dim else Text1, fontSize = 15.sp)
                    if (d.optBoolean("from_box") || d.optBoolean("cooked"))
                        Text(if (d.optBoolean("cooked")) "made it ✓" else "from our recipe box", color = Dim, fontSize = 11.sp)
                }
                if (!d.optBoolean("cooked")) GhostButton("Swap", color = Text2) { if (!busy) laptop { Us.swapMeal(context, id) } }
            }
        }
        if (missing.isNotEmpty()) {
            Text("Still need: " + missing.joinToString(", "), color = Text2, fontSize = 13.sp, modifier = Modifier.padding(top = 10.dp))
            GhostButton("Add to groceries", Modifier.padding(top = 4.dp), color = Mint) { scope.launch { Us.mealGroceries(context) } }
        }
        if (offline) Text("Can't reach the laptop right now.", color = Red, fontSize = 12.sp, modifier = Modifier.padding(top = 6.dp))
    }
}

/** Dishes cooked together, favourites first: tap the stars, cook it again, or take it out. */
@Composable
internal fun RecipeBoxCard(c: JSONObject?, name: String) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    val recipes = c?.optJSONArray("recipes")?.objects().orEmpty()
    var offline by remember { mutableStateOf(false) }
    Card {
        Label("Our recipe box")
        if (recipes.isEmpty()) Text("Cook something with $name (\"let's cook fried rice\", or send a photo of your fridge) " +
                                    "and it lands here when you finish. \"Make that again\" cooks it the same way. A photo of a " +
                                    "restaurant dish + \"can we make this at home?\" gets you her home version.",
                                    color = Text2, fontSize = 13.sp, modifier = Modifier.padding(top = 6.dp))
        recipes.forEach { r ->
            val id = r.optInt("id")
            Column(Modifier.fillMaxWidth().padding(top = 12.dp)) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Column(Modifier.weight(1f)) {
                        Text(r.str("title"), color = Text1, fontSize = 16.sp)
                        if (r.str("source").isNotBlank()) Text("📷 " + r.str("source").replaceFirstChar { it.uppercase() }, color = Dim, fontSize = 12.sp)
                    }
                    Box(Modifier.size(36.dp).clip(RoundedCornerShape(18.dp)).clickable { scope.launch { Us.removeRecipe(context, id) } },
                        contentAlignment = Alignment.Center) {
                        Icon(Icons.Filled.Close, contentDescription = "Take it out", tint = Dim, modifier = Modifier.size(16.dp))
                    }
                }
                Row(verticalAlignment = Alignment.CenterVertically) {
                    (1..5).forEach { n ->
                        Icon(if (n <= r.optInt("stars")) Icons.Filled.Star else Icons.Filled.StarBorder,
                             contentDescription = "$n stars", tint = Butter,
                             modifier = Modifier.size(30.dp).clickable { scope.launch { Us.rateRecipe(context, id, n) } }.padding(3.dp))
                    }
                    val times = r.optInt("cooked")
                    Text(when { times > 1 -> "made $times×"; times == 1 -> "made once"; else -> "not made yet" }, color = Dim, fontSize = 12.sp,
                         modifier = Modifier.padding(start = 8.dp).weight(1f))
                    GhostButton("Cook again", color = Peach) { scope.launch { offline = !Us.cookRecipe(context, id) } }
                }
            }
        }
        if (offline) Text("Can't reach the laptop right now.", color = Red, fontSize = 12.sp, modifier = Modifier.padding(top = 6.dp))
    }
}

/** Cooking together, while a recipe is on: the step you're on big, the rest small, Back / Next. */
@Composable
internal fun CookingCard(c: JSONObject?, name: String, now: () -> Long = { System.currentTimeMillis() }) {
    val s = c?.optJSONObject("session") ?: return
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    val steps = s.optJSONArray("steps")?.objects().orEmpty()
    val i = s.optInt("i", -1)
    var showIngredients by remember(i < 0) { mutableStateOf(i < 0) }
    var offline by remember { mutableStateOf(false) }
    fun act(a: String) = scope.launch { offline = !Us.cooking(context, a) }
    Card {
        Label("Cooking with $name", color = Accent0)
        Text(s.str("title"), style = DisplayStyle, color = Text1, fontSize = 28.sp, lineHeight = 32.sp)
        val until = s.optDouble("timer_until", 0.0)
        if (until > 0) TimerLine((until * 1000).toLong(), now)
        if (i >= 0 && i < steps.size) {
            Text("Step ${i + 1} of ${steps.size}", color = Dim, fontSize = 12.sp, modifier = Modifier.padding(top = 10.dp))
            Text(steps[i].str("text"), color = Text1, fontSize = 20.sp, lineHeight = 27.sp, modifier = Modifier.padding(top = 2.dp))
        } else {
            Text("Say “next” or tap Next when you're ready for step one.", color = Text2, fontSize = 14.sp, modifier = Modifier.padding(top = 8.dp))
        }
        GhostButton(if (showIngredients) "Hide ingredients" else "Ingredients", Modifier.padding(top = 8.dp)) { showIngredients = !showIngredients }
        if (showIngredients) s.optJSONArray("ingredients")?.let { a ->
            Column(Modifier.padding(top = 6.dp)) { (0 until a.length()).forEach { Text("• " + a.optString(it), color = Text2, fontSize = 14.sp) } }
        }
        if (steps.isNotEmpty()) Column(Modifier.padding(top = 10.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
            steps.forEachIndexed { k, st ->
                val mine = k == i
                Row(Modifier.fillMaxWidth().clip(RoundedCornerShape(8.dp))
                        .background(if (mine) Accent0.copy(alpha = 0.12f) else Panel.copy(alpha = 0f)).padding(6.dp)) {
                    Text("${k + 1}", color = if (mine) Accent0 else Dim, fontSize = 13.sp, modifier = Modifier.width(22.dp))
                    Text(st.str("text"), color = if (k < i) Dim else Text2, fontSize = 13.sp)
                }
            }
        }
        Row(Modifier.padding(top = 12.dp), verticalAlignment = Alignment.CenterVertically) {
            GhostButton("Back") { act("back") }
            Spacer(Modifier.width(8.dp))
            GhostButton(if (i >= steps.size - 1 && i >= 0) "Done" else "Next") { act("next") }
            Spacer(Modifier.weight(1f))
            GhostButton("Stop") { act("stop") }
        }
        if (offline) Text("Can't reach the laptop right now.", color = Red, fontSize = 12.sp, modifier = Modifier.padding(top = 6.dp))
    }
}

@Composable
private fun TimerLine(untilMs: Long, now: () -> Long) {
    var t by remember { mutableLongStateOf(now()) }
    LaunchedEffect(untilMs) { while (t < untilMs) { delay(1000); t = now() } }
    val left = ((untilMs - t) / 1000).coerceAtLeast(0)
    Text(if (left > 0) "⏲ %d:%02d left".format(left / 60, left % 60) else "⏲ Time's up!", color = Accent0, fontSize = 15.sp,
         modifier = Modifier.padding(top = 6.dp))
}
