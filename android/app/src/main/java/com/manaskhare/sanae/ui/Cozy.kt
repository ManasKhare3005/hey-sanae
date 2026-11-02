package com.manaskhare.sanae.ui

import androidx.compose.animation.Crossfade
import androidx.compose.animation.animateColorAsState
import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.animation.core.LinearEasing
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.RowScope
import androidx.compose.foundation.layout.defaultMinSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.drawBehind
import androidx.compose.ui.draw.scale
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.manaskhare.sanae.Phase
import com.manaskhare.sanae.R

// Extra warm tones next to the accent (streaks, highlights, little touches)
val Peach = Color(0xFFFFC6A5)
val Lavender = Color(0xFFC9B6FF)
val Butter = Color(0xFFF8D98B)
val Mint = Color(0xFF9FE3C5)

/** Her rendered look per emotion (scripts/phone_faces.py): an upper-body portrait and a head crop. */
object Faces {
    val EMOTIONS = listOf("neutral", "happy", "shy", "laugh", "thinking", "sad", "surprised", "sleepy")

    fun name(emotion: String?) = emotion?.lowercase()?.takeIf { it in EMOTIONS } ?: "happy"

    fun portrait(emotion: String?) = when (name(emotion)) {
        "neutral" -> R.drawable.sanae_neutral
        "shy" -> R.drawable.sanae_shy
        "laugh" -> R.drawable.sanae_laugh
        "thinking" -> R.drawable.sanae_thinking
        "sad" -> R.drawable.sanae_sad
        "surprised" -> R.drawable.sanae_surprised
        "sleepy" -> R.drawable.sanae_sleepy
        else -> R.drawable.sanae_happy
    }

    fun face(emotion: String?) = when (name(emotion)) {
        "neutral" -> R.drawable.face_neutral
        "shy" -> R.drawable.face_shy
        "laugh" -> R.drawable.face_laugh
        "thinking" -> R.drawable.face_thinking
        "sad" -> R.drawable.face_sad
        "surprised" -> R.drawable.face_surprised
        "sleepy" -> R.drawable.face_sleepy
        else -> R.drawable.face_happy
    }
}

/** An emotion for a reply that came without one (old chat turns): the same cues as the laptop's tags.guess. */
object EmotionGuess {
    private val CUES = listOf(
        "laugh" to Regex("""\b(haha+|hehe+|lol|lmao)\b""", RegexOption.IGNORE_CASE),
        "sad" to Regex("""\b(sorry|aw+|oh no|that stinks|that sucks|rough|unfortunately|couldn'?t|failed)\b""", RegexOption.IGNORE_CASE),
        "surprised" to Regex("""\b(wait,? what|whoa|wow|no way|really\?)""", RegexOption.IGNORE_CASE),
        "sleepy" to Regex("""\b(sleepy|tired|yawn|bedtime|so late)\b""", RegexOption.IGNORE_CASE),
        "thinking" to Regex("""\b(hmm+|let me think|i think|maybe|not sure)\b""", RegexOption.IGNORE_CASE),
        "happy" to Regex("""\b(yay|great|awesome|nice|done|perfect|love|glad|hey+|hi+)\b|!""", RegexOption.IGNORE_CASE),
    )

    fun guess(text: String): String = CUES.firstOrNull { it.second.containsMatchIn(text) }?.first ?: "neutral"
}

/** Her face in a soft ring (top bar, chat, empty states). */
@Composable
fun FaceAvatar(emotion: String?, size: Dp = 40.dp, modifier: Modifier = Modifier, ring: Color = Accent0) {
    Box(
        modifier.size(size).clip(CircleShape)
            .background(Brush.verticalGradient(listOf(LocalLook.current.accent.bgTop, Panel)))
            .border(1.5.dp, ring.copy(alpha = 0.55f), CircleShape),
    ) {
        Crossfade(Faces.name(emotion), animationSpec = tween(260), label = "face") { e ->
            Image(painterResource(Faces.face(e)), contentDescription = null, contentScale = ContentScale.Crop,
                  modifier = Modifier.size(size))
        }
    }
}

/**
 * Her face, alive: breathes when idle, the glow follows your voice while she listens, a ring
 * circles while she thinks and pulses while she talks. Calls and the assistant sheet use it.
 */
