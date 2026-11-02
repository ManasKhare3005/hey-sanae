package com.manaskhare.sanae

import android.app.Application
import android.app.NotificationChannel
import android.app.NotificationManager
import android.content.Context
import android.content.Intent
import androidx.core.content.ContextCompat

class SanaeApp : Application() {
    override fun onCreate() {
        super.onCreate()
        CrashLog.install(this)             // crash / freeze reports go to the laptop with the next sync
        com.manaskhare.sanae.ui.Looks.load(this)
        registerActivityLifecycleCallbacks(object : ActivityLifecycleCallbacks {
            override fun onActivityStarted(a: android.app.Activity) { Hub.visible++ }
            override fun onActivityStopped(a: android.app.Activity) { Hub.visible = (Hub.visible - 1).coerceAtLeast(0) }
            override fun onActivityCreated(a: android.app.Activity, b: android.os.Bundle?) {}
            override fun onActivityResumed(a: android.app.Activity) {}
            override fun onActivityPaused(a: android.app.Activity) {}
            override fun onActivitySaveInstanceState(a: android.app.Activity, b: android.os.Bundle) {}
            override fun onActivityDestroyed(a: android.app.Activity) {}
        })
        val nm = getSystemService(NotificationManager::class.java)
        nm.createNotificationChannels(
            listOf(
                NotificationChannel(CH_LINK, "Connection", NotificationManager.IMPORTANCE_MIN).apply {
                    description = "The always-on link to your laptop"
                    setShowBadge(false)
                },
                NotificationChannel(CH_APPROVAL, "Approvals", NotificationManager.IMPORTANCE_HIGH).apply {
                    description = "Asks before risky actions (send, delete, power...)"
                },
                NotificationChannel(CH_REMINDER, "Reminders", NotificationManager.IMPORTANCE_HIGH).apply {
                    description = "Your reminders"
                },
                NotificationChannel(CH_CHAT, "Messages", NotificationManager.IMPORTANCE_HIGH).apply {
                    description = "When she texts you while you're away from the laptop"
                },
                NotificationChannel(CH_UPDATE, "Updates", NotificationManager.IMPORTANCE_DEFAULT).apply {
                    description = "Notes ready, daily digest"
                },
                NotificationChannel(CH_RECORD, "Recording", NotificationManager.IMPORTANCE_LOW).apply {
                    description = "While a lecture or meeting is being recorded on the phone"
                    setShowBadge(false)
                },
                NotificationChannel(CH_ALARM, "Morning alarm", NotificationManager.IMPORTANCE_HIGH).apply {
                    description = "The alarm she sets at wind-down"
                    setSound(android.media.RingtoneManager.getDefaultUri(android.media.RingtoneManager.TYPE_ALARM),
                             android.media.AudioAttributes.Builder().setUsage(android.media.AudioAttributes.USAGE_ALARM)
                                 .setContentType(android.media.AudioAttributes.CONTENT_TYPE_SONIFICATION).build())
                    enableVibration(true)
                },
            )
        )
        Sync.lastSync.value = Prefs(this).lastSync
        startLink(this)
        // Working without the laptop: a recording cut off by a crash is kept, reminders are armed
        RecordService.recover(this)
        runCatching { Alarms.armAll(this) }
        runCatching { WindDown.arm(this) }        // midnight wind-down (Settings -> Wind down)
        runCatching { Routine.arm(this) }         // the routine's evening "you forgot ..." check
        Sync.trigger(this, 1500)
    }

    companion object {
        const val CH_LINK = "link"
        const val CH_APPROVAL = "approvals"
        const val CH_REMINDER = "reminders"
        const val CH_UPDATE = "updates"
        const val CH_RECORD = "recording"
        const val CH_CHAT = "messages"
        const val CH_ALARM = "alarm"

        /** Start (or poke) the foreground service that keeps the WebSocket open. */
        fun startLink(context: Context) {
            if (!Prefs(context).paired) return
            ContextCompat.startForegroundService(context, Intent(context, SanaeService::class.java))
        }
    }
}
