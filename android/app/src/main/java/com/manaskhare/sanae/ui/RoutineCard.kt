package com.manaskhare.sanae.ui

import android.app.TimePickerDialog
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Close
import androidx.compose.material3.Checkbox
import androidx.compose.material3.CheckboxDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.SegmentedButton
import androidx.compose.material3.SegmentedButtonDefaults
import androidx.compose.material3.SingleChoiceSegmentedButtonRow
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.style.TextDecoration
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.manaskhare.sanae.LocalChore
import com.manaskhare.sanae.Prefs
import com.manaskhare.sanae.Routine
import com.manaskhare.sanae.RoutineLogic
import com.manaskhare.sanae.WindDown
import java.time.LocalDate
import java.time.LocalTime

private val KINDS = listOf("daily" to "Daily", "weekdays" to "Weekdays", "weekly" to "Weekly", "monthly" to "Monthly")
private val WEEKDAYS = listOf("M", "T", "W", "T", "F", "S", "S")

/**
 * The routine: tasks that come back every day / week / month. Today's ones can be ticked (and
 * unticked); the rest show when they're due. Unticked ones at the evening check -> a notification.
 */
@Composable
internal fun RoutineCard(chores: List<LocalChore>, today: LocalDate = LocalDate.now()) {
    val context = LocalContext.current
    val prefs = remember { Prefs(context) }
    var draft by remember { mutableStateOf("") }
    var kind by remember { mutableStateOf("daily") }
    var weekday by remember { mutableIntStateOf(today.dayOfWeek.value - 1) }
    var monthDay by remember { mutableIntStateOf(today.dayOfMonth) }
    var checkAt by remember { mutableStateOf(runCatching { LocalTime.parse(prefs.routineCheckAt) }.getOrDefault(LocalTime.of(21, 0))) }
    var checkOn by remember { mutableStateOf(prefs.routineCheckOn) }

    val ordered = RoutineLogic.order(chores, today)
    val dueToday = ordered.filter { RoutineLogic.dueOn(it.freq, today) }
    val left = dueToday.count { !RoutineLogic.done(it, today) }
    Card {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Label("Routine", modifier = Modifier.weight(1f))
            if (dueToday.isNotEmpty()) Label(if (left == 0) "all done today" else "$left left today", color = if (left == 0) Green else Accent0)
        }
        if (chores.isEmpty()) Text("Nothing yet. Add things you do every day, week or month.", color = Text2,
                                   modifier = Modifier.padding(top = 6.dp))
        ordered.forEach { c ->
            val due = RoutineLogic.dueOn(c.freq, today)
            val done = RoutineLogic.done(c, today)
            Row(verticalAlignment = Alignment.CenterVertically) {
                if (due) Checkbox(checked = done, onCheckedChange = { Routine.tick(context, c.uid, it) },
                                  colors = CheckboxDefaults.colors(checkedColor = Cyan, uncheckedColor = Dim, checkmarkColor = Navy))
                else Spacer(Modifier.width(48.dp))
                Column(Modifier.weight(1f).padding(vertical = 4.dp)) {
                    Text(c.text, color = if (done || !due) Text2 else Text1,
                         textDecoration = if (done) TextDecoration.LineThrough else null)
                    Label(RoutineLogic.label(c.freq) + (if (c.dirty) " · not synced yet" else ""))
                }
                IconButton(onClick = { Routine.delete(context, c.uid) }) {
                    Icon(Icons.Filled.Close, contentDescription = "Remove from routine", tint = Dim)
                }
            }
        }
        Spacer(Modifier.height(10.dp))
        Field(draft, { draft = it }, "Add a routine task (water the plants…)")
        Spacer(Modifier.height(8.dp))
        SingleChoiceSegmentedButtonRow(Modifier.fillMaxWidth()) {
            KINDS.forEachIndexed { i, (k, name) ->
                SegmentedButton(selected = kind == k, onClick = { kind = k },
                                shape = SegmentedButtonDefaults.itemShape(i, KINDS.size)) { Text(name, fontSize = 12.sp) }
            }
        }
        if (kind == "weekly") {
            Spacer(Modifier.height(6.dp))
            SingleChoiceSegmentedButtonRow(Modifier.fillMaxWidth()) {
                WEEKDAYS.forEachIndexed { i, d ->
                    SegmentedButton(selected = weekday == i, onClick = { weekday = i },
                                    shape = SegmentedButtonDefaults.itemShape(i, WEEKDAYS.size), icon = {}) { Text(d, fontSize = 12.sp) }
                }
            }
        }
        if (kind == "monthly") {
            Row(verticalAlignment = Alignment.CenterVertically, modifier = Modifier.padding(top = 6.dp)) {
                Text("On the ${RoutineLogic.ordinal(monthDay)}", color = Text1, modifier = Modifier.weight(1f))
                GhostButton("−") { monthDay = if (monthDay <= 1) 31 else monthDay - 1 }
                GhostButton("+") { monthDay = if (monthDay >= 31) 1 else monthDay + 1 }
            }
        }
        Spacer(Modifier.height(8.dp))
        GhostButton("Add") {
            if (draft.isNotBlank()) { Routine.add(context, draft, RoutineLogic.freq(kind, weekday, monthDay)); draft = "" }
        }
        Row(verticalAlignment = Alignment.CenterVertically, modifier = Modifier.padding(top = 6.dp)) {
            Text(if (checkOn) "Evening check at ${WindDown.clock(checkAt)}: I'll tell you if something's still unticked."
                 else "Evening check is off.", color = Text2, fontSize = 12.sp, modifier = Modifier.weight(1f))
            if (checkOn) GhostButton("Change") {
                TimePickerDialog(context, { _, h, m ->
                    checkAt = LocalTime.of(h, m); prefs.routineCheckAt = checkAt.toString(); Routine.arm(context)
                }, checkAt.hour, checkAt.minute, false).show()
            }
            Toggle(checkOn) { on -> checkOn = on; prefs.routineCheckOn = on; Routine.arm(context) }
        }
    }
}
