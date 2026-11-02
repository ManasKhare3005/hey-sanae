package com.manaskhare.sanae

import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import androidx.core.app.NotificationCompat
import kotlinx.coroutines.flow.MutableStateFlow
import org.json.JSONArray
import org.json.JSONObject

/**
 * The "Us" tab's data: the daily list you do together, the exchange diary, promises, her voice
 * notes and the week in review. The laptop keeps them (GET /api/us); the phone keeps the last copy
 * so the tab works offline, and changes made offline wait in an outbox that Sync replays.
 */
object Us {
    val state = MutableStateFlow<JSONObject?>(null)

    fun load(context: Context): JSONObject? {
        if (state.value == null) {
            state.value = Prefs(context).usJson.takeIf { it.isNotBlank() }?.let { runCatching { JSONObject(it) }.getOrNull() }
        }
        return state.value
    }

    private fun save(context: Context, us: JSONObject) {
        state.value = us
        Prefs(context).usJson = us.toString()
    }

    /** Fresh copy from the laptop; false if it can't be reached. */
    suspend fun refresh(context: Context): Boolean {
        val api = SanaeApi.from(Prefs(context)) ?: return false
        flush(context, api)
        val us = runCatching { api.us() }.getOrNull() ?: return false
        save(context, us)
        runCatching { notifyNew(context, us) }
        runCatching { VoiceNotes.sync(context, api, us) }
        runCatching { Scrapbook.sync(context, api, us) }
        runCatching { notifyWeek(context, us) }
        return true
    }

