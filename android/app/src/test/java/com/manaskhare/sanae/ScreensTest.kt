package com.manaskhare.sanae

import android.app.Application
import android.content.Context
import androidx.compose.runtime.Composable
import app.cash.paparazzi.DeviceConfig
import app.cash.paparazzi.Paparazzi
import com.manaskhare.sanae.ui.Accent
import com.manaskhare.sanae.ui.AppBackground
import com.manaskhare.sanae.ui.AppearanceScreen
import com.manaskhare.sanae.ui.FontTheme
import com.manaskhare.sanae.ui.SanaeScreen
import com.manaskhare.sanae.ui.CozyNavBar
import com.manaskhare.sanae.ui.NavItem
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.background
import com.manaskhare.sanae.ui.Look
import com.manaskhare.sanae.ui.Looks
import com.manaskhare.sanae.ui.SanaeTheme
import com.manaskhare.sanae.ui.SettingsScreen
import com.manaskhare.sanae.ui.TodayScreen
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.ui.unit.dp
import androidx.compose.material.icons.filled.Favorite
import androidx.compose.material.icons.filled.Person
import androidx.compose.material.icons.filled.WbSunny
import org.junit.Rule
import org.junit.Test

/** Renders the main screens offscreen (layoutlib) so layout can be checked without a phone.
 *  Run: gradlew recordPaparazziDebug  -> app/src/test/snapshots/images */
class ScreensTest {
    @get:Rule
    val paparazzi = Paparazzi(deviceConfig = DeviceConfig.PIXEL_6, theme = "android:Theme.Material.NoActionBar")

    private fun vm(): MainViewModel {
        val app = Application()
        android.content.ContextWrapper::class.java.getDeclaredMethod("attachBaseContext", Context::class.java).apply { isAccessible = true }
            .invoke(app, paparazzi.context)
        return MainViewModel(app).apply {
            heard.value = "what's due this week"
            reply.value = "Two things: the project report on Friday at 11:59 PM, and the SPARQL quiz on Monday."
        }
    }

    private fun shot(look: Look, content: @Composable () -> Unit) {
        Looks.state.value = look
        paparazzi.snapshot { SanaeTheme { AppBackground { content() } } }
    }

    private fun chatting(m: MainViewModel) = m.apply {
        turns.value = listOf(
            Turn("I just got up from my nap.", "Oh! You just came back from a nap, huh? Did you miss me?", "2026-10-21T18:29:06"),
            Turn("Yeah, I did miss you.", "I was just thinking about you! What's next? Anime or something fun?", "2026-10-21T18:29:21"),
            Turn("what's due this week", "Two things: the project report on Friday at 11:59 PM, and the SPARQL quiz on Monday.", "2026-10-21T19:02:44"),
        )
        emotion.value = "happy"
    }

    /** Her tab as it sits in the app: the screen plus the bottom bar. */
    @Composable private fun tab(m: MainViewModel) {
        androidx.compose.foundation.layout.Column(androidx.compose.ui.Modifier.fillMaxSize()) {
            androidx.compose.foundation.layout.Box(androidx.compose.ui.Modifier.weight(1f)) { SanaeScreen(m) { it() } }
            CozyNavBar(listOf(NavItem("Sanae", null, face = true), NavItem("Today", androidx.compose.material.icons.Icons.Filled.WbSunny),
                              NavItem("Us", androidx.compose.material.icons.Icons.Filled.Favorite),
                              NavItem("Me", androidx.compose.material.icons.Icons.Filled.Person)), 0, m.emotion.value) {}
        }
    }

