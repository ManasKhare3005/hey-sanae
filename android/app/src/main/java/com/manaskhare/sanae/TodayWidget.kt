package com.manaskhare.sanae

import android.content.Context
import android.content.Intent
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.glance.GlanceId
import androidx.glance.GlanceModifier
import androidx.glance.Image
import androidx.glance.ImageProvider
import androidx.glance.LocalSize
import androidx.glance.action.ActionParameters
import androidx.glance.action.actionParametersOf
import androidx.glance.action.clickable
import androidx.glance.appwidget.GlanceAppWidget
import androidx.glance.appwidget.GlanceAppWidgetReceiver
import androidx.glance.appwidget.LinearProgressIndicator
import androidx.glance.appwidget.SizeMode
import androidx.glance.appwidget.action.ActionCallback
import androidx.glance.appwidget.action.actionRunCallback
import androidx.glance.appwidget.action.actionStartActivity
import androidx.glance.appwidget.cornerRadius
import androidx.glance.appwidget.lazy.LazyColumn
import androidx.glance.appwidget.lazy.items
import androidx.glance.appwidget.provideContent
import androidx.glance.appwidget.updateAll
import androidx.glance.background
import androidx.glance.layout.Alignment
import androidx.glance.layout.Box
import androidx.glance.layout.Column
import androidx.glance.layout.Row
import androidx.glance.layout.Spacer
import androidx.glance.layout.fillMaxSize
import androidx.glance.layout.fillMaxWidth
import androidx.glance.layout.height
import androidx.glance.layout.padding
import androidx.glance.layout.size
import androidx.glance.layout.width
import androidx.glance.text.FontWeight
import androidx.glance.text.Text
import androidx.glance.text.TextAlign
import androidx.glance.text.TextDecoration
import androidx.glance.text.TextStyle
import androidx.glance.unit.ColorProvider
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.json.JSONObject
import java.time.LocalDate
import java.time.LocalDateTime
import java.time.format.DateTimeFormatter

/** What the widget shows: the next few things today (same picks as the watch) and the todo list. */
data class WidgetData(val name: String, val greeting: String, val day: String, val next: List<GlanceItem>,
                      val todos: List<LocalTodo>, val lastSync: Long, val now: LocalDateTime, val nowMs: Long,
                      val routine: List<LocalChore> = emptyList())

/**
 * Home-screen widget: today's next things (reminders, Sanae calendar, Canvas due items and
 * classes), the todo list (tap a row to tick or untick it, works offline), and buttons to talk to her.
 * Everything comes from the phone's own copy, so it works with the laptop off.
 *
 * The list is read again on every refresh: Glance keeps one session per widget for a while and
 * only recomposes it, so data read once in provideGlance went stale (a ticked todo couldn't be
 * unticked: the row still carried "done = true").
 */
class TodayWidget : GlanceAppWidget() {
    override val sizeMode = SizeMode.Exact

    override suspend fun provideGlance(context: Context, id: GlanceId) {
        val first = withContext(Dispatchers.IO) { load(context) }
        provideContent {
            val version by changes.collectAsState()
            var data by remember { mutableStateOf(first) }
            LaunchedEffect(version) {
                if (version > 0) data = withContext(Dispatchers.IO) { load(context) }
            }
            Content(context, data)
        }
    }

    companion object {
        private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Default)
        private val changes = MutableStateFlow(0)

        /** Redraw every placed widget (after a sync or a change made on the phone). */
        fun refresh(context: Context) {
            val app = context.applicationContext
            changes.value += 1                                 // a running session reloads its list
            scope.launch { runCatching { TodayWidget().updateAll(app) } }
        }

        fun load(context: Context): WidgetData {
            val db = LocalDb.get(context)
            val prefs = Prefs(context)
            val today = prefs.todayJson.takeIf { it.isNotBlank() }?.let { runCatching { JSONObject(it) }.getOrNull() }
            val nowMs = System.currentTimeMillis()
            val now = LocalDateTime.now()
            val next = Glance.build(today, db.reminders(), db.events(), nowMs, limit = 3).filter { it.kind != "todo" }
            return WidgetData(Persona.name(context), WidgetLogic.greeting(now.hour),
                              LocalDate.now().format(DateTimeFormatter.ofPattern("EEEE, MMM d")),
                              next, WidgetLogic.todoOrder(db.shownTodos()), prefs.lastSync, now, nowMs,
                              RoutineLogic.order(db.chores("status = 'active'"), now.toLocalDate())
                                  .filter { RoutineLogic.dueOn(it.freq, now.toLocalDate()) })
        }
    }
}

class TodayWidgetReceiver : GlanceAppWidgetReceiver() {
    override val glanceAppWidget = TodayWidget()
}

