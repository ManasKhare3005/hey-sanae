package com.manaskhare.sanae.ui

import android.app.DatePickerDialog
import android.app.TimePickerDialog
import android.content.Intent
import android.net.Uri
import android.widget.Toast
import androidx.compose.animation.animateColorAsState
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.IntrinsicSize
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.Assignment
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.CalendarMonth
import androidx.compose.material.icons.filled.Check
import androidx.compose.material.icons.filled.CheckCircle
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.filled.Event
import androidx.compose.material.icons.filled.NotificationsActive
import androidx.compose.material.icons.filled.Repeat
import androidx.compose.material.icons.filled.School
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.OutlinedTextFieldDefaults
import androidx.compose.material3.SwipeToDismissBox
import androidx.compose.material3.SwipeToDismissBoxValue
import androidx.compose.material3.Text
import androidx.compose.material3.pulltorefresh.PullToRefreshBox
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.material3.rememberSwipeToDismissBoxState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.drawBehind
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardCapitalization
import androidx.compose.ui.text.style.TextDecoration
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.manaskhare.sanae.CanvasItem
import com.manaskhare.sanae.DayPlan
import com.manaskhare.sanae.Entry
import com.manaskhare.sanae.EntryKind
import com.manaskhare.sanae.Hub
import com.manaskhare.sanae.LocalChore
import com.manaskhare.sanae.LocalDb
import com.manaskhare.sanae.Link
import com.manaskhare.sanae.MainViewModel
import com.manaskhare.sanae.Offline
import com.manaskhare.sanae.QuickAdd
import com.manaskhare.sanae.Routine
import com.manaskhare.sanae.RoutineLogic
import com.manaskhare.sanae.Sync
import com.manaskhare.sanae.Timeline
import com.manaskhare.sanae.When
import com.manaskhare.sanae.objects
import com.manaskhare.sanae.str
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.withContext
import org.json.JSONObject
import java.time.LocalDate
import java.time.LocalDateTime
import java.time.format.DateTimeFormatter
import java.util.Locale

/**
 * Today in one list: what's on the clock (classes, events, reminders, due dates) with a "now"
 * line, the checklist (routine + todos), then the next week. Swipe right to tick, left to remove,
 * pull down to refresh, "+" to add anything. Calendar, reminders and todos live on the phone too,
 * so it all works with the laptop off; Canvas shows the copy from the last sync.
 */
@Composable
fun TodayScreen(vm: MainViewModel) {
    val context = LocalContext.current
    val db = remember { LocalDb.get(context) }
    val rev by LocalDb.revision.collectAsState()
    val link by Hub.link.collectAsState()
    val emotion by vm.emotion.collectAsState()
    var today by remember { mutableStateOf(vm.prefs.todayJson.takeIf { it.isNotBlank() }?.let { runCatching { JSONObject(it) }.getOrNull() }) }
    var refresh by remember { mutableIntStateOf(0) }
    var refreshing by remember { mutableStateOf(false) }
    LaunchedEffect(refresh, link) {
        if (link == Link.ONLINE) vm.quiet({ it.today() }) { today = it; vm.prefs.todayJson = it.toString(); vm.prefs.todayAt = System.currentTimeMillis() }
        if (refreshing) { delay(1200); refreshing = false }
    }
    val now = LocalDateTime.now()
    val reminders by produceList(rev) { db.reminders("status = 'pending'") }
    val events by produceList(rev) {
        val from = Offline.ms(now.toLocalDate().atStartOfDay())
        db.events("status = 'active' AND end_ms > ? AND start_ms < ?", from.toString(), Offline.ms(now.plusDays(8)).toString())
    }
    val todos by produceList(rev) { db.shownTodos() }
    val chores by produceList(rev) { db.chores("status = 'active'") }
    val canvas = { key: String -> today?.optJSONArray(key)?.objects().orEmpty().map {
        CanvasItem(it.str("title"), it.str("course"), Timeline.parseIso(it.str("due")), it.str("link")) } }
    val plan = Timeline.build(now, canvas("classes"), canvas("due_today"), canvas("due_soon"), events, reminders, todos, chores)
    TodayContent(
        plan, now, emotion, chores,
        note = when {
            today?.str("canvas_error").orEmpty().isNotBlank() -> "Canvas: ${today?.str("canvas_error")}"
            today == null && link != Link.ONLINE -> "Canvas classes and due dates show after the first sync."
            else -> ""
        },
        refreshing = refreshing,
        onRefresh = { refreshing = true; refresh++; Sync.trigger(context, 0) },
    )
}

