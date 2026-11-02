package com.manaskhare.sanae.watch

import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import android.os.Build
import androidx.core.content.ContextCompat
import androidx.health.services.client.HealthServices
import androidx.health.services.client.MeasureCallback
import androidx.health.services.client.data.Availability
import androidx.health.services.client.data.DataPointContainer
import androidx.health.services.client.data.DataType
import androidx.health.services.client.data.DeltaDataType
import androidx.health.services.client.unregisterMeasureCallback
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.withTimeoutOrNull

/** One heart-rate reading from the watch's sensor (Health Services), for "what's my heart rate?". */
object HeartRate {
    /** Android 16 watches use the new health permission; older ones BODY_SENSORS. */
    val PERMISSION: String = if (Build.VERSION.SDK_INT >= 36) "android.permission.health.READ_HEART_RATE" else Manifest.permission.BODY_SENSORS

    fun allowed(context: Context) = ContextCompat.checkSelfPermission(context, PERMISSION) == PackageManager.PERMISSION_GRANTED

    /** Waits for the first steady reading (up to `timeoutMs`); null if none came. */
    suspend fun measure(context: Context, timeoutMs: Long = 25_000): Int? {
        val client = HealthServices.getClient(context).measureClient
        val got = CompletableDeferred<Int>()
        val callback = object : MeasureCallback {
            override fun onAvailabilityChanged(dataType: DeltaDataType<*, *>, availability: Availability) {}
            override fun onDataReceived(data: DataPointContainer) {
                val bpm = data.getData(DataType.HEART_RATE_BPM).lastOrNull()?.value ?: return
                if (bpm >= 30) got.complete(bpm.toInt())
            }
        }
        client.registerMeasureCallback(DataType.HEART_RATE_BPM, callback)
        return try {
            withTimeoutOrNull(timeoutMs) { got.await() }
        } finally {
            runCatching { client.unregisterMeasureCallback(DataType.HEART_RATE_BPM, callback) }
        }
    }
}
