package com.manaskhare.sanae

import android.Manifest
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import android.os.Bundle
import android.widget.Toast
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.result.PickVisualMediaRequest
import androidx.activity.result.contract.ActivityResultContracts
import androidx.activity.viewModels
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.Chat
import androidx.compose.material.icons.filled.Event
import androidx.compose.material.icons.filled.Favorite
import androidx.compose.material.icons.filled.Person
import androidx.compose.material.icons.filled.WbSunny
import androidx.compose.material.icons.filled.GraphicEq
import androidx.compose.material.icons.filled.Psychology
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Icon
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.NavigationBarItemDefaults
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.core.content.ContextCompat
import com.journeyapps.barcodescanner.ScanContract
import com.journeyapps.barcodescanner.ScanOptions
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.consumeWindowInsets
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.manaskhare.sanae.ui.AppBackground
import com.manaskhare.sanae.ui.Cyan
import com.manaskhare.sanae.ui.Dim
import com.manaskhare.sanae.ui.SanaeScreen
import com.manaskhare.sanae.ui.MeScreen
import com.manaskhare.sanae.ui.CozyNavBar
import com.manaskhare.sanae.ui.NavItem
import com.manaskhare.sanae.ui.SanaeTheme
import com.manaskhare.sanae.ui.MemoryScreen
import com.manaskhare.sanae.ui.UsScreen
import com.manaskhare.sanae.ui.Navy
import com.manaskhare.sanae.ui.Panel
import com.manaskhare.sanae.ui.PanelHi
import com.manaskhare.sanae.ui.Red
import com.manaskhare.sanae.ui.SettingsScreen
import com.manaskhare.sanae.ui.Text1
import com.manaskhare.sanae.ui.Text2
import com.manaskhare.sanae.ui.TodayScreen

class MainActivity : ComponentActivity() {
    private val vm: MainViewModel by viewModels()
    private var afterMicGrant: (() -> Unit)? = null

