package com.manaskhare.sanae.watch

import android.annotation.SuppressLint
import android.content.Context
import android.media.AudioAttributes
import android.media.AudioFormat
import android.media.AudioRecord
import android.media.MediaPlayer
import android.media.MediaRecorder
import java.io.ByteArrayOutputStream
import java.io.File
import java.nio.ByteBuffer
import java.nio.ByteOrder
import kotlin.math.sqrt

/** Watch mic: 16 kHz mono PCM16 (what Whisper wants), stops by itself when you stop talking. */
class Recorder(private val onAutoStop: () -> Unit) {
    @Volatile var level = 0f
        private set
    @Volatile private var running = false
    private var record: AudioRecord? = null
    private var thread: Thread? = null
    private val pcm = ByteArrayOutputStream()
    private var spoke = false

    @SuppressLint("MissingPermission")  // the screen asks for RECORD_AUDIO first
    fun start() {
        val min = AudioRecord.getMinBufferSize(RATE, AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT)
        val rec = AudioRecord(MediaRecorder.AudioSource.MIC, RATE, AudioFormat.CHANNEL_IN_MONO,
                              AudioFormat.ENCODING_PCM_16BIT, maxOf(min, RATE / 2))
        record = rec
        rec.startRecording()
        running = true
        val end = Endpoint()
        thread = Thread {
            val buf = ByteArray(RATE / 10 * 2)          // 100 ms
            while (running) {
                val n = rec.read(buf, 0, buf.size)
                if (n <= 0) continue
                synchronized(pcm) { pcm.write(buf, 0, n) }
                val r = rms(buf, n)
                level = (r / 3000.0).coerceIn(0.0, 1.0).toFloat()
                if (end.feed(r)) {
                    spoke = end.spoke
                    running = false
                    onAutoStop()
                }
            }
            spoke = end.spoke
        }.apply { start() }
    }

    /** Stops; a WAV, or empty if nothing was said. */
    fun stop(): ByteArray {
        running = false
        thread?.join(600)
        record?.runCatching { stop(); release() }
        record = null
        level = 0f
        val data = synchronized(pcm) { pcm.toByteArray() }
        return if (!spoke || data.size < RATE / 5) ByteArray(0) else wav(data)
    }

    private fun rms(b: ByteArray, n: Int): Double {
        val s = ByteBuffer.wrap(b, 0, n).order(ByteOrder.LITTLE_ENDIAN).asShortBuffer()
        var sum = 0.0
        val count = s.remaining()
        while (s.hasRemaining()) { val v = s.get().toDouble(); sum += v * v }
        return if (count == 0) 0.0 else sqrt(sum / count)
    }

    companion object {
        const val RATE = 16_000

        fun wav(pcm: ByteArray, rate: Int = RATE): ByteArray {
            val header = ByteBuffer.allocate(44).order(ByteOrder.LITTLE_ENDIAN).apply {
                put("RIFF".toByteArray()); putInt(36 + pcm.size); put("WAVE".toByteArray())
                put("fmt ".toByteArray()); putInt(16); putShort(1); putShort(1)
                putInt(rate); putInt(rate * 2); putShort(2); putShort(16)
                put("data".toByteArray()); putInt(pcm.size)
            }
            return header.array() + pcm
        }
    }
}

/** Her voice through the watch speaker (or earbuds if connected). */
class Player(private val context: Context) {
    private var player: MediaPlayer? = null
    val playing get() = player != null

    fun play(wav: ByteArray, onDone: () -> Unit) {
        stop()
        val file = File(context.cacheDir, "reply.wav").apply { writeBytes(wav) }
        player = runCatching {
            MediaPlayer().apply {
                setAudioAttributes(AudioAttributes.Builder()
                    .setUsage(AudioAttributes.USAGE_ASSISTANT)
                    .setContentType(AudioAttributes.CONTENT_TYPE_SPEECH).build())
                setDataSource(file.path)
                setOnCompletionListener { stop(); onDone() }
                setOnErrorListener { _, _, _ -> stop(); onDone(); true }
                prepare()
                start()
            }
        }.getOrElse { onDone(); null }
    }

    fun stop() {
        player?.runCatching { stop(); release() }
        player = null
    }
}
