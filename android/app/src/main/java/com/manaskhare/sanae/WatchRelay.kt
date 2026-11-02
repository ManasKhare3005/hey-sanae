package com.manaskhare.sanae

import android.content.Context
import android.util.Log
import com.google.android.gms.wearable.ChannelClient
import com.google.android.gms.wearable.MessageEvent
import com.google.android.gms.wearable.Wearable
import com.google.android.gms.wearable.WearableListenerService
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.launch
import kotlinx.coroutines.tasks.await
import org.json.JSONObject

/**
 * The Galaxy Watch app talks to the laptop through this phone app (it needs no pairing of its own):
 * its recordings arrive here over a Data Layer channel, go to the laptop's /api/voice like the
 * phone's own push-to-talk, and the reply (plus her voice) goes back to the watch.
 */
class WatchRelay : WearableListenerService() {
    override fun onMessageReceived(event: MessageEvent) {
        val app = applicationContext
        when (event.path) {
            WatchPaths.GLANCE -> WatchLink.scope.launch { WatchLink.sendGlance(app, event.sourceNodeId) }
            WatchPaths.HR -> WatchLink.heartReply?.complete(String(event.data))
            WatchPaths.APPROVE -> {
                val o = runCatching { JSONObject(String(event.data)) }.getOrNull() ?: return
                val api = SanaeApi.from(Prefs(app)) ?: return
                WatchLink.scope.launch {
                    runCatching { api.approve(o.optInt("id"), o.optBoolean("approved")) }
                        .onFailure { Log.w(TAG, "approval from the watch not sent: ${it.message}") }
                }
            }
        }
    }

    override fun onChannelOpened(channel: ChannelClient.Channel) {
        if (!channel.path.startsWith(WatchPaths.VOICE)) return
        val app = applicationContext
        WatchLink.scope.launch {
            val client = Wearable.getChannelClient(app)
            val wav = runCatching { client.getInputStream(channel).await().use { it.readBytes() } }.getOrNull()
            runCatching { client.close(channel) }
            if (wav == null || wav.size < 1000) return@launch
            WatchLink.answer(app, channel.nodeId, wav, speak = channel.path.endsWith("/speak"))
        }
    }

    companion object { const val TAG = "WatchRelay" }
}

/** Sending to the watch. Everything fails quietly when there's no watch (or no Wear OS on the phone). */
object WatchLink {
    val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    @Volatile var heartReply: kotlinx.coroutines.CompletableDeferred<String>? = null

    /** "What's my heart rate?": the watch measures for up to ~20 s and answers. */
    suspend fun heartRate(context: Context): PhoneActions.Result {
        if (!Prefs(context).healthOn) {
            return PhoneActions.Result(false, "Health sharing is off. Turn it on in the Sanae app: Settings, Health.")
        }
        val node = nodes(context).firstOrNull()
            ?: return PhoneActions.Result(false, "Your watch isn't connected to the phone right now.")
        val wait = kotlinx.coroutines.CompletableDeferred<String>()
        heartReply = wait
        try {
            send(context, node, WatchPaths.HR_REQUEST, JSONObject())
            val o = kotlinx.coroutines.withTimeoutOrNull(35_000) { wait.await() }?.let { runCatching { JSONObject(it) }.getOrNull() }
                ?: return PhoneActions.Result(false, "The watch didn't answer. Is it on your wrist?")
            val bpm = o.optInt("bpm")
            return if (bpm > 0) PhoneActions.Result(true, "$bpm bpm")
                   else PhoneActions.Result(false, o.optString("error").ifBlank { "The watch couldn't read your heart rate." })
        } finally {
            heartReply = null
        }
    }

    /** Tell the watch health sharing was turned on or off (it asks for the heart-rate sensor then). */
    fun healthChanged(context: Context, on: Boolean) = scope.launch {
        val app = context.applicationContext
        for (node in nodes(app)) send(app, node, WatchPaths.HEALTH, JSONObject().put("on", on))
    }

    suspend fun answer(context: Context, node: String, wav: ByteArray, speak: Boolean) {
        val prefs = Prefs(context)
        val api = SanaeApi.from(prefs)
        if (api == null) {
            send(context, node, WatchPaths.REPLY, JSONObject().put("error", "Pair the phone with your laptop first."))
            return
        }
        val res = runCatching { api.voiceFrom(wav, "watch") }.getOrElse {
            send(context, node, WatchPaths.REPLY, JSONObject().put("error", "Can't reach your laptop."))
            return
        }
        val reply = res.optString("reply")
        send(context, node, WatchPaths.REPLY, JSONObject()
            .put("heard", res.optString("heard"))
            .put("reply", reply)
            .put("emotion", res.optString("emotion")))
        if (speak && reply.isNotBlank()) {
            runCatching { api.speak(reply) }.onSuccess { sendSpeech(context, node, it) }
        }
    }

    suspend fun sendGlance(context: Context, node: String) {
        val prefs = Prefs(context)
        val db = LocalDb.get(context)
        val today = prefs.todayJson.takeIf { it.isNotBlank() }?.let { runCatching { JSONObject(it) }.getOrNull() }
        val now = System.currentTimeMillis()
        val items = Glance.build(today, db.reminders(), db.events(), now, limit = 5, todos = db.todos("status = 'open'"))
        send(context, node, WatchPaths.GLANCE,
             Glance.payload(items, Hub.approvals.value, Hub.link.value == Link.ONLINE, now))
    }

    /** An approval opened ("Send the email?") or settled (empty prompt): shown on the watch if it's open. */
    fun approval(context: Context, id: Int, prompt: String) = scope.launch {
        val app = context.applicationContext
        for (node in nodes(app)) send(app, node, WatchPaths.APPROVAL, JSONObject().put("id", id).put("prompt", prompt))
    }

    private suspend fun nodes(context: Context): List<String> = runCatching {
        Wearable.getNodeClient(context).connectedNodes.await().map { it.id }
    }.getOrDefault(emptyList())

    private suspend fun send(context: Context, node: String, path: String, body: JSONObject) {
        runCatching { Wearable.getMessageClient(context).sendMessage(node, path, body.toString().toByteArray()).await() }
            .onFailure { Log.w(WatchRelay.TAG, "$path not sent to the watch: ${it.message}") }
    }

    private suspend fun sendSpeech(context: Context, node: String, wav: ByteArray) {
        runCatching {
            val client = Wearable.getChannelClient(context)
            val ch = client.openChannel(node, WatchPaths.SPEECH).await()
            client.getOutputStream(ch).await().use { it.write(wav) }
            client.close(ch)
        }.onFailure { Log.w(WatchRelay.TAG, "voice not sent to the watch: ${it.message}") }
    }
}
