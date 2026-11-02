package com.manaskhare.sanae

import android.content.Context
import android.net.Uri

/** Where Sanae lives (https://<laptop>.<tailnet>.ts.net) and the pairing token. */
class Prefs(context: Context) {
    private val sp = context.getSharedPreferences("max", Context.MODE_PRIVATE)

    var url: String
        get() = sp.getString("url", "") ?: ""
        set(v) = sp.edit().putString("url", v.trim().trimEnd('/')).apply()

    var token: String
        get() = sp.getString("token", "") ?: ""
        set(v) = sp.edit().putString("token", v.trim()).apply()

    var speakReplies: Boolean
        get() = sp.getBoolean("speak", true)
        set(v) = sp.edit().putBoolean("speak", v).apply()

    /** Time (ms) of the last deadline alert shown, so alerts missed while offline are shown once.
     *  (Event ids restart when Sanae restarts; timestamps don't.) */
    var lastAlertAt: Long
        get() = sp.getLong("lastAlertAt", 0L)
        set(v) = sp.edit().putLong("lastAlertAt", v).apply()

    /** Time (ms) of her last text shown, so texts sent while the phone was offline show once. */
    var lastTextAt: Long
        get() = sp.getLong("lastTextAt", 0L)
        set(v) = sp.edit().putLong("lastTextAt", v).apply()

    /** When the phone last synced with the laptop (ms), and the Today page from then (for offline). */
    var lastSync: Long
        get() = sp.getLong("lastSync", 0L)
        set(v) = sp.edit().putLong("lastSync", v).apply()

    var todayJson: String
        get() = sp.getString("todayJson", "") ?: ""
        set(v) = sp.edit().putString("todayJson", v).apply()

    var personaJson: String
        get() = sp.getString("personaJson", "") ?: ""
        set(v) = sp.edit().putString("personaJson", v).apply()

    /** Health sharing (Settings -> Health): off until turned on. */
    var healthOn: Boolean
        get() = sp.getBoolean("healthOn", false)
        set(v) = sp.edit().putBoolean("healthOn", v).apply()

    var todayAt: Long
        get() = sp.getLong("todayAt", 0L)
        set(v) = sp.edit().putLong("todayAt", v).apply()

    /** The "Us" tab from the last sync (Us.kt), and its changes made offline, waiting to be sent. */
    var usJson: String
        get() = sp.getString("usJson", "") ?: ""
        set(v) = sp.edit().putString("usJson", v).apply()

    var usOutbox: String
        get() = sp.getString("usOutbox", "[]") ?: "[]"
        set(v) = sp.edit().putString("usOutbox", v).apply()

    /** Newest notebook page of hers (or letter) already announced; -1 before the first sync. */
    var notebookSeen: Int
        get() = sp.getInt("notebookSeen", -1)
        set(v) = sp.edit().putInt("notebookSeen", v).apply()

    /** Wind-down at midnight (WindDown.kt): on by default; Do Not Disturb only once access is given. */
    /** The routine's evening check: "you forgot ... today" for anything still unticked (Routine.kt). */
    var routineCheckOn: Boolean
        get() = sp.getBoolean("routineCheckOn", true)
        set(v) = sp.edit().putBoolean("routineCheckOn", v).apply()
    var routineCheckAt: String
        get() = sp.getString("routineCheckAt", "21:00") ?: "21:00"
        set(v) = sp.edit().putString("routineCheckAt", v).apply()

