package com.manaskhare.sanae.ui

import androidx.activity.compose.BackHandler
import androidx.compose.animation.AnimatedContent
import androidx.compose.animation.core.tween
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.slideInHorizontally
import androidx.compose.animation.togetherWith
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.automirrored.filled.KeyboardArrowRight
import androidx.compose.material.icons.automirrored.filled.MenuBook
import androidx.compose.material.icons.filled.AutoAwesome
import androidx.compose.material.icons.filled.AutoStories
import androidx.compose.material.icons.filled.Brush
import androidx.compose.material.icons.filled.CardGiftcard
import androidx.compose.material.icons.filled.Celebration
import androidx.compose.material.icons.filled.GraphicEq
import androidx.compose.material.icons.filled.Handshake
import androidx.compose.material.icons.filled.Hiking
import androidx.compose.material.icons.filled.LiveTv
import androidx.compose.material.icons.filled.PhotoAlbum
import androidx.compose.material.icons.filled.PhotoCamera
import androidx.compose.material.icons.filled.QueueMusic
import androidx.compose.material.icons.filled.Restaurant
import androidx.compose.material.icons.filled.ShoppingCart
import androidx.compose.material.icons.filled.Spa
import androidx.compose.material.icons.filled.Translate
import androidx.compose.material.icons.filled.WbSunny
import androidx.compose.material.icons.filled.Weekend
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.text.style.TextOverflow
import com.manaskhare.sanae.MainActivity
import com.manaskhare.sanae.UsTiles
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
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
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.CornerRadius
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.drawscope.DrawScope
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.drawscope.rotate
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextDecoration
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.manaskhare.sanae.Hub
import com.manaskhare.sanae.Link
import com.manaskhare.sanae.MainViewModel
import com.manaskhare.sanae.Persona
import com.manaskhare.sanae.Us
import com.manaskhare.sanae.objects
import com.manaskhare.sanae.str
import kotlinx.coroutines.launch
import org.json.JSONObject

/**
 * "Us": the things you two share, as tiles. Up top, what's worth a look today; each tile opens
 * its own page (back returns to the tiles). A dot = she made something you haven't opened yet.
 */
@Composable
fun UsScreen(vm: MainViewModel) {
    val context = LocalContext.current
    val us by Us.state.collectAsState()
    val link by Hub.link.collectAsState()
    val emotion by vm.emotion.collectAsState()
    LaunchedEffect(Unit) { Us.load(context) }
    LaunchedEffect(link) { if (link == Link.ONLINE) Us.refresh(context) }
    val name = Persona.name(context)
    var seen by remember { mutableStateOf(UsTiles.seenFromJson(vm.prefs.usSeen)) }
    LaunchedEffect(us) {
        if (us != null) UsTiles.firstSeen(us, seen).takeIf { it != seen }?.let { seen = it; vm.prefs.usSeen = UsTiles.seenToJson(it) }
    }
    var open by rememberSaveable { mutableStateOf<String?>(null) }
    val wanted by MainActivity.openPage.collectAsState()
    LaunchedEffect(wanted) { wanted?.let { open = it; MainActivity.openPage.value = null } }
    LaunchedEffect(open, us) {
        val k = open ?: return@LaunchedEffect
        val sig = UsTiles.signature(k, us?.optJSONObject(k))
        if (sig.isNotBlank() && seen[k] != sig) { seen = seen + (k to sig); vm.prefs.usSeen = UsTiles.seenToJson(seen) }
    }
    BackHandler(enabled = open != null) { open = null }
    AnimatedContent(open, transitionSpec = {
        (fadeIn(tween(220)) + slideInHorizontally(tween(260)) { if (targetState != null) it / 6 else -it / 6 }) togetherWith fadeOut(tween(160))
    }, label = "us") { page ->
        if (page == null) UsHome(us, name, emotion, UsTiles.fresh(us, seen)) { open = it }
        else UsPage(page, us, name) { open = null }
    }
}

private data class TileLook(val icon: ImageVector, val color: Color)

