package com.manaskhare.sanae

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.asRequestBody
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONArray
import org.json.JSONObject
import java.net.URLEncoder
import java.util.concurrent.TimeUnit

class ApiError(val code: Int, message: String) : Exception(message)

/** Sanae's REST API on the laptop (the same one the dashboard uses), with the pairing token. */
class SanaeApi(private val base: String, private val token: String) {

    companion object {
        private val JSON = "application/json".toMediaType()
        private val WAV = "audio/wav".toMediaType()
        private val BINARY = "application/octet-stream".toMediaType()
        private val AAC = "audio/aac".toMediaType()
        private val JPEG = "image/jpeg".toMediaType()
        private val TEXT = "text/plain; charset=utf-8".toMediaType()

        val http: OkHttpClient = OkHttpClient.Builder()
            .connectTimeout(10, TimeUnit.SECONDS)
            .readTimeout(180, TimeUnit.SECONDS)     // a command may wait for an approval tap
            .writeTimeout(60, TimeUnit.SECONDS)
            .pingInterval(20, TimeUnit.SECONDS)     // keeps the WebSocket alive through NAT/Tailscale
            .build()

        /** A photo can take a while: a cold vision model loads from disk (up to ~80 s) before it looks,
         *  and the laptop gives up on the model after 180 s; wait longer than that so its answer arrives. */
        private val photoHttp: OkHttpClient = http.newBuilder().readTimeout(300, TimeUnit.SECONDS).build()

        fun from(prefs: Prefs): SanaeApi? = if (prefs.paired) SanaeApi(prefs.url, prefs.token) else null
    }

    val wsUrl: String
        get() = base.replaceFirst(Regex("^http"), "ws") + "/api/ws?token=" + URLEncoder.encode(token, "UTF-8")

    private fun request(path: String) =
        Request.Builder().url(base + path).header("Authorization", "Bearer $token")

    private suspend fun run(req: Request, client: OkHttpClient = http): ByteArray = withContext(Dispatchers.IO) {
        client.newCall(req).execute().use { res ->
            val body = res.body?.bytes() ?: ByteArray(0)
            if (!res.isSuccessful) {
                val detail = runCatching { JSONObject(String(body)).optString("detail") }.getOrNull()
                throw ApiError(res.code, detail?.ifBlank { null } ?: "HTTP ${res.code}")
            }
            body
        }
    }

    private suspend fun get(path: String) = String(run(request(path).get().build()))
    private suspend fun post(path: String, body: JSONObject = JSONObject()) =
        String(run(request(path).post(body.toString().toRequestBody(JSON)).build()))
    private suspend fun delete(path: String) = String(run(request(path).delete().build()))

    suspend fun ping() = JSONObject(get("/api/ping"))
    suspend fun us() = JSONObject(get("/api/us"))
    /** A crash / freeze report from CrashLog (plain text). */
    suspend fun crashReport(text: String) = String(run(request("/api/phone/crash").post(text.toRequestBody(TEXT)).build()))
    /** One turn of a call: what you said (WAV) -> {heard, reply, emotion, audio (base64 WAV), end}. */
    suspend fun callTurn(wav: ByteArray) = JSONObject(String(run(request("/api/call/turn").post(wav.toRequestBody(WAV)).build())))
    /** A diary page said out loud (WAV): the laptop writes it down; the notebook comes back. */
    suspend fun voicePage(wav: ByteArray, mood: String, private: Boolean) = JSONObject(String(run(
        request("/api/journal/voice?mood=${enc(mood)}&private=$private").post(wav.toRequestBody(WAV)).build())))

    /** Any JSON call (the "Us" tab's changes, replayed from its offline outbox): the reply's text. */
    suspend fun raw(method: String, path: String, body: JSONObject = JSONObject()): String {
        val b = request(path)
        val req = when (method.uppercase()) {
            "GET" -> b.get()
            "DELETE" -> b.delete()
            "PUT" -> b.put(body.toString().toRequestBody(JSON))
            else -> b.post(body.toString().toRequestBody(JSON))
        }
        return String(run(req.build()))
    }
    suspend fun state() = JSONObject(get("/api/state"))
    suspend fun command(text: String) = commandFull(text).optString("reply")

    /** {reply, emotion?}: her face on the phone follows the emotion she answered with. */
    suspend fun commandFull(text: String) = JSONObject(post("/api/command", JSONObject().put("text", text)))

    /** Push-to-talk: 16 kHz WAV in, {heard, reply, emotion?} out. */
    suspend fun voice(wav: ByteArray): JSONObject = JSONObject(String(run(request("/api/voice").post(wav.toRequestBody(WAV)).build())))

    /** The watch's push-to-talk, relayed by WatchRelay: {heard, reply, emotion?}. The header lets the
     *  laptop show it came from the watch. */
    suspend fun voiceFrom(wav: ByteArray, device: String): JSONObject = JSONObject(String(run(
        request("/api/voice").header("X-Sanae-Device", device).post(wav.toRequestBody(WAV)).build())))

