package com.manaskhare.sanae

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.time.LocalDate
import java.time.LocalDateTime

class TimelineLogicTest {
    private val now = LocalDateTime.of(2026, 10, 22, 13, 0)          // a Thursday
    private val today = now.toLocalDate()
    private fun ms(t: LocalDateTime) = Offline.ms(t)

    @Test fun oneOrderedDay() {
        val plan = Timeline.build(
            now,
            classes = listOf(CanvasItem("CS 101", "Data Mining", today.atTime(10, 30))),
            dueToday = listOf(CanvasItem("Lab 4", "CS 105", today.atTime(23, 59))),
            dueSoon = listOf(CanvasItem("Project report", "CS 101", today.plusDays(1).atTime(23, 59))),
            events = listOf(LocalEvent("e1", "Study group", ms(today.atTime(15, 0)), ms(today.atTime(16, 0))),
                            LocalEvent("e2", "Career fair", ms(today.atStartOfDay()), ms(today.plusDays(2).atStartOfDay()), allDay = true),
                            LocalEvent("e3", "Dinner", ms(today.plusDays(2).atTime(19, 0)), ms(today.plusDays(2).atTime(20, 0))),
                            LocalEvent("e4", "Gone", ms(today.atTime(17, 0)), ms(today.atTime(18, 0)), status = "cancelled")),
            reminders = listOf(LocalReminder("r1", "Call mom", ms(today.atTime(18, 0))),
                               LocalReminder("r2", "Pay rent", ms(today.minusDays(1).atTime(9, 0)))),
        )
        assertEquals(listOf("Pay rent", "CS 101", "Study group", "Call mom", "Lab 4"), plan.today.map { it.title })
        assertEquals("missed", plan.today[0].sub)
        assertEquals(listOf("Career fair"), plan.allDay.map { it.title })
        assertEquals(listOf(today.plusDays(1), today.plusDays(2)), plan.later.map { it.first })
        assertEquals(listOf("Project report"), plan.later[0].second.map { it.title })
        assertEquals(2, plan.nowIndex(now))                              // after the 10:30 class, before 15:00
        assertEquals(2, plan.nowIndex(today.atTime(15, 30)))             // still in the study group
    }

    @Test fun checklistMixesRoutineAndTodosDoneLast() {
        val plan = Timeline.build(
            now,
            todos = listOf(LocalTodo("t1", "Milk", "done"), LocalTodo("t2", "Laundry"), LocalTodo("t3", "x", "deleted")),
            chores = listOf(LocalChore("c1", "Water plants", "daily"), LocalChore("c2", "Bins", "weekly:0"),
                            LocalChore("c3", "Stretch", "daily", doneDay = today.toString())),
        )
        assertEquals(listOf("Water plants", "Laundry", "Stretch", "Milk"), plan.checklist.map { it.title })
        assertEquals(2, plan.left)
        assertEquals(2, plan.doneCount)
    }

    @Test fun isoFromTheLaptop() {
        assertEquals(LocalDateTime.of(2026, 10, 22, 23, 59), Timeline.parseIso("2026-10-22T23:59:00"))
        assertEquals(LocalDate.of(2026, 10, 22).atTime(23, 59), Timeline.parseIso("2026-10-22"))
        assertNull(Timeline.parseIso("soon"))
    }

    @Test fun quickAddFindsTheWhen() {
        val a = QuickAdd.parse("call mom tomorrow 5pm", now)
        assertEquals("call mom", a.title)
        assertEquals(today.plusDays(1).atTime(17, 0), a.whenAt!!.at)
        assertFalse(a.wantsReminder)

        val b = QuickAdd.parse("Remind me to stretch in 20 min", now)
        assertEquals("stretch", b.title)
        assertEquals(now.plusMinutes(20), b.whenAt!!.at)
        assertTrue(b.wantsReminder)

        val c = QuickAdd.parse("friday dinner with Maya", now)
        assertEquals("dinner with Maya", c.title)
        assertEquals(today.plusDays(1), c.whenAt!!.at.toLocalDate())

        val d = QuickAdd.parse("read chapter 5", now)
        assertEquals("read chapter 5", d.title)
        assertNull(d.whenAt)
        assertNull(QuickAdd.parse("tomorrow", now).whenAt)               // a when needs a what
    }
}