@Composable
private fun tileLook(key: String) = when (key) {
    "together" -> TileLook(Icons.Filled.Spa, Accent0)
    "journal" -> TileLook(Icons.AutoMirrored.Filled.MenuBook, Peach)
    "voicenotes" -> TileLook(Icons.Filled.GraphicEq, Lavender)
    "japanese" -> TileLook(Icons.Filled.Translate, Accent0)
    "weekend" -> TileLook(Icons.Filled.Weekend, Butter)
    "cooking" -> TileLook(Icons.Filled.Restaurant, Peach)
    "watching" -> TileLook(Icons.Filled.LiveTv, Lavender)
    "bucket" -> TileLook(Icons.Filled.Hiking, Mint)
    "groceries" -> TileLook(Icons.Filled.ShoppingCart, Mint)
    "playlist" -> TileLook(Icons.Filled.QueueMusic, Lavender)
    "dailyphoto" -> TileLook(Icons.Filled.PhotoCamera, Peach)
    "gooddays" -> TileLook(Icons.Filled.WbSunny, Butter)
    "wrapped" -> TileLook(Icons.Filled.Celebration, Peach)
    "scrapbook" -> TileLook(Icons.Filled.PhotoAlbum, Butter)
    "stories" -> TileLook(Icons.Filled.AutoStories, Lavender)
    "drawings" -> TileLook(Icons.Filled.Brush, Peach)
    "asks" -> TileLook(Icons.Filled.CardGiftcard, Accent0)
    "promises" -> TileLook(Icons.Filled.Handshake, Mint)
    else -> TileLook(Icons.Filled.AutoAwesome, Butter)
}

/** The tiles page (data handed in, so it renders without the network). */
@Composable
fun UsHome(us: JSONObject?, name: String, emotion: String, fresh: Set<String>, onOpen: (String) -> Unit) {
    val highlights = UsTiles.today(us, fresh, name)
    LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(start = 16.dp, end = 16.dp, top = 22.dp, bottom = 24.dp),
               verticalArrangement = Arrangement.spacedBy(12.dp)) {
        item("head") {
            Column(Modifier.padding(start = 6.dp)) {
                Label("You & $name", color = Accent0)
                Text("Us", style = DisplayStyle, color = Text1, fontSize = 44.sp, lineHeight = 48.sp)
                OfflineNote(Modifier.padding(top = 6.dp))
            }
        }
        item("today") { TodayWithHer(highlights, name, emotion, onOpen) }
        items(UsTiles.ORDER.chunked(2), key = { it.first() }) { pair ->
            Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                pair.forEach { k -> Tile(k, UsTiles.line(k, us?.optJSONObject(k), name), k in fresh, Modifier.weight(1f)) { onOpen(k) } }
                if (pair.size == 1) Spacer(Modifier.weight(1f))
            }
        }
    }
}

@Composable
private fun TodayWithHer(list: List<UsTiles.Highlight>, name: String, emotion: String, onOpen: (String) -> Unit) {
    Column(Modifier.fillMaxWidth().clip(RoundedCornerShape(24.dp))
               .background(Brush.linearGradient(listOf(Accent0.copy(alpha = 0.16f), Lavender.copy(alpha = 0.08f))))
               .border(1.dp, Accent0.copy(alpha = 0.18f), RoundedCornerShape(24.dp)).padding(16.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            FaceAvatar(emotion, 44.dp)
            Column(Modifier.padding(start = 12.dp).weight(1f)) {
                Text("Today with $name", style = DisplayStyle, color = Text1, fontSize = 19.sp)
                Text(if (list.isEmpty()) "Nothing waiting. Pick anything below." else "Here's what's waiting for you.",
                     color = Text2, fontSize = 13.sp)
            }
        }
        list.forEach { h ->
            val look = tileLook(h.key)
            Row(Modifier.padding(top = 10.dp).fillMaxWidth().clip(RoundedCornerShape(16.dp)).background(Color.White.copy(alpha = 0.06f))
                    .clickable { onOpen(h.key) }.padding(horizontal = 12.dp, vertical = 10.dp), verticalAlignment = Alignment.CenterVertically) {
                Box(Modifier.size(30.dp).clip(CircleShape).background(look.color.copy(alpha = 0.18f)), contentAlignment = Alignment.Center) {
                    Icon(look.icon, null, tint = look.color, modifier = Modifier.size(17.dp))
                }
                Text(h.text, color = Text1, fontSize = 14.5.sp, fontWeight = FontWeight.Medium, maxLines = 1,
                     overflow = TextOverflow.Ellipsis, modifier = Modifier.weight(1f).padding(start = 12.dp))
                Icon(Icons.AutoMirrored.Filled.KeyboardArrowRight, null, tint = Dim, modifier = Modifier.size(20.dp))
            }
        }
    }
}

