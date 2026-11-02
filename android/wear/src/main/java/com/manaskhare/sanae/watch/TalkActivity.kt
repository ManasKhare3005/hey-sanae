package com.manaskhare.sanae.watch

import android.Manifest
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Bundle
import android.os.VibrationEffect
import android.os.Vibrator
import android.view.WindowManager
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Check
import androidx.compose.material.icons.filled.Close
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.core.content.ContextCompat
import androidx.lifecycle.lifecycleScope
import androidx.wear.compose.foundation.lazy.ScalingLazyColumn
import androidx.wear.compose.foundation.lazy.rememberScalingLazyListState
import androidx.wear.compose.material.Button
import androidx.wear.compose.material.ButtonDefaults
import androidx.wear.compose.material.CircularProgressIndicator
import androidx.wear.compose.material.Icon
import androidx.wear.compose.material.ListHeader
import androidx.wear.compose.material.MaterialTheme
import androidx.wear.compose.material.PositionIndicator
import androidx.wear.compose.material.Scaffold
import androidx.wear.compose.material.Switch
import androidx.wear.compose.material.Text
import androidx.wear.compose.material.TimeText
import androidx.wear.compose.material.ToggleChip
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

enum class Phase { IDLE, LISTENING, THINKING, SPEAKING }

private val Navy = Color(0xFF060A13)
private val Text2 = Color(0xFF94A3B8)
private val Red = Color(0xFFF87171)

/**
 * Tap to talk: tap her face, speak, and the reply comes back from the laptop through the phone
 * (text, her face and, if on, her voice). Also shows approvals (yes/no taps) and what's next.
 */
class TalkActivity : ComponentActivity() {
    private val phase = mutableStateOf(Phase.IDLE)
    private val level = mutableFloatStateOf(0f)
    private val heard = mutableStateOf("")
    private val reply = mutableStateOf("")
    private val emotion = mutableStateOf("")
    private val error = mutableStateOf("")
    private val speak = mutableStateOf(true)
    private var recorder: Recorder? = null
    private lateinit var player: Player
    private lateinit var store: Store
    private var waiting: Job? = null
    private var last: Reply? = null

    private val heart = registerForActivityResult(ActivityResultContracts.RequestPermission()) { }

    private val mic = registerForActivityResult(ActivityResultContracts.RequestPermission()) { ok ->
        if (ok) listen() else error.value = "Allow the microphone to talk to Sanae."
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        store = Store(this)
        player = Player(this)
        speak.value = store.speak
        if (WatchHub.glance.value == null) store.glance()?.let { WatchHub.glance.value = it }
        setContent {
            val approvals by WatchHub.approvals.collectAsState()
            val glance by WatchHub.glance.collectAsState()
            TalkScreen(
                phase.value, level.floatValue, heard.value, reply.value, emotion.value, error.value,
                approvals, glance, speak.value,
                onTap = ::tap,
                onApprove = { id, yes -> Phone.approve(this, id, yes) },
                onSpeak = { speak.value = it; store.speak = it },
            )
        }
        lifecycleScope.launch { WatchHub.reply.collect { onReply(it) } }
        lifecycleScope.launch { WatchHub.speech.collect { onSpeech(it) } }
        if (savedInstanceState == null && intent?.getBooleanExtra(EXTRA_LISTEN, false) == true) startListening()
        else if (savedInstanceState == null && store.healthOn && !HeartRate.allowed(this)) heart.launch(HeartRate.PERMISSION)
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        if (intent.getBooleanExtra(EXTRA_LISTEN, false) && phase.value == Phase.IDLE) startListening()
    }

    override fun onStart() {
        super.onStart()
        WatchHub.open = true
        Phone.requestGlance(this)
    }

    override fun onStop() {
        super.onStop()
        WatchHub.open = false
        recorder?.stop()
        recorder = null
        player.stop()
        if (phase.value != Phase.THINKING) setPhase(Phase.IDLE)
    }

    private fun setPhase(p: Phase) {
        phase.value = p
        if (p == Phase.IDLE) window.clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        else window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
    }

    private fun tap() = when (phase.value) {
        Phase.IDLE -> startListening()
        Phase.LISTENING -> finishRecording()
        Phase.SPEAKING -> { player.stop(); setPhase(Phase.IDLE) }
        Phase.THINKING -> Unit
    }

    private fun startListening() {
        if (ContextCompat.checkSelfPermission(this, Manifest.permission.RECORD_AUDIO) == PackageManager.PERMISSION_GRANTED) listen()
        else mic.launch(Manifest.permission.RECORD_AUDIO)
    }

