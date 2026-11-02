package com.manaskhare.sanae

import android.os.Bundle
import android.widget.ScrollView
import android.widget.TextView
import androidx.activity.ComponentActivity

/** What Health Connect shows when you ask why Sanae wants health data. */
class HealthRationaleActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val text = TextView(this).apply {
            setPadding(48, 64, 48, 64)
            textSize = 16f
            text = "${Persona.name(this@HealthRationaleActivity)} reads your sleep, steps and heart rate (read-only) " +
                "so you can ask \u201chow did I sleep?\u201d or \u201cwhat's my heart rate?\u201d and hear last night's " +
                "sleep in the morning briefing.\n\nThe numbers go only to your own laptop (over your Tailscale " +
                "network), are kept there, and can be deleted on the dashboard's Privacy tab. Turn it off any time " +
                "in Sanae \u2192 Settings \u2192 Health."
        }
        setContentView(ScrollView(this).apply { addView(text) })
    }
}
