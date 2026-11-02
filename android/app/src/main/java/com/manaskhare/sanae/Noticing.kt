package com.manaskhare.sanae

import android.app.AppOpsManager
import android.app.usage.UsageEvents
import android.app.usage.UsageStatsManager
import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.media.session.MediaSessionManager
import android.media.session.PlaybackState
import android.os.Process
import androidx.health.connect.client.HealthConnectClient
import androidx.health.connect.client.permission.HealthPermission
import androidx.health.connect.client.records.DistanceRecord
import androidx.health.connect.client.records.ExerciseSessionRecord
import androidx.health.connect.client.request.AggregateRequest
import androidx.health.connect.client.request.ReadRecordsRequest
import androidx.health.connect.client.time.TimeRangeFilter
import org.json.JSONArray
import org.json.JSONObject
import java.time.Duration
import java.time.Instant
import java.time.LocalDate
import java.time.LocalDateTime
import java.time.ZoneId

/**
 * "She notices" (Settings, each part off until turned on): what the phone tells the laptop so she
 * can react like a roommate would (roommate.py). Only these are ever sent:
 *   - minutes today in a short list of apps (social apps, Duolingo, and apps linked to your daily
 *     list), and before 5 AM the minutes since midnight in the social ones;
 *   - workouts logged in Health Connect (Strava, Samsung Health...) in the last day: type, length, km;
 *   - the song playing right now (title and artist), from the media controls.
 * POST /api/phone/life, from the link service every few minutes, only when something changed.
 */
object Noticing {
    val SOCIAL = setOf("com.instagram.android", "com.zhiliaoapp.musically", "com.ss.android.ugc.trill", "com.reddit.frontpage",
                       "com.twitter.android", "com.google.android.youtube", "com.snapchat.android", "com.facebook.katana")
    const val DUOLINGO = "com.duolingo"
    val WORKOUT_PERMISSIONS = setOf(
        HealthPermission.getReadPermission(ExerciseSessionRecord::class),
        HealthPermission.getReadPermission(DistanceRecord::class),
    )

    fun usageGranted(context: Context): Boolean = runCatching {
        val ops = context.getSystemService(AppOpsManager::class.java)
        ops.unsafeCheckOpNoThrow(AppOpsManager.OPSTR_GET_USAGE_STATS, Process.myUid(), context.packageName) == AppOpsManager.MODE_ALLOWED
    }.getOrDefault(false)

    fun usageSettings(): Intent = Intent(android.provider.Settings.ACTION_USAGE_ACCESS_SETTINGS)

    fun listenerOn(context: Context): Boolean =
        androidx.core.app.NotificationManagerCompat.getEnabledListenerPackages(context).contains(context.packageName)

    suspend fun workoutsGranted(context: Context): Boolean = HealthShare.available(context) &&
        HealthConnectClient.getOrCreate(context).permissionController.getGrantedPermissions().containsAll(WORKOUT_PERMISSIONS)

    /** Foreground minutes per package between `from` and `to` (from the usage events, which are exact). */
    fun minutes(context: Context, from: Long, to: Long, packages: Set<String>): Map<String, Double> {
        val usm = context.getSystemService(UsageStatsManager::class.java) ?: return emptyMap()
        val events = usm.queryEvents(from, to)
        val open = HashMap<String, Long>()
        val total = HashMap<String, Long>()
        val e = UsageEvents.Event()
        while (events.hasNextEvent()) {
            events.getNextEvent(e)
            val pkg = e.packageName ?: continue
            if (pkg !in packages) continue
            when (e.eventType) {
                UsageEvents.Event.ACTIVITY_RESUMED -> open[pkg] = e.timeStamp
                UsageEvents.Event.ACTIVITY_PAUSED, UsageEvents.Event.ACTIVITY_STOPPED ->
                    open.remove(pkg)?.let { total[pkg] = (total[pkg] ?: 0L) + (e.timeStamp - it) }
            }
        }
        open.forEach { (pkg, t) -> total[pkg] = (total[pkg] ?: 0L) + (to - t) }     // still in front
        return total.mapValues { (it.value / 60_000.0 * 10).toLong() / 10.0 }.filterValues { it >= 0.5 }
    }

    /** Apps linked to the daily list (Us tab), so they can tick themselves. */
    private fun linkedApps(context: Context): Set<String> =
        Us.together(context)?.optJSONArray("activities")?.objects().orEmpty().map { it.optString("app") }.filter { it.isNotBlank() }.toSet()

    suspend fun workouts(context: Context, zone: ZoneId = ZoneId.systemDefault()): JSONArray {
        val hc = HealthConnectClient.getOrCreate(context)
        val end = Instant.now()
        val start = end.minus(Duration.ofHours(30))
        val out = JSONArray()
        val sessions = runCatching { hc.readRecords(ReadRecordsRequest(ExerciseSessionRecord::class, TimeRangeFilter.between(start, end))).records }
            .getOrDefault(emptyList())
        for (s in sessions.takeLast(5)) {
            val km = runCatching {
                hc.aggregate(AggregateRequest(setOf(DistanceRecord.DISTANCE_TOTAL), TimeRangeFilter.between(s.startTime, s.endTime)))[DistanceRecord.DISTANCE_TOTAL]?.inKilometers
            }.getOrNull()
            val type = workoutType(s.exerciseType)
            out.put(JSONObject()
                .put("start", LocalDateTime.ofInstant(s.startTime, zone).withNano(0).toString())
                .put("end", LocalDateTime.ofInstant(s.endTime, zone).withNano(0).toString())
                .put("type", type)
                .put("minutes", Duration.between(s.startTime, s.endTime).toMinutes())
                .apply { if (km != null && km > 0.05) put("km", Math.round(km * 100) / 100.0) })
        }
        return out
    }