    private val micPermission = registerForActivityResult(ActivityResultContracts.RequestPermission()) { granted ->
        if (granted) afterMicGrant?.invoke() else toast("${Persona.name(this@MainActivity)} needs the microphone for push-to-talk.")
        afterMicGrant = null
    }
    private var shot: android.net.Uri? = null
    private val camera = registerForActivityResult(ActivityResultContracts.TakePicture()) { ok ->
        val uri = shot ?: return@registerForActivityResult
        shot = null
        if (ok) vm.stagePhoto(uri) else { Photos.clearShots(this); vm.photoPrep("cancel") }
    }
    private val gallery = registerForActivityResult(ActivityResultContracts.PickVisualMedia()) { uri ->
        if (uri != null) vm.stagePhoto(uri) else vm.photoPrep("cancel")
    }
    private val notifPermission = registerForActivityResult(ActivityResultContracts.RequestPermission()) { }
    private val scanner = registerForActivityResult(ScanContract()) { result ->
        val text = result.contents ?: return@registerForActivityResult
        toast(if (vm.pair(text)) "Paired with your laptop" else "That isn't a pairing code")
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        handleLink(intent)
        if (Build.VERSION.SDK_INT >= 33 &&
            ContextCompat.checkSelfPermission(this, Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) {
            notifPermission.launch(Manifest.permission.POST_NOTIFICATIONS)
        }
        SanaeApp.startLink(this)

        setContent {
            SanaeTheme {
                var tab by remember { mutableIntStateOf(if (vm.prefs.paired) TAB_SANAE else TAB_ME) }
                val approvals by Hub.approvals.collectAsState()
                val photo by vm.photo.collectAsState()
                LaunchedEffect(photo) { if (photo != null) tab = TAB_SANAE }      // a shared photo opens her tab
                val wanted by openTab.collectAsState()
                LaunchedEffect(wanted) { if (wanted >= 0) { tab = wanted; openTab.value = -1 } }   // the widget's "Today"
                val emotion by vm.emotion.collectAsState()
                AppBackground(glowAt = 0.2f) {
                Scaffold(
                    containerColor = Color.Transparent,
                    bottomBar = {
                        CozyNavBar(
                            listOf(NavItem(Persona.name(this@MainActivity), null, face = true), NavItem("Today", Icons.Filled.WbSunny),
                                   NavItem("Us", Icons.Filled.Favorite), NavItem("Me", Icons.Filled.Person)),
                            selected = tab, emotion = emotion, modifier = Modifier.navigationBarsPadding(),
                        ) { tab = it }
                    },
                ) { pad ->
                    // Edge-to-edge: make room for the keyboard ourselves (minus the nav bar it covers)
                    Box(Modifier.fillMaxSize().padding(pad).consumeWindowInsets(pad).imePadding()) {
                        when (tab) {
                            TAB_SANAE -> SanaeScreen(vm, ::takePhoto, ::pickPhoto, askMic = ::withMic,
                                                     onCall = { withMic { startActivity(Intent(this@MainActivity, CallActivity::class.java)) } })
                            TAB_TODAY -> TodayScreen(vm)
                            TAB_US -> UsScreen(vm)
                            else -> MeScreen(vm, ::scanQr)
                        }
                    }
                }
                }
                com.manaskhare.sanae.ui.WeekStoryHost(Persona.name(this@MainActivity))   // "your week" plays over everything
                // A risky action is waiting for this phone's OK (also shown as a notification)
                approvals.firstOrNull()?.let { a ->
                    AlertDialog(
                        onDismissRequest = {},
                        containerColor = Panel,
                        title = { Text("${Persona.name(this@MainActivity)} needs your OK", color = Text1) },
                        text = { Text(a.prompt, color = Text2) },
                        confirmButton = { TextButton(onClick = { vm.answer(a.id, true) }) { Text("Approve", color = Cyan) } },
                        dismissButton = { TextButton(onClick = { vm.answer(a.id, false) }) { Text("Deny", color = Red) } },
                    )
                }
            }
        }
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        handleLink(intent)
    }

    override fun onResume() {
        super.onResume()
        SanaeApp.startLink(this)          // reconnects right away if the link dropped
    }

    private fun handleLink(intent: Intent?) {
        intent?.getIntExtra(EXTRA_TAB, -1)?.takeIf { it >= 0 }?.let { openTab.value = it }
        intent?.getStringExtra(EXTRA_PAGE)?.let { openPage.value = it }
        if (intent?.action == Intent.ACTION_SEND && intent.type?.startsWith("image/") == true) {
            @Suppress("DEPRECATION")
            val uri = if (Build.VERSION.SDK_INT >= 33) intent.getParcelableExtra(Intent.EXTRA_STREAM, android.net.Uri::class.java)
                      else intent.getParcelableExtra<android.net.Uri>(Intent.EXTRA_STREAM)
            setIntent(Intent(this, MainActivity::class.java))          // don't share it again on rotation
            if (uri != null) vm.stagePhoto(uri)
            return
        }
        val data = intent?.data ?: return
        if (data.scheme == "max") toast(if (vm.pair(data.toString())) "Paired with your laptop" else "Invalid pairing link")
    }

    private fun withMic(action: () -> Unit) {
        if (ContextCompat.checkSelfPermission(this, Manifest.permission.RECORD_AUDIO) == PackageManager.PERMISSION_GRANTED) {
            action()
        } else {
            afterMicGrant = action
            micPermission.launch(Manifest.permission.RECORD_AUDIO)
        }
    }

    private fun takePhoto() {
        val uri = Photos.shotUri(this)
        shot = uri
        vm.photoPrep("ready")          // the laptop swaps models while the shot is framed
        runCatching { camera.launch(uri) }.onFailure { shot = null; vm.photoPrep("cancel"); toast("No camera app found") }
    }

    private fun pickPhoto() {
        vm.photoPrep("ready")          // same warm-up as the camera
        runCatching { gallery.launch(PickVisualMediaRequest(ActivityResultContracts.PickVisualMedia.ImageOnly)) }
            .onFailure { vm.photoPrep("cancel"); toast("No gallery app found") }
    }

    private fun scanQr() = scanner.launch(ScanOptions()
        .setDesiredBarcodeFormats(ScanOptions.QR_CODE)
        .setPrompt("Scan the QR code in Sanae's dashboard (Phone tab)")
        .setBeepEnabled(false)
        .setOrientationLocked(false))

    private fun toast(text: String) = Toast.makeText(this, text, Toast.LENGTH_SHORT).show()

    companion object {
        const val EXTRA_TAB = "tab"
        const val EXTRA_PAGE = "page"           // an Us tile to open (UsTiles.ORDER key)
        const val TAB_SANAE = 0
        const val TAB_TODAY = 1
        const val TAB_US = 2
        const val TAB_ME = 3
        val openTab = kotlinx.coroutines.flow.MutableStateFlow(-1)
        val openPage = kotlinx.coroutines.flow.MutableStateFlow<String?>(null)
    }
}
