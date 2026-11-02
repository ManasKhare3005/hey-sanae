package com.manaskhare.sanae.ui

import android.graphics.BitmapFactory
import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.Crossfade
import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateDpAsState
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.animation.expandVertically
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.shrinkVertically
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.ime
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.requiredWidth
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.Send
import androidx.compose.material.icons.automirrored.filled.VolumeOff
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.Call
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.Mic
import androidx.compose.material.icons.filled.PhotoCamera
import androidx.compose.material.icons.filled.PhotoLibrary
import androidx.compose.material.icons.filled.Stop
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.clipToBounds
import androidx.compose.ui.draw.drawBehind
import androidx.compose.ui.draw.drawWithContent
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.BlendMode
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.CompositingStrategy
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.manaskhare.sanae.Hub
import com.manaskhare.sanae.Link
import com.manaskhare.sanae.MainViewModel
import com.manaskhare.sanae.Persona
import com.manaskhare.sanae.Phase
import com.manaskhare.sanae.Photos
import com.manaskhare.sanae.Turn

/**
 * Her tab: she's at the top (portrait in her current emotion; glows while she listens), the chat
 * runs underneath and fades out under her, and one bar at the bottom: + (camera / gallery), a text
 * box and the mic (send while there's text).
 */
@OptIn(ExperimentalLayoutApi::class)
@Composable
fun SanaeScreen(vm: MainViewModel, takePhoto: () -> Unit = {}, pickPhoto: () -> Unit = {}, onCall: () -> Unit = {},
                askMic: (() -> Unit) -> Unit) {
    val phase by vm.phase.collectAsState()
    val level by vm.level.collectAsState()
    val heard by vm.heard.collectAsState()
    val error by vm.error.collectAsState()
    val turns by vm.turns.collectAsState()
    val emotion by vm.emotion.collectAsState()
    val link by Hub.link.collectAsState()
    val photo by vm.photo.collectAsState()
    val name = Persona.name(androidx.compose.ui.platform.LocalContext.current)
    val keyboardOpen = WindowInsets.ime.getBottom(androidx.compose.ui.platform.LocalDensity.current) > 0
    val list = rememberLazyListState()
    LaunchedEffect(Unit) { vm.refreshTurns() }
    val count = turns.size + (if (phase == Phase.THINKING) 1 else 0) + (if (error.isNotBlank()) 1 else 0)
    LaunchedEffect(count, keyboardOpen) { if (count > 0) list.animateScrollToItem(count) }

    Column(Modifier.fillMaxSize()) {
        TopBar(name, emotion, phase, link, heard, showFace = keyboardOpen, onCall = onCall)
        val portraitH by animateDpAsState(if (keyboardOpen) 0.dp else 250.dp, tween(260), label = "portrait")
        if (portraitH > 0.dp) Portrait(emotion, phase, level, Modifier.fillMaxWidth().height(portraitH))

        LazyColumn(
            state = list,
            modifier = Modifier.weight(1f).fillMaxWidth().fadeTop(),
            contentPadding = PaddingValues(start = 16.dp, end = 16.dp, top = 18.dp, bottom = 12.dp),
            verticalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            if (turns.isEmpty()) item { HerBubble("Hi! I'm right here. Tap the mic or type to me.") }
            items(turns) { TurnRow(it) }
            if (phase == Phase.THINKING && turns.lastOrNull()?.pending != true) item { TypingBubble() }
            if (error.isNotBlank()) item {
                Text(error, color = Red, fontSize = 13.sp, textAlign = TextAlign.Center, modifier = Modifier.fillMaxWidth().padding(top = 4.dp))
            }
        }

        photo?.let { jpeg -> PhotoComposer(jpeg, onSend = { q, keep -> vm.sendPhoto(q, keep) }, onDrop = vm::dropPhoto) }
        Composer(
            phase = phase, level = level, name = name, photoWaiting = photo != null,
            onSend = { vm.send(it) }, onMic = { if (phase == Phase.IDLE) askMic { vm.toggleMic() } else vm.toggleMic() },
            takePhoto = takePhoto, pickPhoto = pickPhoto,
        )
    }
}