    fun playing(context: Context): JSONObject? = runCatching {
        val msm = context.getSystemService(MediaSessionManager::class.java)
        val controllers = msm.getActiveSessions(ComponentName(context, SanaeNotificationListener::class.java))
        val c = controllers.firstOrNull { it.playbackState?.state == PlaybackState.STATE_PLAYING } ?: return null
        val md = c.metadata ?: return null
        val title = md.getString(android.media.MediaMetadata.METADATA_KEY_TITLE).orEmpty()
        val artist = md.getString(android.media.MediaMetadata.METADATA_KEY_ARTIST)
            ?: md.getString(android.media.MediaMetadata.METADATA_KEY_ALBUM_ARTIST).orEmpty()
        if (title.isBlank() || c.packageName == context.packageName) null
        else JSONObject().put("title", title).put("artist", artist).put("package", c.packageName)   // YouTube (ReVanced) = video
    }.getOrNull()

    /** What to send now, or null if every part is off. */
    suspend fun build(context: Context): JSONObject? {
        val prefs = Prefs(context)
        if (!prefs.noticeApps && !prefs.noticeMusic && !prefs.noticeWorkouts) return null
        val zone = ZoneId.systemDefault()
        val now = System.currentTimeMillis()
        val today = LocalDate.now(zone)
        val body = JSONObject().put("day", today.toString())
        if (prefs.noticeApps && usageGranted(context)) {
            val midnight = today.atStartOfDay(zone).toInstant().toEpochMilli()
            val apps = minutes(context, midnight, now, SOCIAL + DUOLINGO + linkedApps(context))
            body.put("apps", JSONObject(apps as Map<*, *>))
            if (LocalDateTime.now(zone).hour < 5) body.put("night", JSONObject(apps.filterKeys { it in SOCIAL } as Map<*, *>))
        }
        if (prefs.noticeWorkouts && runCatching { workoutsGranted(context) }.getOrDefault(false)) {
            body.put("workouts", runCatching { workouts(context, zone) }.getOrDefault(JSONArray()))
        }
        if (prefs.noticeMusic && listenerOn(context)) playing(context)?.let { body.put("playing", it) }
        return body
    }

    /** Sends a report if anything changed since the last one (minutes rounded so it isn't every tick). */
    suspend fun report(context: Context) {
        val api = SanaeApi.from(Prefs(context)) ?: return
        val body = build(context) ?: return
        val apps = body.optJSONObject("apps")
        val sig = JSONObject(body.toString()).apply {
            apps?.let { a -> put("apps", JSONObject().also { r -> a.keys().forEach { k -> r.put(k, (a.optDouble(k) / 3).toInt()) } }) }
            optJSONObject("night")?.let { n -> put("night", JSONObject().also { r -> n.keys().forEach { k -> r.put(k, (n.optDouble(k) / 5).toInt()) } }) }
        }.toString()
        val prefs = Prefs(context)
        if (sig == prefs.lifeSent) return
        runCatching { api.raw("POST", "/api/phone/life", body) }.onSuccess { prefs.lifeSent = sig }
    }

    /** Apps the daily list can be linked to: installed apps with a launcher icon, by name. */
    fun launchable(context: Context): List<Pair<String, String>> = runCatching {
        val pm = context.packageManager
        pm.queryIntentActivities(Intent(Intent.ACTION_MAIN).addCategory(Intent.CATEGORY_LAUNCHER), 0)
            .map { it.activityInfo.packageName to it.loadLabel(pm).toString() }
            .filter { it.first != context.packageName }
            .distinctBy { it.first }
            .sortedBy { it.second.lowercase() }
    }.getOrDefault(emptyList())

    fun label(context: Context, pkg: String): String = runCatching {
        context.packageManager.getApplicationLabel(context.packageManager.getApplicationInfo(pkg, 0)).toString()
    }.getOrDefault(pkg.substringAfterLast('.'))

    fun open(context: Context, pkg: String): Boolean {
        val intent = context.packageManager.getLaunchIntentForPackage(pkg) ?: return false
        context.startActivity(intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
        return true
    }
}

/** Health Connect's workout number -> the names the laptop knows (roommate.py KINDS); its own
 *  number-to-name map is internal to the library. */
private fun workoutType(t: Int): String = when (t) {
    ExerciseSessionRecord.EXERCISE_TYPE_RUNNING, ExerciseSessionRecord.EXERCISE_TYPE_RUNNING_TREADMILL -> "running"
    ExerciseSessionRecord.EXERCISE_TYPE_WALKING -> "walking"
    ExerciseSessionRecord.EXERCISE_TYPE_BIKING, ExerciseSessionRecord.EXERCISE_TYPE_BIKING_STATIONARY -> "biking"
    ExerciseSessionRecord.EXERCISE_TYPE_SWIMMING_POOL, ExerciseSessionRecord.EXERCISE_TYPE_SWIMMING_OPEN_WATER -> "swimming"
    ExerciseSessionRecord.EXERCISE_TYPE_HIKING -> "hiking"
    ExerciseSessionRecord.EXERCISE_TYPE_STRENGTH_TRAINING -> "strength_training"
    ExerciseSessionRecord.EXERCISE_TYPE_WEIGHTLIFTING -> "weightlifting"
    ExerciseSessionRecord.EXERCISE_TYPE_YOGA -> "yoga"
    else -> "workout"
}