/** A todo row on the widget: tick or untick, saved on the phone and synced later. */
class ToggleTodo : ActionCallback {
    override suspend fun onAction(context: Context, glanceId: GlanceId, parameters: ActionParameters) {
        val uid = parameters[UID] ?: return
        withContext(Dispatchers.IO) {
            val now = LocalDb.get(context).todo(uid) ?: return@withContext
            Offline.tickTodo(context, uid, parameters[DONE] ?: !now.done)      // refreshes the widget
        }
    }

    companion object {
        val UID = ActionParameters.Key<String>("uid")
        val DONE = ActionParameters.Key<Boolean>("done")
    }
}

/** A routine row on the widget: tick or untick it for today. */
class ToggleChore : ActionCallback {
    override suspend fun onAction(context: Context, glanceId: GlanceId, parameters: ActionParameters) {
        val uid = parameters[ToggleTodo.UID] ?: return
        val done = parameters[ToggleTodo.DONE] ?: return
        withContext(Dispatchers.IO) { Routine.tick(context, uid, done) }      // refreshes the widget
    }
}

/** "Clear done" on the widget. */
class ClearDoneTodos : ActionCallback {
    override suspend fun onAction(context: Context, glanceId: GlanceId, parameters: ActionParameters) {
        withContext(Dispatchers.IO) { Offline.clearDoneTodos(context) }
    }
}

/** Tap the "synced ..." line: sync with the laptop now (the widget redraws after). */
class SyncNow : ActionCallback {
    override suspend fun onAction(context: Context, glanceId: GlanceId, parameters: ActionParameters) {
        Sync.trigger(context, 0)
        TodayWidget.refresh(context)
    }
}

private val Bg = Color(0xF2150D16)
private val Card = Color(0xFF2A1A28)
private val Text1 = ColorProvider(Color(0xFFFFF3EE))
private val Text2 = ColorProvider(Color(0xFFCDB6C2))
private val Text3 = ColorProvider(Color(0xFF9C8695))
private val Cyan = Color(0xFFFF9EB8)
private val CyanText = ColorProvider(Cyan)
private val KIND = mapOf("class" to Color(0xFFC9B6FF), "due" to Color(0xFFFFC6A5), "reminder" to Color(0xFFF8D98B),
                         "event" to Color(0xFF9FE3C5))

