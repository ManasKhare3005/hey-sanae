package com.manaskhare.sanae.ui

import android.Manifest
import android.content.pm.PackageManager
import android.os.Build
import android.os.PowerManager
import androidx.activity.compose.BackHandler
import androidx.compose.animation.AnimatedContent
import androidx.compose.animation.core.tween
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.slideInHorizontally
import androidx.compose.animation.togetherWith
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.automirrored.filled.KeyboardArrowRight
import androidx.compose.material.icons.filled.AutoAwesome
import androidx.compose.material.icons.filled.Bedtime
import androidx.compose.material.icons.filled.Code
import androidx.compose.material.icons.filled.Favorite
import androidx.compose.material.icons.filled.Link
import androidx.compose.material.icons.filled.Palette
import androidx.compose.material.icons.filled.PhoneAndroid
import androidx.compose.material.icons.filled.Psychology
import androidx.compose.material.icons.filled.Visibility
import androidx.compose.material.icons.filled.WarningAmber
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.core.content.ContextCompat
import androidx.lifecycle.compose.LifecycleResumeEffect
import com.manaskhare.sanae.Hub
import com.manaskhare.sanae.Link
import com.manaskhare.sanae.MainViewModel
import com.manaskhare.sanae.Persona
import com.manaskhare.sanae.Sync

/** Settings groups on the Me tab: key -> page title. */
object MeGroups {
    val ORDER = listOf("connection", "look", "phone", "health", "night", "noticing", "memory", "brain", "dev")
    fun title(key: String) = when (key) {
        "connection" -> "Connection"
        "look" -> "Look & voice"
        "phone" -> "Phone"
        "health" -> "Health"
        "night" -> "Night"
        "noticing" -> "Noticing"
        "memory" -> "Memory"
        "brain" -> "Her brain"
        "dev" -> "Changes & updates"
        else -> key
    }
}

/** The "Me" tab: how things stand at a glance, then settings in small groups (and her memory). */
@Composable
fun MeScreen(vm: MainViewModel, scanQr: () -> Unit) {
    var page by rememberSaveable { mutableStateOf<String?>(null) }
    BackHandler(enabled = page != null) { page = null }
    AnimatedContent(page, transitionSpec = {
        (fadeIn(tween(220)) + slideInHorizontally(tween(260)) { if (targetState != null) it / 6 else -it / 6 }) togetherWith fadeOut(tween(160))
    }, label = "me") { p ->
        when (p) {
            null -> MeHome(vm) { page = it }
            "memory" -> MemoryScreen(vm) { page = null }
            "brain" -> BrainScreen(vm) { page = null }
            else -> SettingsScreen(vm, scanQr, group = p) { page = null }
        }
    }
}

/** What needs a tap: missing permissions that make things late or quiet. */
internal data class Attention(val text: String, val group: String)

