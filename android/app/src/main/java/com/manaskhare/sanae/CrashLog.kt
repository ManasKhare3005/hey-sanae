package com.manaskhare.sanae

import android.app.ActivityManager
import android.app.ApplicationExitInfo
import android.content.Context
import android.os.Build
import java.io.File
import java.time.Instant
import java.time.ZoneId

/**
 * Crashes and freezes reach the laptop (logs/phone-crash.log), since there's usually no USB cable
 * to read logcat. A crash is written to a file as it happens; on the next start Android's own
 * record of why the app last died (crash or "isn't responding", with the ANR thread dump) is added.
 * Reports go up with the next sync and are deleted once the laptop has them.
 */
object CrashLog {
    private const val MAX_TRACE = 150_000

    private fun dir(context: Context) = File(context.filesDir, "crashes").apply { mkdirs() }

    private fun stamp(ms: Long) = Instant.ofEpochMilli(ms).atZone(ZoneId.systemDefault()).toLocalDateTime().withNano(0).toString()

    private fun header(context: Context, what: String, ms: Long) =
        "$what at ${stamp(ms)}\napp built ${stamp(BuildConfig.BUILD_TIME)} · ${Build.MANUFACTURER} ${Build.MODEL} · Android ${Build.VERSION.RELEASE}\n"

    fun install(context: Context) {
        val app = context.applicationContext
        val previous = Thread.getDefaultUncaughtExceptionHandler()
        Thread.setDefaultUncaughtExceptionHandler { thread, e ->
            runCatching {
                val now = System.currentTimeMillis()
                File(dir(app), "crash-$now.txt").writeText(header(app, "crash on thread ${thread.name}", now) + e.stackTraceToString())
            }
            previous?.uncaughtException(thread, e)
        }
        runCatching { collectExits(app) }
    }

    /** Android's record of how the app last ended: crashes and freezes since the last look. */
    private fun collectExits(context: Context) {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.R) return
        val prefs = context.getSharedPreferences("crashlog", Context.MODE_PRIVATE)
        // the first time, the last 3 days count too (a freeze from before this was added)
        val seen = prefs.getLong("seen", System.currentTimeMillis() - 3 * 86_400_000L)
        val am = context.getSystemService(ActivityManager::class.java)
        val exits = am.getHistoricalProcessExitReasons(context.packageName, 0, 10)
        for (x in exits.filter { it.timestamp > seen }) {
            val what = when (x.reason) {
                ApplicationExitInfo.REASON_ANR -> "froze (not responding)"
                ApplicationExitInfo.REASON_CRASH -> "crashed"
                ApplicationExitInfo.REASON_CRASH_NATIVE -> "crashed (native)"
                else -> continue
            }
            val trace = if (x.reason == ApplicationExitInfo.REASON_CRASH) "" else
                runCatching { x.traceInputStream?.use { s -> s.bufferedReader().let { r -> CharArray(MAX_TRACE).let { b -> String(b, 0, r.read(b).coerceAtLeast(0)) } } } }
                    .getOrNull().orEmpty()
            File(dir(context), "exit-${x.timestamp}.txt").writeText(
                header(context, what, x.timestamp) + "process ${x.processName}: ${x.description.orEmpty()}\n" + trace)
        }
        prefs.edit().putLong("seen", maxOf(seen, exits.maxOfOrNull { it.timestamp } ?: seen)).apply()
    }

    /** Send waiting reports; each is deleted once the laptop has it. */
    suspend fun upload(context: Context, api: SanaeApi) {
        dir(context).listFiles()?.sortedBy { it.name }?.forEach { f ->
            runCatching { api.crashReport(f.readText()) }.onSuccess { f.delete() }
        }
    }
}