    private fun listen() {
        if (phase.value == Phase.LISTENING) return
        player.stop()
        error.value = ""
        val rec = Recorder(onAutoStop = { runOnUiThread { finishRecording() } })
        runCatching { rec.start() }.onFailure { error.value = "Mic unavailable."; return }
        recorder = rec
        buzz()
        setPhase(Phase.LISTENING)
        lifecycleScope.launch {
            while (phase.value == Phase.LISTENING && recorder === rec) { level.floatValue = rec.level; delay(80) }
            level.floatValue = 0f
        }
    }

    private fun finishRecording() {
        val rec = recorder ?: return
        recorder = null
        lifecycleScope.launch {
            val wav = withContext(Dispatchers.IO) { rec.stop() }
            if (wav.isEmpty()) { setPhase(Phase.IDLE); return@launch }
            setPhase(Phase.THINKING)
            heard.value = "…"
            reply.value = ""
            emotion.value = "thinking"
            if (!Phone.sendVoice(this@TalkActivity, wav, speak.value)) {
                fail("Can't reach your phone.")
                return@launch
            }
            waiting?.cancel()
            waiting = lifecycleScope.launch {            // a command can wait for an approval: be patient
                delay(150_000)
                if (phase.value == Phase.THINKING) fail("No answer from your phone.")
            }
        }
    }

    private fun onReply(r: Reply) {
        waiting?.cancel()
        last = r
        if (r.error.isNotBlank()) { fail(r.error); return }
        heard.value = r.heard.ifBlank { "(didn't catch that)" }
        reply.value = r.reply
        emotion.value = r.emotion
        buzz()
        if (speak.value && r.reply.isNotBlank()) {
            waiting = lifecycleScope.launch {            // her voice follows; don't wait forever for it
                delay(20_000)
                if (phase.value == Phase.THINKING) { setPhase(Phase.IDLE); maybeListenAgain() }
            }
        } else {
            setPhase(Phase.IDLE)
            maybeListenAgain()
        }
    }

    private fun onSpeech(wav: ByteArray) {
        if (phase.value != Phase.THINKING || !speak.value) return
        waiting?.cancel()
        setPhase(Phase.SPEAKING)
        player.play(wav) {
            runOnUiThread {
                if (phase.value == Phase.SPEAKING) { setPhase(Phase.IDLE); maybeListenAgain() }
            }
        }
    }

    private fun maybeListenAgain() {
        val r = last ?: return
        if (asksBack(r, WatchHub.approvals.value.isNotEmpty())) {
            last = null
            lifecycleScope.launch { delay(300); if (phase.value == Phase.IDLE) startListening() }
        }
    }

    private fun fail(message: String) {
        waiting?.cancel()
        error.value = message
        heard.value = ""
        emotion.value = "sad"
        setPhase(Phase.IDLE)
    }

    @Suppress("DEPRECATION")
    private fun buzz() {
        runCatching { getSystemService(Vibrator::class.java)?.vibrate(VibrationEffect.createPredefined(VibrationEffect.EFFECT_TICK)) }
    }

    companion object { const val EXTRA_LISTEN = "listen" }
}

@Composable
fun TalkScreen(
    phase: Phase, level: Float, heard: String, reply: String, emotion: String, error: String,
    approvals: List<Approval>, glance: Glance?, speak: Boolean,
    onTap: () -> Unit, onApprove: (Int, Boolean) -> Unit, onSpeak: (Boolean) -> Unit,
    flat: Boolean = false,        // snapshot tests: a plain column (ScalingLazyColumn draws nothing offscreen)
) {
    val rows = mutableListOf<@Composable () -> Unit>()
    rows += { FaceButton(phase, level, emotion, onTap) }
    val status = when {
        error.isNotBlank() -> error
        phase == Phase.LISTENING -> "Listening…"
        phase == Phase.THINKING -> "Thinking…"
        phase == Phase.SPEAKING -> "Tap to stop"
        reply.isBlank() -> "Tap to talk"
        else -> ""
    }
    if (status.isNotBlank()) rows += {
        Text(status, color = if (error.isNotBlank()) Red else Text2, fontSize = 13.sp, textAlign = TextAlign.Center)
    }
    approvals.forEach { a -> rows += { ApprovalCard(a, onApprove) } }
    if (heard.isNotBlank()) rows += {
        Text(heard, color = Text2, fontSize = 12.sp, textAlign = TextAlign.Center, modifier = Modifier.padding(horizontal = 12.dp))
    }
    if (reply.isNotBlank()) rows += {
        Text(reply, color = Color.White, fontSize = 15.sp, textAlign = TextAlign.Center,
             modifier = Modifier.padding(horizontal = 8.dp))
    }
    val items = glance?.items.orEmpty()
    if (items.isNotEmpty()) {
        rows += { ListHeader { Text("Next up", color = Color(Faces.CYAN)) } }
        val now = System.currentTimeMillis()
        items.forEach { item ->
            rows += {
                Column(Modifier.fillMaxWidth().padding(horizontal = 14.dp)) {
                    Text(item.title, color = Color.White, fontSize = 13.sp, maxLines = 2)
                    Text(whenLabel(item, now), color = Text2, fontSize = 11.sp)
                }
            }
        }
    }
    rows += {
        ToggleChip(
            checked = speak,
            onCheckedChange = onSpeak,
            label = { Text("Her voice") },
            toggleControl = { Switch(checked = speak) },
            modifier = Modifier.fillMaxWidth(),
        )
    }

    MaterialTheme {
        val list = rememberScalingLazyListState()
        Scaffold(
            modifier = Modifier.background(Navy),
            timeText = { TimeText() },
            positionIndicator = { PositionIndicator(scalingLazyListState = list) },
        ) {
            if (flat) {
                Column(Modifier.fillMaxSize().background(Navy).padding(top = 10.dp),
                       horizontalAlignment = Alignment.CenterHorizontally,
                       verticalArrangement = Arrangement.spacedBy(6.dp)) { rows.forEach { it() } }
            } else {
                ScalingLazyColumn(
                    state = list,
                    modifier = Modifier.fillMaxSize().background(Navy),
                    horizontalAlignment = Alignment.CenterHorizontally,
                    verticalArrangement = Arrangement.spacedBy(6.dp),
                ) { rows.forEach { row -> item { row() } } }
            }
        }
    }
}