@Composable
private fun Tile(key: String, line: String, fresh: Boolean, modifier: Modifier, onClick: () -> Unit) {
    val look = tileLook(key)
    Box(modifier.height(132.dp).clip(RoundedCornerShape(24.dp))
            .background(Brush.verticalGradient(listOf(look.color.copy(alpha = 0.15f), look.color.copy(alpha = 0.05f))))
            .border(1.dp, Color.White.copy(alpha = 0.06f), RoundedCornerShape(24.dp)).clickable(onClick = onClick).padding(14.dp)) {
        Box(Modifier.size(40.dp).clip(CircleShape).background(look.color.copy(alpha = 0.2f)), contentAlignment = Alignment.Center) {
            Icon(look.icon, null, tint = look.color, modifier = Modifier.size(22.dp))
        }
        if (fresh) Box(Modifier.align(Alignment.TopEnd).size(10.dp).clip(CircleShape).background(Accent0))
        Column(Modifier.align(Alignment.BottomStart)) {
            Text(UsTiles.TITLES[key] ?: key, color = Text1, fontSize = 16.sp, fontWeight = FontWeight.Bold)
            Text(line, color = Text2, fontSize = 12.sp, lineHeight = 16.sp, maxLines = 2, overflow = TextOverflow.Ellipsis)
        }
    }
}

/** One feature, full screen, with a back arrow. */
@Composable
fun UsPage(key: String, us: JSONObject?, name: String, onBack: () -> Unit) {
    val o = us?.optJSONObject(key)
    val look = tileLook(key)
    LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(start = 16.dp, end = 16.dp, top = 14.dp, bottom = 24.dp)) {
        item("head") {
            Row(Modifier.padding(bottom = 14.dp), verticalAlignment = Alignment.CenterVertically) {
                Box(Modifier.size(44.dp).clip(CircleShape).background(Color.White.copy(alpha = 0.07f)).clickable(onClick = onBack),
                    contentAlignment = Alignment.Center) { Icon(Icons.AutoMirrored.Filled.ArrowBack, "Back", tint = Text1) }
                Icon(look.icon, null, tint = look.color, modifier = Modifier.padding(start = 14.dp).size(24.dp))
                Column(Modifier.padding(start = 10.dp)) {
                    Text(UsTiles.TITLES[key] ?: key, style = DisplayStyle, color = Text1, fontSize = 28.sp, lineHeight = 32.sp)
                    Text(UsTiles.line(key, o, name), color = Text2, fontSize = 13.sp, maxLines = 1, overflow = TextOverflow.Ellipsis)
                }
            }
        }
        item("body") {
            when (key) {
                "together" -> TogetherCard(o, name)
                "journal" -> NotebookCard(o, name)
                "voicenotes" -> VoiceNotesCard(o, name)
                "japanese" -> JapaneseCard(o, name)
                "weekend" -> WeekendCard(o, name)
                "cooking" -> KitchenPage(o, us?.optJSONObject("meals"), name)
                "watching" -> WatchingCard(o, name)
                "bucket" -> BucketCard(o, name)
                "groceries" -> GroceryCard(o, name)
                "playlist" -> PlaylistCard(o, name)
                "dailyphoto" -> DailyPhotoCard(o, name)
                "gooddays" -> GoodDaysCard(o, name)
                "wrapped" -> WrappedCard(o, name)
                "scrapbook" -> ScrapbookCard(o, name)
                "stories" -> StoriesCard(o, name)
                "drawings" -> SketchbookCard(o, name)
                "asks" -> GiftsCard(o, name)
                "promises" -> PromisesCard(o, name)
                else -> WeekCard(o, name)
            }
        }
    }
}

// ----- doing it together -----