    @Test fun sanae_chat() { val m = chatting(vm()); shot(Look()) { tab(m) } }
    @Test fun sanae_empty() { val m = vm().apply { emotion.value = "neutral" }; shot(Look()) { tab(m) } }
    @Test fun sanae_thinking_shy() { val m = chatting(vm()).apply { emotion.value = "shy"; phase.value = Phase.THINKING }; shot(Look()) { tab(m) } }
    @Test fun sanae_photo_waiting() {
        val m = chatting(vm())
        val img = android.graphics.Bitmap.createBitmap(160, 120, android.graphics.Bitmap.Config.ARGB_8888).apply { eraseColor(0xFFE08A3C.toInt()) }
        m.photo.value = java.io.ByteArrayOutputStream().also { img.compress(android.graphics.Bitmap.CompressFormat.JPEG, 85, it) }.toByteArray()
        shot(Look()) { tab(m) }
    }
    @Test fun sanae_gold_classic() { val m = chatting(vm()); shot(Look(accent = Accent.GOLD, font = FontTheme.CLASSIC)) { tab(m) } }
    @Test fun settings() {
        val m = vm()
        val owner = object : androidx.activity.result.ActivityResultRegistryOwner {   // permission prompts (not shown)
            override val activityResultRegistry = object : androidx.activity.result.ActivityResultRegistry() {
                override fun <I, O> onLaunch(requestCode: Int, contract: androidx.activity.result.contract.ActivityResultContract<I, O>,
                                             input: I, options: androidx.core.app.ActivityOptionsCompat?) {}
            }
        }
        paparazzi.unsafeUpdateConfig(deviceConfig = DeviceConfig.PIXEL_6.copy(screenHeight = 5600))   // whole page
        shot(Look()) {
            androidx.compose.runtime.CompositionLocalProvider(
                androidx.activity.compose.LocalActivityResultRegistryOwner provides owner) { SettingsScreen(m, {}) }
        }
    }
    @Test fun me_home() { val m = vm(); shot(Look()) { com.manaskhare.sanae.ui.MeHome(m) {} } }
    @Test fun me_page() {
        val m = vm()
        val owner = object : androidx.activity.result.ActivityResultRegistryOwner {
            override val activityResultRegistry = object : androidx.activity.result.ActivityResultRegistry() {
                override fun <I, O> onLaunch(requestCode: Int, contract: androidx.activity.result.contract.ActivityResultContract<I, O>,
                                             input: I, options: androidx.core.app.ActivityOptionsCompat?) {}
            }
        }
        shot(Look()) {
            androidx.compose.runtime.CompositionLocalProvider(
                androidx.activity.compose.LocalActivityResultRegistryOwner provides owner) { SettingsScreen(m, {}, group = "phone") }
        }
    }
    @Test fun appearance() { shot(Look(ringBars = true)) { AppearanceScreen {} } }
    /** A full day (sample data; the real screen reads SQLite, which Paparazzi can't open). */
    private fun day(now: java.time.LocalDateTime): Pair<DayPlan, List<LocalChore>> {
        val d = now.toLocalDate()
        val at = { days: Long, h: Int, m: Int -> Offline.ms(d.plusDays(days).atTime(h, m)) }
        val chores = listOf(LocalChore("c1", "Water the plants", "daily", doneDay = d.toString(), dirty = false, synced = true),
                            LocalChore("c2", "Take vitamins", "daily", dirty = false, synced = true))
        return Timeline.build(
            now,
            classes = listOf(CanvasItem("CS 101 Data Mining", "Lecture · Room 210", d.atTime(10, 30)),
                             CanvasItem("CS 105 Data Processing", "Lecture · Room 170", d.atTime(16, 30))),
            dueToday = listOf(CanvasItem("Lab 4: Spark joins", "CS 105", d.atTime(23, 59))),
            dueSoon = listOf(CanvasItem("Project report", "CS 101", d.plusDays(1).atTime(23, 59)),
                             CanvasItem("SPARQL quiz", "CS 105", d.plusDays(4).atTime(12, 0))),
            events = listOf(LocalEvent("e1", "Study group", at(0, 14, 0), at(0, 15, 0), location = "the library", dirty = false, synced = true),
                            LocalEvent("e2", "Career fair", at(0, 0, 0), at(1, 0, 0), allDay = true, dirty = false, synced = true),
                            LocalEvent("e3", "Dinner with Maya", at(2, 19, 0), at(2, 20, 30), dirty = false, synced = true)),
            reminders = listOf(LocalReminder("r1", "Call mom", at(0, 18, 0), dirty = false, synced = true),
                               LocalReminder("r2", "Pay Insurance", at(3, 9, 0), repeat = "monthly:25", dirty = false, synced = true)),
            todos = listOf(LocalTodo("t1", "Buy milk", dirty = false, synced = true), LocalTodo("t2", "Laundry", "done", dirty = false, synced = true),
                           LocalTodo("t3", "Email the TA about the regrade")),
            chores = chores,
        ) to chores
    }
    @Test fun today() {
        val now = java.time.LocalDate.now().atTime(12, 20)
        val (plan, chores) = day(now)
        paparazzi.unsafeUpdateConfig(deviceConfig = DeviceConfig.PIXEL_6.copy(screenHeight = 4200))
        shot(Look()) { com.manaskhare.sanae.ui.TodayContent(plan, now, "happy", chores) }
    }
    @Test fun today_screen() {
        val now = java.time.LocalDate.now().atTime(12, 20)
        val (plan, chores) = day(now)
        shot(Look()) { com.manaskhare.sanae.ui.TodayContent(plan, now, "happy", chores) }
    }
    @Test fun today_empty() {
        val now = java.time.LocalDate.now().atTime(20, 0)
        shot(Look()) { com.manaskhare.sanae.ui.TodayContent(Timeline.build(now), now, "sleepy", emptyList()) }
    }
    @Test fun today_add() {
        val now = java.time.LocalDate.now().atTime(12, 20)
        shot(Look()) {
            androidx.compose.foundation.layout.Box(androidx.compose.ui.Modifier.fillMaxSize(), contentAlignment = androidx.compose.ui.Alignment.BottomCenter) {
                androidx.compose.foundation.layout.Box(androidx.compose.ui.Modifier.background(com.manaskhare.sanae.ui.Panel)) {
                    com.manaskhare.sanae.ui.AddPanel(now, "call mom tomorrow 5pm") {}
                }
            }
        }
    }

