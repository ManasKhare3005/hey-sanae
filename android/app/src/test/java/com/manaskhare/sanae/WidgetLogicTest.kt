package com.manaskhare.sanae

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import java.time.LocalDateTime
import java.time.ZoneId

class WidgetLogicTest {
    private val zone = ZoneId.of("Etc/GMT+7")
    private val now = LocalDateTime.of(2026, 10, 20, 9, 0)
    private fun ms(t: LocalDateTime) = t.atZone(zone).toInstant().toEpochMilli()

    @Test fun greetsByTheHour() {
        assertEquals("Good morning", WidgetLogic.greeting(9))
        assertEquals("Good afternoon", WidgetLogic.greeting(14))
        assertEquals("Good evening", WidgetLogic.greeting(20))
        assertEquals("Up late", WidgetLogic.greeting(1))
    }

    @Test fun shortTimeLabels() {
        assertEquals("3:30 PM", WidgetLogic.timeLabel(GlanceItem("lab", ms(now.withHour(15).withMinute(30)), "class"), now, zone))
        assertEquals("Due 11:59 PM", WidgetLogic.timeLabel(GlanceItem("hw", ms(now.withHour(23).withMinute(59)), "due"), now, zone))
        assertEquals("Tmrw 9 AM", WidgetLogic.timeLabel(GlanceItem("x", ms(now.plusDays(1)), "event"), now, zone))
        assertEquals("All day", WidgetLogic.timeLabel(GlanceItem("trip", ms(now), "event", allDay = true), now, zone))
        assertEquals("Thu 9 AM", WidgetLogic.timeLabel(GlanceItem("x", ms(now.plusDays(2)), "event"), now, zone))
    }

    @Test fun soonIsWithinTheHour() {
        val n = ms(now)
        assertTrue(WidgetLogic.soon(GlanceItem("a", n + 30 * 60_000L, "class"), n))
        assertFalse(WidgetLogic.soon(GlanceItem("a", n + 3 * 3600_000L, "class"), n))
        assertFalse(WidgetLogic.soon(GlanceItem("a", n, "event", allDay = true), n))
    }

    @Test fun todosOpenFirstWithCountsAndProgress() {
        val todos = listOf(LocalTodo("a", "milk", "done"), LocalTodo("b", "eggs", "open"), LocalTodo("c", "bread", "open"))
        assertEquals(listOf("eggs", "bread", "milk"), WidgetLogic.todoOrder(todos).map { it.text })
        assertEquals("To do · 2 left", WidgetLogic.todoHeader(todos))
        assertEquals(1f / 3, WidgetLogic.progress(todos), 0.001f)
        assertEquals("To do · all done", WidgetLogic.todoHeader(listOf(LocalTodo("a", "milk", "done"))))
        assertEquals("To do", WidgetLogic.todoHeader(emptyList()))
    }

    @Test fun syncedLine() {
        assertEquals("synced 5 min ago · tap to sync", WidgetLogic.syncedLabel(1_000_000, 1_000_000 + 5 * 60_000))
        assertEquals("not synced yet · tap to sync", WidgetLogic.syncedLabel(0, 5))
    }
}
