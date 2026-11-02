package com.manaskhare.sanae.watch

import android.content.Context
import android.util.Log
import androidx.wear.tiles.TileService
import com.google.android.gms.wearable.CapabilityClient
import com.google.android.gms.wearable.ChannelClient
import com.google.android.gms.wearable.MessageEvent
import com.google.android.gms.wearable.Wearable
import com.google.android.gms.wearable.WearableListenerService
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.coroutines.tasks.await
import org.json.JSONObject

/** What the phone sent, shared by the listener service, the talk screen and the tile. */
object WatchHub {
    val reply = MutableSharedFlow<Reply>(extraBufferCapacity = 4)
    val speech = MutableSharedFlow<ByteArray>(extraBufferCapacity = 2)
    val approvals = MutableStateFlow<List<Approval>>(emptyList())
    val glance = MutableStateFlow<Glance?>(null)
    /** The talk screen is open (her voice is only played then). */
    @Volatile var open = false
}

/** Small settings + the last Today list (the tile draws from it). */
class Store(context: Context) {
    private val sp = context.getSharedPreferences("sanae-watch", Context.MODE_PRIVATE)

    var speak: Boolean
        get() = sp.getBoolean("speak", true)
        set(v) = sp.edit().putBoolean("speak", v).apply()

    var glanceJson: String
        get() = sp.getString("glance", "") ?: ""
        set(v) = sp.edit().putString("glance", v).apply()

    /** The phone turned health sharing on: ask for the heart-rate sensor next time the app opens. */
    var healthOn: Boolean
        get() = sp.getBoolean("healthOn", false)
        set(v) = sp.edit().putBoolean("healthOn", v).apply()

    fun glance(): Glance? = glanceJson.takeIf { it.isNotBlank() }?.let { Glance.parse(it) }
}

/** Talking to the phone app over the Wear OS Data Layer (Bluetooth or Wi-Fi, handled by Wear OS). */
object Phone {
    private const val TAG = "SanaePhone"
    val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)

    /** The phone running Sanae, or null when it's out of reach / the app isn't installed. */
    suspend fun node(context: Context): String? = runCatching {
        val nodes = Wearable.getCapabilityClient(context)
            .getCapability(Paths.CAPABILITY, CapabilityClient.FILTER_REACHABLE).await().nodes
        (nodes.firstOrNull { it.isNearby } ?: nodes.firstOrNull())?.id
    }.getOrNull()

    /** Sends a recording; the reply comes back as a message (PhoneListener). False = no phone. */
    suspend fun sendVoice(context: Context, wav: ByteArray, speak: Boolean): Boolean {
        val node = node(context) ?: return false
        return runCatching {
            val client = Wearable.getChannelClient(context)
            val ch = client.openChannel(node, Paths.VOICE + if (speak) "/speak" else "/quiet").await()
            client.getOutputStream(ch).await().use { it.write(wav) }
            client.close(ch)
            true
        }.getOrElse { Log.w(TAG, "voice not sent: ${it.message}"); false }
    }

    fun approve(context: Context, id: Int, approved: Boolean) = scope.launch {
        WatchHub.approvals.update { list -> list.filter { it.id != id } }
        send(context, Paths.APPROVE, JSONObject().put("id", id).put("approved", approved).toString())
    }

    /** Ask for the Today list; it arrives in PhoneListener (and refreshes the tile). */
    fun requestGlance(context: Context) = scope.launch { send(context, Paths.GLANCE, "") }

    private suspend fun send(context: Context, path: String, body: String): Boolean {
        val node = node(context) ?: return false
        return runCatching {
            Wearable.getMessageClient(context).sendMessage(node, path, body.toByteArray()).await()
            true
        }.getOrElse { Log.w(TAG, "$path not sent: ${it.message}"); false }
    }
}

class PhoneListener : WearableListenerService() {
    override fun onMessageReceived(event: MessageEvent) {
        val text = String(event.data)
        when (event.path) {
            Paths.REPLY -> WatchHub.reply.tryEmit(Reply.parse(text))
            Paths.GLANCE -> Glance.parse(text)?.let { g ->
                Store(this).glanceJson = text
                WatchHub.glance.value = g
                WatchHub.approvals.value = g.approvals
                TileService.getUpdater(this).requestUpdate(TodayTile::class.java)
            }
            Paths.HEALTH -> Store(this).healthOn = runCatching { JSONObject(text).optBoolean("on") }.getOrDefault(false)
            Paths.HR_REQUEST -> {
                val app = applicationContext
                val node = event.sourceNodeId
                Phone.scope.launch {
                    val reply = when {
                        !HeartRate.allowed(app) -> JSONObject().put("error", "Open Sanae on your watch once and allow the heart rate sensor.")
                        else -> HeartRate.measure(app)?.let { JSONObject().put("bpm", it) }
                            ?: JSONObject().put("error", "The watch couldn't get a reading. Is it snug on your wrist?")
                    }
                    runCatching { Wearable.getMessageClient(app).sendMessage(node, Paths.HR, reply.toString().toByteArray()).await() }
                }
            }
            Paths.APPROVAL -> runCatching { JSONObject(text) }.getOrNull()?.let { o ->
                val a = Approval(o.optInt("id"), o.optString("prompt"))
                WatchHub.approvals.update { list ->
                    list.filter { it.id != a.id } + if (a.prompt.isNotBlank()) listOf(a) else emptyList()
                }
            }
        }
    }

    override fun onChannelOpened(channel: ChannelClient.Channel) {
        if (channel.path != Paths.SPEECH) return
        val app = applicationContext
        Phone.scope.launch {
            val client = Wearable.getChannelClient(app)
            val wav = runCatching { client.getInputStream(channel).await().use { it.readBytes() } }.getOrNull()
            runCatching { client.close(channel) }
            if (wav != null && WatchHub.open) WatchHub.speech.tryEmit(wav)
        }
    }
}