@Composable
internal fun TogetherCard(t: JSONObject?, name: String) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    var adding by remember { mutableStateOf(false) }
    var editing by remember { mutableStateOf<JSONObject?>(null) }
    Card {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Label("Doing it together", modifier = Modifier.weight(1f))
            GhostButton("Add") { adding = true }
        }
        if (t == null) {
            Text("Your daily list shows up after the first sync with the laptop.", color = Text2, modifier = Modifier.padding(top = 6.dp))
            if (adding) ActivityDialog(null, onDone = { adding = false }) { a -> scope.launch { Us.addActivity(context, a) } }
            return@Card
        }
        val room = t.optJSONObject("room") ?: JSONObject()
        Room(room, Modifier.padding(top = 10.dp).fillMaxWidth().height(170.dp))
        RoomCaption(room, name)
        t.optJSONObject("session")?.let { SessionBanner(it, name) }
        val list = t.optJSONArray("activities")?.objects().orEmpty()
        if (list.isEmpty()) {
            Text("Nothing yet. Add something you want to do every day; $name will do it with you.",
                 color = Text2, modifier = Modifier.padding(top = 8.dp))
        }
        val today = list.filter { it.optBoolean("due", true) || !it.isNull("how") }
        val later = list - today.toSet()
        today.forEach { a -> ActivityRow(a, t.optBoolean("pass_free"), onEdit = { editing = a }) }
        if (later.isNotEmpty()) {
            Text("Not today: " + later.joinToString { it.str("title") }, color = Dim, fontSize = 12.sp,
                 modifier = Modifier.padding(top = 6.dp))
        }
        val goals = t.optJSONArray("goals")?.objects().orEmpty()
        if (goals.isNotEmpty()) {
            Label("This week's goals", modifier = Modifier.padding(top = 12.dp))
            goals.forEach { g ->
                Text("${g.str("text")} · ${g.str("progress")}", color = Text2, fontSize = 13.sp, modifier = Modifier.padding(top = 4.dp))
            }
        }
        Text(if (t.optBoolean("pass_free")) "This week's pass is free: on a day you can't, $name covers for you."
             else "$name already covered for you once this week.", color = Dim, fontSize = 12.sp, modifier = Modifier.padding(top = 10.dp))
    }
    if (adding) ActivityDialog(null, onDone = { adding = false }) { a -> scope.launch { Us.addActivity(context, a) } }
    editing?.let { a ->
        ActivityDialog(a, onDone = { editing = null }) { change -> scope.launch { Us.editActivity(context, a.optInt("id"), change) } }
    }
}

@Composable
private fun RoomCaption(room: JSONObject, name: String) {
    val next = room.optJSONObject("next")
    val text = when {
        room.optBoolean("droopy") -> "The plant's drooping a little. It misses you; one thing today perks it up."
        room.optInt("points") == 0 -> "Your room with $name. Every thing you do adds something to it."
        next != null -> "${room.optInt("points")} things done together · ${next.optInt("in")} more for ${next.str("label")}"
        else -> "${room.optInt("points")} things done together · the room is full of you two"
    }
    Text(text, color = Text2, fontSize = 12.sp, modifier = Modifier.padding(top = 6.dp))
}

@Composable
private fun SessionBanner(s: JSONObject, name: String) {
    val left = ((s.optDouble("until") * 1000 - System.currentTimeMillis()) / 60_000).toInt().coerceAtLeast(0)
    Row(
        Modifier.padding(top = 10.dp).fillMaxWidth().clip(RoundedCornerShape(14.dp)).background(Accent0.copy(alpha = 0.10f)).padding(12.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Column(Modifier.weight(1f)) {
            Text("You: ${s.str("title")}", color = Text1, fontWeight = FontWeight.SemiBold)
            Text("$name: ${s.str("her").replaceFirstChar { it.uppercase() }}", color = Text2, fontSize = 13.sp)
        }
        Text(if (left > 0) "$left min" else "done?", color = Accent0, fontSize = 13.sp)
    }
}

@Composable
private fun ActivityRow(a: JSONObject, passFree: Boolean, onEdit: () -> Unit) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    val how = if (a.isNull("how")) null else a.str("how")
    val done = how != null
    var menu by remember { mutableStateOf(false) }
    Row(Modifier.fillMaxWidth().padding(top = 10.dp), verticalAlignment = Alignment.CenterVertically) {
        Box(
            Modifier.size(30.dp).clip(CircleShape)
                .background(if (done) Accent0.copy(alpha = if (how == "pass") 0.25f else 0.9f) else Color.Transparent)
                .border(1.5.dp, if (done) Accent0 else Dim, CircleShape)
                .clickable { scope.launch { Us.tick(context, a.optInt("id"), !done) } },
            contentAlignment = Alignment.Center,
        ) { if (done) Icon(Icons.Filled.Check, contentDescription = "Done", tint = if (how == "pass") Accent0 else Navy, modifier = Modifier.size(18.dp)) }
        Column(Modifier.weight(1f).padding(start = 12.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(a.str("title"), color = if (done) Text2 else Text1, fontWeight = FontWeight.Medium,
                     textDecoration = if (done && how != "pass") TextDecoration.LineThrough else null)
                val streak = a.optInt("streak")
                if (streak >= 2) Text("  🔥 $streak", color = Amber, fontSize = 12.sp)
            }
            val sub = listOfNotNull(
                a.str("days_words").takeIf { it.isNotBlank() && it != "every day" },
                a.str("at").takeIf { it.isNotBlank() }?.let { clock(it) },
                if (how == "pass") "covered today" else null,
            ).joinToString(" · ")
            if (sub.isNotBlank()) Text(sub, color = Dim, fontSize = 12.sp)
            if (a.str("why").isNotBlank()) Text("“${a.str("why")}”", color = Text2, fontSize = 12.sp, fontStyle = FontStyle.Italic, maxLines = 2)
        }
        if (!done && a.str("app").isNotBlank()) {
            TextButton(onClick = { com.manaskhare.sanae.Noticing.open(context, a.str("app")) }) { Text("Open", color = Accent0, fontSize = 13.sp) }
        } else if (!done) {
            TextButton(onClick = {
                scope.launch { Us.start(context, a.optInt("id"), a.optInt("minutes").takeIf { it > 0 } ?: 25) }
            }) { Text("Start", color = Accent0, fontSize = 13.sp) }
        }
        Box {
            IconButton(onClick = { menu = true }) { Icon(Icons.Filled.MoreVert, contentDescription = "More", tint = Dim) }
            DropdownMenu(expanded = menu, onDismissRequest = { menu = false }) {
                if (!done && passFree) DropdownMenuItem(text = { Text("Can't today (use the pass)") }, onClick = {
                    menu = false; scope.launch { Us.tick(context, a.optInt("id"), true, "pass") }
                })
                DropdownMenuItem(text = { Text("Edit") }, onClick = { menu = false; onEdit() })
                DropdownMenuItem(text = { Text("Remove", color = Red) }, onClick = {
                    menu = false; scope.launch { Us.removeActivity(context, a.optInt("id")) }
                })
            }
        }
    }
}