    /** Her new notebook page / a letter from past you: one notification each, even if it came
     *  while the phone was offline (seen ids are remembered). */
    private fun notifyNew(context: Context, us: JSONObject) {
        val prefs = Prefs(context)
        val pages = us.optJSONObject("journal")?.optJSONArray("pages")?.objects().orEmpty()
        val newest = pages.filter { it.optString("author") == "her" || it.optString("kind") == "letter" }.maxOfOrNull { it.optInt("id") } ?: 0
        val seen = prefs.notebookSeen
        prefs.notebookSeen = maxOf(seen, newest)
        if (seen < 0 || newest <= seen) return                  // first sync (-1): don't announce old pages
        val fresh = pages.filter { it.optInt("id") in (seen + 1)..newest }
        val letter = fresh.firstOrNull { it.optString("kind") == "letter" }
        val name = Persona.name(context)
        val (title, text) = if (letter != null) "A letter from past you" to "You wrote this on ${letter.optString("created").take(10)}. $name kept it safe."
                            else "$name wrote in your notebook" to (fresh.firstOrNull { it.optString("author") == "her" }?.optString("text")?.take(140) ?: "")
        val open = PendingIntent.getActivity(context, 3,
            Intent(context, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP).putExtra(MainActivity.EXTRA_TAB, MainActivity.TAB_US).putExtra(MainActivity.EXTRA_PAGE, "journal"),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
        context.getSystemService(NotificationManager::class.java).notify(7100, NotificationCompat.Builder(context, SanaeApp.CH_CHAT)
            .setSmallIcon(R.drawable.ic_stat_sanae)
            .setContentTitle(title)
            .setContentText(text)
            .setStyle(NotificationCompat.BigTextStyle().bigText(text))
            .setAutoCancel(true)
            .setContentIntent(open)
            .build())
    }

    /** A change: sent now if the laptop answers (its reply, a section, replaces ours), else queued.
     *  `local` edits the cached copy right away so the tab shows it either way. */
    suspend fun change(context: Context, method: String, path: String, body: JSONObject = JSONObject(),
                       section: String? = null, local: (JSONObject) -> Unit = {}): Boolean {
        val cached = load(context) ?: JSONObject()
        runCatching { local(cached) }
        save(context, JSONObject(cached.toString()))
        val api = SanaeApi.from(Prefs(context))
        val res = if (api != null) runCatching { api.raw(method, path, body) } else Result.failure(Exception("not paired"))
        res.onSuccess { text ->
            if (section != null) runCatching { JSONObject(text) }.getOrNull()?.let { fresh ->
                save(context, JSONObject(cached.toString()).put(section, fresh))
            }
            return true
        }
        val err = res.exceptionOrNull()
        if (err is ApiError && err.code in 400..499) return false      // refused (bad input): don't retry it
        queue(context, method, path, body)
        return false
    }

    private fun queue(context: Context, method: String, path: String, body: JSONObject) {
        val prefs = Prefs(context)
        val box = runCatching { JSONArray(prefs.usOutbox) }.getOrElse { JSONArray() }
        box.put(JSONObject().put("method", method).put("path", path).put("body", body))
        prefs.usOutbox = box.toString()
    }

    /** Replays changes made offline, oldest first; stops at the first one the laptop can't take yet. */
    suspend fun flush(context: Context, api: SanaeApi) {
        val prefs = Prefs(context)
        val box = runCatching { JSONArray(prefs.usOutbox) }.getOrElse { JSONArray() }
        if (box.length() == 0) return
        var sent = 0
        for (o in box.objects()) {
            val r = runCatching { api.raw(o.optString("method"), o.optString("path"), o.optJSONObject("body") ?: JSONObject()) }
            val e = r.exceptionOrNull()
            if (e != null && !(e is ApiError && e.code in 400..499)) break      // offline again: keep the rest
            sent++
        }
        val rest = JSONArray()
        box.objects().drop(sent).forEach { rest.put(it) }
        prefs.usOutbox = rest.toString()
    }

    // ----- the daily list together -----
    fun together(context: Context): JSONObject? = load(context)?.optJSONObject("together")

    private fun activities(us: JSONObject): List<JSONObject> =
        us.optJSONObject("together")?.optJSONArray("activities")?.objects().orEmpty()

    suspend fun tick(context: Context, id: Int, done: Boolean, how: String = "tap") =
        change(context, "POST", "/api/together/$id/day",
               JSONObject().put("day", java.time.LocalDate.now().toString()).put("done", done).put("how", how),
               "together") { us ->
            activities(us).firstOrNull { it.optInt("id") == id }?.let { a ->
                val was = !a.isNull("how")
                a.put("how", if (done) how else JSONObject.NULL)
                if (done && !was) a.put("streak", a.optInt("streak") + 1)
                if (!done && was) a.put("streak", maxOf(0, a.optInt("streak") - 1))
            }
            if (how == "pass") us.optJSONObject("together")?.put("pass_free", false)
        }

    suspend fun addActivity(context: Context, a: JSONObject) =
        change(context, "POST", "/api/together", a, "together") { us ->
            val list = us.optJSONObject("together")?.optJSONArray("activities") ?: return@change
            list.put(JSONObject(a.toString()).put("id", -1).put("streak", 0).put("due", true).put("how", JSONObject.NULL)
                .put("days_words", a.optString("days")))
        }

    suspend fun editActivity(context: Context, id: Int, change: JSONObject) =
        change(context, "PUT", "/api/together/$id", change, "together") { us ->
            activities(us).firstOrNull { it.optInt("id") == id }?.let { a -> change.keys().forEach { k -> a.put(k, change.get(k)) } }
        }

    suspend fun removeActivity(context: Context, id: Int) =
        change(context, "DELETE", "/api/together/$id", JSONObject(), "together") { us ->
            val list = us.optJSONObject("together")?.optJSONArray("activities") ?: return@change
            val keep = JSONArray()
            list.objects().filter { it.optInt("id") != id }.forEach { keep.put(it) }
            us.optJSONObject("together")?.put("activities", keep)
        }

    /** "Start" with her: she does her own thing alongside and checks in when the time's up. */
    suspend fun start(context: Context, id: Int, minutes: Int): JSONObject? {
        val api = SanaeApi.from(Prefs(context)) ?: return null
        val text = runCatching { api.raw("POST", "/api/together/$id/start", JSONObject().put("minutes", minutes)) }.getOrNull() ?: return null
        val res = runCatching { JSONObject(text) }.getOrNull() ?: return null
        val us = load(context) ?: JSONObject()
        res.remove("started")
        save(context, JSONObject(us.toString()).put("together", res))
        return res
    }

    /** A new week in review: one notification. */
    private fun notifyWeek(context: Context, us: JSONObject) {
        val weekly = us.optJSONObject("weekly") ?: return
        val week = weekly.optJSONArray("weeks")?.objects()?.firstOrNull()?.optString("week") ?: ""
        val prefs = Prefs(context)
        val seen = prefs.weekSeen
        if (week > seen || seen == "?") prefs.weekSeen = week
        if (seen == "?" || week.isBlank() || week <= seen) return          // first sync: nothing to announce
        val open = PendingIntent.getActivity(context, 4,
            Intent(context, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP).putExtra(MainActivity.EXTRA_TAB, MainActivity.TAB_US).putExtra(MainActivity.EXTRA_PAGE, "weekly"),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
        context.getSystemService(NotificationManager::class.java).notify(7400, NotificationCompat.Builder(context, SanaeApp.CH_CHAT)
            .setSmallIcon(R.drawable.ic_stat_sanae)
            .setContentTitle("Your week, by ${Persona.name(context)}")
            .setContentText("She made you a little recap. Tap to watch.")
            .setAutoCancel(true)
            .setContentIntent(open)
            .build())
    }

    // ----- the exchange diary -----
    suspend fun writePage(context: Context, text: String, mood: String, private: Boolean, letterMonths: Int = 0) =
        change(context, "POST", "/api/journal",
               JSONObject().put("text", text).put("mood", mood).put("private", private).put("letter_months", letterMonths),
               "journal") { us ->
            val j = us.optJSONObject("journal") ?: JSONObject().put("pages", JSONArray()).put("sealed", JSONArray()).also { us.put("journal", it) }
            val now = java.time.LocalDateTime.now().withNano(0).toString()
            if (letterMonths > 0) {
                j.optJSONArray("sealed")?.put(JSONObject().put("id", -1).put("created", now)
                    .put("deliver_on", java.time.LocalDate.now().plusMonths(letterMonths.toLong()).toString()))
            } else {
                val pages = JSONArray().put(JSONObject().put("id", -1).put("author", "you").put("kind", "page").put("text", text)
                    .put("mood", mood).put("private", if (private) 1 else 0).put("created", now))
                j.optJSONArray("pages")?.objects()?.forEach { pages.put(it) }
                j.put("pages", pages)
            }
        }

    /** A page said out loud: needs the laptop (it transcribes). The fresh notebook, or an error message. */
    suspend fun voicePage(context: Context, wav: ByteArray, mood: String, private: Boolean): String? {
        val api = SanaeApi.from(Prefs(context)) ?: return "Pair with your laptop first."
        return runCatching { api.voicePage(wav, mood, private) }.fold(
            onSuccess = { j -> save(context, JSONObject((load(context) ?: JSONObject()).toString()).put("journal", j)); null },
            onFailure = { e -> if (e is ApiError) e.message else "Can't reach the laptop: spoken pages need it to write them down." })
    }

    suspend fun setPrivate(context: Context, id: Int, private: Boolean) =
        change(context, "PUT", "/api/journal/$id", JSONObject().put("private", private), "journal") { us ->
            us.optJSONObject("journal")?.optJSONArray("pages")?.objects()?.firstOrNull { it.optInt("id") == id }
                ?.put("private", if (private) 1 else 0)
        }

    suspend fun deletePage(context: Context, id: Int) =
        change(context, "DELETE", "/api/journal/$id", JSONObject(), "journal") { us ->
            val j = us.optJSONObject("journal") ?: return@change
            val keep = JSONArray()
            j.optJSONArray("pages")?.objects()?.filter { it.optInt("id") != id && it.optInt("reply_to") != id }?.forEach { keep.put(it) }
            j.put("pages", keep)
        }

    // ----- cooking together: Back / Next / Stop (needs the laptop, it keeps the recipe) -----
    suspend fun cooking(context: Context, action: String): Boolean {
        val api = SanaeApi.from(Prefs(context)) ?: return false
        val text = runCatching { api.raw("POST", "/api/cooking/$action", JSONObject()) }.getOrNull() ?: return false
        val res = runCatching { JSONObject(text) }.getOrNull() ?: return false
        res.remove("said")
        save(context, JSONObject((load(context) ?: JSONObject()).toString()).put("cooking", res))
        return true
    }

    // ----- the week's dinners (planning and swapping need the laptop: it writes the ideas) -----
    private suspend fun meals(context: Context, path: String): Boolean {
        val api = SanaeApi.from(Prefs(context)) ?: return false
        val body = if (path.endsWith("/plan")) JSONObject().put("count", 5) else JSONObject()
        val text = runCatching { api.raw("POST", path, body) }.getOrNull() ?: return false
        val res = runCatching { JSONObject(text) }.getOrNull() ?: return false
        save(context, JSONObject((load(context) ?: JSONObject()).toString()).put("meals", res))
        return true
    }

    suspend fun planMeals(context: Context, count: Int) = meals(context, "/api/meals/plan")
    suspend fun swapMeal(context: Context, id: Int) = meals(context, "/api/meals/$id/swap")

    /** What the plan still needs -> the grocery list (refreshes both). */
    suspend fun mealGroceries(context: Context): Boolean {
        val ok = change(context, "POST", "/api/meals/groceries", JSONObject(), "meals") { us -> us.optJSONObject("meals")?.put("missing", JSONArray()) }
        if (ok) refresh(context)
        return ok
    }

    // ----- photo a day: swap today's challenge or skip it (the laptop picks, so it needs the laptop) -----
    suspend fun dailyPhoto(context: Context, action: String): Boolean {
        val api = SanaeApi.from(Prefs(context)) ?: return false
        val text = runCatching { api.raw("POST", "/api/dailyphoto/$action", JSONObject()) }.getOrNull() ?: return false
        val res = runCatching { JSONObject(text) }.getOrNull() ?: return false
        save(context, JSONObject((load(context) ?: JSONObject()).toString()).put("dailyphoto", res))
        return true
    }

    // ----- the watchlist -----
    suspend fun addWatch(context: Context, title: String) =
        change(context, "POST", "/api/watchlist", JSONObject().put("text", title), "watching") { us ->
            val w = us.optJSONObject("watching") ?: JSONObject().also { us.put("watching", it) }
            val list = w.optJSONArray("watchlist") ?: JSONArray().also { w.put("watchlist", it) }
            list.put(JSONObject().put("id", -1).put("title", title).put("kind", "movie"))
        }

    suspend fun removeWatch(context: Context, id: Int) =
        change(context, "DELETE", "/api/watchlist/$id", JSONObject(), "watching") { us ->
            val w = us.optJSONObject("watching") ?: return@change
            val keep = JSONArray()
            w.optJSONArray("watchlist")?.objects()?.filter { it.optInt("id") != id }?.forEach { keep.put(it) }
            w.put("watchlist", keep)
        }

    private fun movies(us: JSONObject): JSONArray? = us.optJSONObject("watching")?.optJSONArray("log")

    suspend fun rateMovie(context: Context, id: Int, stars: Int) =
        change(context, "POST", "/api/movies/$id/stars", JSONObject().put("stars", stars), "watching") { us ->
            movies(us)?.objects()?.firstOrNull { it.optInt("id") == id }?.put("stars", stars)
        }

    suspend fun removeMovie(context: Context, id: Int) =
        change(context, "DELETE", "/api/movies/$id", JSONObject(), "watching") { us ->
            val keep = JSONArray()
            movies(us)?.objects()?.filter { it.optInt("id") != id }?.forEach { keep.put(it) }
            us.optJSONObject("watching")?.put("log", keep)
        }

    // ----- our playlist -----
    suspend fun removeSong(context: Context, id: Int) =
        change(context, "DELETE", "/api/playlist/$id", JSONObject(), "playlist") { us ->
            val p = us.optJSONObject("playlist") ?: return@change
            val keep = JSONArray()
            p.optJSONArray("songs")?.objects()?.filter { it.optInt("id") != id }?.forEach { keep.put(it) }
            p.put("songs", keep)
        }

    // ----- the recipe box -----
    private fun recipes(us: JSONObject): JSONArray? = us.optJSONObject("cooking")?.optJSONArray("recipes")

    suspend fun rateRecipe(context: Context, id: Int, stars: Int) =
        change(context, "POST", "/api/recipes/$id/stars", JSONObject().put("stars", stars), "cooking") { us ->
            recipes(us)?.objects()?.firstOrNull { it.optInt("id") == id }?.put("stars", stars)
        }

    suspend fun removeRecipe(context: Context, id: Int) =
        change(context, "DELETE", "/api/recipes/$id", JSONObject(), "cooking") { us ->
            val keep = JSONArray()
            recipes(us)?.objects()?.filter { it.optInt("id") != id }?.forEach { keep.put(it) }
            us.optJSONObject("cooking")?.put("recipes", keep)
        }

    /** Starts the walkthrough on the laptop (it keeps the recipe), so it needs the laptop now. */
    suspend fun cookRecipe(context: Context, id: Int): Boolean {
        val api = SanaeApi.from(Prefs(context)) ?: return false
        val text = runCatching { api.raw("POST", "/api/recipes/$id/cook", JSONObject()) }.getOrNull() ?: return false
        val res = runCatching { JSONObject(text) }.getOrNull() ?: return false
        save(context, JSONObject((load(context) ?: JSONObject()).toString()).put("cooking", res))
        return true
    }

    // ----- Japanese flashcards (graded here, sent when the laptop answers) -----
    suspend fun reviewJapanese(context: Context, results: List<Pair<String, Boolean>>) {
        val day = java.time.LocalDate.now().toString()
        val arr = JSONArray()
        results.forEach { (w, ok) -> arr.put(JSONObject().put("word", w).put("right", ok).put("day", day)) }
        change(context, "POST", "/api/japanese/review", JSONObject().put("results", arr), "japanese") { us ->
            val j = us.optJSONObject("japanese") ?: return@change
            val seen = results.toMap()
            j.optJSONArray("deck")?.objects()?.forEach { c -> seen[c.optString("word")]?.let { ok -> c.put("due", !ok) } }
            j.put("due", j.optJSONArray("deck")?.objects()?.count { it.optBoolean("due") } ?: 0)
        }
    }

    // ----- the scrapbook -----
    suspend fun deletePhoto(context: Context, id: Int) =
        change(context, "DELETE", "/api/scrapbook/$id", JSONObject(), "scrapbook") { us ->
            us.optJSONObject("scrapbook")?.optJSONArray("months")?.objects()?.forEach { m ->
                val keep = JSONArray()
                m.optJSONArray("photos")?.objects()?.filter { it.optInt("id") != id }?.forEach { keep.put(it) }
                m.put("photos", keep)
            }
            Scrapbook.file(context, id).delete()
        }

    // ----- the bucket list -----
    private fun bucketItems(us: JSONObject): JSONArray? = us.optJSONObject("bucket")?.optJSONArray("items")

    suspend fun addBucket(context: Context, text: String) =
        change(context, "POST", "/api/bucket", JSONObject().put("text", text), "bucket") { us ->
            val b = us.optJSONObject("bucket") ?: JSONObject().put("items", JSONArray()).also { us.put("bucket", it) }
            b.optJSONArray("items")?.put(JSONObject().put("id", -1).put("text", text).put("who", "you").put("done_day", JSONObject.NULL))
        }

    suspend fun bucketDone(context: Context, id: Int, done: Boolean) =
        change(context, "POST", "/api/bucket/$id", JSONObject().put("done", done), "bucket") { us ->
            bucketItems(us)?.objects()?.firstOrNull { it.optInt("id") == id }
                ?.put("done_day", if (done) java.time.LocalDate.now().toString() else JSONObject.NULL)
        }

    suspend fun removeBucket(context: Context, id: Int) =
        change(context, "DELETE", "/api/bucket/$id", JSONObject(), "bucket") { us ->
            val keep = JSONArray()
            bucketItems(us)?.objects()?.filter { it.optInt("id") != id }?.forEach { keep.put(it) }
            us.optJSONObject("bucket")?.put("items", keep)
        }

    // ----- the grocery list -----
    private fun groceryItems(us: JSONObject): JSONArray? = us.optJSONObject("groceries")?.optJSONArray("items")

    /** "milk, 2 eggs": shown right away (in "Other" until the laptop sorts it into its aisle). */
    suspend fun addGroceries(context: Context, text: String) =
        change(context, "POST", "/api/groceries", JSONObject().put("text", text), "groceries") { us ->
            val g = us.optJSONObject("groceries") ?: JSONObject().put("items", JSONArray()).also { us.put("groceries", it) }
            text.split(",").map { it.trim() }.filter { it.isNotEmpty() }.forEach { item ->
                g.optJSONArray("items")?.put(JSONObject().put("id", -1).put("item", item).put("qty", "")
                    .put("section", "Other").put("done", false).put("who", "you"))
            }
            val ideas = JSONArray()
            g.optJSONArray("ideas")?.objects()?.filter { i -> text.split(",").none { it.trim().equals(i.str("item"), true) } }
                ?.forEach { ideas.put(it) }
            g.put("ideas", ideas)
        }

    suspend fun groceryDone(context: Context, id: Int, done: Boolean) =
        change(context, "POST", "/api/groceries/$id", JSONObject().put("done", done), "groceries") { us ->
            groceryItems(us)?.objects()?.firstOrNull { it.optInt("id") == id }?.put("done", done)
        }

    suspend fun removeGrocery(context: Context, id: Int) =
        change(context, "DELETE", "/api/groceries/$id", JSONObject(), "groceries") { us ->
            val keep = JSONArray()
            groceryItems(us)?.objects()?.filter { it.optInt("id") != id }?.forEach { keep.put(it) }
            us.optJSONObject("groceries")?.put("items", keep)
        }

    /** which: "done" (what's in the cart) or "all". */
    suspend fun clearGroceries(context: Context, which: String) =
        change(context, "POST", "/api/groceries/clear", JSONObject().put("which", which), "groceries") { us ->
            val keep = JSONArray()
            if (which != "all") groceryItems(us)?.objects()?.filter { !it.optBoolean("done") }?.forEach { keep.put(it) }
            us.optJSONObject("groceries")?.put("items", keep)
        }

    /** Fresh food that's used up (or still fine): she stops saying it's going off. */
    suspend fun groceryUsed(context: Context, item: String) =
        change(context, "POST", "/api/groceries/used", JSONObject().put("text", item), "groceries") { us ->
            val g = us.optJSONObject("groceries") ?: return@change
            val keep = JSONArray()
            g.optJSONArray("going_off")?.objects()?.filter { it.str("item") != item }?.forEach { keep.put(it) }
            g.put("going_off", keep)
        }

    /** One of her ideas isn't needed (it stays away for two weeks). */
    suspend fun skipGroceryIdea(context: Context, item: String) =
        change(context, "POST", "/api/groceries/skip", JSONObject().put("text", item), "groceries") { us ->
            val g = us.optJSONObject("groceries") ?: return@change
            val ideas = JSONArray()
            g.optJSONArray("ideas")?.objects()?.filter { it.str("item") != item }?.forEach { ideas.put(it) }
            g.put("ideas", ideas)
        }

    // ----- weekend plans -----
    private fun plans(us: JSONObject): JSONArray? = us.optJSONObject("weekend")?.optJSONArray("plans")

    suspend fun addPlan(context: Context, text: String, day: String, at: String) =
        change(context, "POST", "/api/weekend", JSONObject().put("text", text).put("day", day).put("at", at), "weekend") { us ->
            val w = us.optJSONObject("weekend") ?: JSONObject().put("plans", JSONArray()).also { us.put("weekend", it) }
            w.optJSONArray("plans")?.put(JSONObject().put("id", -1).put("text", text).put("day", day).put("at", at).put("done", false))
        }

    suspend fun planDone(context: Context, id: Int, done: Boolean) =
        change(context, "POST", "/api/weekend/$id", JSONObject().put("done", done), "weekend") { us ->
            plans(us)?.objects()?.firstOrNull { it.optInt("id") == id }?.put("done", done)
        }

    suspend fun removePlan(context: Context, id: Int) =
        change(context, "DELETE", "/api/weekend/$id", JSONObject(), "weekend") { us ->
            val keep = JSONArray()
            plans(us)?.objects()?.filter { it.optInt("id") != id }?.forEach { keep.put(it) }
            us.optJSONObject("weekend")?.put("plans", keep)
        }

    // ----- pinky promises -----
    suspend fun makePromise(context: Context, who: String, text: String, whenWords: String) =
        change(context, "POST", "/api/promises", JSONObject().put("who", who).put("text", text).put("when", whenWords), "promises") { us ->
            val p = us.optJSONObject("promises") ?: JSONObject().put("open", JSONArray()).also { us.put("promises", it) }
            p.optJSONArray("open")?.put(JSONObject().put("id", -1).put("who", who).put("text", text).put("due", "").put("status", "open"))
        }

    suspend fun settlePromise(context: Context, id: Int, status: String) =
        change(context, "POST", "/api/promises/$id", JSONObject().put("status", status), "promises") { us ->
            val p = us.optJSONObject("promises") ?: return@change
            val keep = JSONArray()
            p.optJSONArray("open")?.objects()?.filter { it.optInt("id") != id }?.forEach { keep.put(it) }
            p.put("open", keep)
        }
}
