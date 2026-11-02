package com.manaskhare.sanae

import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test
import java.time.LocalDateTime
import java.time.ZoneId
import java.time.ZoneOffset

class WatchLogicTest {
    private val zone = ZoneId.of("Etc/GMT+7")
    private fun ms(m: Int, d: Int, h: Int, min: Int = 0) =
        LocalDateTime.of(2026, m, d, h, min).atZone(zone).toInstant().toEpochMilli()
    // Friday, October 16 2026, 1:00 PM in Phoenix
    private val now = ms(10, 16, 13)

    @Test fun nextThingsInOrder() {
        val today = JSONObject("""{
            "due_today": [{"title": "HW 5", "due": "2026-10-16T23:59:00"}],
            "due_soon": [{"title": "Lab report", "due": "2026-10-18T23:59:00"}, {"title": "Far away", "due": "2026-10-25T23:59:00"}],
            "classes": [{"title": "CS 104", "due": "2026-10-16T12:30:00"}, {"title": "MAT 343", "due": "2026-10-17T09:00:00"}]
        }""")
        val reminders = listOf(
            LocalReminder("a", "Call mom", ms(10, 16, 18)),
            LocalReminder("b", "Done already", ms(10, 16, 14), status = "done"),
            LocalReminder("c", "Long ago", ms(10, 16, 9)),
        )
        val events = listOf(
            LocalEvent("e", "Dentist", ms(10, 16, 15), ms(10, 16, 16)),
            LocalEvent("f", "Maya's birthday",
                LocalDateTime.of(2026, 10, 16, 0, 0).toInstant(ZoneOffset.UTC).toEpochMilli(),
                LocalDateTime.of(2026, 10, 17, 0, 0).toInstant(ZoneOffset.UTC).toEpochMilli(), allDay = true),
            LocalEvent("g", "Cancelled thing", ms(10, 16, 16), ms(10, 16, 17), status = "cancelled"),
        )
        val items = Glance.build(today, reminders, events, now, zone, limit = 10)
        assertEquals(listOf("Maya's birthday", "CS 104", "Dentist", "Call mom", "HW 5", "MAT 343", "Lab report"),
                     items.map { it.title })
        assertEquals(listOf("event", "class", "event", "reminder", "due", "class", "due"), items.map { it.kind })
        assertEquals(4, Glance.build(today, reminders, events, now, zone).size)
    }

    @Test fun duplicatesAndTimes() {
        val r = LocalReminder("a", "Pay Insurance", ms(10, 16, 17))
        val today = JSONObject("""{"due_today": [{"title": "pay insurance", "due": "2026-10-16T17:00:00"}]}""")
        assertEquals(1, Glance.build(today, listOf(r), emptyList(), now, zone).size)
        assertEquals(ms(10, 16, 17), Glance.parse("2026-10-16T17:00:00", zone))
        assertEquals(ms(10, 16, 17), Glance.parse("2026-10-17T00:00:00+00:00", zone))
        assertNull(Glance.parse("", zone))
        assertNull(Glance.parse("tomorrow", zone))
    }

    @Test fun payloadShape() {
        val p = Glance.payload(listOf(GlanceItem("Dentist", 5L, "event")), listOf(PendingApproval(3, "Send it?", "send_email")), true, 9L)
        assertEquals("Dentist", p.getJSONArray("items").getJSONObject(0).getString("title"))
        assertEquals(3, p.getJSONArray("approvals").getJSONObject(0).getInt("id"))
        assertEquals(true, p.getBoolean("online"))
    }
}