    /** A photo (already shrunk, no EXIF: Photos.read) plus an optional question -> her reply. */
    suspend fun photo(jpeg: ByteArray, question: String, keep: Boolean = false): String = JSONObject(String(run(
        request("/api/photo?q=" + URLEncoder.encode(question, "UTF-8") + (if (keep) "&keep=true" else ""))
            .post(jpeg.toRequestBody(JPEG)).build(), photoHttp))).optString("reply")

    /** "ready": a photo is probably coming (camera / share opened), so the laptop swaps its vision
     *  model in now; "cancel": it isn't, swap back. */
    suspend fun photoPrep(action: String) = post("/api/photo/$action")

    /** Sanae's own (Piper) voice as WAV. */
    suspend fun speak(text: String): ByteArray =
        run(request("/api/speak").post(JSONObject().put("text", text).toString().toRequestBody(JSON)).build())

    suspend fun approve(id: Int, approved: Boolean) = post("/api/approvals/$id", JSONObject().put("approved", approved))
    suspend fun control(action: String) = JSONObject(post("/api/control/$action"))

    suspend fun today() = JSONObject(get("/api/today"))
    suspend fun health(days: JSONArray) = JSONObject(post("/api/health", JSONObject().put("days", days)))
    suspend fun turns(limit: Int = 60) = JSONArray(get("/api/turns?limit=$limit"))
    suspend fun facts() = JSONArray(get("/api/facts"))
    suspend fun addFact(text: String) = post("/api/facts", JSONObject().put("text", text))
    suspend fun deleteFact(id: Int) = delete("/api/facts/$id")
    suspend fun reminders() = JSONArray(get("/api/reminders"))
    suspend fun addReminder(text: String, whenText: String) =
        JSONObject(post("/api/reminders", JSONObject().put("text", text).put("when", whenText)))
    suspend fun cancelReminder(id: Int) = delete("/api/reminders/$id")

    suspend fun notes() = JSONArray(get("/api/notes"))
    suspend fun note(id: Int) = JSONObject(get("/api/notes/$id"))
    suspend fun noteSummary(id: Int, refresh: Boolean = false) =
        JSONObject(post("/api/notes/$id/summary" + if (refresh) "?refresh=true" else "")).optString("summary_md")
    suspend fun phoneResult(id: Int, ok: Boolean, message: String) =
        post("/api/phone/result", JSONObject().put("id", id).put("ok", ok).put("message", message))
    suspend fun phoneState(state: JSONObject) = post("/api/phone/state", state)
    /** Offline work: send what changed on the phone, get the laptop's reminders and events back. */
    suspend fun sync(body: JSONObject) = JSONObject(post("/api/sync", body))

    /** A lecture / meeting recorded on the phone; the laptop writes its notes in the background. */
    suspend fun uploadRecording(r: LocalRecording, file: java.io.File): JSONObject {
        val q = "uid=${enc(r.uid)}&kind=${enc(r.kind)}&title=${enc(r.title)}&started_ms=${r.startedMs}"
        return JSONObject(String(run(request("/api/notes/upload?$q").post(file.asRequestBody(AAC)).build())))
    }
    suspend fun recordingStatus(uid: String) = JSONObject(get("/api/notes/upload/${enc(uid)}"))
    private fun enc(s: String) = URLEncoder.encode(s, "UTF-8")

    suspend fun notesStatus() = JSONObject(get("/api/notes/status"))
    suspend fun notesStart(kind: String) = post("/api/notes/start", JSONObject().put("kind", kind))
    suspend fun notesStop() = post("/api/notes/stop")

    /** Change Sanae from the phone (Claude Code on the laptop) and install the app it builds. */
    suspend fun devRequest(text: String, project: String = "") =
        JSONObject(post("/api/dev/request", JSONObject().put("text", text).put("project", project)))
    suspend fun devDiff(id: Int) = JSONObject(get("/api/dev/jobs/$id/diff"))
    suspend fun projects() = JSONArray(get("/api/projects"))
    suspend fun devJobs() = JSONArray(get("/api/dev/jobs"))
    suspend fun devDecide(id: Int, action: String) = JSONObject(post("/api/dev/jobs/$id/$action"))
    suspend fun appInfo() = JSONObject(get("/api/app/info"))
    suspend fun download(path: String, to: java.io.File) = withContext(Dispatchers.IO) {
        http.newCall(request(path).get().build()).execute().use { res ->
            if (!res.isSuccessful) throw ApiError(res.code, "HTTP ${res.code}")
            to.outputStream().use { out -> res.body!!.byteStream().copyTo(out) }
        }
        to
    }

    /** Course documents: list (with which have notes), write notes, add a file from the phone. */
    suspend fun documents() = JSONObject(get("/api/documents"))
    suspend fun summarizeDocs(paths: List<String>, redo: Boolean = false) =
        JSONObject(post("/api/documents/summarize", JSONObject().put("paths", JSONArray(paths)).put("redo", redo)))
    suspend fun uploadDoc(name: String, bytes: ByteArray) = JSONObject(String(run(
        request("/api/documents/upload?name=" + URLEncoder.encode(name, "UTF-8")).post(bytes.toRequestBody(BINARY)).build())))
}

fun JSONArray.objects(): List<JSONObject> = (0 until length()).map { getJSONObject(it) }
