package com.manaskhare.sanae

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test
import java.time.LocalDateTime
import java.time.ZoneId

class HealthLogicTest {
    private val zone = ZoneId.of("Etc/GMT+7")
    private fun at(d: Int, h: Int, m: Int = 0) = LocalDateTime.of(2026, 10, d, h, m).atZone(zone).toInstant()

    @Test fun sleepAddsUpSessionsAndSkipsNaps() {
        val row = HealthShare.sleepRow(listOf(at(17, 23, 40) to at(18, 3, 10), at(18, 3, 30) to at(18, 7, 45),
                                              at(18, 14, 0) to at(18, 14, 15)), zone)
        assertEquals(Triple(465, "2026-10-17T23:40", "2026-10-18T07:45"), row)
        assertNull(HealthShare.sleepRow(listOf(at(18, 14, 0) to at(18, 14, 10)), zone))
    }

    @Test fun restingHeartRateFromSleepThenTheDay() {
        val sleep = listOf(at(18, 1) to at(18, 7))
        // asleep every 10 min: 52-61, one odd 35 and a 200 (dropped); awake readings in the 80s-100s
        val night = (0 until 36).map { at(18, 1 + it / 6, (it % 6) * 10) to (52L + it % 10) } + listOf(at(18, 3, 5) to 35L, at(18, 4, 5) to 200L)
        val day = (0 until 40).map { at(18, 9 + it / 6, (it % 6) * 10) to (80L + it % 25) }
        assertEquals(52, HealthShare.restingFrom(night + day, sleep))
        assertEquals(82, HealthShare.restingFrom(day, sleep))               // no sleep readings: the day's lowest fifth
        assertNull(HealthShare.restingFrom(day.take(10), emptyList()))      // too few
    }
}