private fun clock(hm: String): String = runCatching {
    val (h, m) = hm.split(":").map { it.toInt() }
    "${if (h % 12 == 0) 12 else h % 12}${if (m > 0) ":%02d".format(m) else ""} ${if (h < 12) "AM" else "PM"}"
}.getOrDefault(hm)

private val DAY_KEYS = listOf("mon", "tue", "wed", "thu", "fri", "sat", "sun")

/** Add (a == null) or edit one. Sends only what's needed: the laptop works out the rest. */
@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun ActivityDialog(a: JSONObject?, onDone: () -> Unit, onSave: (JSONObject) -> Unit) {
    var title by remember { mutableStateOf(a?.str("title").orEmpty()) }
    var why by remember { mutableStateOf(a?.str("why").orEmpty()) }
    var at by remember { mutableStateOf(a?.str("at").orEmpty()) }
    var minutes by remember { mutableStateOf(a?.optInt("minutes")?.takeIf { it > 0 }?.toString().orEmpty()) }
    var app by remember { mutableStateOf(a?.str("app").orEmpty()) }
    var picking by remember { mutableStateOf(false) }
    val context = LocalContext.current
    val initial = a?.str("days") ?: "daily"
    var mode by remember { mutableStateOf(when { initial == "daily" -> "Every day"; initial.endsWith("/week") -> "Per week"; else -> "Some days" }) }
    var picked by remember { mutableStateOf(if (initial.contains(",") || initial in DAY_KEYS) initial.split(",").toSet() else setOf("mon", "wed", "fri")) }
    var perWeek by remember { mutableStateOf(if (initial.endsWith("/week")) initial.substringBefore("/").toInt() else 3) }
    val fieldColors = OutlinedTextFieldDefaults.colors(focusedTextColor = Text1, unfocusedTextColor = Text1,
        focusedBorderColor = Accent0, unfocusedBorderColor = Line, cursorColor = Accent0)
    AlertDialog(
        onDismissRequest = onDone,
        containerColor = Panel,
        title = { Text(if (a == null) "Something to do together" else "Edit", color = Text1) },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                OutlinedTextField(title, { title = it }, label = { Text("What") }, placeholder = { Text("read 20 minutes") },
                                  singleLine = true, colors = fieldColors)
                OutlinedTextField(why, { why = it }, label = { Text("Why it matters to you") },
                                  placeholder = { Text("I miss getting lost in a story") }, colors = fieldColors)
                Segmented(listOf("Every day", "Some days", "Per week"), mode, { it }) { mode = it }
                if (mode == "Some days") FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                    DAY_KEYS.forEach { d ->
                        val on = d in picked
                        Text(d.replaceFirstChar { it.uppercase() }, color = if (on) Navy else Text2, fontSize = 13.sp,
                             modifier = Modifier.clip(RoundedCornerShape(10.dp)).background(if (on) Accent0 else Color.Transparent)
                                 .border(1.dp, Line, RoundedCornerShape(10.dp)).clickable { picked = if (on) picked - d else picked + d }
                                 .padding(horizontal = 10.dp, vertical = 6.dp))
                    }
                }
                if (mode == "Per week") Row(verticalAlignment = Alignment.CenterVertically) {
                    TextButton(onClick = { perWeek = (perWeek - 1).coerceAtLeast(1) }) { Text("−", color = Accent0, fontSize = 18.sp) }
                    Text("$perWeek times a week", color = Text1)
                    TextButton(onClick = { perWeek = (perWeek + 1).coerceAtMost(6) }) { Text("+", color = Accent0, fontSize = 18.sp) }
                }
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    OutlinedTextField(at, { at = it.filter { c -> c.isDigit() || c == ':' }.take(5) }, label = { Text("Time (21:00)") },
                                      singleLine = true, colors = fieldColors, modifier = Modifier.weight(1f))
                    OutlinedTextField(minutes, { minutes = it.filter { c -> c.isDigit() }.take(3) }, label = { Text("Minutes") },
                                      singleLine = true, colors = fieldColors, modifier = Modifier.width(110.dp))
                }
                // an app it happens in: tap to open it from the list, and (with "Apps you use" on) it ticks itself
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text(if (app.isBlank()) "No linked app" else "App: ${com.manaskhare.sanae.Noticing.label(context, app)}",
                         color = Text2, fontSize = 13.sp, modifier = Modifier.weight(1f))
                    if (app.isNotBlank()) TextButton(onClick = { app = "" }) { Text("Unlink", color = Text2, fontSize = 13.sp) }
                    TextButton(onClick = { picking = true }) { Text(if (app.isBlank()) "Link an app" else "Change", color = Accent0, fontSize = 13.sp) }
                }
            }
        },
        confirmButton = {
            TextButton(enabled = title.isNotBlank(), onClick = {
                val days = when (mode) {
                    "Every day" -> "daily"
                    "Per week" -> "$perWeek/week"
                    else -> DAY_KEYS.filter { it in picked }.joinToString(",").ifBlank { "daily" }
                }
                val okAt = Regex("\\d{1,2}:\\d{2}").matches(at)
                onSave(JSONObject().put("title", title.trim()).put("why", why.trim()).put("days", days)
                    .put("at", if (okAt) at.padStart(5, '0') else "").put("minutes", minutes.toIntOrNull() ?: 0).put("app", app))
                onDone()
            }) { Text("Save", color = Accent0) }
        },
        dismissButton = { TextButton(onClick = onDone) { Text("Cancel", color = Text2) } },
    )
    if (picking) AppPicker(onDone = { picking = false }) { app = it }
}

