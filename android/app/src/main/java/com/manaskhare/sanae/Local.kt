package com.manaskhare.sanae

import android.content.ContentValues
import android.content.Context
import android.database.Cursor
import android.database.sqlite.SQLiteDatabase
import android.database.sqlite.SQLiteOpenHelper
import kotlinx.coroutines.flow.MutableStateFlow
import org.json.JSONObject
import java.util.UUID

/**
 * What the phone keeps on its own, so Sanae's reminders, calendar and recordings work with the
 * laptop off: a small SQLite database. Changes are saved here first (marked `dirty`) and sent to
 * the laptop by Sync; the laptop's answer then replaces what it knows better (see SyncRules).
 */
data class LocalReminder(
    override val uid: String, val text: String, val dueMs: Long, val status: String = "pending",
    override val updatedMs: Long = System.currentTimeMillis(), override val dirty: Boolean = true,
    override val synced: Boolean = false,
    val repeat: String = "",          // "" = once; daily, weekdays, weekly, monthly:<day>, yearly:<month>-<day> (see Repeat)
) : Syncable {
    override val finished get() = status != "pending"
    fun toJson(): JSONObject = JSONObject().put("uid", uid).put("text", text).put("due_ms", dueMs)
        .put("status", status).put("updated_ms", updatedMs).put("repeat", repeat)

    companion object {
        fun fromJson(o: JSONObject) = LocalReminder(o.optString("uid"), o.optString("text"), o.optLong("due_ms"),
            o.optString("status", "pending"), o.optLong("updated_ms"), dirty = false, synced = true,
            repeat = o.optString("repeat"))
    }
}

data class LocalEvent(
    override val uid: String, val title: String, val startMs: Long, val endMs: Long, val allDay: Boolean = false,
    val location: String = "", val status: String = "active",
    override val updatedMs: Long = System.currentTimeMillis(), override val dirty: Boolean = true,
    override val synced: Boolean = false,
) : Syncable {
    override val finished get() = status == "cancelled"
    fun toJson(): JSONObject = JSONObject().put("uid", uid).put("title", title).put("start_ms", startMs)
        .put("end_ms", endMs).put("all_day", allDay).put("location", location).put("status", status)
        .put("updated_ms", updatedMs)

    companion object {
        fun fromJson(o: JSONObject) = LocalEvent(o.optString("uid"), o.optString("title"), o.optLong("start_ms"),
            o.optLong("end_ms"), o.optBoolean("all_day"), o.optString("location"), o.optString("status", "active"),
            o.optLong("updated_ms"), dirty = false, synced = true)
    }
}

/** A todo-list item: open, done (ticked, shown until cleared) or deleted. Deleted counts as finished
 *  for the sync rule, so a cleared todo never comes back; open <-> done goes by the later edit. */
data class LocalTodo(
    override val uid: String, val text: String, val status: String = "open", val created: String = "",
    override val updatedMs: Long = System.currentTimeMillis(), override val dirty: Boolean = true,
    override val synced: Boolean = false,
) : Syncable {
    override val finished get() = status == "deleted"
    val done get() = status == "done"
    fun toJson(): JSONObject = JSONObject().put("uid", uid).put("text", text).put("status", status)
        .put("created", created).put("updated_ms", updatedMs)

    companion object {
        fun fromJson(o: JSONObject) = LocalTodo(o.optString("uid"), o.optString("text"), o.optString("status", "open"),
            o.optString("created"), o.optLong("updated_ms"), dirty = false, synced = true)
    }
}

/** A routine task: comes back daily / weekdays / weekly:<0-6, Monday = 0> / monthly:<1-31> (RoutineLogic).
 *  `doneDay` = the ISO date it was last ticked ("" = not ticked). Deleted counts as finished for sync. */
data class LocalChore(
    override val uid: String, val text: String, val freq: String, val doneDay: String = "", val status: String = "active",
    val created: String = "", override val updatedMs: Long = System.currentTimeMillis(), override val dirty: Boolean = true,
    override val synced: Boolean = false,
) : Syncable {
    override val finished get() = status == "deleted"
    fun toJson(): JSONObject = JSONObject().put("uid", uid).put("text", text).put("freq", freq).put("done_day", doneDay)
        .put("status", status).put("created", created).put("updated_ms", updatedMs)

    companion object {
        fun fromJson(o: JSONObject) = LocalChore(o.optString("uid"), o.optString("text"), o.optString("freq"),
            o.optString("done_day"), o.optString("status", "active"), o.optString("created"), o.optLong("updated_ms"),
            dirty = false, synced = true)
    }
}

/** A lecture / meeting recorded on the phone. state: recording, waiting (for the laptop), uploading,
 *  processing (the laptop is writing the notes), done (note_id), failed. */