@Composable
private fun TopBar(name: String, emotion: String, phase: Phase, link: Link, heard: String, showFace: Boolean, onCall: () -> Unit) {
    val (status, dot) = when {
        phase == Phase.LISTENING -> "listening…" to Accent0
        phase == Phase.THINKING -> (if (heard.startsWith(Photos.CAMERA)) "looking at your photo…" else "thinking…") to Lavender
        phase == Phase.SPEAKING -> "talking" to Accent0
        link == Link.ONLINE -> "here with you" to Mint
        link == Link.CONNECTING -> "waking up…" to Butter
        link == Link.UNAUTHORIZED -> "not paired yet" to Red
        else -> "away · laptop offline" to Dim
    }
    Row(Modifier.fillMaxWidth().padding(start = 20.dp, end = 14.dp, top = 14.dp, bottom = 4.dp), verticalAlignment = Alignment.CenterVertically) {
        AnimatedVisibility(showFace) { FaceAvatar(emotion, 40.dp, Modifier.padding(end = 12.dp)) }
        Column(Modifier.weight(1f)) {
            Text(name, style = DisplayStyle, color = Text1, fontSize = 24.sp, fontWeight = FontWeight.Bold)
            Row(verticalAlignment = Alignment.CenterVertically) {
                Box(Modifier.size(7.dp).background(dot, CircleShape))
                Text(status, color = Text2, fontSize = 13.sp, modifier = Modifier.padding(start = 6.dp))
            }
        }
        RoundIcon(Icons.Filled.Call, "Call her", enabled = phase == Phase.IDLE, onClick = onCall)
    }
}

/** Her portrait over a soft glow; the glow swells with your voice while she listens, and she breathes. */
@Composable
private fun Portrait(emotion: String, phase: Phase, level: Float, modifier: Modifier) {
    val look = LocalLook.current
    val accent = Accent0
    // animation values are States read only while drawing: reading them here recomposed the whole
    // screen every frame, which left the main thread little time for typing
    val breathe = rememberInfiniteTransition(label = "breathe")
    val t = breathe.animateFloat(0f, 1f, infiniteRepeatable(tween(3600), RepeatMode.Reverse), label = "t")
    val voice = animateFloatAsState(if (phase == Phase.LISTENING) level else 0f, tween(90), label = "voice")
    val glow = {
        when (phase) {
            Phase.LISTENING -> 0.32f + 0.5f * voice.value
            Phase.SPEAKING -> 0.30f + 0.08f * t.value
            Phase.THINKING -> 0.22f + 0.10f * t.value
            Phase.IDLE -> 0.16f + 0.05f * t.value
        }
    }
    Box(modifier.clipToBounds(), contentAlignment = Alignment.TopCenter) {
        Box(Modifier.fillMaxSize().drawBehind {
            drawCircle(Brush.radialGradient(listOf(accent.copy(alpha = glow()), Color.Transparent),
                                            center = Offset(size.width / 2, size.height * 0.5f), radius = size.height * 0.5f),
                       radius = size.height * 0.5f, center = Offset(size.width / 2, size.height * 0.5f))
        })
        Crossfade(emotion, animationSpec = tween(320), label = "portrait") { e ->
            Image(
                painterResource(Faces.portrait(e)), contentDescription = "Sanae looking $e",
                contentScale = ContentScale.FillWidth, alignment = Alignment.TopCenter,
                modifier = Modifier.requiredWidth(430.dp).fillMaxHeight()
                    .graphicsLayer { if (look.motion) (1f + 0.008f * t.value).let { scaleX = it; scaleY = it } }
                    .fadeBottom(),
            )
        }
        if (phase == Phase.THINKING) ThoughtDots(Modifier.align(Alignment.TopEnd).padding(top = 34.dp, end = 54.dp))
    }
}

