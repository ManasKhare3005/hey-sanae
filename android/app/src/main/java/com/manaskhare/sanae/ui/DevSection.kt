package com.manaskhare.sanae.ui

import android.content.Context
import android.content.Intent
import android.net.Uri
import android.provider.Settings
import android.widget.Toast
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.SystemUpdate
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.OutlinedTextFieldDefaults
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.core.content.FileProvider
import com.manaskhare.sanae.BuildConfig
import com.manaskhare.sanae.MainViewModel
import com.manaskhare.sanae.objects
import com.manaskhare.sanae.str
import kotlinx.coroutines.delay
import org.json.JSONObject
import java.io.File
import java.text.DateFormat
import java.util.Date

private val WORKING = setOf("queued", "working", "testing", "building")

/** Type a change for Sanae or one of your projects; Claude Code on the laptop makes it on a branch;
 *  approve or reject here, then push (projects only). */
@Composable
fun ChangeSanaeSection(vm: MainViewModel) {
    var jobs by remember { mutableStateOf<List<JSONObject>>(emptyList()) }
    var projects by remember { mutableStateOf(listOf("Sanae")) }
    var project by remember { mutableStateOf("Sanae") }
    var rev by remember { mutableIntStateOf(0) }
    var err by remember { mutableStateOf("") }
    val latest = jobs.firstOrNull()
    val active = latest != null && latest.str("status") in WORKING
    LaunchedEffect(Unit) {
        vm.call({ api -> runCatching { api.projects() } }) { r ->
            r.onSuccess { list ->
                val names = list.objects().map { it.str("name") }.filter { it.isNotBlank() }
                if (names.isNotEmpty()) projects = listOf("Sanae") + names.filter { it != "Sanae" }
                list.objects().firstOrNull { it.optBoolean("current") }?.let { project = it.str("name") }
            }
        }
    }
    LaunchedEffect(rev) {
        while (true) {
            vm.call({ api -> runCatching { api.devJobs() } }) { r ->
                r.onSuccess { jobs = it.objects(); err = "" }.onFailure { err = it.message ?: "" }
            }
            delay(if (jobs.firstOrNull()?.str("status") in WORKING) 2500 else 15000)
        }
    }

    Section("Code changes") {
        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            Text("Pick a project and describe a change. Claude makes it on the laptop on its own branch, runs the " +
                 "tests, then asks for your OK here.", color = Text2, fontSize = 13.sp)
            Row(Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                projects.forEach { name -> ProjectPill(name, name == project) { if (!active) project = name } }
            }
            RequestBox(active) { text, sent ->
                val target = if (project == "Sanae") "" else project
                vm.call({ api -> runCatching { api.devRequest(text, target) } }) { r ->
                    r.onSuccess { sent(); err = ""; rev++ }.onFailure { err = it.message ?: "Couldn't send it" }
                }
            }
            if (err.isNotBlank()) Text(err, color = Red, fontSize = 13.sp)
            latest?.let { JobCard(vm, it) { rev++ } }
            jobs.drop(1).take(3).forEach { j ->
                Text("#${j.optInt("id")} · ${j.str("project").ifBlank { "Sanae" }} · ${j.str("status")} · ${j.str("request").take(50)}",
                     color = Dim, fontSize = 12.sp)
            }
        }
    }
}

/** The request box keeps its own text, so a keystroke redraws only the box (not the job cards and diff). */
@Composable
private fun RequestBox(active: Boolean, onSend: (text: String, sent: () -> Unit) -> Unit) {
    var text by remember { mutableStateOf("") }
    OutlinedTextField(
        value = text, onValueChange = { text = it }, modifier = Modifier.fillMaxWidth().heightIn(min = 96.dp),
        placeholder = { Text("e.g. make the Notes list show the course name", color = Dim, fontSize = 14.sp) },
        shape = RoundedCornerShape(10.dp), enabled = !active,
        colors = OutlinedTextFieldDefaults.colors(unfocusedBorderColor = Line, focusedBorderColor = Cyan),
    )
    GhostButton(if (active) "Claude is working…" else "Send to Claude", Modifier.fillMaxWidth()) {
        if (!active && text.isNotBlank()) onSend(text) { text = "" }
    }
}