@Composable
fun MeHome(vm: MainViewModel, onOpen: (String) -> Unit) {
    val context = LocalContext.current
    val look = LocalLook.current
    val name = Persona.name(context)
    val paired by vm.paired.collectAsState()
    val link by Hub.link.collectAsState()
    val last by Sync.lastSync.collectAsState()
    val emotion by vm.emotion.collectAsState()
    fun needs(): List<Attention> = buildList {
        if (!paired) add(Attention("Pair with your laptop", "connection"))
        if (Build.VERSION.SDK_INT >= 33 && ContextCompat.checkSelfPermission(context, Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED)
            add(Attention("Notifications are off: reminders stay silent", "phone"))
        if (!com.manaskhare.sanae.Alarms.exact(context)) add(Attention("Allow alarms so reminders ring on time", "phone"))
        val unrestricted = runCatching { context.getSystemService(PowerManager::class.java).isIgnoringBatteryOptimizations(context.packageName) }.getOrDefault(true)
        if (paired && !unrestricted) add(Attention("Allow background so she isn't closed", "connection"))
    }
    var attention by remember { mutableStateOf(needs()) }
    LifecycleResumeEffect(paired) {
        attention = needs()
        onPauseOrDispose { }
    }
    val rows = MeGroups.ORDER.filter { (it != "dev" && it != "brain") || paired }
    LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(start = 16.dp, end = 16.dp, top = 22.dp, bottom = 24.dp),
               verticalArrangement = Arrangement.spacedBy(10.dp)) {
        item("head") {
            Column(Modifier.padding(start = 6.dp, bottom = 4.dp)) {
                Label("Settings & memory", color = Accent0)
                Text("Me", style = DisplayStyle, color = Text1, fontSize = 44.sp, lineHeight = 48.sp)
            }
        }
        item("status") {
            Column(Modifier.fillMaxWidth().clip(RoundedCornerShape(24.dp))
                       .background(Brush.linearGradient(listOf(Accent0.copy(alpha = 0.16f), Lavender.copy(alpha = 0.08f))))
                       .border(1.dp, Accent0.copy(alpha = 0.18f), RoundedCornerShape(24.dp)).padding(16.dp)) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    FaceAvatar(emotion, 52.dp)
                    Column(Modifier.padding(start = 14.dp).weight(1f)) {
                        Text("You & $name", style = DisplayStyle, color = Text1, fontSize = 20.sp)
                        LinkChip(link)
                        Text(when {
                            !paired -> "Not paired yet"
                            last > 0 -> "Synced ${ago(last)}"
                            else -> "Not synced yet"
                        }, color = Text2, fontSize = 12.5.sp)
                    }
                }
                if (attention.isEmpty()) {
                    Text("Everything's set up. She can reach you.", color = Text2, fontSize = 13.sp, modifier = Modifier.padding(top = 12.dp))
                }
                attention.forEach { a ->
                    Row(Modifier.padding(top = 10.dp).fillMaxWidth().clip(RoundedCornerShape(16.dp)).background(Amber.copy(alpha = 0.12f))
                            .clickable { onOpen(a.group) }.padding(horizontal = 12.dp, vertical = 10.dp), verticalAlignment = Alignment.CenterVertically) {
                        Icon(Icons.Filled.WarningAmber, null, tint = Amber, modifier = Modifier.size(18.dp))
                        Text(a.text, color = Text1, fontSize = 13.5.sp, modifier = Modifier.weight(1f).padding(start = 10.dp))
                        Icon(Icons.AutoMirrored.Filled.KeyboardArrowRight, null, tint = Dim, modifier = Modifier.size(20.dp))
                    }
                }
            }
        }
        items(rows, key = { it }) { k ->
            val (icon, color, sub) = when (k) {
                "connection" -> Triple(Icons.Filled.Link, Accent0, if (paired) "Laptop, controls, staying connected" else "Pair with your laptop")
                "look" -> Triple(Icons.Filled.Palette, Peach, "${look.accent.label} · ${look.font.label} font · voice")
                "phone" -> Triple(Icons.Filled.PhoneAndroid, Mint, "Calendar, reminders, calls, contacts")
                "health" -> Triple(Icons.Filled.Favorite, Accent0, if (vm.prefs.healthOn) "On: sleep, steps, heart rate" else "Off")
                "night" -> Triple(Icons.Filled.Bedtime, Lavender, if (vm.prefs.windDownOn) "Wind down at 12 AM" else "Wind-down is off")
                "noticing" -> Triple(Icons.Filled.Visibility, Butter, "Home Wi-Fi, apps, music, workouts")
                "memory" -> Triple(Icons.Filled.Psychology, Lavender, "What she remembers, your notes")
                "brain" -> Triple(Icons.Filled.AutoAwesome, Butter, "Lessons, aims, what Claude saw")
                else -> Triple(Icons.Filled.Code, Mint, "Change $name, app updates")
            }
            GroupRow(MeGroups.title(k), sub, icon, color) { onOpen(k) }
        }
    }
}

@Composable
private fun GroupRow(title: String, sub: String, icon: ImageVector, color: Color, onClick: () -> Unit) {
    Row(Modifier.fillMaxWidth().clip(RoundedCornerShape(20.dp)).background(Color.White.copy(alpha = 0.05f)).clickable(onClick = onClick)
            .padding(horizontal = 14.dp, vertical = 12.dp), verticalAlignment = Alignment.CenterVertically) {
        Box(Modifier.size(40.dp).clip(CircleShape).background(color.copy(alpha = 0.18f)), contentAlignment = Alignment.Center) {
            Icon(icon, null, tint = color, modifier = Modifier.size(21.dp))
        }
        Column(Modifier.weight(1f).padding(start = 14.dp)) {
            Text(title, color = Text1, fontSize = 15.5.sp, fontWeight = FontWeight.Bold)
            Text(sub, color = Text2, fontSize = 12.5.sp)
        }
        Icon(Icons.AutoMirrored.Filled.KeyboardArrowRight, null, tint = Dim)
    }
}

@Composable
internal fun BackButton(onBack: () -> Unit) =
    Box(Modifier.size(44.dp).clip(CircleShape).background(Color.White.copy(alpha = 0.07f)).clickable(onClick = onBack),
        contentAlignment = Alignment.Center) { Icon(Icons.AutoMirrored.Filled.ArrowBack, "Back", tint = Text1) }

/** A settings page's top: back + title. */
@Composable
internal fun PageHead(title: String, onBack: () -> Unit) {
    Row(Modifier.padding(top = 14.dp), verticalAlignment = Alignment.CenterVertically) {
        BackButton(onBack)
        Text(title, style = DisplayStyle, color = Text1, fontSize = 28.sp, modifier = Modifier.padding(start = 14.dp))
    }
}