/** Fade the bottom of her portrait into the sky, so she sits in the screen instead of on it. */
private fun Modifier.fadeBottom() = graphicsLayer(compositingStrategy = CompositingStrategy.Offscreen).drawWithContent {
    drawContent()
    drawRect(Brush.verticalGradient(0.62f to Color.Black, 1f to Color.Transparent), blendMode = BlendMode.DstIn)
}

/** Messages scrolling up fade out before they reach her. */
private fun Modifier.fadeTop() = graphicsLayer(compositingStrategy = CompositingStrategy.Offscreen).drawWithContent {
    drawContent()
    drawRect(Brush.verticalGradient(0f to Color.Transparent, 0.06f to Color.Black), blendMode = BlendMode.DstIn)
}

@Composable
private fun ThoughtDots(modifier: Modifier = Modifier) {
    Row(modifier.clip(RoundedCornerShape(16.dp)).background(Panel.copy(alpha = 0.9f)).padding(horizontal = 12.dp, vertical = 8.dp),
        horizontalArrangement = Arrangement.spacedBy(5.dp)) { Dots() }
}

@Composable
private fun Dots() {
    val motion = LocalLook.current.motion
    val wave = rememberInfiniteTransition(label = "dots")
    val p by wave.animateFloat(0f, 3f, infiniteRepeatable(tween(1200)), label = "p")
    repeat(3) { i ->
        val on = motion && p.toInt() == i
        Box(Modifier.size(7.dp).background(Text2.copy(alpha = if (on) 1f else 0.4f), CircleShape))
    }
}

@Composable
private fun TurnRow(t: Turn) {
    Column(Modifier.fillMaxWidth(), verticalArrangement = Arrangement.spacedBy(8.dp)) {
        if (t.user.isNotBlank()) MyBubble(Photos.label(t.user))       // blank: she texted first
        if (t.pending) TypingBubble() else if (t.reply.isNotBlank()) HerBubble(t.reply, clock(t.ts))
    }
}

@Composable
private fun MyBubble(text: String) {
    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.End) {
        Text(text, color = Text1, fontSize = 15.5.sp, lineHeight = 22.sp, modifier = Modifier
            .padding(start = 56.dp)
            .clip(RoundedCornerShape(22.dp, 6.dp, 22.dp, 22.dp))
            .background(Accent0.copy(alpha = 0.24f))
            .padding(horizontal = 15.dp, vertical = 10.dp))
    }
}

@Composable
private fun HerBubble(text: String, time: String = "") {
    Column(Modifier.padding(end = 40.dp)) {
        Text(highlighted(text), color = Text1, fontSize = 16.sp, lineHeight = 23.sp, modifier = Modifier
            .clip(RoundedCornerShape(6.dp, 22.dp, 22.dp, 22.dp))
            .background(Color.White.copy(alpha = 0.075f))
            .border(1.dp, Color.White.copy(alpha = 0.06f), RoundedCornerShape(6.dp, 22.dp, 22.dp, 22.dp))
            .padding(horizontal = 15.dp, vertical = 11.dp))
        if (time.isNotBlank()) Text(time, color = Dim, fontSize = 11.sp, modifier = Modifier.padding(start = 8.dp, top = 3.dp))
    }
}

@Composable
private fun TypingBubble() {
    Row(Modifier.clip(RoundedCornerShape(6.dp, 22.dp, 22.dp, 22.dp)).background(Color.White.copy(alpha = 0.075f))
            .padding(horizontal = 16.dp, vertical = 14.dp), horizontalArrangement = Arrangement.spacedBy(5.dp)) { Dots() }
}

/** "2026-10-21T19:22:10" -> "7:22 PM" (today) or "Oct 20, 7:22 PM". */
private fun clock(ts: String): String = runCatching {
    val t = java.time.LocalDateTime.parse(ts.take(19))
    val time = t.format(java.time.format.DateTimeFormatter.ofPattern("h:mm a"))
    if (t.toLocalDate() == java.time.LocalDate.now()) time
    else t.format(java.time.format.DateTimeFormatter.ofPattern("MMM d, ")) + time
}.getOrDefault("")

