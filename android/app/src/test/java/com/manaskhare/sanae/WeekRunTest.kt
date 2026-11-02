package com.manaskhare.sanae

import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onAllNodesWithText
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.test.core.app.ApplicationProvider
import com.manaskhare.sanae.ui.SanaeTheme
import com.manaskhare.sanae.ui.UsScreen
import com.manaskhare.sanae.ui.WeekStories
import com.manaskhare.sanae.ui.WeekStoryHost
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

/** "Your week": open the page the way the notification does, watch the story to the end (it runs
 *  for real here, unlike the Paparazzi snapshots). Data shaped like the laptop's /api/us. */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [34], application = android.app.Application::class)   // not SanaeApp: no service, database or alarms
class WeekRunTest {
    @get:Rule
    val compose = createComposeRule()

    private val us = JSONObject("""{"weekly": {"weeks": [
      {"week": "2026-W43", "start": "2026-10-19", "created": "2026-10-25T18:15:26", "slides": [
        {"kind": "cover", "title": "Your week", "range": "Oct 19 – Oct 25", "feel": "a good week", "talked": 6},
        {"kind": "wins", "items": ["made 1 commit on Quizzard today"]},
        {"kind": "notebook", "pages": 0, "moods": [], "highlight": "We joked about coffee."},
        {"kind": "moment", "type": "memory", "text": "the pasta disaster"},
        {"kind": "proud", "text": "You brought Quizzard to life."},
        {"kind": "next", "items": ["Lab 7 due Wed", "Assignment 2 due Sun"]}]},
      {"week": "2026-W42", "start": "2026-10-12", "slides": [
        {"kind": "cover", "title": "Your week", "range": "Oct 12 – Oct 18", "feel": "an okay week", "talked": 3},
        {"kind": "next", "items": ["Lab 6 due Wed"]}]}]}}""")

    private fun storyShown() = compose.onAllNodesWithText("Sanae · your week").fetchSemanticsNodes().size

    @Test fun watch_the_week_to_the_end() {
        Us.state.value = us
        val vm = MainViewModel(ApplicationProvider.getApplicationContext())
        compose.setContent { SanaeTheme { UsScreen(vm); WeekStoryHost("Sanae") } }
        MainActivity.openPage.value = "weekly"
        compose.waitForIdle()
        compose.onNodeWithText("Watch").performClick()
        compose.waitForIdle()
        assertEquals(1, storyShown())
        compose.mainClock.autoAdvance = false
        repeat(90) { compose.mainClock.advanceTimeBy(500) }                         // 6 slides x 6.5 s
        compose.mainClock.autoAdvance = true
        compose.waitForIdle()
        assertEquals(0, storyShown())
        assertEquals(null, WeekStories.watching.value)
    }

    @Test fun rewatch_an_older_week() {
        Us.state.value = us
        val vm = MainViewModel(ApplicationProvider.getApplicationContext())
        compose.setContent { SanaeTheme { UsScreen(vm); WeekStoryHost("Sanae") } }
        MainActivity.openPage.value = "weekly"
        compose.waitForIdle()
        compose.onNodeWithText("Rewatch Oct 12 – Oct 18").performClick()
        compose.waitForIdle()
        compose.onNodeWithText("an okay week", substring = true, ignoreCase = true).assertExists()
        WeekStories.watching.value = null
    }
}