/** The screen itself, with the data handed in (so it can be rendered without the phone's database). */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun TodayContent(plan: DayPlan, now: LocalDateTime, emotion: String, chores: List<LocalChore>, note: String = "",
                 refreshing: Boolean = false, onRefresh: () -> Unit = {}) {
    var adding by remember { mutableStateOf(false) }
    var routine by remember { mutableStateOf(false) }
    Box(Modifier.fillMaxSize()) {
        PullToRefreshBox(refreshing, onRefresh, Modifier.fillMaxSize()) {
            LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(start = 16.dp, end = 16.dp, top = 22.dp, bottom = 110.dp)) {
                item("head") { Header(plan, now, emotion, note) }

                item("today") { SectionHead("On the clock") }
                if (plan.allDay.isNotEmpty()) item("allday") { AllDay(plan.allDay) }
                val nowAt = plan.nowIndex(now)
                if (plan.today.isEmpty()) item("free") { Quiet("Nothing scheduled. Tap + to plan something.") }
                plan.today.forEachIndexed { i, e ->
                    if (i == nowAt) item("now") { NowLine(now) }
                    item("t:" + e.id) { Swipeable(e) { TimelineRow(e, past = i < nowAt, first = i == 0, last = i == plan.today.lastIndex) } }
                }
                if (plan.today.isNotEmpty() && nowAt == plan.today.size) item("now") { NowLine(now) }

                item("list") {
                    SectionHead("Checklist", trailing = if (plan.checklist.isEmpty()) "" else "${plan.doneCount} of ${plan.checklist.size} done") {
                        Text("Routine", color = Accent0, fontSize = 13.sp, fontWeight = FontWeight.Bold,
                             modifier = Modifier.clip(RoundedCornerShape(50)).clickable { routine = true }.padding(horizontal = 10.dp, vertical = 4.dp))
                    }
                    if (plan.checklist.isNotEmpty()) Progress(plan.doneCount.toFloat() / plan.checklist.size)
                }
                if (plan.checklist.isEmpty()) item("nolist") { Quiet("Your list is empty. Tap + to add a todo or a routine.") }
                items(plan.checklist, key = { "c:" + it.id }) { e -> Swipeable(e) { CheckRow(e) } }

                if (plan.later.isNotEmpty()) item("later") { SectionHead("Coming up") }
                plan.later.forEach { (day, list) ->
                    item("d:$day") { DayHead(day, now.toLocalDate()) }
                    items(list, key = { "l:" + it.id }) { e -> Swipeable(e) { LaterRow(e) } }
                }
            }
        }
        Box(
            Modifier.align(Alignment.BottomEnd).padding(end = 20.dp, bottom = 20.dp).size(58.dp).clip(CircleShape)
                .background(Accent0).clickable { adding = true },
            contentAlignment = Alignment.Center,
        ) { Icon(Icons.Filled.Add, "Add", tint = Navy, modifier = Modifier.size(28.dp)) }
    }
    if (adding) {
        val sheet = rememberModalBottomSheetState(skipPartiallyExpanded = true)
        ModalBottomSheet({ adding = false }, sheetState = sheet, containerColor = Panel, dragHandle = { Grabber() }) {
            AddPanel(now) { adding = false }
        }
    }
    if (routine) {
        ModalBottomSheet({ routine = false }, sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true),
                         containerColor = Panel, dragHandle = { Grabber() }) {
            Column(Modifier.padding(horizontal = 16.dp).padding(bottom = 24.dp).navigationBarsPadding()) {
                Text("Routine", style = DisplayStyle, color = Text1, fontSize = 26.sp, modifier = Modifier.padding(start = 4.dp, bottom = 10.dp))
                RoutineCard(chores)
            }
        }
    }
}