@Composable
private fun AppPicker(onDone: () -> Unit, onPick: (String) -> Unit) {
    val context = LocalContext.current
    val apps = remember { com.manaskhare.sanae.Noticing.launchable(context) }
    var q by remember { mutableStateOf("") }
    AlertDialog(
        onDismissRequest = onDone,
        containerColor = Panel,
        title = { Text("Which app?", color = Text1) },
        text = {
            Column {
                OutlinedTextField(q, { q = it }, placeholder = { Text("Search") }, singleLine = true,
                    colors = OutlinedTextFieldDefaults.colors(focusedTextColor = Text1, unfocusedTextColor = Text1,
                        focusedBorderColor = Accent0, unfocusedBorderColor = Line, cursorColor = Accent0))
                LazyColumn(Modifier.height(320.dp).padding(top = 8.dp)) {
                    items(apps.filter { q.isBlank() || it.second.contains(q, ignoreCase = true) }.size) { i ->
                        val (pkg, label) = apps.filter { q.isBlank() || it.second.contains(q, ignoreCase = true) }[i]
                        Text(label, color = Text1, modifier = Modifier.fillMaxWidth().clickable { onPick(pkg); onDone() }.padding(vertical = 10.dp))
                    }
                }
            }
        },
        confirmButton = { TextButton(onClick = onDone) { Text("Cancel", color = Text2) } },
    )
}

// ----- the room you build together -----