/** The bar at the bottom: + (photo), a text box, and the mic (or send while there's text). */
@Composable
private fun Composer(phase: Phase, level: Float, name: String, photoWaiting: Boolean, onSend: (String) -> Unit, onMic: () -> Unit,
                     takePhoto: () -> Unit, pickPhoto: () -> Unit) {
    var text by remember { mutableStateOf("") }
    var menu by remember { mutableStateOf(false) }
    val send = { if (text.isNotBlank()) { onSend(text); text = "" } }
    Row(Modifier.fillMaxWidth().padding(start = 12.dp, end = 12.dp, top = 6.dp, bottom = 4.dp), verticalAlignment = Alignment.CenterVertically) {
        Box {
            RoundIcon(Icons.Filled.Add, "Show her a photo", enabled = phase == Phase.IDLE, tint = if (photoWaiting) Accent0 else Text2) { menu = true }
            DropdownMenu(expanded = menu, onDismissRequest = { menu = false }, containerColor = PanelHi, shape = RoundedCornerShape(18.dp)) {
                DropdownMenuItem(text = { Text("Take a photo", color = Text1) }, onClick = { menu = false; takePhoto() },
                                 leadingIcon = { Icon(Icons.Filled.PhotoCamera, null, tint = Accent0) })
                DropdownMenuItem(text = { Text("Choose from gallery", color = Text1) }, onClick = { menu = false; pickPhoto() },
                                 leadingIcon = { Icon(Icons.Filled.PhotoLibrary, null, tint = Accent0) })
            }
        }
        Spacer(Modifier.width(8.dp))
        Box(Modifier.weight(1f).height(52.dp).clip(RoundedCornerShape(26.dp)).background(Color.White.copy(alpha = 0.07f))
                .border(1.dp, Color.White.copy(alpha = 0.06f), RoundedCornerShape(26.dp)).padding(horizontal = 18.dp),
            contentAlignment = Alignment.CenterStart) {
            if (phase == Phase.LISTENING) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    LevelBars(level)
                    Text("Listening… tap to send", color = Text2, fontSize = 15.sp, modifier = Modifier.padding(start = 10.dp))
                }
            } else {
                if (text.isEmpty()) Text("Talk to $name…", color = Dim, fontSize = 15.sp)
                BasicTextField(
                    value = text, onValueChange = { text = it }, singleLine = true, modifier = Modifier.fillMaxWidth(),
                    textStyle = TextStyle(color = Text1, fontSize = 15.sp, fontFamily = LocalLook.current.font.body),
                    cursorBrush = SolidColor(Accent0),
                    keyboardOptions = KeyboardOptions(imeAction = ImeAction.Send),
                    keyboardActions = KeyboardActions(onSend = { send() }),
                )
            }
        }
        Spacer(Modifier.width(8.dp))
        val typed = text.isNotBlank() && phase == Phase.IDLE
        val icon = when {
            typed -> Icons.AutoMirrored.Filled.Send
            phase == Phase.LISTENING -> Icons.Filled.Stop
            phase == Phase.SPEAKING -> Icons.AutoMirrored.Filled.VolumeOff
            else -> Icons.Filled.Mic
        }
        val label = when {
            typed -> "Send"
            phase == Phase.LISTENING -> "Send what you said"
            phase == Phase.SPEAKING -> "Stop talking"
            else -> "Talk"
        }
        Box(Modifier.size(54.dp).clip(CircleShape)
                .background(if (phase == Phase.THINKING) Accent0.copy(alpha = 0.3f) else Accent0)
                .clickable(enabled = phase != Phase.THINKING, role = Role.Button) { if (typed) send() else onMic() },
            contentAlignment = Alignment.Center) {
            Icon(icon, label, tint = Navy, modifier = Modifier.size(24.dp))
        }
    }
}