// ---------- pieces ----------

private val CLOCK = DateTimeFormatter.ofPattern("h:mm", Locale.US)
private val AMPM = DateTimeFormatter.ofPattern("a", Locale.US)
private val DAY = DateTimeFormatter.ofPattern("EEEE · MMMM d", Locale.US)
private val SHORT_DAY = DateTimeFormatter.ofPattern("EEE, MMM d", Locale.US)

private fun clockOf(t: LocalDateTime) = CLOCK.format(t) + " " + AMPM.format(t)

private data class KindLook(val color: Color, val icon: ImageVector, val name: String)

@Composable
private fun look(kind: EntryKind) = when (kind) {
    EntryKind.CLASS -> KindLook(Lavender, Icons.Filled.School, "class")
    EntryKind.EVENT -> KindLook(Mint, Icons.Filled.Event, "event")
    EntryKind.REMINDER -> KindLook(Butter, Icons.Filled.NotificationsActive, "reminder")
    EntryKind.DUE -> KindLook(Peach, Icons.AutoMirrored.Filled.Assignment, "due")
    EntryKind.TODO -> KindLook(Accent0, Icons.Filled.CheckCircle, "todo")
    EntryKind.ROUTINE -> KindLook(Accent0, Icons.Filled.Repeat, "routine")
}

/** What she'd say looking at your day. */
internal fun herLine(plan: DayPlan, now: LocalDateTime): String {
    val next = plan.today.drop(plan.nowIndex(now)).firstOrNull()
    val first = when {
        next == null && plan.today.isEmpty() -> "A free day, nothing on the clock."
        next == null -> "That's everything on the clock for today."
        next.at!! <= now -> "You're in ${next.title} right now."
        next.kind == EntryKind.DUE -> "${next.title} is due at ${clockOf(next.at)}."
        else -> "Next up: ${next.title} at ${clockOf(next.at)}."
    }
    val second = when {
        plan.checklist.isEmpty() -> ""
        plan.left == 0 -> " Checklist all done. Proud of you."
        plan.left == 1 -> " One thing left on your list."
        else -> " ${plan.left} things left on your list."
    }
    return first + second
}

@Composable
private fun Header(plan: DayPlan, now: LocalDateTime, emotion: String, note: String) {
    Column(Modifier.padding(start = 6.dp, end = 6.dp, bottom = 6.dp)) {
        Label(DAY.format(now), color = Accent0)
        Text("Today", style = DisplayStyle, color = Text1, fontSize = 44.sp, lineHeight = 48.sp)
        Row(Modifier.padding(top = 14.dp), verticalAlignment = Alignment.Top) {
            FaceAvatar(emotion, 46.dp)
            Box(
                Modifier.padding(start = 10.dp).clip(RoundedCornerShape(topStart = 4.dp, topEnd = 20.dp, bottomEnd = 20.dp, bottomStart = 20.dp))
                    .background(Color.White.copy(alpha = 0.075f)).padding(horizontal = 14.dp, vertical = 10.dp),
            ) { Text(herLine(plan, now), color = Text1, fontSize = 14.5.sp, lineHeight = 20.sp) }
        }
        OfflineNote(Modifier.padding(top = 10.dp))
        if (note.isNotBlank()) Text(note, color = Amber, fontSize = 12.5.sp, modifier = Modifier.padding(top = 6.dp))
    }
}

