package com.manaskhare.sanae

import android.content.Context
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.Matrix
import android.media.ExifInterface
import android.net.Uri
import androidx.core.content.FileProvider
import java.io.ByteArrayOutputStream
import java.io.File

/**
 * Photos for Sanae (a shared image or one taken with the camera button).
 *
 * The photo is shrunk and re-encoded here before it leaves the phone: a fresh JPEG carries no EXIF,
 * so no location or camera data is sent. It's kept in memory only; a camera shot's temporary file
 * is deleted as soon as it's read. The laptop never saves it either (sanae/vision.py).
 */
object Photos {
    const val MAX_SIDE = 1280      // the laptop's vision model sees 896 x 896 anyway

    /** A temporary file the camera app writes the shot into (deleted by [read]). */
    fun shotUri(context: Context): Uri {
        val dir = File(context.cacheDir, "photos").apply { mkdirs() }
        dir.listFiles()?.forEach { it.delete() }           // leftovers from a cancelled shot
        val file = File(dir, "shot.jpg")
        return FileProvider.getUriForFile(context, "${context.packageName}.files", file)
    }

    fun clearShots(context: Context) {
        File(context.cacheDir, "photos").listFiles()?.forEach { it.delete() }
    }

    /** The image at [uri] as a small, upright JPEG without metadata, or null if it can't be read. */
    fun read(context: Context, uri: Uri): ByteArray? = try {
        val cr = context.contentResolver
        val bounds = BitmapFactory.Options().apply { inJustDecodeBounds = true }
        cr.openInputStream(uri)?.use { BitmapFactory.decodeStream(it, null, bounds) }
        if (bounds.outWidth <= 0 || bounds.outHeight <= 0) {
            null
        } else {
            val opts = BitmapFactory.Options().apply { inSampleSize = sampleSize(bounds.outWidth, bounds.outHeight, MAX_SIDE) }
            val raw = cr.openInputStream(uri)?.use { BitmapFactory.decodeStream(it, null, opts) }
            val turn = runCatching { cr.openInputStream(uri)?.use { degrees(ExifInterface(it)) } }.getOrNull() ?: 0
            raw?.let { encode(upright(fit(it, MAX_SIDE), turn)) }
        }
    } catch (e: Exception) {
        null
    } finally {
        if (uri.authority == "${context.packageName}.files") clearShots(context)
    }

    private fun degrees(exif: ExifInterface) = when (exif.getAttributeInt(ExifInterface.TAG_ORIENTATION, ExifInterface.ORIENTATION_NORMAL)) {
        ExifInterface.ORIENTATION_ROTATE_90 -> 90
        ExifInterface.ORIENTATION_ROTATE_180 -> 180
        ExifInterface.ORIENTATION_ROTATE_270 -> 270
        else -> 0
    }

    private fun fit(b: Bitmap, max: Int): Bitmap {
        val (w, h) = fitSize(b.width, b.height, max)
        return if (w == b.width && h == b.height) b else Bitmap.createScaledBitmap(b, w, h, true)
    }

    private fun upright(b: Bitmap, degrees: Int): Bitmap =
        if (degrees == 0) b else Bitmap.createBitmap(b, 0, 0, b.width, b.height, Matrix().apply { postRotate(degrees.toFloat()) }, true)

    private fun encode(b: Bitmap): ByteArray = ByteArrayOutputStream().also { b.compress(Bitmap.CompressFormat.JPEG, 85, it) }.toByteArray()

    /** Largest power of two that still leaves the image at least [max] px on its long side. */
    fun sampleSize(w: Int, h: Int, max: Int): Int {
        var n = 1
        while (maxOf(w, h) / (n * 2) >= max) n *= 2
        return n
    }

    /** [w] x [h] scaled down (never up) so the long side is at most [max]. */
    fun fitSize(w: Int, h: Int, max: Int): Pair<Int, Int> {
        val long = maxOf(w, h)
        if (long <= max) return w to h
        val s = max.toDouble() / long
        return maxOf(1, Math.round(w * s).toInt()) to maxOf(1, Math.round(h * s).toInt())
    }

    /** "(Sent a photo) what is this?" from the conversation log, shown as "📷 what is this?". */
    fun label(text: String): String =
        if (text.startsWith(TAG)) ("$CAMERA " + text.removePrefix(TAG).trim()).trim() else text

    /** Said the moment a photo is sent, so the ~15 s while the laptop looks isn't dead air. */
    private val REACTIONS = listOf("Ooh, let me see…", "Ooh, show me!", "Hmm, let me take a look…", "Oh? Let me see…")
    private var lastReaction = -1

    fun reaction(): String {
        var i = REACTIONS.indices.random()
        if (i == lastReaction) i = (i + 1) % REACTIONS.size
        lastReaction = i
        return REACTIONS[i]
    }

    const val TAG = "(Sent a photo)"
    const val CAMERA = "📷"
}