@Composable
private fun Content(context: Context, data: WidgetData) {
    val app = Intent(context, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_SINGLE_TOP)
    val openToday = actionStartActivity(Intent(app).putExtra(MainActivity.EXTRA_TAB, MainActivity.TAB_TODAY))
    val talk = actionStartActivity(assistIntent(context))
    val tall = LocalSize.current.height >= 230.dp
    Column(GlanceModifier.fillMaxSize().background(Bg).cornerRadius(24.dp).padding(14.dp)) {
        // Header: her face + greeting, Talk button
        Row(GlanceModifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
            Image(ImageProvider(R.drawable.face_happy), contentDescription = data.name,
                  modifier = GlanceModifier.size(38.dp).cornerRadius(19.dp).clickable(talk))
            Spacer(GlanceModifier.width(10.dp))
            Column(GlanceModifier.defaultWeight().clickable(openToday)) {
                Text(data.greeting, style = TextStyle(color = Text1, fontSize = 16.sp, fontWeight = FontWeight.Bold), maxLines = 1)
                Text(data.day, style = TextStyle(color = Text2, fontSize = 12.sp), maxLines = 1)
            }
            Box(GlanceModifier.background(Color(0x33FF9EB8)).cornerRadius(18.dp).padding(horizontal = 14.dp, vertical = 7.dp)
                    .clickable(talk)) {
                Text("Talk", style = TextStyle(color = CyanText, fontSize = 13.sp, fontWeight = FontWeight.Medium))
            }
        }
        Spacer(GlanceModifier.height(10.dp))

        // Next up
        if (data.next.isEmpty()) {
            Text("Nothing else on today", style = TextStyle(color = Text3, fontSize = 12.sp),
                 modifier = GlanceModifier.clickable(openToday))
        } else {
            Column(GlanceModifier.fillMaxWidth().background(Card).cornerRadius(14.dp).padding(horizontal = 10.dp, vertical = 6.dp)
                    .clickable(openToday)) {
                data.next.take(if (tall) 3 else 2).forEach { item ->
                    val soon = WidgetLogic.soon(item, data.nowMs)
                    Row(GlanceModifier.fillMaxWidth().padding(vertical = 3.dp), verticalAlignment = Alignment.CenterVertically) {
                        Box(GlanceModifier.size(7.dp).cornerRadius(4.dp).background(KIND[item.kind] ?: Cyan)) {}
                        Spacer(GlanceModifier.width(8.dp))
                        Text(WidgetLogic.timeLabel(item, data.now),
                             style = TextStyle(color = if (soon) CyanText else Text2, fontSize = 12.sp,
                                               fontWeight = if (soon) FontWeight.Bold else FontWeight.Normal),
                             modifier = GlanceModifier.width(84.dp), maxLines = 1)
                        Text(item.title, style = TextStyle(color = Text1, fontSize = 13.sp), maxLines = 1)
                    }
                }
            }
        }
        Spacer(GlanceModifier.height(10.dp))

        // Todos
        Row(GlanceModifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
            Text(WidgetLogic.todoHeader(data.todos), style = TextStyle(color = Text2, fontSize = 12.sp, fontWeight = FontWeight.Medium),
                 modifier = GlanceModifier.defaultWeight())
            if (data.todos.any { it.done }) {
                Text("Clear done", style = TextStyle(color = Text3, fontSize = 12.sp),
                     modifier = GlanceModifier.padding(end = 12.dp).clickable(actionRunCallback<ClearDoneTodos>()))
            }
            Text("+ Add", style = TextStyle(color = CyanText, fontSize = 12.sp, fontWeight = FontWeight.Medium),
                 modifier = GlanceModifier.clickable(openToday))
        }
        if (data.todos.isNotEmpty()) {
            Spacer(GlanceModifier.height(5.dp))
            LinearProgressIndicator(progress = WidgetLogic.progress(data.todos),
                                    modifier = GlanceModifier.fillMaxWidth().height(3.dp),
                                    color = CyanText, backgroundColor = ColorProvider(Color(0xFF3A2238)))
        }
        Spacer(GlanceModifier.height(4.dp))
        if (data.todos.isEmpty() && data.routine.isEmpty()) {
            Box(GlanceModifier.fillMaxWidth().defaultWeight().padding(top = 4.dp).clickable(talk)) {
                Text("Nothing on your list. Tap Talk and say “add milk to my list”.",
                     style = TextStyle(color = Text3, fontSize = 12.sp))
            }
        } else {
            LazyColumn(GlanceModifier.fillMaxWidth().defaultWeight()) {
                if (data.routine.isNotEmpty()) {
                    item(itemId = 1L) {
                        Text(WidgetLogic.routineHeader(data.routine, data.now.toLocalDate()),
                             style = TextStyle(color = Text3, fontSize = 11.sp), modifier = GlanceModifier.padding(top = 2.dp))
                    }
                    items(data.routine, itemId = { ("r" + it.uid).hashCode().toLong() }) { c ->
                        val done = RoutineLogic.done(c, data.now.toLocalDate())
                        CheckRow(c.text, done, actionRunCallback<ToggleChore>(actionParametersOf(ToggleTodo.UID to c.uid, ToggleTodo.DONE to !done)))
                    }
                    if (data.todos.isNotEmpty()) item(itemId = 2L) {
                        Text("To do", style = TextStyle(color = Text3, fontSize = 11.sp), modifier = GlanceModifier.padding(top = 4.dp))
                    }
                }
                items(data.todos, itemId = { it.uid.hashCode().toLong() }) { t -> TodoRow(t) }
            }
        }
        Text(WidgetLogic.syncedLabel(data.lastSync, data.nowMs),
             style = TextStyle(color = Text3, fontSize = 10.sp, textAlign = TextAlign.End),
             modifier = GlanceModifier.fillMaxWidth().padding(top = 4.dp).clickable(actionRunCallback<SyncNow>()))
    }
}

@Composable
private fun TodoRow(t: LocalTodo) =
    // The whole row is the tap target; the state it sets comes from this (fresh) list
    CheckRow(t.text, t.done, actionRunCallback<ToggleTodo>(actionParametersOf(ToggleTodo.UID to t.uid, ToggleTodo.DONE to !t.done)))

@Composable
private fun CheckRow(text: String, done: Boolean, toggle: androidx.glance.action.Action) {
    Row(GlanceModifier.fillMaxWidth().padding(vertical = 5.dp).clickable(toggle), verticalAlignment = Alignment.CenterVertically) {
        Box(GlanceModifier.size(20.dp).cornerRadius(10.dp).background(if (done) Cyan else Color(0xFF6E5868)),
            contentAlignment = Alignment.Center) {
            if (done) {
                Text("✓", style = TextStyle(color = ColorProvider(Color(0xFF150D16)), fontSize = 12.sp, fontWeight = FontWeight.Bold))
            } else {
                Box(GlanceModifier.size(16.dp).cornerRadius(8.dp).background(Bg)) {}
            }
        }
        Spacer(GlanceModifier.width(10.dp))
        Text(text, style = TextStyle(color = if (done) Text3 else Text1, fontSize = 14.sp,
                                       textDecoration = if (done) TextDecoration.LineThrough else TextDecoration.None),
             maxLines = 2)
    }
}