data class LocalRecording(
    val uid: String, val kind: String, val title: String, val startedMs: Long, val durationS: Long,
    val file: String, val state: String, val noteId: Int = 0, val error: String = "",
)

class LocalDb private constructor(context: Context) : SQLiteOpenHelper(context, "max-local.db", null, 4) {
    override fun onCreate(db: SQLiteDatabase) {
        db.execSQL("CREATE TABLE reminders (uid TEXT PRIMARY KEY, text TEXT NOT NULL, due_ms INTEGER NOT NULL, " +
                   "status TEXT NOT NULL, updated_ms INTEGER NOT NULL, dirty INTEGER NOT NULL, synced INTEGER NOT NULL, " +
                   "repeat_rule TEXT NOT NULL DEFAULT '')")
        db.execSQL("CREATE TABLE events (uid TEXT PRIMARY KEY, title TEXT NOT NULL, start_ms INTEGER NOT NULL, " +
                   "end_ms INTEGER NOT NULL, all_day INTEGER NOT NULL, location TEXT NOT NULL, status TEXT NOT NULL, " +
                   "updated_ms INTEGER NOT NULL, dirty INTEGER NOT NULL, synced INTEGER NOT NULL)")
        db.execSQL("CREATE TABLE recordings (uid TEXT PRIMARY KEY, kind TEXT NOT NULL, title TEXT NOT NULL, " +
                   "started_ms INTEGER NOT NULL, duration_s INTEGER NOT NULL, file TEXT NOT NULL, state TEXT NOT NULL, " +
                   "note_id INTEGER NOT NULL DEFAULT 0, error TEXT NOT NULL DEFAULT '')")
        createTodos(db)
        createRoutine(db)
    }

    private fun createTodos(db: SQLiteDatabase) =
        db.execSQL("CREATE TABLE IF NOT EXISTS todos (uid TEXT PRIMARY KEY, text TEXT NOT NULL, status TEXT NOT NULL, " +
                   "created TEXT NOT NULL, updated_ms INTEGER NOT NULL, dirty INTEGER NOT NULL, synced INTEGER NOT NULL)")

    private fun createRoutine(db: SQLiteDatabase) =
        db.execSQL("CREATE TABLE IF NOT EXISTS routine (uid TEXT PRIMARY KEY, text TEXT NOT NULL, freq TEXT NOT NULL, " +
                   "done_day TEXT NOT NULL, status TEXT NOT NULL, created TEXT NOT NULL, updated_ms INTEGER NOT NULL, " +
                   "dirty INTEGER NOT NULL, synced INTEGER NOT NULL)")

    override fun onUpgrade(db: SQLiteDatabase, oldVersion: Int, newVersion: Int) {
        if (oldVersion < 2) db.execSQL("ALTER TABLE reminders ADD COLUMN repeat_rule TEXT NOT NULL DEFAULT ''")
        if (oldVersion < 3) createTodos(db)
        if (oldVersion < 4) createRoutine(db)
    }

    // ----- routine -----
    fun chores(where: String = "1", vararg args: String): List<LocalChore> =
        readableDatabase.rawQuery("SELECT * FROM routine WHERE $where ORDER BY created, rowid", args).use { c ->
            generateSequence { if (c.moveToNext()) c else null }.map {
                LocalChore(c.s("uid"), c.s("text"), c.s("freq"), c.s("done_day"), c.s("status"), c.s("created"),
                           c.l("updated_ms"), c.l("dirty") == 1L, c.l("synced") == 1L)
            }.toList()
        }

    fun chore(uid: String) = chores("uid = ?", uid).firstOrNull()

    fun put(t: LocalChore) {
        writableDatabase.insertWithOnConflict("routine", null, ContentValues().apply {
            put("uid", t.uid); put("text", t.text); put("freq", t.freq); put("done_day", t.doneDay); put("status", t.status)
            put("created", t.created); put("updated_ms", t.updatedMs); put("dirty", if (t.dirty) 1 else 0)
            put("synced", if (t.synced) 1 else 0)
        }, SQLiteDatabase.CONFLICT_REPLACE)
        changed()
    }

    // ----- reminders -----
    fun reminders(where: String = "1", vararg args: String): List<LocalReminder> =
        readableDatabase.rawQuery("SELECT * FROM reminders WHERE $where ORDER BY due_ms", args).use { c ->
            generateSequence { if (c.moveToNext()) c else null }.map {
                LocalReminder(c.s("uid"), c.s("text"), c.l("due_ms"), c.s("status"), c.l("updated_ms"),
                              c.l("dirty") == 1L, c.l("synced") == 1L, c.s("repeat_rule"))
            }.toList()
        }

    fun reminder(uid: String) = reminders("uid = ?", uid).firstOrNull()

