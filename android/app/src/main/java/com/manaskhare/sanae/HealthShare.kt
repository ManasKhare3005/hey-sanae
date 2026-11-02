package com.manaskhare.sanae

import android.content.Context
import androidx.health.connect.client.HealthConnectClient
import androidx.health.connect.client.permission.HealthPermission
import androidx.health.connect.client.records.HeartRateRecord
import androidx.health.connect.client.records.RestingHeartRateRecord
import androidx.health.connect.client.records.SleepSessionRecord
import androidx.health.connect.client.records.StepsRecord
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
 * Health from the Galaxy Watch, read on the phone from Health Connect (Samsung Health puts the
 * watch's sleep, steps and heart rate there). Off until turned on in Settings -> Health; then each
 * sync sends today's and yesterday's numbers to the laptop (POST /api/health). Read-only.
 */
object HealthShare {
    val PERMISSIONS = setOf(
        HealthPermission.getReadPermission(SleepSessionRecord::class),
        HealthPermission.getReadPermission(StepsRecord::class),
        HealthPermission.getReadPermission(RestingHeartRateRecord::class),
        HealthPermission.getReadPermission(HeartRateRecord::class),
    )

    fun available(context: Context): Boolean = runCatching {      // (screenshot tests have no system services)
        HealthConnectClient.getSdkStatus(context) == HealthConnectClient.SDK_AVAILABLE
    }.getOrDefault(false)

    suspend fun granted(context: Context): Boolean = available(context) &&
        HealthConnectClient.getOrCreate(context).permissionController.getGrantedPermissions().containsAll(PERMISSIONS)

    /** One day's row for the laptop: sleep that ended that day (after 6 PM the day before), steps,
     *  resting heart rate, and the latest heart rate reading. Missing numbers are left out. */
    suspend fun read(context: Context, day: LocalDate, zone: ZoneId = ZoneId.systemDefault(),
                     now: Instant = Instant.now()): JSONObject {
        val hc = HealthConnectClient.getOrCreate(context)
        val start = day.atStartOfDay(zone).toInstant()
        val end = minOf(day.plusDays(1).atStartOfDay(zone).toInstant(), now)
        val out = JSONObject().put("day", day.toString())

        val sleepFrom = day.minusDays(1).atTime(18, 0).atZone(zone).toInstant()
        val sleeps = runCatching {
            hc.readRecords(ReadRecordsRequest(SleepSessionRecord::class, TimeRangeFilter.between(sleepFrom, end))).records
        }.getOrDefault(emptyList()).filter { it.endTime >= start.minus(Duration.ofHours(6)) && it.endTime <= end }
        sleepRow(sleeps.map { it.startTime to it.endTime }, zone)?.let { (mins, a, b) ->
            out.put("sleep_min", mins).put("sleep_start", a).put("sleep_end", b)
        }
        runCatching {
            hc.aggregate(AggregateRequest(setOf(StepsRecord.COUNT_TOTAL), TimeRangeFilter.between(start, end)))[StepsRecord.COUNT_TOTAL]
        }.getOrNull()?.let { out.put("steps", it) }
        val resting = runCatching {
            hc.readRecords(ReadRecordsRequest(RestingHeartRateRecord::class, TimeRangeFilter.between(start, end))).records
        }.getOrDefault(emptyList()).maxByOrNull { it.time }?.beatsPerMinute
        // from last night's sleep (it can start the evening before), so read from sleepFrom
        val samples = runCatching {
            hc.readRecords(ReadRecordsRequest(HeartRateRecord::class, TimeRangeFilter.between(sleepFrom, end), pageSize = 5000)).records
        }.getOrDefault(emptyList()).flatMap { it.samples }.map { it.time to it.beatsPerMinute }
        if (resting != null) out.put("resting_hr", resting)
        else restingFrom(samples.filter { it.first >= start || sleeps.any { s -> it.first >= s.startTime && it.first <= s.endTime } },
                         sleeps.map { it.startTime to it.endTime })?.let { out.put("resting_hr", it).put("resting_est", true) }
        samples.filter { it.first >= start }.maxByOrNull { it.first }?.let { (t, bpm) ->
            out.put("hr", bpm).put("hr_at", LocalDateTime.ofInstant(t, zone).withNano(0).toString())
        }
        return out
    }

    /** Samsung Health doesn't put a resting heart rate in Health Connect: estimate one from the
     *  readings. Asleep is best (the median of the lowest fifth, so one odd low reading doesn't
     *  count); without enough sleep readings, the same over the day's readings. Null if too few. */
    fun restingFrom(samples: List<Pair<Instant, Long>>, sleeps: List<Pair<Instant, Instant>>): Int? {
        val ok = samples.filter { it.second in 30..150 }
        val asleep = ok.filter { (t, _) -> sleeps.any { t >= it.first && t <= it.second } }
        val pool = when {
            asleep.size >= 10 -> asleep
            ok.size >= 30 -> ok
            else -> return null
        }.map { it.second }.sorted()
        val low = pool.take(maxOf(5, pool.size / 5))
        return if (low.size % 2 == 1) low[low.size / 2].toInt()
               else Math.round((low[low.size / 2 - 1] + low[low.size / 2]) / 2.0).toInt()
    }

    /** Yesterday and today, for one sync. */
    suspend fun recent(context: Context): JSONArray {
        val today = LocalDate.now()
        return JSONArray().put(read(context, today.minusDays(1))).put(read(context, today))
    }

    /** Sleep sessions -> (minutes asleep, first start, last end) as local ISO times; naps under 20 min ignored. */
    fun sleepRow(sessions: List<Pair<Instant, Instant>>, zone: ZoneId): Triple<Int, String, String>? {
        val real = sessions.filter { Duration.between(it.first, it.second).toMinutes() >= 20 }
        if (real.isEmpty()) return null
        val mins = real.sumOf { Duration.between(it.first, it.second).toMinutes() }.toInt()
        val iso = { t: Instant -> LocalDateTime.ofInstant(t, zone).withNano(0).toString() }
        return Triple(mins, iso(real.minOf { it.first }), iso(real.maxOf { it.second }))
    }
}
