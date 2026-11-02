package com.manaskhare.sanae

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.time.LocalDateTime
import java.time.ZoneId

class TodoLogicTest {
    @Test fun splitsLikeTheLaptop() {
        assertEquals(listOf("milk", "eggs", "bread"), TodoText.split("milk, eggs and bread"))
        assertEquals(listOf("call mom and dad"), TodoText.split("call mom and dad"))
        assertEquals(listOf("finish the lab report"), TodoText.split(" finish the lab report. "))
        assertEquals(emptyList<String>(), TodoText.split("  "))
    }

    @Test fun deletedWinsAndTicksGoByTime() {
        val local = listOf(
            LocalTodo("a", "milk", "done", updatedMs = 50, dirty = false, synced = true),
            LocalTodo("b", "eggs", "open", updatedMs = 60, dirty = true, synced = true),     // ticked off here, then unticked during the request
        )
        val server = listOf(LocalTodo("a", "milk", "deleted", updatedMs = 40, dirty = false, synced = true),
                            LocalTodo("b", "eggs", "done", updatedMs = 55, dirty = false, synced = true))
        val plan = SyncRules.plan(local, server, mapOf("b" to 55L))
        assertEquals(listOf("a"), plan.write.map { it.uid })                 // b changed here since: kept
        assertTrue(plan.delete.isEmpty())
        assertTrue(server[0].finished)
    }

    @Test fun watchShowsOpenTodosAfterTimedThings() {
        val zone = ZoneId.of("Etc/GMT+7")
        val now = LocalDateTime.of(2026, 10, 16, 13, 0).atZone(zone).toInstant().toEpochMilli()
        val r = LocalReminder("r", "Call mom", now + 3_600_000)
        val todos = listOf(LocalTodo("t1", "milk"), LocalTodo("t2", "laundry", "done"), LocalTodo("t3", "rent"))
        val items = Glance.build(null, listOf(r), emptyList(), now, zone, limit = 3, todos = todos)
        assertEquals(listOf("Call mom", "milk", "rent"), items.map { it.title })
        assertEquals(listOf("reminder", "todo", "todo"), items.map { it.kind })
        assertEquals(1, Glance.build(null, listOf(r), emptyList(), now, zone, limit = 1, todos = todos).size)
    }
}
