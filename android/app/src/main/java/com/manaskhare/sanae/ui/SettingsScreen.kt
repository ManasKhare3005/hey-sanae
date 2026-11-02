package com.manaskhare.sanae.ui

import android.Manifest
import android.annotation.SuppressLint
import android.content.pm.PackageManager
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.core.content.ContextCompat
import androidx.compose.material.icons.filled.Alarm
import androidx.compose.material.icons.filled.Bedtime
import androidx.compose.material.icons.filled.DoNotDisturbOn
import androidx.compose.material.icons.filled.CalendarMonth
import androidx.compose.material.icons.filled.Call
import androidx.compose.material.icons.filled.CheckCircle
import androidx.compose.material.icons.filled.Contacts
import androidx.compose.material.icons.filled.NotificationsActive
import androidx.compose.material.icons.automirrored.filled.OpenInNew
import android.app.StatusBarManager
import android.appwidget.AppWidgetManager
import android.content.ComponentName
import android.content.Intent
import android.graphics.drawable.Icon
import android.net.Uri
import android.os.Build
import android.os.PowerManager
import android.provider.Settings
import android.widget.Toast
import androidx.activity.compose.BackHandler
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.VolumeUp
import androidx.compose.material.icons.filled.BatteryChargingFull
import androidx.compose.material.icons.filled.Hearing
import androidx.compose.material.icons.filled.Link
import androidx.compose.material.icons.filled.LinkOff
import androidx.compose.material.icons.filled.MicOff
import androidx.compose.material.icons.filled.Palette
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material.icons.filled.QrCodeScanner
import androidx.compose.material.icons.filled.SettingsInputAntenna
import androidx.compose.material.icons.filled.SmartButton
import androidx.compose.material.icons.filled.TouchApp
import androidx.compose.material.icons.filled.Widgets
import androidx.compose.material.icons.filled.Edit
import androidx.compose.material.icons.filled.Favorite
import androidx.compose.material.icons.filled.Apps
import androidx.compose.material.icons.filled.Home
import androidx.compose.material.icons.filled.MusicNote
import androidx.compose.material.icons.automirrored.filled.DirectionsRun
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
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.compose.LifecycleResumeEffect
import com.manaskhare.sanae.Hub
import com.manaskhare.sanae.MainViewModel
import com.manaskhare.sanae.SanaeTileService
import com.manaskhare.sanae.SanaeWidget
import com.manaskhare.sanae.PhoneActions
import com.manaskhare.sanae.R