    fun put(r: LocalReminder) {
        writableDatabase.insertWithOnConflict("reminders", null, ContentValues().apply {
            put("uid", r.uid); put("text", r.text); put("due_ms", r.dueMs); put("status", r.status)
            put("updated_ms", r.updatedMs); put("dirty", if (r.dirty) 1 else 0); put("synced", if (r.synced) 1 else 0)
            put("repeat_rule", r.repeat)
        }, SQLiteDatabase.CONFLICT_REPLACE)
        changed()
    }

    // ----- events -----
    fun events(where: String = "1", vararg args: String): List<LocalEvent> =
        readableDatabase.rawQuery("SELECT * FROM events WHERE $where ORDER BY start_ms", args).use { c ->
            generateSequence { if (c.moveToNext()) c else null }.map {
                LocalEvent(c.s("uid"), c.s("title"), c.l("start_ms"), c.l("end_ms"), c.l("all_day") == 1L,
                           c.s("location"), c.s("status"), c.l("updated_ms"), c.l("dirty") == 1L, c.l("synced") == 1L)
            }.toList()
        }

    fun event(uid: String) = events("uid = ?", uid).firstOrNull()

    fun put(e: LocalEvent) {
        writableDatabase.insertWithOnConflict("events", null, ContentValues().apply {
            put("uid", e.uid); put("title", e.title); put("start_ms", e.startMs); put("end_ms", e.endMs)
            put("all_day", if (e.allDay) 1 else 0); put("location", e.location); put("status", e.status)
            put("updated_ms", e.updatedMs); put("dirty", if (e.dirty) 1 else 0); put("synced", if (e.synced) 1 else 0)
        }, SQLiteDatabase.CONFLICT_REPLACE)
        changed()
    }

    // ----- todos -----
    fun todos(where: String = "1", vararg args: String): List<LocalTodo> =
        readableDatabase.rawQuery("SELECT * FROM todos WHERE $where ORDER BY created, rowid", args).use { c ->
            generateSequence { if (c.moveToNext()) c else null }.map {
                LocalTodo(c.s("uid"), c.s("text"), c.s("status"), c.s("created"), c.l("updated_ms"),
                          c.l("dirty") == 1L, c.l("synced") == 1L)
            }.toList()
        }

    fun todo(uid: String) = todos("uid = ?", uid).firstOrNull()

    /** What the list shows: open ones first, then ticked ones (until cleared). */
    fun shownTodos(): List<LocalTodo> = todos("status = 'open'") + todos("status = 'done'")

    fun put(t: LocalTodo) {
        writableDatabase.insertWithOnConflict("todos", null, ContentValues().apply {
            put("uid", t.uid); put("text", t.text); put("status", t.status); put("created", t.created)
            put("updated_ms", t.updatedMs); put("dirty", if (t.dirty) 1 else 0); put("synced", if (t.synced) 1 else 0)
        }, SQLiteDatabase.CONFLICT_REPLACE)
        changed()
    }

    fun delete(table: String, uid: String) {
        require(table in setOf("reminders", "events", "todos", "routine", "recordings"))
        writableDatabase.delete(table, "uid = ?", arrayOf(uid))
        changed()
    }

    // ----- recordings -----
    fun recordings(where: String = "1", vararg args: String): List<LocalRecording> =
        readableDatabase.rawQuery("SELECT * FROM recordings WHERE $where ORDER BY started_ms DESC", args).use { c ->
            generateSequence { if (c.moveToNext()) c else null }.map {
                LocalRecording(c.s("uid"), c.s("kind"), c.s("title"), c.l("started_ms"), c.l("duration_s"),
                               c.s("file"), c.s("state"), c.l("note_id").toInt(), c.s("error"))
            }.toList()
        }

    fun recording(uid: String) = recordings("uid = ?", uid).firstOrNull()

    fun put(r: LocalRecording) {
        writableDatabase.insertWithOnConflict("recordings", null, ContentValues().apply {
            put("uid", r.uid); put("kind", r.kind); put("title", r.title); put("started_ms", r.startedMs)
            put("duration_s", r.durationS); put("file", r.file); put("state", r.state); put("note_id", r.noteId)
            put("error", r.error)
        }, SQLiteDatabase.CONFLICT_REPLACE)
        changed()
    }

    private fun Cursor.s(col: String): String = getString(getColumnIndexOrThrow(col)) ?: ""
    private fun Cursor.l(col: String): Long = getLong(getColumnIndexOrThrow(col))

    companion object {
        @Volatile private var instance: LocalDb? = null
        fun get(context: Context): LocalDb =
            instance ?: synchronized(this) { instance ?: LocalDb(context.applicationContext).also { instance = it } }

        /** Bumped on every change, so screens showing local data refresh. */
        val revision = MutableStateFlow(0)
        fun changed() { revision.value++ }

        fun newUid(): String = UUID.randomUUID().toString().replace("-", "")
    }
}