    var windDownOn: Boolean
        get() = sp.getBoolean("windDownOn", true)
        set(v) = sp.edit().putBoolean("windDownOn", v).apply()
    var windDownAt: String
        get() = sp.getString("windDownAt", "00:00") ?: "00:00"
        set(v) = sp.edit().putString("windDownAt", v).apply()
    var windDownQuiet: Boolean
        get() = sp.getBoolean("windDownQuiet", true)
        set(v) = sp.edit().putBoolean("windDownQuiet", v).apply()
    var windDownAlarm: Boolean
        get() = sp.getBoolean("windDownAlarm", true)
        set(v) = sp.edit().putBoolean("windDownAlarm", v).apply()
    var wakeAt: String
        get() = sp.getString("wakeAt", "08:30") ?: "08:30"
        set(v) = sp.edit().putString("wakeAt", v).apply()
    var windDownQuieted: Boolean
        get() = sp.getBoolean("windDownQuieted", false)
        set(v) = sp.edit().putBoolean("windDownQuieted", v).apply()
    var windDownAlarmAt: Long
        get() = sp.getLong("windDownAlarmAt", 0L)
        set(v) = sp.edit().putLong("windDownAlarmAt", v).apply()

    /** Home Wi-Fi (HomeWifi.kt): its name / router fingerprint stay on the phone; only arrived/left is sent. */
    var homeEnabled: Boolean
        get() = sp.getBoolean("homeEnabled", false)
        set(v) = sp.edit().putBoolean("homeEnabled", v).apply()
    var homeSsid: String
        get() = sp.getString("homeSsid", "") ?: ""
        set(v) = sp.edit().putString("homeSsid", v).apply()
    var homeFingerprint: String
        get() = sp.getString("homeFingerprint", "") ?: ""
        set(v) = sp.edit().putString("homeFingerprint", v).apply()
    var homeState: String
        get() = sp.getString("homeState", "") ?: ""
        set(v) = sp.edit().putString("homeState", v).apply()
    var homeLeaveSince: Long
        get() = sp.getLong("homeLeaveSince", 0L)
        set(v) = sp.edit().putLong("homeLeaveSince", v).apply()

    /** She notices (Settings): app minutes, what's playing, workouts. Each off until turned on. */
    var noticeApps: Boolean
        get() = sp.getBoolean("noticeApps", false)
        set(v) = sp.edit().putBoolean("noticeApps", v).apply()

    var noticeMusic: Boolean
        get() = sp.getBoolean("noticeMusic", false)
        set(v) = sp.edit().putBoolean("noticeMusic", v).apply()

    var noticeWorkouts: Boolean
        get() = sp.getBoolean("noticeWorkouts", false)
        set(v) = sp.edit().putBoolean("noticeWorkouts", v).apply()

    /** The last report sent (rounded), so an unchanged one isn't sent again. */
    var lifeSent: String
        get() = sp.getString("lifeSent", "") ?: ""
        set(v) = sp.edit().putString("lifeSent", v).apply()

    /** Her newest voice note already announced. */
    var voiceNoteSeen: Int
        get() = sp.getInt("voiceNoteSeen", 0)
        set(v) = sp.edit().putInt("voiceNoteSeen", v).apply()

    /** Newest week in review already announced ("2026-W42"); "?" before the first sync. */
    var usSeen: String                       // Us tiles: what each one showed when last opened (UsTiles.signature)
        get() = sp.getString("usSeen", "") ?: ""
        set(v) = sp.edit().putString("usSeen", v).apply()
    var weekSeen: String
        get() = sp.getString("weekSeen", "?") ?: "?"
        set(v) = sp.edit().putString("weekSeen", v).apply()

    val paired: Boolean get() = url.isNotBlank() && token.isNotBlank()

    fun clear() = sp.edit().remove("url").remove("token").apply()

    /** max://pair?url=...&token=...  ->  saved; returns false if the link is not a pairing link. */
    fun pairFrom(link: String): Boolean {
        val uri = runCatching { Uri.parse(link.trim()) }.getOrNull() ?: return false
        if (uri.scheme != "max" || uri.host != "pair") return false
        val u = uri.getQueryParameter("url").orEmpty()
        val t = uri.getQueryParameter("token").orEmpty()
        if (!u.startsWith("http") || t.length < 20) return false
        url = u
        token = t
        return true
    }
}
