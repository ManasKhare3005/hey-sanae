package com.manaskhare.sanae

import android.os.Bundle
import android.view.WindowManager
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.CallEnd
import androidx.compose.material.icons.filled.Mic
import androidx.compose.material.icons.filled.MicOff
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableLongStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.manaskhare.sanae.ui.Accent0
import com.manaskhare.sanae.ui.AppBackground
import com.manaskhare.sanae.ui.LiveFace
import com.manaskhare.sanae.ui.DisplayStyle
import com.manaskhare.sanae.ui.Dim
import com.manaskhare.sanae.ui.Label
import com.manaskhare.sanae.ui.Red
import com.manaskhare.sanae.ui.SanaeTheme
import com.manaskhare.sanae.ui.Text1
import com.manaskhare.sanae.ui.Text2
import kotlinx.coroutines.delay

/** The call screen: her, the time on the call, what she just said, mute and hang up. The call
 *  itself lives in CallService, so leaving this screen doesn't end it. */
class CallActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        if (CallState.phase.value == CallPhase.ENDED) CallService.start(this)
        val activity = this
        setContent { SanaeTheme { AppBackground(glowAt = 0.35f) { CallScreen(Persona.name(activity), onHangUp = {
            CallService.hangUp(activity); activity.finish()
        }) } } }
    }
}

@Composable
fun CallScreen(name: String, onHangUp: () -> Unit) {
    val phase by CallState.phase.collectAsState()
    val reply by CallState.reply.collectAsState()
    val heard by CallState.heard.collectAsState()
    val error by CallState.error.collectAsState()
    val level by CallState.level.collectAsState()
    var muted by remember { mutableStateOf(CallState.muted) }
    var now by remember { mutableLongStateOf(System.currentTimeMillis()) }
    LaunchedEffect(Unit) { while (true) { now = System.currentTimeMillis(); delay(500) } }
    val secs = if (CallState.startedAt > 0) ((now - CallState.startedAt) / 1000).toInt() else 0
    Column(Modifier.fillMaxSize().statusBarsPadding().navigationBarsPadding().padding(horizontal = 26.dp),
           horizontalAlignment = Alignment.CenterHorizontally) {
        Spacer(Modifier.height(28.dp))
        Text(name, style = DisplayStyle, color = Text1, fontSize = 40.sp)
        Label(when (phase) {
            CallPhase.CONNECTING -> "calling…"
            CallPhase.ENDED -> "call ended"
            else -> "%d:%02d".format(secs / 60, secs % 60) + when (phase) {
                CallPhase.LISTENING -> " · listening"
                CallPhase.THINKING -> " · thinking"
                CallPhase.SPEAKING -> " · talking"
                CallPhase.MUTED -> " · muted"
                else -> ""
            }
        }, color = Accent0, modifier = Modifier.padding(top = 4.dp))
        val orb = when (phase) {
            CallPhase.LISTENING -> Phase.LISTENING
            CallPhase.THINKING, CallPhase.CONNECTING -> Phase.THINKING
            CallPhase.SPEAKING -> Phase.SPEAKING
            else -> Phase.IDLE
        }
        val emotion by CallState.emotion.collectAsState()
        Box(Modifier.fillMaxWidth().height(320.dp), contentAlignment = Alignment.Center) {
            LiveFace(emotion.ifBlank { null }, orb, level, 180.dp)
        }
        Column(Modifier.weight(1f).fillMaxWidth(), horizontalAlignment = Alignment.CenterHorizontally) {
            if (heard.isNotBlank()) Text("“$heard”", color = Text2, fontSize = 14.sp, textAlign = TextAlign.Center)
            Spacer(Modifier.height(10.dp))
            Text(reply, color = Text1, fontSize = 20.sp, lineHeight = 26.sp, textAlign = TextAlign.Center)
            if (error.isNotBlank()) Text(error, color = Red, fontSize = 13.sp, textAlign = TextAlign.Center, modifier = Modifier.padding(top = 10.dp))
        }
        Row(Modifier.padding(bottom = 36.dp), horizontalArrangement = Arrangement.spacedBy(48.dp), verticalAlignment = Alignment.CenterVertically) {
            RoundButton(if (muted) Icons.Filled.MicOff else Icons.Filled.Mic, if (muted) "Unmute" else "Mute",
                        if (muted) Accent0 else Color.White.copy(alpha = 0.10f), if (muted) Color.Black else Text1) {
                muted = !muted; CallState.muted = muted
            }
            RoundButton(Icons.Filled.CallEnd, "Hang up", Red, Color.White, onClick = onHangUp)
        }
    }
}

@Composable
private fun RoundButton(icon: androidx.compose.ui.graphics.vector.ImageVector, label: String, bg: Color, tint: Color, onClick: () -> Unit) {
    Column(horizontalAlignment = Alignment.CenterHorizontally) {
        Box(Modifier.size(72.dp).clip(CircleShape).background(bg).border(1.dp, Color.White.copy(alpha = 0.12f), CircleShape).clickable(onClick = onClick),
            contentAlignment = Alignment.Center) { Icon(icon, contentDescription = label, tint = tint, modifier = Modifier.size(30.dp)) }
        Text(label, color = Dim, fontSize = 12.sp, modifier = Modifier.padding(top = 6.dp))
    }
}