/** Drawn from the items the laptop says are unlocked (together.py ROOM), in order of unlocking. */
@Composable
internal fun Room(room: JSONObject, modifier: Modifier = Modifier) {
    val items = room.optJSONArray("items")?.let { arr -> (0 until arr.length()).map { arr.optString(it) }.toSet() } ?: emptySet()
    val droopy = room.optBoolean("droopy")
    val accent = Accent0
    val wall = Panel
    val floor = PanelHi
    val night = java.time.LocalTime.now().hour.let { it >= 19 || it < 6 }
    Canvas(modifier.clip(RoundedCornerShape(16.dp))) {
        val w = size.width
        val h = size.height
        val floorY = h * 0.72f
        drawRect(wall, size = Size(w, floorY))
        drawRect(floor, topLeft = Offset(0f, floorY), size = Size(w, h - floorY))
        drawLine(accent.copy(alpha = 0.25f), Offset(0f, floorY), Offset(w, floorY), strokeWidth = 2f)
        // window
        val win = Offset(w * 0.40f, h * 0.12f)
        val winSize = Size(w * 0.20f, h * 0.36f)
        drawRoundRect(if (night) Color(0xFF0B1A3A) else Color(0xFF8EC9F0), win, winSize, CornerRadius(6f))
        if (night) drawCircle(Color(0xFFFFF4C2), radius = winSize.width * 0.12f, center = Offset(win.x + winSize.width * 0.72f, win.y + winSize.height * 0.28f))
        else drawCircle(Color(0xFFFFE08A), radius = winSize.width * 0.13f, center = Offset(win.x + winSize.width * 0.3f, win.y + winSize.height * 0.3f))
        drawRoundRect(accent.copy(alpha = 0.45f), win, winSize, CornerRadius(6f), style = Stroke(3f))
        drawLine(accent.copy(alpha = 0.45f), Offset(win.x + winSize.width / 2, win.y), Offset(win.x + winSize.width / 2, win.y + winSize.height), 2f)
        if ("stars" in items) {
            listOf(0.08f to 0.08f, 0.2f to 0.05f, 0.7f to 0.07f, 0.85f to 0.12f, 0.3f to 0.15f, 0.92f to 0.04f).forEach { (x, y) ->
                drawCircle(Color(0xFFE9FFB0).copy(alpha = 0.8f), radius = 2.6f, center = Offset(w * x, h * y))
            }
        }
        if ("fairy_lights" in items) {
            val colors = listOf(Color(0xFFFFD166), Color(0xFFFF8FAB), Color(0xFF8BE9FD), Color(0xFFB9FBC0))
            for (i in 0..13) {
                val x = w * (0.04f + i * 0.07f)
                val y = h * 0.06f + kotlin.math.sin(i * 0.9f) * h * 0.025f + h * 0.03f
                drawCircle(colors[i % colors.size].copy(alpha = 0.35f), radius = 7f, center = Offset(x, y))
                drawCircle(colors[i % colors.size], radius = 3f, center = Offset(x, y))
            }
        }
        if ("poster" in items) {
            val p = Offset(w * 0.22f, h * 0.20f)
            drawRoundRect(Color(0xFFFFB4C6), p, Size(w * 0.13f, h * 0.30f), CornerRadius(4f))
            drawCircle(Color(0xFFFFF1F5), radius = w * 0.03f, center = Offset(p.x + w * 0.065f, p.y + h * 0.12f))
            drawRect(Color(0xFFFF7FA0), Offset(p.x + w * 0.02f, p.y + h * 0.21f), Size(w * 0.09f, h * 0.03f))
        }
        if ("window_plant" in items) pot(Offset(win.x + winSize.width * 0.5f, win.y + winSize.height), 0.6f, droopy, flowers = false)
        if ("rug" in items) drawOval(accent.copy(alpha = 0.22f), Offset(w * 0.28f, h * 0.80f), Size(w * 0.44f, h * 0.13f))
        if ("bookshelf" in items) {
            val b = Offset(w * 0.04f, h * 0.48f)
            drawRect(Color(0xFF6B4F3A), b, Size(w * 0.16f, floorY - b.y + h * 0.04f))
            val shelfColors = listOf(Color(0xFFEF6F6C), Color(0xFF7FD1B9), Color(0xFFF4D35E), Color(0xFF8E9AAF), Color(0xFFB8B8FF))
            for (row in 0..1) for (i in 0..4) {
                drawRect(shelfColors[(i + row) % 5], Offset(b.x + w * (0.012f + i * 0.028f), b.y + h * (0.03f + row * 0.13f)),
                         Size(w * 0.022f, h * 0.10f))
            }
        }
        if ("lamp" in items) {
            val base = Offset(w * 0.90f, floorY + h * 0.08f)
            drawCircle(Color(0xFFFFE6A7).copy(alpha = if (night) 0.22f else 0.10f), radius = h * 0.22f, center = Offset(base.x, h * 0.36f))
            drawLine(Color(0xFF9A8C98), base, Offset(base.x, h * 0.40f), strokeWidth = 4f)
            val shade = Path().apply {
                moveTo(base.x - w * 0.045f, h * 0.42f); lineTo(base.x + w * 0.045f, h * 0.42f)
                lineTo(base.x + w * 0.03f, h * 0.30f); lineTo(base.x - w * 0.03f, h * 0.30f); close()
            }
            drawPath(shade, Color(0xFFFFE6A7))
        }
        if ("beanbag" in items) drawOval(Color(0xFF9381FF), Offset(w * 0.70f, floorY - h * 0.02f), Size(w * 0.13f, h * 0.17f))
        if ("cat_bed" in items) {
            drawOval(Color(0xFFB56576), Offset(w * 0.30f, floorY + h * 0.05f), Size(w * 0.14f, h * 0.10f))
            drawOval(Color(0xFFE5989B), Offset(w * 0.315f, floorY + h * 0.06f), Size(w * 0.11f, h * 0.06f))
        }
        if ("cat" in items) cat(Offset(w * 0.37f, floorY + h * 0.06f), h * 0.07f)
        val plantStage = when { "plant_big" in items -> 3; "plant" in items -> 2; "sprout" in items -> 1; else -> 0 }
        if (plantStage > 0) pot(Offset(w * 0.60f, floorY + h * 0.14f), 0.6f + plantStage * 0.35f, droopy, "flowers" in items)
    }
}

