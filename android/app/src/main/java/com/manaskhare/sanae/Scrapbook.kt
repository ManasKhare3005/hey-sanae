package com.manaskhare.sanae

import android.content.Context
import android.graphics.BitmapFactory
import androidx.compose.ui.graphics.ImageBitmap
import androidx.compose.ui.graphics.asImageBitmap
import kotlinx.coroutines.flow.MutableStateFlow
import org.json.JSONObject
import java.io.File

/** Our scrapbook's photos (scrapbook.py on the laptop), copied into the app's files on sync so the
 *  pages show offline. Photos removed on the laptop are removed here too. */
object Scrapbook {
    /** Bumped when a photo lands, so the pages redraw. */
    val version = MutableStateFlow(0)

    fun file(context: Context, id: Int) = File(File(context.filesDir, "scrapbook").apply { mkdirs() }, "$id.jpg")

    fun ids(us: JSONObject?): List<Int> =
        us?.optJSONObject("scrapbook")?.optJSONArray("months")?.objects().orEmpty()
            .flatMap { m -> m.optJSONArray("photos")?.objects().orEmpty() }.map { it.optInt("id") }

    suspend fun sync(context: Context, api: SanaeApi, us: JSONObject) {
        if (!us.has("scrapbook")) return
        val keep = ids(us).toSet()
        File(context.filesDir, "scrapbook").listFiles()?.forEach { f -> if (f.nameWithoutExtension.toIntOrNull() !in keep) f.delete() }
        var got = false
        for (id in keep) {
            val f = file(context, id)
            if (!f.exists() || f.length() == 0L) {
                runCatching { api.download("/api/scrapbook/$id.jpg", f) }.onSuccess { got = true }.onFailure { f.delete() }
            }
        }
        if (got) version.value++
    }

    /** The photo, scaled down to about `side` pixels, or null if it isn't here yet. */
    fun image(context: Context, id: Int, side: Int = 600): ImageBitmap? {
        val f = file(context, id)
        if (!f.exists() || f.length() == 0L) return null
        val bounds = BitmapFactory.Options().apply { inJustDecodeBounds = true }
        BitmapFactory.decodeFile(f.path, bounds)
        var sample = 1
        while (maxOf(bounds.outWidth, bounds.outHeight) / (sample * 2) >= side) sample *= 2
        return BitmapFactory.decodeFile(f.path, BitmapFactory.Options().apply { inSampleSize = sample })?.asImageBitmap()
    }
}
