package com.manaskhare.sanae

import android.app.NotificationManager
import android.app.PendingIntent
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import androidx.core.app.NotificationCompat
import androidx.core.app.Person
import androidx.core.app.RemoteInput
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch

/**
 * Her texts while you're away from the laptop (the laptop's texts.py): a message notification
 * with a Reply box. A reply goes to her like any phone command, and her answer is added to the
 * same notification, so it reads like a chat thread. The Galaxy Watch mirrors it (reply there too).
 */
object Texts {
    const val NOTIFICATION_ID = 7000
    const val KEY_REPLY = "reply"
    private val thread = mutableListOf<Triple<String, Boolean, Long>>()      // (text, from her, time)

    fun received(context: Context, text: String, at: Long = System.currentTimeMillis()) {
        if (text.isBlank()) return
        synchronized(thread) {
            if (thread.isNotEmpty() && at - thread.last().third > 6 * 3600_000L) thread.clear()   // a new conversation
            thread += Triple(text, true, at)
        }
        show(context)
    }

    /** You replied from the notification: shown right away (no sound); her answer follows. */
    fun replied(context: Context, mine: String) {
        synchronized(thread) { thread += Triple(mine, false, System.currentTimeMillis()) }
        show(context, alert = false)
    }

    fun answered(context: Context, hers: String) {
        if (hers.isBlank()) return
        synchronized(thread) { thread += Triple(hers, true, System.currentTimeMillis()) }
        show(context)
    }

    private fun show(context: Context, alert: Boolean = true) {
        val her = Person.Builder().setName(Persona.name(context)).build()
        val me = Person.Builder().setName("You").build()
        val style = NotificationCompat.MessagingStyle(me)
        synchronized(thread) {
            thread.takeLast(8).forEach { (text, fromHer, at) -> style.addMessage(text, at, if (fromHer) her else null) }
        }
        val replyIntent = PendingIntent.getBroadcast(
            context, NOTIFICATION_ID, Intent(context, TextReplyReceiver::class.java),
            PendingIntent.FLAG_MUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
        val reply = NotificationCompat.Action.Builder(0, "Reply", replyIntent)
            .addRemoteInput(RemoteInput.Builder(KEY_REPLY).setLabel("Message ${Persona.name(context)}").build())
            .setAllowGeneratedReplies(true)
            .build()
        val open = PendingIntent.getActivity(context, 0,
            Intent(context, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
        context.getSystemService(NotificationManager::class.java).notify(NOTIFICATION_ID,
            NotificationCompat.Builder(context, SanaeApp.CH_CHAT)
                .setSmallIcon(R.drawable.ic_stat_sanae)
                .setStyle(style)
                .setCategory(NotificationCompat.CATEGORY_MESSAGE)
                .setOnlyAlertOnce(!alert)
                .setAutoCancel(true)
                .setContentIntent(open)
                .addAction(reply)
                .build())
    }
}

class TextReplyReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        val text = RemoteInput.getResultsFromIntent(intent)?.getCharSequence(Texts.KEY_REPLY)?.toString()?.trim()
        if (text.isNullOrBlank()) return
        val api = SanaeApi.from(Prefs(context)) ?: return
        Texts.replied(context, text)
        val pending = goAsync()
        CoroutineScope(Dispatchers.IO).launch {
            val answer = runCatching { api.command(text) }.getOrElse { "(Couldn't reach the laptop: ${it.message})" }
            Texts.answered(context, answer)
            pending.finish()
        }
    }
}
