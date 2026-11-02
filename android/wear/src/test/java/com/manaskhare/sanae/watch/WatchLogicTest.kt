package com.manaskhare.sanae.watch

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.time.LocalDateTime
import java.time.ZoneId

class WatchLogicTest {
    private val zone = ZoneId.of("Etc/GMT+7")
    private fun ms(d: Int, h: Int, min: Int = 0) = LocalDateTime.of(2026, 10, d, h, min).atZone(zone).toInstant().toEpochMilli()
    private val now = ms(16, 13)        // Friday 1 PM

    @Test fun stopsAfterQuietOnceSomethingWasSaid() {
        val e = Endpoint()
        repeat(3) { assertFalse(e.feed(100.0)) }          // room noise
        repeat(20) { assertFalse(e.feed(120.0)) }          // still quiet, nothing said: keep waiting
        assertFalse(e.feed(2000.0))
        assertTrue(e.spoke)
        repeat(11) { assertFalse(e.feed(100.0)) }
        assertTrue(e.feed(100.0))                          // 1.2 s of quiet
    }

    @Test fun stopsAtTheTimeLimit() {
        val e = Endpoint(maxFrames = 10)
        repeat(9) { assertFalse(e.feed(5000.0)) }
        assertTrue(e.feed(5000.0))
    }

    @Test fun readsThePhonesMessages() {
        val g = Glance.parse("""{"items":[{"title":"Dentist","at":5,"kind":"event","all_day":false}],
            "approvals":[{"id":3,"prompt":"Send it?"}],"online":true,"made":9}""")!!
        assertEquals(listOf(Item("Dentist", 5, "event", false)), g.items)
        assertEquals(listOf(Approval(3, "Send it?")), g.approvals)
        assertTrue(g.online)
        assertNull(Glance.parse("nope"))
        assertEquals(Reply("open youtube", "Done!", "happy", ""),
                     Reply.parse("""{"heard":"open youtube","reply":"Done!","emotion":"happy"}"""))
        assertTrue(Reply.parse("{oops").error.isNotBlank())
    }

    @Test fun timeLabels() {
        assertEquals("3 PM", whenLabel(Item("x", ms(16, 15), "event", false), now, zone))
        assertEquals("Due 11:59 PM", whenLabel(Item("x", ms(16, 23, 59), "due", false), now, zone))
        assertEquals("Tmrw 9:30 AM", whenLabel(Item("x", ms(17, 9, 30), "class", false), now, zone))
        assertEquals("Due Sun 12 AM", whenLabel(Item("x", ms(18, 0), "due", false), now, zone))
        assertEquals("All day", whenLabel(Item("x", ms(16, 0), "event", true), now, zone))
    }

    @Test fun listensAgainOnlyForQuestions() {
        assertTrue(asksBack(Reply("", "Which one, the red or the blue?", "", ""), approvalsOpen = false))
        assertFalse(asksBack(Reply("", "Send it?", "", ""), approvalsOpen = true))
        assertFalse(asksBack(Reply("", "Done!", "", ""), approvalsOpen = false))
        assertFalse(asksBack(Reply("", "", "", "Can't reach your laptop."), approvalsOpen = false))
    }

    @Test fun facesForEveryEmotion() {
        assertEquals(Faces.CYAN, Faces.of("").ring)
        assertEquals(Faces.CYAN, Faces.of("neutral").ring)
        assertTrue(Faces.of("happy").bounce)
        assertTrue(Faces.of("sad").dim)
        for (e in listOf("happy", "shy", "laugh", "thinking", "sad", "surprised", "sleepy"))
            assertTrue(e, Faces.of(e).ring != Faces.CYAN)
    }
}