@Composable
private fun JobCard(vm: MainViewModel, j: JSONObject, changed: () -> Unit) {
    val status = j.str("status")
    val color = when (status) { "ready" -> Cyan; "failed", "rejected" -> Red; "merged" -> Accent0; else -> Text1 }
    val project = j.str("project").ifBlank { "Sanae" }
    var diff by remember(j.optInt("id")) { mutableStateOf("") }
    Card {
        Label("#${j.optInt("id")} · ${project.uppercase()} · ${status.uppercase()}" +
              if (j.optBoolean("pushed")) " · PUSHED" else "", color = color)
        Text(j.str("request"), color = Text1, fontWeight = FontWeight.SemiBold, fontSize = 14.sp)
        val steps = j.optJSONArray("progress")
        if (status in WORKING && steps != null && steps.length() > 0) {
            Text("▸ ${steps.getString(steps.length() - 1)}", color = Text2, fontSize = 13.sp, modifier = Modifier.padding(top = 6.dp))
        }
        if (j.str("summary").isNotBlank() && status !in WORKING) {
            Text(j.str("summary"), color = Text2, fontSize = 13.sp, modifier = Modifier.padding(top = 6.dp))
        }
        if (status == "ready" || status == "merged") {
            val files = j.optJSONArray("files")?.length() ?: 0
            Text("${if (j.optBoolean("tests_ok")) "✓" else "✗"} tests: ${j.str("tests").lines().last()} · $files files" +
                 if (j.optBoolean("apk")) " · new phone app" else "",
                 color = if (j.optBoolean("tests_ok")) Text2 else Red, fontSize = 12.5.sp, modifier = Modifier.padding(top = 6.dp))
        }
        if (j.str("error").isNotBlank()) Text(j.str("error"), color = Red, fontSize = 12.5.sp, modifier = Modifier.padding(top = 6.dp))
        if (status == "ready") {
            Row(Modifier.padding(top = 10.dp), horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                GhostButton("Approve", Modifier.weight(1f)) { vm.call({ it.devDecide(j.optInt("id"), "approve") }) { changed() } }
                GhostButton("Reject", Modifier.weight(1f), color = Red) { vm.call({ it.devDecide(j.optInt("id"), "reject") }) { changed() } }
            }
            if (j.optBoolean("apk")) Text("After approving, install the update below.", color = Dim, fontSize = 12.sp,
                                          modifier = Modifier.padding(top = 6.dp))
            GhostButton(if (diff.isBlank()) "Show the changes" else "Hide the changes", Modifier.padding(top = 8.dp), color = Text2) {
                if (diff.isNotBlank()) { diff = ""; return@GhostButton }
                vm.call({ api -> runCatching { api.devDiff(j.optInt("id")) } }) { r ->
                    r.onSuccess { diff = it.str("diff").take(20000).ifBlank { "(no diff)" } }
                        .onFailure { diff = "Couldn't load the diff: ${it.message}" }
                }
            }
            if (diff.isNotBlank()) Text(diff, color = Text1, fontSize = 10.5.sp, fontFamily = FontFamily.Monospace,
                                        modifier = Modifier.padding(top = 6.dp).horizontalScroll(rememberScrollState()))
        } else if (status == "merged" && project != "Sanae" && !j.optBoolean("pushed")) {
            GhostButton("Push to GitHub", Modifier.padding(top = 8.dp)) {
                vm.call({ it.devDecide(j.optInt("id"), "push") }) { changed() }
            }
        } else if (status in WORKING) {
            GhostButton("Cancel", Modifier.padding(top = 8.dp), color = Red) {
                vm.call({ it.devDecide(j.optInt("id"), "reject") }) { changed() }
            }
        }
    }
}

@Composable
private fun ProjectPill(name: String, selected: Boolean, onClick: () -> Unit) {
    Text(name, color = if (selected) Cyan else Text2, fontSize = 13.sp,
         fontWeight = if (selected) FontWeight.SemiBold else FontWeight.Normal,
         modifier = Modifier
             .border(1.dp, if (selected) Cyan else Line, RoundedCornerShape(50))
             .clickable(onClick = onClick)
             .padding(horizontal = 12.dp, vertical = 6.dp))
}

/** Install the phone app the laptop last built (downloaded over the same Tailscale link). */
@Composable
fun UpdateSection(vm: MainViewModel) {
    val context = LocalContext.current
    var info by remember { mutableStateOf<JSONObject?>(null) }
    var busy by remember { mutableStateOf("") }
    LaunchedEffect(Unit) {
        while (true) {
            vm.call({ api -> runCatching { api.appInfo() } }) { r -> r.onSuccess { info = it } }
            delay(30000)
        }
    }
    val fmt = DateFormat.getDateTimeInstance(DateFormat.MEDIUM, DateFormat.SHORT)
    val laptop = info?.optLong("built") ?: 0L
    val newer = info?.optBoolean("available") == true && laptop > BuildConfig.BUILD_TIME + 60_000
    Section("App update") {
        SettingRow(
            when { busy.isNotBlank() -> busy; newer -> "Install update"; else -> "Up to date" }, Icons.Filled.SystemUpdate,
            subtitle = "This app: ${fmt.format(Date(BuildConfig.BUILD_TIME))}" +
                if (laptop > 0) "\nOn the laptop: ${fmt.format(Date(laptop))}" else "",
            color = if (newer) Cyan else Text1,
            onClick = {
                if (busy.isNotBlank() || info?.optBoolean("available") != true) return@SettingRow
                if (!context.packageManager.canRequestPackageInstalls()) {
                    toast(context, "Allow Sanae to install updates, then tap again")
                    context.startActivity(Intent(Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES, Uri.parse("package:${context.packageName}")))
                    return@SettingRow
                }
                busy = "Downloading…"
                val file = File(context.cacheDir, "updates/sanae.apk").apply { parentFile?.mkdirs() }
                vm.call({ api -> runCatching { api.download("/api/app/apk", file) } }) { r ->
                    busy = ""
                    r.onSuccess { install(context, file) }.onFailure { toast(context, "Download failed: ${it.message}") }
                }
            },
        )
    }
}

private fun install(context: Context, apk: File) {
    val uri = FileProvider.getUriForFile(context, "${context.packageName}.files", apk)
    context.startActivity(Intent(Intent.ACTION_VIEW).setDataAndType(uri, "application/vnd.android.package-archive")
        .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_ACTIVITY_NEW_TASK))
}

private fun toast(context: Context, msg: String) = Toast.makeText(context, msg, Toast.LENGTH_LONG).show()
