package com.manaskhare.sanae.watch

import app.cash.paparazzi.DeviceConfig
import app.cash.paparazzi.Paparazzi
import org.junit.Rule
import org.junit.Test

/** The talk screen on a round watch, rendered offscreen. Run: gradlew :wear:recordPaparazziDebug
 *  -> wear/src/test/snapshots/images */
class ScreensTest {
    @get:Rule
    val paparazzi = Paparazzi(deviceConfig = DeviceConfig.WEAR_OS_SMALL_ROUND, theme = "android:Theme.DeviceDefault")

    private val now = System.currentTimeMillis()
    private val glance = Glance(listOf(
        Item("Dentist", now + 2 * 3_600_000, "event", false),
        Item("HW 5", now + 9 * 3_600_000, "due", false),
    ), emptyList(), true, now)

    private fun screen(phase: Phase, heard: String = "", reply: String = "", emotion: String = "", error: String = "",
                       approvals: List<Approval> = emptyList()) {
        paparazzi.snapshot {
            TalkScreen(phase, 0.5f, heard, reply, emotion, error, approvals, glance, true, {}, { _, _ -> }, {}, flat = true)
        }
    }

    @Test fun idle() = screen(Phase.IDLE)
    @Test fun listening() = screen(Phase.LISTENING)
    @Test fun thinking() = screen(Phase.THINKING, heard = "what's due this week", emotion = "thinking")
    @Test fun answered() = screen(Phase.IDLE, heard = "what's due this week",
                                  reply = "Just HW 5 tonight at 11:59, you've got this!", emotion = "happy")
    @Test fun approval() = screen(Phase.THINKING, heard = "email Maya I'm running late",
                                  approvals = listOf(Approval(3, "Send the email to Maya?")))
    @Test fun offline() = screen(Phase.IDLE, error = "Can't reach your laptop.", emotion = "sad")
}