@Composable
private fun SectionHead(title: String, trailing: String = "", action: (@Composable () -> Unit)? = null) {
    Row(Modifier.fillMaxWidth().padding(start = 6.dp, top = 22.dp, bottom = 10.dp), verticalAlignment = Alignment.CenterVertically) {
        Text(title, style = DisplayStyle, color = Text1, fontSize = 21.sp, modifier = Modifier.weight(1f))
        if (trailing.isNotBlank()) Text(trailing, color = Text2, fontSize = 12.5.sp, modifier = Modifier.padding(end = 4.dp))
        action?.invoke()
    }
}

@Composable
private fun Progress(f: Float) {
    val v by animateFloatAsState(f, label = "progress")
    Box(Modifier.fillMaxWidth().padding(start = 6.dp, end = 6.dp, bottom = 10.dp).height(6.dp).clip(RoundedCornerShape(50))
            .background(Color.White.copy(alpha = 0.07f))) {
        Box(Modifier.fillMaxWidth(v.coerceIn(0f, 1f)).fillMaxHeight().clip(RoundedCornerShape(50)).background(Accent0))
    }
}

@Composable
private fun Quiet(text: String) =
    Text(text, color = Text2, fontSize = 14.sp, modifier = Modifier.padding(start = 6.dp, top = 2.dp, bottom = 4.dp))

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun AllDay(list: List<Entry>) {
    FlowRow(Modifier.padding(start = 4.dp, bottom = 10.dp), horizontalArrangement = Arrangement.spacedBy(8.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp)) {
        list.forEach { e -> Chip(e.title + if (e.kind == EntryKind.DUE) " · due" else "", selected = true, color = look(e.kind).color, icon = look(e.kind).icon) }
    }
}

@Composable
private fun NowLine(now: LocalDateTime) {
    Row(Modifier.fillMaxWidth().padding(vertical = 4.dp), verticalAlignment = Alignment.CenterVertically) {
        Text("now", color = Navy, fontSize = 11.sp, fontWeight = FontWeight.Bold,
             modifier = Modifier.width(58.dp).clip(RoundedCornerShape(50)).background(Accent0).padding(vertical = 2.dp),
             textAlign = androidx.compose.ui.text.style.TextAlign.Center)
        Spacer(Modifier.width(8.dp))
        Box(Modifier.size(10.dp).clip(CircleShape).background(Accent0))
        Box(Modifier.weight(1f).height(1.5.dp).background(Accent0.copy(alpha = 0.6f)))
        Text(clockOf(now), color = Accent0, fontSize = 11.sp, modifier = Modifier.padding(start = 6.dp))
    }
}

@Composable
private fun TimelineRow(e: Entry, past: Boolean, first: Boolean, last: Boolean) {
    val k = look(e.kind)
    val context = LocalContext.current
    val rail = Color.White.copy(alpha = 0.10f)
    Row(Modifier.fillMaxWidth().height(IntrinsicSize.Min).alpha(if (past) 0.5f else 1f), verticalAlignment = Alignment.CenterVertically) {
        Column(Modifier.width(58.dp), horizontalAlignment = Alignment.End) {
            if (e.sub == "missed" || e.sub.startsWith("missed")) Text("missed", color = Amber, fontSize = 12.sp, fontWeight = FontWeight.Bold)
            else {
                Text(CLOCK.format(e.at!!), color = Text1, fontSize = 15.sp, fontWeight = FontWeight.Bold)
                Text(AMPM.format(e.at), color = Text2, fontSize = 10.5.sp)
            }
        }
        Box(Modifier.width(26.dp).fillMaxHeight().drawBehind {
            val x = size.width / 2
            drawLine(rail, Offset(x, if (first) size.height / 2 else 0f), Offset(x, if (last) size.height / 2 else size.height), 3f)
        }, contentAlignment = Alignment.Center) {
            Box(Modifier.size(12.dp).clip(CircleShape).background(k.color).border(2.dp, Navy, CircleShape))
        }
        Row(
            Modifier.weight(1f).padding(vertical = 4.dp).clip(RoundedCornerShape(18.dp)).background(k.color.copy(alpha = 0.09f))
                .then(if (e.link.isNotBlank()) Modifier.clickable { runCatching { context.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(e.link))) } } else Modifier)
                .padding(horizontal = 14.dp, vertical = 11.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Column(Modifier.weight(1f)) {
                Text(e.title, color = Text1, fontSize = 15.5.sp, fontWeight = FontWeight.Bold, maxLines = 2, overflow = TextOverflow.Ellipsis)
                val sub = listOf(if (e.kind == EntryKind.DUE) "due" else "", e.sub.removePrefix("missed").trim(' ', '·'),
                                 e.end?.takeIf { e.kind == EntryKind.EVENT }?.let { "until " + clockOf(it) } ?: "",
                                 if (e.dirty) "not synced yet" else "").filter { it.isNotBlank() }.joinToString(" · ")
                if (sub.isNotBlank()) Text(sub, color = Text2, fontSize = 12.5.sp, maxLines = 1, overflow = TextOverflow.Ellipsis)
            }
            Icon(k.icon, k.name, tint = k.color, modifier = Modifier.size(18.dp))
        }
    }
}

