package com.manaskhare.sanae

import android.app.Application
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.json.JSONObject

enum class Phase { IDLE, LISTENING, THINKING, SPEAKING }

data class Turn(val user: String, val reply: String, val ts: String, val pending: Boolean = false)

class MainViewModel(app: Application) : AndroidViewModel(app) {
    val prefs = Prefs(app)
    private val player = Player(app)
    private var recorder: Recorder? = null

    val phase = MutableStateFlow(Phase.IDLE)
    val level = MutableStateFlow(0f)
    val heard = MutableStateFlow("")
    val reply = MutableStateFlow("")
    val error = MutableStateFlow("")
    val turns = MutableStateFlow<List<Turn>>(emptyList())
    /** How she looks right now (her portrait and face follow it). */
    val emotion = MutableStateFlow("happy")
    val paired = MutableStateFlow(prefs.paired)
    /** A photo waiting to be sent (shared to the app or just taken), in memory only. */
    val photo = MutableStateFlow<ByteArray?>(null)

    private fun api(): SanaeApi? = SanaeApi.from(prefs).also { if (it == null) error.value = "Pair with your laptop first (Settings)." }

    init {
        viewModelScope.launch {           // orb follows the mic level while recording
            while (isActive) {
                level.value = recorder?.level ?: 0f
                delay(50)
            }
        }
        viewModelScope.launch {           // conversation stays current with the laptop
            Hub.events.collect {
                if (it.kind == "answer" || it.kind == "direct_reply") { delay(400); refreshTurns() }  // turn is logged just after
                if (it.kind == "emotion") it.data.optString("emotion").takeIf { e -> e.isNotBlank() }?.let { e -> emotion.value = e }
            }
        }
    }

    // ----- talking -----
    fun toggleMic() {
        when (phase.value) {
            Phase.LISTENING -> finishRecording()
            Phase.SPEAKING -> { player.stop(); phase.value = Phase.IDLE }
            Phase.THINKING -> Unit
            Phase.IDLE -> startRecording()
        }
    }

    /** Start listening if idle (the assistant sheet calls this as soon as it opens). */
    fun listen() {
        if (phase.value == Phase.IDLE) startRecording()
    }

    fun stopSpeaking() {
        player.stop()
        if (phase.value == Phase.SPEAKING) phase.value = Phase.IDLE
    }

    private fun startRecording() {
        api() ?: return
        error.value = ""
        player.stop()
        recorder = Recorder(onAutoStop = { viewModelScope.launch { finishRecording() } }).also {
            runCatching { it.start() }.onFailure { e -> error.value = "Mic unavailable: ${e.message}"; recorder = null; return }
        }
        phase.value = Phase.LISTENING
    }

    private fun finishRecording() {
        val rec = recorder ?: return
        recorder = null
        viewModelScope.launch {
            val wav = withContext(Dispatchers.IO) { rec.stop() }
            if (wav.isEmpty()) { phase.value = Phase.IDLE; return@launch }
            phase.value = Phase.THINKING
            heard.value = "…"
            reply.value = ""
            val api = api() ?: run { phase.value = Phase.IDLE; return@launch }
            runCatching { api.voice(wav) }
                .onSuccess { res ->
                    val h = res.optString("heard")
                    val r = res.optString("reply")
                    heard.value = h.ifBlank { "(didn't catch that)" }
                    reply.value = r
                    feel(res, r)
                    if (h.isNotBlank()) refreshTurns()
                    speakOrIdle(api, r)
                }
                .onFailure { fail(it) }
        }
    }

    fun send(text: String) {
        val t = text.trim()
        if (t.isEmpty() || phase.value == Phase.THINKING) return
        if (photo.value != null) { sendPhoto(t); return }     // typed in the main box with a photo waiting: it's about the photo
        val api = api() ?: return
        error.value = ""
        heard.value = t
        reply.value = ""
        phase.value = Phase.THINKING
        turns.value = turns.value + Turn(t, "", "", pending = true)
        viewModelScope.launch {
            runCatching { api.commandFull(t) }
                .onSuccess { res -> val r = res.optString("reply"); reply.value = r; feel(res, r); refreshTurns(); speakOrIdle(api, r) }
                .onFailure { fail(it) }
        }
    }

    // ----- photos -----
    /** Shrink the picked / shot / shared image off the main thread (decoding a 12 MP photo there froze the app). */
    fun stagePhoto(uri: android.net.Uri) {
        val context = getApplication<Application>()
        viewModelScope.launch {
            stagePhoto(withContext(Dispatchers.Default) { Photos.read(context, uri) })
        }
    }

    fun stagePhoto(jpeg: ByteArray?) {
        if (jpeg == null) { error.value = "Couldn't open that photo."; photoPrep("cancel"); return }
        error.value = ""
        photo.value = jpeg
        photoPrep("ready")           // a shared photo: swap while the question is typed
    }