private fun DrawScope.pot(at: Offset, scale: Float, droopy: Boolean, flowers: Boolean) {
    val s = size.height * 0.06f * scale
    val pot = Path().apply {
        moveTo(at.x - s, at.y - s * 1.3f); lineTo(at.x + s, at.y - s * 1.3f)
        lineTo(at.x + s * 0.75f, at.y); lineTo(at.x - s * 0.75f, at.y); close()
    }
    drawPath(pot, Color(0xFFD08C60))
    val stemTop = Offset(at.x, at.y - s * 1.3f - s * 1.6f * scale)
    drawLine(Color(0xFF52B788), Offset(at.x, at.y - s * 1.3f), stemTop, strokeWidth = 3f)
    val leaves = (2 * scale).toInt().coerceIn(2, 6)
    for (i in 0 until leaves) {
        val t = (i + 1f) / (leaves + 1f)
        val y = at.y - s * 1.3f - (at.y - s * 1.3f - stemTop.y) * t
        val side = if (i % 2 == 0) -1f else 1f
        val angle = (if (droopy) 40f else -25f) * side
        rotate(angle, pivot = Offset(at.x, y)) {
            drawOval(Color(0xFF74C69D), Offset(at.x + (if (side > 0) 0f else -s * 1.4f), y - s * 0.3f), Size(s * 1.4f, s * 0.6f))
        }
    }
    if (flowers && !droopy) {
        listOf(-0.6f to -0.2f, 0.5f to 0.1f, 0f to -0.6f).forEach { (dx, dy) ->
            drawCircle(Color(0xFFFF8FAB), radius = s * 0.32f, center = Offset(stemTop.x + dx * s, stemTop.y + dy * s))
            drawCircle(Color(0xFFFFE066), radius = s * 0.12f, center = Offset(stemTop.x + dx * s, stemTop.y + dy * s))
        }
    }
}

private fun DrawScope.cat(at: Offset, r: Float) {
    val fur = Color(0xFF3D3D4E)
    drawOval(fur, Offset(at.x - r * 1.3f, at.y - r * 0.4f), Size(r * 2.2f, r * 1.1f))
    drawCircle(fur, radius = r * 0.62f, center = Offset(at.x + r * 0.9f, at.y - r * 0.45f))
    val ear = Path().apply {
        moveTo(at.x + r * 0.45f, at.y - r * 0.75f); lineTo(at.x + r * 0.62f, at.y - r * 1.25f); lineTo(at.x + r * 0.85f, at.y - r * 0.9f); close()
        moveTo(at.x + r * 0.98f, at.y - r * 0.92f); lineTo(at.x + r * 1.25f, at.y - r * 1.25f); lineTo(at.x + r * 1.35f, at.y - r * 0.7f); close()
    }
    drawPath(ear, fur)
    drawLine(Color(0xFFFFE066), Offset(at.x + r * 0.62f, at.y - r * 0.5f), Offset(at.x + r * 0.8f, at.y - r * 0.5f), strokeWidth = 2f)
    drawLine(Color(0xFFFFE066), Offset(at.x + r * 0.98f, at.y - r * 0.5f), Offset(at.x + r * 1.16f, at.y - r * 0.5f), strokeWidth = 2f)
}