@Composable
private fun CheckRow(e: Entry) {
    val context = LocalContext.current
    val tick = { if (e.kind == EntryKind.ROUTINE) Routine.tick(context, e.id, !e.done) else Offline.tickTodo(context, e.id, !e.done) }
    val fill by animateColorAsState(if (e.done) Accent0 else Color.Transparent, label = "tick")
    Row(
        Modifier.fillMaxWidth().padding(vertical = 3.dp).clip(RoundedCornerShape(18.dp)).background(Color.White.copy(alpha = 0.05f))
            .clickable { tick() }.padding(horizontal = 14.dp, vertical = 12.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Box(Modifier.size(24.dp).clip(CircleShape).background(fill).border(2.dp, if (e.done) Accent0 else Dim, CircleShape),
            contentAlignment = Alignment.Center) {
            if (e.done) Icon(Icons.Filled.Check, null, tint = Navy, modifier = Modifier.size(16.dp))
        }
        Column(Modifier.weight(1f).padding(start = 12.dp)) {
            Text(e.title, color = if (e.done) Text2 else Text1, fontSize = 15.5.sp,
                 textDecoration = if (e.done) TextDecoration.LineThrough else null)
            val sub = listOf(e.sub, if (e.dirty) "not synced yet" else "").filter { it.isNotBlank() }.joinToString(" · ")
            if (sub.isNotBlank()) Text(sub, color = Text2, fontSize = 12.sp)
        }
        if (e.kind == EntryKind.ROUTINE) Icon(Icons.Filled.Repeat, "routine", tint = Dim, modifier = Modifier.size(16.dp))
    }
}

@Composable
private fun DayHead(day: LocalDate, today: LocalDate) {
    Text(if (day == today.plusDays(1)) "Tomorrow · " + day.dayOfWeek.name.lowercase().replaceFirstChar { it.uppercase() }.take(3)
         else SHORT_DAY.format(day),
         color = Accent0, fontSize = 13.sp, fontWeight = FontWeight.Bold, modifier = Modifier.padding(start = 6.dp, top = 10.dp, bottom = 4.dp))
}

@Composable
private fun LaterRow(e: Entry) {
    val k = look(e.kind)
    Row(Modifier.fillMaxWidth().padding(vertical = 3.dp).clip(RoundedCornerShape(16.dp)).background(Color.White.copy(alpha = 0.045f))
            .padding(horizontal = 14.dp, vertical = 10.dp), verticalAlignment = Alignment.CenterVertically) {
        Icon(k.icon, k.name, tint = k.color, modifier = Modifier.size(18.dp))
        Column(Modifier.weight(1f).padding(start = 12.dp)) {
            Text(e.title, color = Text1, fontSize = 14.5.sp, maxLines = 1, overflow = TextOverflow.Ellipsis)
            val sub = listOf(e.sub, if (e.dirty) "not synced yet" else "").filter { it.isNotBlank() }.joinToString(" · ")
            if (sub.isNotBlank()) Text(sub, color = Text2, fontSize = 12.sp, maxLines = 1, overflow = TextOverflow.Ellipsis)
        }
        Text(if (e.hasTime) clockOf(e.at!!) else "all day", color = Text2, fontSize = 12.5.sp)
    }
}

/** Swipe right ticks (todos, routine), swipe left removes (todos, reminders, your own events). */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun Swipeable(e: Entry, content: @Composable () -> Unit) {
    val context = LocalContext.current
    val canTick = e.kind == EntryKind.TODO || e.kind == EntryKind.ROUTINE
    val canRemove = e.kind == EntryKind.TODO || e.kind == EntryKind.REMINDER || e.kind == EntryKind.EVENT
    if (!canTick && !canRemove) { content(); return }
    val state = rememberSwipeToDismissBoxState(confirmValueChange = { v ->
        when (v) {
            SwipeToDismissBoxValue.StartToEnd -> {
                if (e.kind == EntryKind.ROUTINE) Routine.tick(context, e.id, !e.done) else Offline.tickTodo(context, e.id, !e.done)
                false
            }
            SwipeToDismissBoxValue.EndToStart -> {
                when (e.kind) {
                    EntryKind.TODO -> Offline.deleteTodo(context, e.id)
                    EntryKind.REMINDER -> Offline.cancelReminder(context, e.id)
                    else -> Offline.cancelEvent(context, e.id)
                }
                Toast.makeText(context, "Removed “${e.title}”", Toast.LENGTH_SHORT).show()
                true
            }
            else -> false
        }
    }, positionalThreshold = { it * 0.4f })
    SwipeToDismissBox(state, enableDismissFromStartToEnd = canTick, enableDismissFromEndToStart = canRemove, backgroundContent = {
        if (state.dismissDirection == SwipeToDismissBoxValue.Settled) return@SwipeToDismissBox
        val toRight = state.dismissDirection == SwipeToDismissBoxValue.StartToEnd
        Row(Modifier.fillMaxSize().padding(vertical = 4.dp).clip(RoundedCornerShape(18.dp))
                .background(if (toRight) Mint.copy(alpha = 0.25f) else Red.copy(alpha = 0.25f)).padding(horizontal = 20.dp),
            verticalAlignment = Alignment.CenterVertically, horizontalArrangement = if (toRight) Arrangement.Start else Arrangement.End) {
            Icon(if (toRight) Icons.Filled.Check else Icons.Filled.Delete, null, tint = if (toRight) Mint else Red)
        }
    }) { content() }
}

@Composable
private fun Grabber() =
    Box(Modifier.padding(top = 10.dp, bottom = 6.dp).size(width = 40.dp, height = 4.dp).clip(RoundedCornerShape(50)).background(Dim))

// ---------- the "+" panel ----------

private enum class AddKind(val label: String, val hint: String) {
    TODO("To-do", "milk, eggs and bread"),
    REMINDER("Reminder", "call mom tomorrow 5pm"),
    EVENT("Event", "dinner with Maya fri 7pm"),
    ROUTINE("Routine", "water the plants"),
}

private val ROUTINE_KINDS = listOf("daily" to "Daily", "weekdays" to "Weekdays", "weekly" to "Weekly", "monthly" to "Monthly")

/** One box for everything: pick a kind (or let it guess from a time in the text) and type. */
@OptIn(ExperimentalLayoutApi::class)
@Composable
fun AddPanel(now: LocalDateTime = LocalDateTime.now(), startText: String = "", onDone: () -> Unit) {
    val context = LocalContext.current
    var text by remember { mutableStateOf(startText) }
    var picked by remember { mutableStateOf<AddKind?>(null) }
    var pickedWhen by remember { mutableStateOf<When?>(null) }
    var freq by remember { mutableStateOf("daily") }
    var weekday by remember { mutableIntStateOf(now.dayOfWeek.value - 1) }
    var monthDay by remember { mutableIntStateOf(now.dayOfMonth) }
    val guess = QuickAdd.parse(text, now)
    val kind = picked ?: if (guess.wantsReminder || guess.whenAt != null) AddKind.REMINDER else AddKind.TODO
    val timed = kind == AddKind.REMINDER || kind == AddKind.EVENT
    val whenAt = pickedWhen ?: guess.whenAt
    val title = if (timed) guess.title else text.trim()
    val ready = title.isNotBlank() && (!timed || whenAt != null)

    fun add() {
        if (!ready) return
        val msg = when (kind) {
            AddKind.TODO -> Offline.addTodos(context, title).let { if (it.size == 1) "Added to your list" else "Added ${it.size} things to your list" }
            AddKind.REMINDER -> Offline.addReminder(context, title, whenAt!!.at).let { "I'll remind you " + whenLabel(it.dueMs).replaceFirstChar { c -> c.lowercase() } }
            AddKind.EVENT -> Offline.addEvent(context, title, whenAt!!).let { "Added: ${it.title}, ${whenLabel(it.startMs, !it.allDay)}" }
            AddKind.ROUTINE -> Routine.add(context, title, RoutineLogic.freq(freq, weekday, monthDay)).let { "Added to your routine: ${RoutineLogic.label(it.freq)}" }
        }
        Toast.makeText(context, msg, Toast.LENGTH_SHORT).show()
        onDone()
    }

    Column(Modifier.fillMaxWidth().padding(horizontal = 20.dp).padding(bottom = 22.dp).navigationBarsPadding()) {
        Text("Add something", style = DisplayStyle, color = Text1, fontSize = 26.sp, modifier = Modifier.padding(bottom = 14.dp))
        FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            AddKind.entries.forEach { k ->
                val color = when (k) {
                    AddKind.REMINDER -> Butter
                    AddKind.EVENT -> Mint
                    else -> Accent0
                }
                val icon = when (k) {
                    AddKind.TODO -> Icons.Filled.CheckCircle
                    AddKind.REMINDER -> Icons.Filled.NotificationsActive
                    AddKind.EVENT -> Icons.Filled.Event
                    AddKind.ROUTINE -> Icons.Filled.Repeat
                }
                Chip(k.label, selected = kind == k, color = color, icon = icon) { picked = k }
            }
        }
        Spacer(Modifier.height(14.dp))
        Row(Modifier.fillMaxWidth().clip(RoundedCornerShape(20.dp)).background(Color.White.copy(alpha = 0.07f))
                .padding(start = 16.dp, end = 6.dp), verticalAlignment = Alignment.CenterVertically) {
            Box(Modifier.weight(1f).padding(vertical = 15.dp)) {
                if (text.isEmpty()) Text(kind.hint, color = Dim, fontSize = 16.sp)
                BasicTextField(text, { text = it }, Modifier.fillMaxWidth(), singleLine = true,
                               textStyle = TextStyle(color = Text1, fontSize = 16.sp, fontFamily = LocalLook.current.font.body),
                               cursorBrush = SolidColor(Accent0),
                               keyboardOptions = KeyboardOptions(capitalization = KeyboardCapitalization.Sentences, imeAction = ImeAction.Done),
                               keyboardActions = KeyboardActions(onDone = { add() }))
            }
            if (timed) Box(Modifier.size(44.dp).clip(CircleShape).clickable {
                DatePickerDialog(context, { _, y, m, d ->
                    TimePickerDialog(context, { _, h, min -> pickedWhen = When(LocalDateTime.of(y, m + 1, d, h, min), true) },
                                     9, 0, false).apply {
                        if (kind == AddKind.EVENT) setButton(android.content.DialogInterface.BUTTON_NEUTRAL, "All day") { _, _ ->
                            pickedWhen = When(LocalDate.of(y, m + 1, d).atStartOfDay(), false)
                        }
                    }.show()
                }, now.year, now.monthValue - 1, now.dayOfMonth).show()
            }, contentAlignment = Alignment.Center) { Icon(Icons.Filled.CalendarMonth, "Pick a date", tint = Accent0) }
        }
        val hint = when {
            timed && whenAt != null -> "→ " + (if (title.isNotBlank()) "“$title”, " else "") + whenLabel(whenAt.at, whenAt.hasTime) +
                                       if (!whenAt.hasTime && kind == AddKind.EVENT) " (all day)" else ""
            timed && text.isNotBlank() -> "Add a time: “tomorrow 5pm”, “fri 9am”, “in 2 hours”, or pick one"
            kind == AddKind.TODO && text.contains(',') -> "→ ${com.manaskhare.sanae.TodoText.split(text).size} things"
            else -> ""
        }
        if (hint.isNotBlank()) Text(hint, color = if (timed && whenAt == null) Amber else Text2, fontSize = 13.sp,
                                    modifier = Modifier.padding(start = 6.dp, top = 8.dp))
        if (kind == AddKind.ROUTINE) {
            FlowRow(Modifier.padding(top = 12.dp), horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                ROUTINE_KINDS.forEach { (k, name) -> Chip(name, selected = freq == k) { freq = k } }
            }
            if (freq == "weekly") Row(Modifier.padding(top = 10.dp), horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                listOf("M", "T", "W", "T", "F", "S", "S").forEachIndexed { i, d ->
                    val on = weekday == i
                    Box(Modifier.size(36.dp).clip(CircleShape).background(if (on) Accent0 else Color.White.copy(alpha = 0.06f))
                            .clickable { weekday = i }, contentAlignment = Alignment.Center) {
                        Text(d, color = if (on) Navy else Text2, fontSize = 13.sp, fontWeight = FontWeight.Bold)
                    }
                }
            }
            if (freq == "monthly") Row(Modifier.padding(top = 10.dp), verticalAlignment = Alignment.CenterVertically) {
                Text("On the ${RoutineLogic.ordinal(monthDay)}", color = Text1, modifier = Modifier.weight(1f))
                Chip("−") { monthDay = if (monthDay <= 1) 31 else monthDay - 1 }
                Spacer(Modifier.width(8.dp))
                Chip("+") { monthDay = if (monthDay >= 31) 1 else monthDay + 1 }
            }
        }
        Spacer(Modifier.height(18.dp))
        SoftButton(if (kind == AddKind.TODO) "Add to list" else "Add ${kind.label.lowercase()}", Modifier.fillMaxWidth(), enabled = ready) { add() }
    }
}

/** Reads from the local database off the main thread whenever `key` changes. */
@Composable
private fun <T> produceList(key: Any, read: () -> List<T>) =
    androidx.compose.runtime.produceState(initialValue = emptyList<T>(), key) { value = withContext(Dispatchers.IO) { read() } }

@Composable
fun Field(value: String, onChange: (String) -> Unit, hint: String, modifier: Modifier = Modifier.fillMaxWidth()) =
    OutlinedTextField(
        value = value, onValueChange = onChange, modifier = modifier, singleLine = true,
        placeholder = { Text(hint, color = Dim, fontSize = 14.sp) }, shape = RoundedCornerShape(18.dp),
        colors = OutlinedTextFieldDefaults.colors(unfocusedBorderColor = Color.Transparent, focusedBorderColor = Accent0.copy(alpha = 0.6f),
                                                  unfocusedContainerColor = Color.White.copy(alpha = 0.06f),
                                                  focusedContainerColor = Color.White.copy(alpha = 0.08f),
                                                  focusedTextColor = Text1, unfocusedTextColor = Text1, cursorColor = Accent0),
    )