@Composable
fun LiveFace(emotion: String?, phase: Phase, level: Float, size: Dp, modifier: Modifier = Modifier) {
    val accent = Accent0
    val t = rememberInfiniteTransition(label = "live")
    val breathe by t.animateFloat(0f, 1f, infiniteRepeatable(tween(2600), RepeatMode.Reverse), label = "breathe")
    val pulse by t.animateFloat(0f, 1f, infiniteRepeatable(tween(520), RepeatMode.Reverse), label = "pulse")
    val spin by t.animateFloat(0f, 360f, infiniteRepeatable(tween(1600, easing = LinearEasing)), label = "spin")
    val voice by animateFloatAsState(if (phase == Phase.LISTENING) level.coerceIn(0f, 1f) else 0f, tween(90), label = "voice")
    val glow = when (phase) {
        Phase.LISTENING -> 0.35f + voice * 0.6f
        Phase.SPEAKING -> 0.35f + pulse * 0.25f
        Phase.THINKING -> 0.3f
        Phase.IDLE -> 0.18f + breathe * 0.1f
    }
    Box(modifier.size(size * 1.55f).drawBehind {
        val c = Offset(this.size.width / 2, this.size.height / 2)
        val r = this.size.minDimension / 2
        drawCircle(Brush.radialGradient(listOf(accent.copy(alpha = glow), accent.copy(alpha = glow * 0.35f), Color.Transparent), c, r), r, c)
        val ring = size.toPx() / 2 + 10.dp.toPx() + voice * 14.dp.toPx() + (if (phase == Phase.SPEAKING) pulse * 6.dp.toPx() else 0f)
        when (phase) {
            Phase.THINKING -> drawArc(accent.copy(alpha = 0.8f), spin, 100f, false, Offset(c.x - ring, c.y - ring), Size(ring * 2, ring * 2),
                                      style = Stroke(3.dp.toPx(), cap = StrokeCap.Round))
            Phase.IDLE -> drawCircle(accent.copy(alpha = 0.25f), ring, c, style = Stroke(1.5.dp.toPx()))
            else -> drawCircle(accent.copy(alpha = 0.55f), ring, c, style = Stroke(2.5.dp.toPx()))
        }
    }, contentAlignment = Alignment.Center) {
        FaceAvatar(emotion ?: if (phase == Phase.THINKING) "thinking" else "happy", size,
                   Modifier.scale(1f + (if (phase == Phase.IDLE) breathe * 0.015f else 0f)), ring = Color.Transparent)
    }
}

/** The one filled button a screen leads with. */
@Composable
fun SoftButton(text: String, modifier: Modifier = Modifier, icon: ImageVector? = null, enabled: Boolean = true, onClick: () -> Unit) {
    Row(
        modifier.defaultMinSize(minHeight = 46.dp).clip(RoundedCornerShape(50))
            .background(if (enabled) Accent0 else Accent0.copy(alpha = 0.3f))
            .clickable(enabled = enabled, role = Role.Button, onClick = onClick)
            .padding(horizontal = 20.dp),
        verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp, Alignment.CenterHorizontally),
    ) {
        if (icon != null) Icon(icon, null, tint = Navy, modifier = Modifier.size(18.dp))
        Text(text, color = Navy, fontSize = 15.sp, fontWeight = FontWeight.Bold)
    }
}

/** A small rounded pill: filters, kinds, tags. */
@Composable
fun Chip(text: String, selected: Boolean = false, modifier: Modifier = Modifier, color: Color = Accent0, icon: ImageVector? = null,
         onClick: (() -> Unit)? = null) {
    val bg by animateColorAsState(if (selected) color.copy(alpha = 0.22f) else Color.White.copy(alpha = 0.06f), label = "chip")
    Row(
        modifier.height(34.dp).clip(RoundedCornerShape(50)).background(bg)
            .border(1.dp, if (selected) color.copy(alpha = 0.7f) else Color.Transparent, RoundedCornerShape(50))
            .then(if (onClick != null) Modifier.clickable(role = Role.Button, onClick = onClick) else Modifier)
            .padding(horizontal = 14.dp),
        verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(6.dp),
    ) {
        if (icon != null) Icon(icon, null, tint = if (selected) color else Text2, modifier = Modifier.size(16.dp))
        Text(text, color = if (selected) Text1 else Text2, fontSize = 13.sp, fontWeight = FontWeight.Medium)
    }
}

data class NavItem(val label: String, val icon: ImageVector?, val face: Boolean = false)

/** The floating bottom bar: four soft pills; the picked one fills with the accent. Her tab shows her face. */
@Composable
fun CozyNavBar(items: List<NavItem>, selected: Int, emotion: String?, modifier: Modifier = Modifier, onPick: (Int) -> Unit) {
    Row(
        modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 10.dp)
            .clip(RoundedCornerShape(30.dp)).background(Panel.copy(alpha = 0.96f))
            .border(1.dp, Color.White.copy(alpha = 0.07f), RoundedCornerShape(30.dp)).padding(6.dp),
        horizontalArrangement = Arrangement.SpaceBetween, verticalAlignment = Alignment.CenterVertically,
    ) {
        items.forEachIndexed { i, item -> NavPill(item, i == selected, emotion) { onPick(i) } }
    }
}

@Composable
private fun RowScope.NavPill(item: NavItem, on: Boolean, emotion: String?, onClick: () -> Unit) {
    val bg by animateColorAsState(if (on) Accent0.copy(alpha = 0.2f) else Color.Transparent, tween(220), label = "nav")
    Row(
        Modifier.weight(1f).height(48.dp).clip(RoundedCornerShape(24.dp)).background(bg)
            .clickable(interactionSource = remember { MutableInteractionSource() }, indication = null, role = Role.Tab, onClick = onClick),
        horizontalArrangement = Arrangement.Center, verticalAlignment = Alignment.CenterVertically,
    ) {
        if (item.face) FaceAvatar(emotion, 26.dp, ring = if (on) Accent0 else Color.Transparent)
        else if (item.icon != null) Icon(item.icon, item.label, tint = if (on) Accent0 else Dim, modifier = Modifier.size(22.dp))
        if (on) Text(item.label, color = Text1, fontSize = 13.sp, fontWeight = FontWeight.Bold, modifier = Modifier.padding(start = 7.dp))
    }
}