@SuppressLint("BatteryLife")
@Composable
fun SettingsScreen(vm: MainViewModel, scanQr: () -> Unit, group: String? = null, onBack: () -> Unit = {}) {
    val shows = { g: String -> group == null || group == g }
    var appearance by rememberSaveable { mutableStateOf(false) }
    if (appearance) {
        BackHandler { appearance = false }
        AppearanceScreen(onBack = { appearance = false })
        return
    }

    val context = LocalContext.current
    val look = LocalLook.current
    val paired by vm.paired.collectAsState()
    val link by Hub.link.collectAsState()
    var url by remember { mutableStateOf(vm.prefs.url) }
    var token by remember { mutableStateOf("") }
    var manual by remember { mutableStateOf(false) }
    var speak by remember { mutableStateOf(vm.prefs.speakReplies) }
    var test by remember { mutableStateOf("") }
    val ignoring = {
        runCatching { context.getSystemService(PowerManager::class.java).isIgnoringBatteryOptimizations(context.packageName) }
            .getOrDefault(false)
    }
    var unrestricted by remember { mutableStateOf(ignoring()) }
    // Re-check whenever you come back (e.g. from the system battery prompt or Samsung's settings)
    LifecycleResumeEffect(Unit) {
        unrestricted = ignoring()
        onPauseOrDispose { }
    }
    val toast = { msg: String -> Toast.makeText(context, msg, Toast.LENGTH_SHORT).show() }
    val granted = { perm: String -> ContextCompat.checkSelfPermission(context, perm) == PackageManager.PERMISSION_GRANTED }
    var contacts by remember { mutableStateOf(granted(Manifest.permission.READ_CONTACTS)) }
    var calls by remember { mutableStateOf(granted(Manifest.permission.CALL_PHONE)) }
    var notifs by remember { mutableStateOf(PhoneActions.notificationAccess(context)) }
    var overlay by remember { mutableStateOf(Settings.canDrawOverlays(context)) }
    var calendar by remember { mutableStateOf(com.manaskhare.sanae.SanaeCalendar.allowed(context)) }
    var exact by remember { mutableStateOf(com.manaskhare.sanae.Alarms.exact(context)) }
    LifecycleResumeEffect(Unit) {
        contacts = granted(Manifest.permission.READ_CONTACTS); calls = granted(Manifest.permission.CALL_PHONE)
        notifs = PhoneActions.notificationAccess(context); overlay = Settings.canDrawOverlays(context)
        calendar = com.manaskhare.sanae.SanaeCalendar.allowed(context); exact = com.manaskhare.sanae.Alarms.exact(context)
        onPauseOrDispose { }
    }
    val askPermission = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) {
        contacts = granted(Manifest.permission.READ_CONTACTS); calls = granted(Manifest.permission.CALL_PHONE)
    }
    var healthOn by remember { mutableStateOf(vm.prefs.healthOn) }
    val healthReady = remember { com.manaskhare.sanae.HealthShare.available(context) }
    val askHealth = rememberLauncherForActivityResult(
        androidx.health.connect.client.PermissionController.createRequestPermissionResultContract()) { got ->
        val ok = got.containsAll(com.manaskhare.sanae.HealthShare.PERMISSIONS)
        healthOn = ok; vm.prefs.healthOn = ok
        com.manaskhare.sanae.WatchLink.healthChanged(context, ok)
        if (ok) com.manaskhare.sanae.Sync.trigger(context, 0) else toast("Health stays off (permissions not given)")
    }
    // She notices: each part off until turned on (Noticing.kt / roommate.py on the laptop)
    var noticeApps by remember { mutableStateOf(vm.prefs.noticeApps && com.manaskhare.sanae.Noticing.usageGranted(context)) }
    var noticeMusic by remember { mutableStateOf(vm.prefs.noticeMusic) }
    var noticeWorkouts by remember { mutableStateOf(vm.prefs.noticeWorkouts) }
    LifecycleResumeEffect(Unit) {            // back from Android's Usage access screen
        if (vm.prefs.noticeApps && com.manaskhare.sanae.Noticing.usageGranted(context)) noticeApps = true
        onPauseOrDispose { }
    }
    val askWorkouts = rememberLauncherForActivityResult(
        androidx.health.connect.client.PermissionController.createRequestPermissionResultContract()) { got ->
        val ok = got.containsAll(com.manaskhare.sanae.Noticing.WORKOUT_PERMISSIONS)
        noticeWorkouts = ok; vm.prefs.noticeWorkouts = ok
        if (!ok) toast("Workouts stay off (permission not given)")
    }
    // Home Wi-Fi (HomeWifi.kt): its name only shows with location permission, so ask, then save
    var homeName by remember { mutableStateOf(if (vm.prefs.homeEnabled) vm.prefs.homeSsid.ifBlank { "your Wi-Fi" } else "") }
    fun saveHome() {
        val name = com.manaskhare.sanae.HomeWifi.saveHome(context)
        if (name == null) toast("Connect to your home Wi-Fi first, then tap again") else { homeName = name; toast("Got it: $name is home") }
    }
    val askLocation = rememberLauncherForActivityResult(ActivityResultContracts.RequestMultiplePermissions()) {
        saveHome()                                   // without permission the router fingerprint still works
    }
    // Wind-down at midnight (WindDown.kt)
    var windOn by remember { mutableStateOf(vm.prefs.windDownOn) }
    var windQuiet by remember { mutableStateOf(vm.prefs.windDownQuiet) }
    var windAlarm by remember { mutableStateOf(vm.prefs.windDownAlarm) }
    var wakeAt by remember { mutableStateOf(vm.prefs.wakeAt) }
    var dndAllowed by remember { mutableStateOf(com.manaskhare.sanae.WindDown.quietAllowed(context)) }
    LifecycleResumeEffect(Unit) {            // back from Android's Do Not Disturb access screen
        dndAllowed = com.manaskhare.sanae.WindDown.quietAllowed(context)
        onPauseOrDispose { }
    }
    val askCalendar = rememberLauncherForActivityResult(ActivityResultContracts.RequestMultiplePermissions()) {
        calendar = com.manaskhare.sanae.SanaeCalendar.allowed(context)
        if (calendar) com.manaskhare.sanae.Sync.trigger(context, 0)        // fills the new Sanae calendar
    }
    val openSettings = { action: String, withPackage: Boolean ->
        runCatching {
            context.startActivity(if (withPackage) Intent(action, Uri.parse("package:${context.packageName}")) else Intent(action))
        }.onFailure { toast("Open your phone's settings and search for Sanae") }
    }

    LazyColumn(Modifier.fillMaxSize().padding(horizontal = 16.dp), verticalArrangement = Arrangement.spacedBy(22.dp)) {
        item {
            if (group == null) Row(Modifier.padding(start = 10.dp, top = 22.dp)) { Title("Settings") }
            else PageHead(MeGroups.title(group), onBack)
        }

        if (shows("connection")) item {
            Section("Laptop") {
                SettingRow(if (paired) "Paired" else "Not paired yet", Icons.Filled.Link,
                           subtitle = if (paired) vm.prefs.url.removePrefix("https://") else "Dashboard → Phone tab shows a QR code",
                           trailing = { LinkChip(link) })
                RowDivider()
                SettingRow(if (paired) "Re-pair (scan QR code)" else "Pair (scan QR code)", Icons.Filled.QrCodeScanner, onClick = scanQr)
                if (paired) {
                    RowDivider()
                    SettingRow("Test connection", Icons.Filled.SettingsInputAntenna,
                               subtitle = test.ifBlank { null }, onClick = {
                        test = "Checking…"
                        vm.call({ it.ping() }) { test = "✓ ${it.optString("name")} is reachable (${it.optString("mode")} mode)" }
                    })
                }
                RowDivider()
                SettingRow("Pair manually", Icons.Filled.Edit, subtitle = "Type the address and token instead",
                           onClick = { manual = !manual })
                if (manual) {
                    Column(Modifier.padding(start = 16.dp, end = 16.dp, bottom = 16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                        Field(url, { url = it }, "https://laptop.tailnet.ts.net")
                        Field(token, { token = it }, "Token (dashboard → Phone → show)")
                        GhostButton("Save", Modifier.fillMaxWidth()) {
                            if (url.isNotBlank() && token.length >= 20) { vm.pairManually(url, token); manual = false }
                            else toast("Enter the address and the full token")
                        }
                    }
                }
            }
        }

        if (paired && shows("dev")) {
            item { ChangeSanaeSection(vm) }
            item { UpdateSection(vm) }
        }

        if (shows("look")) item {
            Section("Look & sound") {
                SettingRow("Appearance", Icons.Filled.Palette,
                           subtitle = "${look.accent.label} · ${look.font.label} font",
                           onClick = { appearance = true })
                RowDivider()
                SettingRow("Speak replies", Icons.AutoMirrored.Filled.VolumeUp, subtitle = "In Sanae's own voice",
                           trailing = { Toggle(speak) { speak = it; vm.prefs.speakReplies = it } })
            }
        }

        if (shows("connection") && paired) item {
            Column {
                Label("Laptop controls", Modifier.padding(start = 6.dp, bottom = 8.dp))
                Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                    ControlTile("Listen now", Icons.Filled.Hearing, Modifier.weight(1f)) { vm.call({ it.control("listen") }) { toast("The laptop is listening") } }
                    ControlTile("Pause mic", Icons.Filled.MicOff, Modifier.weight(1f)) { vm.call({ it.control("pause") }) { toast("Laptop mic paused") } }
                    ControlTile("Resume", Icons.Filled.PlayArrow, Modifier.weight(1f)) { vm.call({ it.control("resume") }) { toast("Laptop mic on") } }
                }
                Text("“Listen now” makes the laptop listen as if you said “Hey Sanae”.", color = Text2, fontSize = 12.5.sp,
                     modifier = Modifier.padding(start = 6.dp, top = 8.dp))
            }
        }

        if (shows("phone")) item {
            Section("Without the laptop") {
                SettingRow("Calendar", Icons.Filled.CalendarMonth,
                           subtitle = if (calendar) "✓ Sanae's events show in your calendar app as “Sanae”, offline too"
                                      else "Show Sanae's events in your phone's calendar app",
                           onClick = if (calendar) null else ({ askCalendar.launch(arrayOf(Manifest.permission.READ_CALENDAR,
                                                                                         Manifest.permission.WRITE_CALENDAR)) }),
                           trailing = if (calendar) ({ Check() }) else null)
                RowDivider()
                SettingRow("Reminders on time", Icons.Filled.Alarm,
                           subtitle = if (exact) "✓ Reminders ring on this phone at the exact minute, laptop on or off"
                                      else "Allow “Alarms & reminders”, or they may come a few minutes late",
                           onClick = if (exact) null else ({ openSettings(Settings.ACTION_REQUEST_SCHEDULE_EXACT_ALARM, true) }),
                           trailing = if (exact) ({ Check() }) else null)
            }
        }

        if (shows("health")) item {
            Section("Health") {
                SettingRow("Sleep, steps & heart rate", Icons.Filled.Favorite,
                           subtitle = when {
                               !healthReady -> "Needs Health Connect (and Samsung Health syncing to it)"
                               healthOn -> "✓ From your watch, to your laptop only. “How did I sleep?”"
                               else -> "Off. Shares your watch's numbers with your laptop only"
                           },
                           trailing = if (healthReady) ({ Toggle(healthOn) { on ->
                               if (on) askHealth.launch(com.manaskhare.sanae.HealthShare.PERMISSIONS)
                               else { healthOn = false; vm.prefs.healthOn = false; com.manaskhare.sanae.WatchLink.healthChanged(context, false) }
                           } }) else null)
            }
        }

        if (shows("night")) item {
            Section("Wind down at midnight") {
                SettingRow("Wind down", Icons.Filled.Bedtime,
                           subtitle = if (windOn) "✓ Every night at 12 AM she says goodnight" else "Off",
                           trailing = { Toggle(windOn) { on ->
                               windOn = on; vm.prefs.windDownOn = on; com.manaskhare.sanae.WindDown.arm(context)
                           } })
                if (windOn) {
                    RowDivider()
                    SettingRow("Phone goes quiet", Icons.Filled.DoNotDisturbOn,
                               subtitle = when {
                                   !dndAllowed -> "Needs Do Not Disturb access: tap to allow"
                                   windQuiet -> "✓ Do Not Disturb until the alarm (alarms still ring)"
                                   else -> "Off"
                               },
                               onClick = if (!dndAllowed) ({ openSettings(android.provider.Settings.ACTION_NOTIFICATION_POLICY_ACCESS_SETTINGS, false) }) else null,
                               trailing = { Toggle(windQuiet && dndAllowed) { on ->
                                   if (on && !dndAllowed) openSettings(android.provider.Settings.ACTION_NOTIFICATION_POLICY_ACCESS_SETTINGS, false)
                                   else { windQuiet = on; vm.prefs.windDownQuiet = on }
                               } })
                    RowDivider()
                    SettingRow("Morning alarm", Icons.Filled.Alarm,
                               subtitle = if (windAlarm) "✓ Usually ${wakeAt.let { runCatching { com.manaskhare.sanae.WindDown.clock(java.time.LocalTime.parse(it)) }.getOrDefault(it) }}; earlier when your first class is early"
                                          else "Off",
                               trailing = { Toggle(windAlarm) { on -> windAlarm = on; vm.prefs.windDownAlarm = on } })
                    if (windAlarm) Segmented(listOf("07:00", "07:30", "08:00", "08:30", "09:00"), wakeAt,
                                             { runCatching { com.manaskhare.sanae.WindDown.clock(java.time.LocalTime.parse(it)) }.getOrDefault(it) }) {
                        wakeAt = it; vm.prefs.wakeAt = it
                    }
                }
            }
        }

        if (shows("noticing")) item {
            Section("Home") {
                SettingRow("Home Wi-Fi", Icons.Filled.Home,
                           subtitle = if (homeName.isNotBlank()) "✓ $homeName. Joining it means you're home; only “arrived” / “left” is sent"
                                      else "Connect to your home Wi-Fi and tap Set: she'll know when you get home",
                           trailing = {
                               if (homeName.isBlank()) GhostButton("Set") {
                                   if (com.manaskhare.sanae.HomeWifi.locationAllowed(context)) saveHome()
                                   else askLocation.launch(arrayOf(android.Manifest.permission.ACCESS_FINE_LOCATION,
                                                                   android.Manifest.permission.ACCESS_COARSE_LOCATION))
                               } else GhostButton("Forget") { com.manaskhare.sanae.HomeWifi.forget(context); homeName = "" }
                           })
            }
        }

        if (shows("noticing")) item {
            Section("She notices") {
                SettingRow("Apps you use", Icons.Filled.Apps,
                           subtitle = if (noticeApps) "✓ Minutes in Duolingo, social apps and apps on your daily list. Nothing else is sent"
                                      else "Duolingo done, scrolling at 2 AM, ticks app-linked things on your daily list",
                           trailing = { Toggle(noticeApps) { on ->
                               vm.prefs.noticeApps = on
                               if (on && !com.manaskhare.sanae.Noticing.usageGranted(context)) {
                                   toast("Turn on Usage access for Sanae, then come back")
                                   runCatching { context.startActivity(com.manaskhare.sanae.Noticing.usageSettings()) }
                               } else noticeApps = on
                           } })
                SettingRow("What's playing", Icons.Filled.MusicNote,
                           subtitle = when {
                               !notifs -> "Needs notification access (Phone powers below)"
                               noticeMusic -> "✓ Song and artist only, so she notices what's on repeat"
                               else -> "Off. She'd notice a song on repeat all week"
                           },
                           trailing = { Toggle(noticeMusic && notifs) { on ->
                               if (on && !notifs) toast("Turn on notification access first (Phone powers)")
                               else { noticeMusic = on; vm.prefs.noticeMusic = on }
                           } })
                SettingRow("Workouts", Icons.AutoMirrored.Filled.DirectionsRun,
                           subtitle = when {
                               !healthReady -> "Needs Health Connect (Strava, Samsung Health...)"
                               noticeWorkouts -> "✓ Type, length and distance, to your laptop only"
                               else -> "Off. She'd react to your runs and workouts"
                           },
                           trailing = if (healthReady) ({ Toggle(noticeWorkouts) { on ->
                               if (on) askWorkouts.launch(com.manaskhare.sanae.Noticing.WORKOUT_PERMISSIONS)
                               else { noticeWorkouts = false; vm.prefs.noticeWorkouts = false }
                           } }) else null)
            }
        }

        if (shows("phone")) item {
            Section("Phone powers") {
                SettingRow("Contacts", Icons.Filled.Contacts,
                           subtitle = if (contacts) "✓ “Call Mom”, “text Alex” find the right person" else "So Sanae knows who “Mom” is",
                           onClick = if (contacts) null else ({ askPermission.launch(Manifest.permission.READ_CONTACTS) }),
                           trailing = if (contacts) ({ Check() }) else null)
                RowDivider()
                SettingRow("Phone calls", Icons.Filled.Call,
                           subtitle = if (calls) "✓ Calls start after you say yes" else "Without this, Sanae dials and you tap Call",
                           onClick = if (calls) null else ({ askPermission.launch(Manifest.permission.CALL_PHONE) }),
                           trailing = if (calls) ({ Check() }) else null)
                RowDivider()
                SettingRow("Notifications", Icons.Filled.NotificationsActive,
                           subtitle = if (notifs) "✓ “What did I miss?” works (kept in memory only)" else "Lets Sanae read your recent notifications",
                           onClick = { openSettings(Settings.ACTION_NOTIFICATION_LISTENER_SETTINGS, false) },
                           trailing = if (notifs) ({ Check() }) else null)
                RowDivider()
                SettingRow("Act while the phone is locked away", Icons.AutoMirrored.Filled.OpenInNew,
                           subtitle = if (overlay) "✓ Asks from the laptop happen right away"
                                      else "“Display over other apps”: otherwise you get a tap-to-open notification",
                           onClick = { openSettings(Settings.ACTION_MANAGE_OVERLAY_PERMISSION, true) },
                           trailing = if (overlay) ({ Check() }) else null)
            }
        }

        if (shows("look")) item {
            Section("Quick access") {
                SettingRow("Add Quick Settings tile", Icons.Filled.TouchApp, subtitle = "Pull down the shade, tap Sanae, talk", onClick = {
                    if (Build.VERSION.SDK_INT >= 33) {
                        context.getSystemService(StatusBarManager::class.java).requestAddTileService(
                            ComponentName(context, SanaeTileService::class.java), "Sanae",
                            Icon.createWithResource(context, R.drawable.ic_stat_sanae), context.mainExecutor) { }
                    } else toast("Edit your Quick Settings and drag the Sanae tile in")
                })
                RowDivider()
                SettingRow("Add home-screen widget", Icons.Filled.Widgets, subtitle = "A “Talk to Sanae” button", onClick = {
                    val wm = context.getSystemService(AppWidgetManager::class.java)
                    if (wm.isRequestPinAppWidgetSupported) wm.requestPinAppWidget(ComponentName(context, SanaeWidget::class.java), null, null)
                    else toast("Long-press your home screen → Widgets → Sanae")
                })
                RowDivider()
                SettingRow("Side key", Icons.Filled.SmartButton,
                           subtitle = "Make Sanae the digital assistant, then Side button → Press and hold → Digital assistant",
                           onClick = { runCatching { context.startActivity(Intent(Settings.ACTION_MANAGE_DEFAULT_APPS_SETTINGS)) } })
            }
        }

        if (shows("connection")) item {
            Section("Stay connected") {
                SettingRow(if (unrestricted) "Background: unrestricted" else "Allow background",
                           Icons.Filled.BatteryChargingFull,
                           subtitle = if (unrestricted) "Reminders and approvals arrive reliably"
                                      else "Samsung may close Sanae and delay reminders",
                           color = if (unrestricted) Text1 else Amber,
                           onClick = if (unrestricted) null else ({
                               runCatching {
                                   context.startActivity(Intent(Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS,
                                                                Uri.parse("package:${context.packageName}")))
                               }.onFailure {      // some Samsung builds hide that prompt: open the app's own settings
                                   context.startActivity(Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS,
                                                                Uri.parse("package:${context.packageName}")))
                               }
                           }))
            }
        }

        if (paired && shows("connection")) item {
            Section("Danger zone") {
                SettingRow("Unpair this phone", Icons.Filled.LinkOff, color = Red, onClick = { vm.unpair(); test = "" })
            }
        }
        item { Spacer(Modifier.height(20.dp)) }
    }
}

@Composable
private fun Check() = Icon(Icons.Filled.CheckCircle, contentDescription = "On", tint = Accent0)

/** Equal-size tile (icon over a one-line label), three to a row. */
@Composable
private fun ControlTile(label: String, icon: ImageVector, modifier: Modifier = Modifier, onClick: () -> Unit) {
    Column(
        modifier.height(84.dp)
            .clip(RoundedCornerShape(18.dp))
            .background(Color.White.copy(alpha = 0.035f))
            .border(1.dp, Accent0.copy(alpha = 0.16f), RoundedCornerShape(18.dp))
            .clickable(role = Role.Button, onClick = onClick)
            .padding(8.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.Center,
    ) {
        Icon(icon, null, tint = Accent0, modifier = Modifier.size(24.dp))
        Spacer(Modifier.height(8.dp))
        Text(label, color = Text1, fontSize = 13.sp, fontWeight = FontWeight.Medium, maxLines = 1, textAlign = TextAlign.Center)
    }
}
