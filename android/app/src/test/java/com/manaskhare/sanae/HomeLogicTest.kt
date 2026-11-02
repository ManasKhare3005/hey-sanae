package com.manaskhare.sanae

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class HomeLogicTest {
    @Test fun arrivesRightAwayLeavesAfterAWhile() {
        val h = HomeLogic()
        assertNull(h.update(false, 0))                                  // first look: out, nothing to say
        assertEquals(HomeLogic.Event("arrived", 1_000), h.update(true, 1_000))
        assertNull(h.update(true, 2_000))
        assertNull(h.update(false, 10_000))                             // Wi-Fi dropped: maybe a router restart
        assertNull(h.update(true, 60_000))                              // it was: back, no second "arrived"
        assertNull(h.update(false, 100_000))
        assertNull(h.update(false, 100_000 + HomeLogic.LEAVE_MS - 1))
        assertEquals(HomeLogic.Event("left", 100_000), h.update(false, 100_000 + HomeLogic.LEAVE_MS))
        assertNull(h.update(false, 900_000))
        assertEquals("arrived", h.update(true, 5_000_000)?.event)
    }

    @Test fun homeIsTheNameOrTheRouter() {
        assertTrue(isHomeNetwork("\"Home WiFi\"", "", "Home WiFi", "gw"))
        assertFalse(isHomeNetwork("Starbucks", "gw", "Home WiFi", "gw"))  // a known different name wins
        assertTrue(isHomeNetwork("<unknown ssid>", "gw|dns", "Home WiFi", "gw|dns"))   // name hidden: fingerprint
        assertFalse(isHomeNetwork(null, "", "", ""))
    }

    @Test fun ipv6ChangesAreStillHome() {
        val saved = "192.168.1.1,fe80::1|192.168.1.1,2600:1700:aa::1|192.168.1/24|lan"
        val later = "192.168.1.1,fe80::1|192.168.1.1,2600:1700:bb::1|192.168.1/24|lan"
        assertTrue(isHomeNetwork(null, later, "", saved))                   // the ISP's IPv6 prefix rotated
        assertFalse(isHomeNetwork(null, "10.0.0.1|10.0.0.1|10.0.0/24|", "", saved))
        assertFalse(isHomeNetwork(null, "fe80::1|2600::1||", "", "fe80::1|2600::1||"))   // nothing stable to go on
    }
}
