package com.manaskhare.sanae

/**
 * Home or out, from whether the phone is on the home Wi-Fi (pure, JVM-tested). Joining it is
 * "arrived" right away; dropping off it only counts as "left" once it has stayed off for LEAVE_MS
 * (a router restart or a walk to the mailbox isn't leaving).
 */
class HomeLogic(var state: String = "", var leaveSince: Long = 0L) {
    companion object { const val LEAVE_MS = 5 * 60_000L }

    data class Event(val event: String, val atMs: Long)

    fun update(isHome: Boolean, now: Long): Event? {
        if (isHome) {
            leaveSince = 0L
            if (state == "home") return null
            state = "home"
            return Event("arrived", now)
        }
        if (state != "home") { state = "out"; return null }
        if (leaveSince == 0L) { leaveSince = now; return null }
        if (now - leaveSince < LEAVE_MS) return null
        state = "out"
        return Event("left", leaveSince).also { leaveSince = 0L }
    }
}

/** Is this network the home one: the saved Wi-Fi name, or (when Android hides the name) the same
 *  router fingerprint (gateway, DNS, subnet) seen when it was saved. */
fun isHomeNetwork(ssid: String?, fingerprint: String, homeSsid: String, homeFingerprint: String): Boolean {
    val name = ssid?.trim('"')?.takeIf { it.isNotBlank() && it != "<unknown ssid>" }
    if (name != null && homeSsid.isNotBlank()) return name == homeSsid
    val router = stableRouter(fingerprint)
    return router.isNotBlank() && router == stableRouter(homeFingerprint)
}

/** The fingerprint without its IPv6 addresses: those rotate with the ISP's prefix, and a changed
 *  DNS address made the phone think you'd left home while it sat on the same Wi-Fi. */
fun stableRouter(fingerprint: String): String {
    val parts = fingerprint.split("|").map { p -> p.split(",").filter { it.isNotBlank() && ':' !in it }.joinToString(",") }
    return if (parts.firstOrNull().isNullOrBlank()) "" else parts.joinToString("|")
}
