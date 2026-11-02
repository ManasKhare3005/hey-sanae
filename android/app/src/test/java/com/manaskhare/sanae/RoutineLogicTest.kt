package com.manaskhare.sanae

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import java.time.LocalDate

class RoutineLogicTest {
    private val tue = LocalDate.of(2026, 10, 20)

    @Test fun dueDaysMatchTheLaptop() {
        assertTrue(RoutineLogic.dueOn("daily", tue))
        assertTrue(RoutineLogic.dueOn("weekdays", tue))
        assertFalse(RoutineLogic.dueOn("weekdays", LocalDate.of(2026, 10, 25)))
        assertTrue(RoutineLogic.dueOn("weekly:1", tue))                       // Monday = 0
        assertFalse(RoutineLogic.dueOn("weekly:6", tue))
        assertTrue(RoutineLogic.dueOn("monthly:20", tue))
        assertTrue(RoutineLogic.dueOn("monthly:31", LocalDate.of(2026, 11, 30)))
        assertFalse(RoutineLogic.dueOn("monthly:31", LocalDate.of(2026, 11, 29)))
        assertFalse(RoutineLogic.dueOn("nonsense", tue))
    }

    @Test fun labels() {
        assertEquals("every day", RoutineLogic.label("daily"))
        assertEquals("every Sunday", RoutineLogic.label("weekly:6"))
        assertEquals("monthly on the 1st", RoutineLogic.label("monthly:1"))
        assertEquals("monthly on the 11th", RoutineLogic.label("monthly:11"))
        assertEquals("monthly on the 23rd", RoutineLogic.label("monthly:23"))
        assertEquals("weekly:3", RoutineLogic.freq("weekly", 3, 9))
        assertEquals("monthly:9", RoutineLogic.freq("monthly", 3, 9))
        assertEquals("daily", RoutineLogic.freq("daily", 3, 9))
    }

    @Test fun forgottenAndOrder() {
        val plants = LocalChore("a", "water the plants", "daily")
        val gym = LocalChore("b", "gym", "weekly:1", doneDay = "2026-10-20")
        val laundry = LocalChore("c", "laundry", "weekly:6")
        val old = LocalChore("d", "stretch", "daily", doneDay = "2026-10-19")
        val gone = LocalChore("e", "rent", "daily", status = "deleted")
        val all = listOf(laundry, gym, plants, old, gone)
        assertEquals(listOf("water the plants", "stretch"), RoutineLogic.forgotten(all, tue).map { it.text })
        assertEquals(listOf("water the plants", "stretch", "gym", "laundry"),
                     RoutineLogic.order(all.filter { it.status == "active" }, tue).map { it.text })
        assertEquals("water the plants and stretch", RoutineLogic.join(listOf("water the plants", "stretch")))
        assertEquals("a, b and c", RoutineLogic.join(listOf("a", "b", "c")))
        assertEquals("Routine · 2 left today", WidgetLogic.routineHeader(listOf(plants, gym, old), tue))
        assertEquals("Routine · all done today", WidgetLogic.routineHeader(listOf(gym), tue))
    }
}
