package com.manaskhare.sanae

import android.app.AlarmManager
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import androidx.core.app.NotificationCompat
import org.json.JSONObject
import java.io.File
import java.time.LocalDate
import java.time.LocalDateTime
import java.time.LocalTime
import java.time.ZoneId

/**
 * Her morning voice notes (voicenotes.py on the laptop): downloaded on sync into the app's files so
 * they play without the laptop, and announced once in the morning (at MORNING if it came overnight).
 */
object VoiceNotes {
    val MORNING: LocalTime = LocalTime.of(7, 30)
    private const val NOTIFY_ID = 7300

    fun file(context: Context, id: Int) = File(File(context.filesDir, "voicenotes").apply { mkdirs() }, "$id.wav")

    fun has(context: Context, id: Int) = file(context, id).let { it.exists() && it.length() > 44 }

    /** After a refresh: fetch the new ones, drop old files, announce today's. */
    suspend fun sync(context: Context, api: SanaeApi, us: JSONObject) {
        val notes = us.optJSONObject("voicenotes")?.optJSONArray("notes")?.objects().orEmpty()
        val keep = notes.map { it.optInt("id") }.toSet()
        File(context.filesDir, "voicenotes").listFiles()?.forEach { f -> if (f.nameWithoutExtension.toIntOrNull() !in keep) f.delete() }
        for (n in notes) {
            val id = n.optInt("id")
            if (!has(context, id)) runCatching { api.download("/api/voicenotes/$id.wav", file(context, id)) }
        }
        val today = notes.firstOrNull { it.optString("day") == LocalDate.now().toString() } ?: return
        val prefs = Prefs(context)
        val id = today.optInt("id")
        if (prefs.voiceNoteSeen >= id || !has(context, id)) return
        prefs.voiceNoteSeen = id
        if (LocalTime.now() >= MORNING) notify(context) else schedule(context)
    }

    private fun schedule(context: Context) {
        val at = LocalDateTime.of(LocalDate.now(), MORNING).atZone(ZoneId.systemDefault()).toInstant().toEpochMilli()
        val pi = PendingIntent.getBroadcast(context, NOTIFY_ID, Intent(context, VoiceNoteReceiver::class.java),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
        context.getSystemService(AlarmManager::class.java).setAndAllowWhileIdle(AlarmManager.RTC_WAKEUP, at, pi)
    }

    fun notify(context: Context) {
        val name = Persona.name(context)
        val open = PendingIntent.getActivity(context, NOTIFY_ID,
            Intent(context, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP).putExtra(MainActivity.EXTRA_TAB, MainActivity.TAB_US).putExtra(MainActivity.EXTRA_PAGE, "voicenotes"),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
        context.getSystemService(NotificationManager::class.java).notify(NOTIFY_ID, NotificationCompat.Builder(context, SanaeApp.CH_CHAT)
            .setSmallIcon(R.drawable.ic_stat_sanae)
            .setContentTitle("$name left you a voice message")
            .setContentText("Tap to listen")
            .setCategory(NotificationCompat.CATEGORY_MESSAGE)
            .setAutoCancel(true)
            .setContentIntent(open)
            .build())
    }
}

class VoiceNoteReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) = VoiceNotes.notify(context)
}