@Composable
private fun FaceButton(phase: Phase, level: Float, emotion: String, onTap: () -> Unit) {
    val face = Faces.of(if (phase == Phase.LISTENING) "" else emotion)
    val motion = rememberInfiniteTransition(label = "face")
    val bob by motion.animateFloat(0f, 1f, infiniteRepeatable(tween(700), RepeatMode.Reverse), label = "bob")
    val ring = Color(face.ring)
    val width = if (phase == Phase.LISTENING) (3 + level * 9).dp else 3.dp
    Box(Modifier.size(104.dp).padding(top = 18.dp), contentAlignment = Alignment.Center) {
        if (phase == Phase.THINKING) {
            CircularProgressIndicator(modifier = Modifier.size(86.dp), indicatorColor = ring, strokeWidth = 3.dp)
        }
        Image(
            painterResource(faceImage(if (phase == Phase.LISTENING) "" else emotion)), contentDescription = "Sanae — tap to talk",
            modifier = Modifier
                .size(78.dp)
                .graphicsLayer {
                    rotationZ = face.tilt
                    translationY = if (face.bounce && phase != Phase.LISTENING) -4f * bob else 0f
                }
                .alpha(if (face.dim) 0.8f else 1f)
                .clip(CircleShape)
                .border(width, ring, CircleShape)
                .background(Color(0xFF0F172A))
                .clickable(onClick = onTap),
        )
        if (phase == Phase.LISTENING || phase == Phase.SPEAKING) {
            Box(Modifier.align(Alignment.BottomEnd).size(26.dp).clip(CircleShape).background(ring),
                contentAlignment = Alignment.Center) {
                Icon(painterResource(R.drawable.ic_stop), contentDescription = "Stop", tint = Navy,
                     modifier = Modifier.size(14.dp))
            }
        }
    }
}

/** Her face rendered from the 3D avatar in each emotion (scripts/watch_faces.py). */
private fun faceImage(emotion: String): Int = when (emotion.lowercase()) {
    "happy" -> R.drawable.face_happy
    "shy" -> R.drawable.face_shy
    "laugh" -> R.drawable.face_laugh
    "thinking" -> R.drawable.face_thinking
    "sad" -> R.drawable.face_sad
    "surprised" -> R.drawable.face_surprised
    "sleepy" -> R.drawable.face_sleepy
    else -> R.drawable.face_neutral
}

@Composable
private fun ApprovalCard(a: Approval, onApprove: (Int, Boolean) -> Unit) {
    Column(
        Modifier.fillMaxWidth().padding(horizontal = 8.dp).clip(RoundedCornerShape(16.dp))
            .background(Color(0xFF1E293B)).padding(10.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Text(a.prompt, color = Color.White, fontSize = 13.sp, textAlign = TextAlign.Center)
        Row(Modifier.padding(top = 6.dp), horizontalArrangement = Arrangement.spacedBy(14.dp)) {
            Button(onClick = { onApprove(a.id, false) }, colors = ButtonDefaults.secondaryButtonColors(),
                   modifier = Modifier.size(ButtonDefaults.SmallButtonSize)) {
                Icon(Icons.Filled.Close, contentDescription = "No")
            }
            Button(onClick = { onApprove(a.id, true) }, modifier = Modifier.size(ButtonDefaults.SmallButtonSize)) {
                Icon(Icons.Filled.Check, contentDescription = "Yes")
            }
        }
    }
}
