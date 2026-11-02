package com.manaskhare.sanae

import android.app.Notification
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.media.AudioAttributes
import android.media.MediaPlayer
import android.os.Build
import android.os.IBinder
import android.util.Base64
import androidx.core.app.NotificationCompat
import androidx.core.content.ContextCompat
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.coroutines.suspendCancellableCoroutine
import kotlinx.coroutines.withContext
import java.io.File
import kotlin.coroutines.resume

enum class CallPhase { CONNECTING, LISTENING, THINKING, SPEAKING, MUTED, ENDED }

/** What the call screen shows. */
object CallState {
    val phase = MutableStateFlow(CallPhase.ENDED)
    val heard = MutableStateFlow("")
    val reply = MutableStateFlow("")
    val emotion = MutableStateFlow("")
    val error = MutableStateFlow("")
    val level = MutableStateFlow(0f)
    var startedAt = 0L
    @Volatile var muted = false
}

/**
 * A voice call with her: listen (stops at a pause) -> POST /api/call/turn -> play her voice ->
 * listen again, in a foreground service so it keeps going with the screen off or the app closed.
 * Ends on "Hang up", when she hears bye, or when the laptop can't be reached.
 */
class CallService : Service() {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private var loop: Job? = null
    private var recorder: Recorder? = null
    private var player: MediaPlayer? = null

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (intent?.action == ACTION_HANG_UP) {
            hangUp()
            return START_NOT_STICKY
        }
        val n = notification()
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) startForeground(ID, n, ServiceInfo.FOREGROUND_SERVICE_TYPE_MICROPHONE)
        else startForeground(ID, n)
        if (loop?.isActive != true) loop = scope.launch { talk() }
        return START_NOT_STICKY
    }

    private suspend fun talk() {
        val api = SanaeApi.from(Prefs(this)) ?: return fail("Pair with your laptop first.")
        CallState.apply { phase.value = CallPhase.CONNECTING; heard.value = ""; reply.value = ""; error.value = ""; muted = false }
        CallState.startedAt = System.currentTimeMillis()
        val hello = runCatching { org.json.JSONObject(api.raw("POST", "/api/call/start")) }.getOrElse {
            return fail("Can't reach your laptop. Is it on, with Sanae and Tailscale running?")
        }
        say(hello)
        var quiet = 0
        while (scope.isActive && CallState.phase.value != CallPhase.ENDED) {
            if (CallState.muted) { CallState.phase.value = CallPhase.MUTED; delay(300); continue }
            CallState.phase.value = CallPhase.LISTENING
            val wav = listen()
            if (CallState.phase.value == CallPhase.ENDED) break
            if (wav.isEmpty()) { if (++quiet >= 6) break else continue }       // ~3 minutes of nothing
            quiet = 0
            CallState.phase.value = CallPhase.THINKING
            val res = runCatching { api.callTurn(wav) }.getOrNull()
            if (res == null) {
                CallState.error.value = "Lost the laptop for a moment…"
                delay(1500)
                if (runCatching { api.ping() }.isFailure) return fail("The laptop stopped answering, so the call ended.")
                continue
            }
            CallState.error.value = ""
            if (res.optString("heard").isBlank()) continue
            CallState.heard.value = res.optString("heard")
            say(res)
            if (res.optBoolean("end")) break
        }
        hangUp()
    }

    /** Records until a pause (or 30 s). Empty if nothing was said. */
    private suspend fun listen(): ByteArray = suspendCancellableCoroutine { cont ->
        val r = Recorder(onAutoStop = {
            scope.launch {                  // off the recorder's own thread (stop() waits for it)
                val wav = recorder?.stop() ?: ByteArray(0)
                recorder = null
                if (cont.isActive) cont.resume(wav)
            }
        })
        recorder = r
        runCatching { r.start() }.onFailure {
            recorder = null
            CallState.error.value = "Mic unavailable: ${it.message}"
            if (cont.isActive) cont.resume(ByteArray(0))
            return@suspendCancellableCoroutine
        }
        scope.launch {                      // the mic level for the screen, and hang-up / mute while listening
            while (recorder === r) {
                CallState.level.value = r.level
                if (CallState.phase.value == CallPhase.ENDED || CallState.muted) {
                    recorder = null
                    r.stop()
                    if (cont.isActive) cont.resume(ByteArray(0))
                }
                delay(60)
            }
            CallState.level.value = 0f
        }
    }

    private suspend fun say(res: org.json.JSONObject) {
        CallState.reply.value = res.optString("reply")
        CallState.emotion.value = res.optString("emotion")
        val audio = res.optString("audio")
        if (audio.isBlank()) return
        CallState.phase.value = CallPhase.SPEAKING
        val file = File(cacheDir, "call.wav").apply { writeBytes(Base64.decode(audio, Base64.DEFAULT)) }
        withContext(Dispatchers.Main) {
            suspendCancellableCoroutine { cont ->
                val p = MediaPlayer()
                player = p
                runCatching {
                    p.setAudioAttributes(AudioAttributes.Builder().setUsage(AudioAttributes.USAGE_MEDIA)
                        .setContentType(AudioAttributes.CONTENT_TYPE_SPEECH).build())
                    p.setDataSource(file.path)
                    p.setOnCompletionListener { done(p); if (cont.isActive) cont.resume(Unit) }
                    p.setOnErrorListener { _, _, _ -> done(p); if (cont.isActive) cont.resume(Unit); true }
                    p.prepare()
                    p.start()
                }.onFailure { done(p); if (cont.isActive) cont.resume(Unit) }
                cont.invokeOnCancellation { done(p) }
            }
        }
    }

    private fun done(p: MediaPlayer) {
        runCatching { p.release() }
        if (player === p) player = null
    }

    private fun fail(why: String) {
        CallState.error.value = why
        hangUp()
    }

    private fun hangUp() {
        val was = CallState.phase.value
        CallState.phase.value = CallPhase.ENDED
        recorder?.stop(); recorder = null
        player?.let { runCatching { it.stop() }; done(it) }
        if (was != CallPhase.ENDED) scope.launch { runCatching { SanaeApi.from(Prefs(this@CallService))?.raw("POST", "/api/call/end") } }
        stopForeground(STOP_FOREGROUND_REMOVE)
        stopSelf()
    }

    override fun onDestroy() {
        CallState.phase.value = CallPhase.ENDED
        recorder?.stop()
        player?.let { done(it) }
        super.onDestroy()
    }

    private fun notification(): Notification {
        val open = PendingIntent.getActivity(this, 0, Intent(this, CallActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
        val hang = PendingIntent.getService(this, 1, Intent(this, CallService::class.java).setAction(ACTION_HANG_UP),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
        return NotificationCompat.Builder(this, SanaeApp.CH_RECORD)
            .setSmallIcon(R.drawable.ic_stat_sanae)
            .setContentTitle("On a call with ${Persona.name(this)}")
            .setUsesChronometer(true)
            .setWhen(System.currentTimeMillis())
            .setOngoing(true)
            .setCategory(NotificationCompat.CATEGORY_CALL)
            .setContentIntent(open)
            .addAction(0, "Hang up", hang)
            .build()
    }

    companion object {
        const val ID = 7200
        const val ACTION_HANG_UP = "com.manaskhare.sanae.HANG_UP"

        fun start(context: Context) {
            CallState.phase.value = CallPhase.CONNECTING
            ContextCompat.startForegroundService(context, Intent(context, CallService::class.java))
        }

        fun hangUp(context: Context) {
            context.startService(Intent(context, CallService::class.java).setAction(ACTION_HANG_UP))
        }
    }
}