    /** Laptop off: reminders, events and recordings kept on the phone (sample data; no SQLite here). */
    @Test fun offline_cards() {
        val m = vm()
        val at = { days: Long, h: Int -> Offline.ms(java.time.LocalDate.now().plusDays(days).atTime(h, 0)) }
        val reminders = listOf(LocalReminder("r1", "Submit the lab report", at(0, 21)),
                               LocalReminder("r2", "Call mom", at(1, 18), dirty = false, synced = true))
        val events = listOf(LocalEvent("e1", "Study group", at(1, 15), at(1, 16), location = "the library"),
                            LocalEvent("e2", "Career fair", at(3, 0), at(4, 0), allDay = true, dirty = false, synced = true))
        val recordings = listOf(LocalRecording("p1", "lecture", "CS 101 week 7", at(0, 9), 4380, "x", "waiting"),
                                LocalRecording("p2", "meeting", "Project sync", at(-1, 14), 1500, "x", "processing"),
                                LocalRecording("p3", "lecture", "CS 105 midterm review", at(-2, 10), 4800, "x", "done", noteId = 7),
                                LocalRecording("p4", "lecture", "Physics lab", at(-3, 10), 600, "x", "failed", error = "bad audio"))
        paparazzi.unsafeUpdateConfig(deviceConfig = DeviceConfig.PIXEL_6.copy(screenHeight = 5000))
        val owner = object : androidx.activity.result.ActivityResultRegistryOwner {   // permission prompts (not shown)
            override val activityResultRegistry = object : androidx.activity.result.ActivityResultRegistry() {
                override fun <I, O> onLaunch(requestCode: Int, contract: androidx.activity.result.contract.ActivityResultContract<I, O>,
                                             input: I, options: androidx.core.app.ActivityOptionsCompat?) {}
            }
        }
        shot(Look()) {
            androidx.compose.runtime.CompositionLocalProvider(androidx.activity.compose.LocalActivityResultRegistryOwner provides owner) {
            androidx.compose.foundation.layout.Column(androidx.compose.ui.Modifier.padding(16.dp)) {
                com.manaskhare.sanae.ui.OfflineNote()
                androidx.compose.foundation.layout.Spacer(androidx.compose.ui.Modifier.height(12.dp))
                com.manaskhare.sanae.ui.PhoneRecorderCard(m, {}, recordings)
            }
            }
        }
    }
}