    fun dropPhoto() {
        photo.value = null
        photoPrep("cancel")
    }

    /** Tell the laptop a photo is (or isn't) coming, so its model swap overlaps with framing / typing. */
    fun photoPrep(action: String) = quiet({ it.photoPrep(action) })

    /** Send the waiting photo with an optional question. Takes ~20 s: the laptop swaps in its vision model. */
    fun sendPhoto(question: String, keep: Boolean = false) {
        val jpeg = photo.value ?: return
        if (phase.value == Phase.THINKING) return
        val api = api() ?: return
        val q = question.trim()
        photo.value = null
        player.stop()
        error.value = ""
        heard.value = Photos.label("${Photos.TAG} $q")
        reply.value = ""
        phase.value = Phase.THINKING
        turns.value = turns.value + Turn("${Photos.TAG} $q", "", "", pending = true)
        val react = Photos.reaction()
        reply.value = react                       // she reacts right away; the real answer replaces it
        if (prefs.speakReplies) viewModelScope.launch {
            val wav = runCatching { api.speak(react) }.getOrNull()
            if (wav != null && phase.value == Phase.THINKING) runCatching { player.play(wav) {} }
        }
        viewModelScope.launch {
            runCatching { api.photo(jpeg, q, keep) }
                .onSuccess { r -> reply.value = r; emotion.value = com.manaskhare.sanae.ui.EmotionGuess.guess(r); refreshTurns(); speakOrIdle(api, r) }
                .onFailure { reply.value = ""; fail(it) }
        }
    }

    /** Her emotion from a reply: the tag she answered with, else a guess from the words. */
    private fun feel(res: JSONObject, reply: String) {
        emotion.value = res.optString("emotion").takeIf { it.isNotBlank() && it != "null" }
            ?: com.manaskhare.sanae.ui.EmotionGuess.guess(reply)
    }

    private suspend fun speakOrIdle(api: SanaeApi, text: String) {
        if (text.isBlank() || !prefs.speakReplies) { phase.value = Phase.IDLE; return }
        val wav = runCatching { api.speak(text) }.getOrNull()
        if (wav == null) { phase.value = Phase.IDLE; return }
        phase.value = Phase.SPEAKING
        runCatching { player.play(wav) { phase.value = Phase.IDLE } }.onFailure { phase.value = Phase.IDLE }
    }

    private fun fail(e: Throwable) {
        phase.value = Phase.IDLE
        error.value = when {
            e is ApiError && e.code == 401 -> "The laptop rejected this phone. Pair again in Settings."
            e is ApiError -> e.message ?: "Error ${e.code}"
            else -> "Can't reach the laptop. Is it on, with the assistant and Tailscale running?"
        }
    }

    // ----- conversation -----
    fun refreshTurns() {
        val api = SanaeApi.from(prefs) ?: return
        viewModelScope.launch {
            runCatching { api.turns() }.onSuccess { arr ->
                turns.value = arr.objects().map { Turn(it.optString("user"), it.optString("reply"), it.optString("ts")) }
            }
        }
    }

    // ----- approvals -----
    fun answer(id: Int, approved: Boolean) {
        val api = SanaeApi.from(prefs) ?: return
        Hub.removeApproval(id)
        viewModelScope.launch { runCatching { api.approve(id, approved) } }
    }

    // ----- pairing -----
    fun pair(link: String): Boolean {
        if (!prefs.pairFrom(link)) return false
        onPaired()
        return true
    }

    fun pairManually(url: String, token: String) {
        prefs.url = if (url.startsWith("http")) url else "https://$url"
        prefs.token = token
        onPaired()
    }

    private fun onPaired() {
        paired.value = prefs.paired
        error.value = ""
        val ctx = getApplication<Application>()
        ctx.startForegroundService(android.content.Intent(ctx, SanaeService::class.java).setAction(SanaeService.ACTION_RECONNECT))
        refreshTurns()
    }

    fun unpair() {
        val ctx = getApplication<Application>()
        ctx.stopService(android.content.Intent(ctx, SanaeService::class.java))
        prefs.clear()
        paired.value = false
        turns.value = emptyList()
    }

    /** Runs an API call and reports failures on the shared error line. */
    fun <T> call(block: suspend (SanaeApi) -> T, onResult: (T) -> Unit = {}) {
        val api = api() ?: return
        viewModelScope.launch {
            runCatching { block(api) }.onSuccess(onResult).onFailure { fail(it) }
        }
    }

    /** Like call(), but a failure (laptop offline) says nothing: for background refreshes. */
    fun <T> quiet(block: suspend (SanaeApi) -> T, onResult: (T) -> Unit = {}) {
        val api = SanaeApi.from(prefs) ?: return
        viewModelScope.launch { runCatching { block(api) }.onSuccess(onResult) }
    }

    override fun onCleared() {
        recorder?.stop()
        player.stop()
    }
}

fun JSONObject.str(key: String) = if (isNull(key)) "" else optString(key)