@Composable
private fun LevelBars(level: Float) {
    val v by animateFloatAsState(level, tween(90), label = "lvl")
    Row(horizontalArrangement = Arrangement.spacedBy(3.dp), verticalAlignment = Alignment.CenterVertically) {
        listOf(0.5f, 0.9f, 0.7f, 1f, 0.6f).forEach { k ->
            Box(Modifier.width(3.dp).height((6 + 18 * (v * k).coerceIn(0f, 1f)).dp).clip(RoundedCornerShape(2.dp)).background(Accent0))
        }
    }
}

@Composable
fun RoundIcon(icon: androidx.compose.ui.graphics.vector.ImageVector, label: String, enabled: Boolean = true, tint: Color = Text2,
              onClick: () -> Unit) {
    Box(Modifier.size(44.dp).clip(CircleShape).background(Color.White.copy(alpha = 0.07f))
            .clickable(enabled = enabled, role = Role.Button, onClick = onClick),
        contentAlignment = Alignment.Center) {
        Icon(icon, label, tint = if (enabled) tint else Dim.copy(alpha = 0.5f), modifier = Modifier.size(22.dp))
    }
}

/** A photo waiting to go: thumbnail (tap to keep it in our scrapbook), an optional question, send or drop. */
@Composable
private fun PhotoComposer(jpeg: ByteArray, onSend: (String, Boolean) -> Unit, onDrop: () -> Unit) {
    var q by remember(jpeg) { mutableStateOf("") }
    var keep by remember(jpeg) { mutableStateOf(false) }
    val thumb = remember(jpeg) {     // a 60 dp thumbnail: a quarter-size decode is plenty
        BitmapFactory.decodeByteArray(jpeg, 0, jpeg.size, BitmapFactory.Options().apply { inSampleSize = 4 })?.asImageBitmap()
    }
    Row(Modifier.padding(horizontal = 12.dp, vertical = 6.dp).fillMaxWidth().clip(RoundedCornerShape(22.dp))
            .background(Color.White.copy(alpha = 0.07f)).padding(8.dp), verticalAlignment = Alignment.CenterVertically) {
        Box(Modifier.size(60.dp).clip(RoundedCornerShape(16.dp)).border(2.dp, if (keep) Accent0 else Color.Transparent, RoundedCornerShape(16.dp))
                .clickable { keep = !keep }) {
            if (thumb != null) Image(thumb, contentDescription = "Your photo", contentScale = ContentScale.Crop, modifier = Modifier.fillMaxSize())
            Text(if (keep) "♡ kept" else "keep?", color = if (keep) Accent0 else Color.White, fontSize = 10.sp, textAlign = TextAlign.Center,
                 modifier = Modifier.align(Alignment.BottomCenter).fillMaxWidth().background(Color.Black.copy(alpha = 0.55f)))
        }
        Box(Modifier.weight(1f).padding(horizontal = 12.dp)) {
            if (q.isEmpty()) Text("Ask about it (optional)", color = Dim, fontSize = 15.sp)
            BasicTextField(
                value = q, onValueChange = { q = it }, singleLine = true, modifier = Modifier.fillMaxWidth(),
                textStyle = TextStyle(color = Text1, fontSize = 15.sp, fontFamily = LocalLook.current.font.body),
                cursorBrush = SolidColor(Accent0),
                keyboardOptions = KeyboardOptions(imeAction = ImeAction.Send), keyboardActions = KeyboardActions(onSend = { onSend(q, keep) }),
            )
        }
        RoundIcon(Icons.Filled.Close, "Don't send", onClick = onDrop)
        Spacer(Modifier.width(6.dp))
        Box(Modifier.size(44.dp).clip(CircleShape).background(Accent0).clickable(role = Role.Button) { onSend(q, keep) },
            contentAlignment = Alignment.Center) { Icon(Icons.AutoMirrored.Filled.Send, "Send photo", tint = Navy, modifier = Modifier.size(20.dp)) }
    }
}
