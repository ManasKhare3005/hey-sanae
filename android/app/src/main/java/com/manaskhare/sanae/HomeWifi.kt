package com.manaskhare.sanae

import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import android.net.ConnectivityManager
import android.net.LinkProperties
import android.net.Network
import android.net.NetworkCapabilities
import android.net.NetworkRequest
import android.net.wifi.WifiInfo
import android.net.wifi.WifiManager
import android.os.Build
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.launch
import org.json.JSONObject

/**
 * "Reached home" = the phone joined your home Wi-Fi (Settings -> Home Wi-Fi). Only "arrived" /
 * "left" and the time go to the laptop (place.py); the Wi-Fi's name stays on the phone. Android
 * only shows Wi-Fi names to apps with location permission, so the router's fingerprint (gateway,
 * DNS, subnet; no permission needed) is saved too and used when the name is hidden.
 */
object HomeWifi {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    @Volatile private var ssid: String? = null
    @Volatile private var fingerprint: String = ""
    @Volatile private var onWifi = false
    private var callback: ConnectivityManager.NetworkCallback? = null

    fun locationAllowed(context: Context) =
        context.checkSelfPermission(Manifest.permission.ACCESS_FINE_LOCATION) == PackageManager.PERMISSION_GRANTED

    fun fingerprintOf(lp: LinkProperties?): String {
        if (lp == null) return ""
        val gw = lp.routes.filter { it.isDefaultRoute }.mapNotNull { it.gateway?.hostAddress }.sorted()
        val dns = lp.dnsServers.mapNotNull { it.hostAddress }.sorted()
        val net = lp.linkAddresses.filter { it.address is java.net.Inet4Address }.map { "${it.address.hostAddress?.substringBeforeLast('.')}/${it.prefixLength}" }
        return listOf(gw.joinToString(","), dns.joinToString(","), net.joinToString(","), lp.domains ?: "").joinToString("|")
    }

    /** The Wi-Fi the phone is on right now (name if allowed, fingerprint), for "this is my home Wi-Fi". */
    @Suppress("DEPRECATION")
    fun current(context: Context): Pair<String?, String>? {
        val cm = context.getSystemService(ConnectivityManager::class.java)
        val n = cm.activeNetwork ?: return null
        val caps = cm.getNetworkCapabilities(n) ?: return null
        if (!caps.hasTransport(NetworkCapabilities.TRANSPORT_WIFI)) return null
        val name = if (locationAllowed(context)) runCatching {
            context.applicationContext.getSystemService(WifiManager::class.java).connectionInfo?.ssid?.trim('"')
        }.getOrNull()?.takeIf { it.isNotBlank() && it != "<unknown ssid>" } else null
        return name to fingerprintOf(cm.getLinkProperties(n))
    }

    fun saveHome(context: Context): String? {
        val (name, fp) = current(context) ?: return null
        val prefs = Prefs(context)
        prefs.homeSsid = name ?: ""
        prefs.homeFingerprint = fp
        prefs.homeEnabled = true
        prefs.homeState = ""                    // starts fresh: the next check says where you are
        check(context)
        return name ?: "this Wi-Fi"
    }

    fun forget(context: Context) {
        val prefs = Prefs(context)
        prefs.homeEnabled = false
        prefs.homeSsid = ""
        prefs.homeFingerprint = ""
        prefs.homeState = ""
    }

    /** Watches Wi-Fi changes while the service runs. */
    fun start(context: Context) {
        if (callback != null) return
        val app = context.applicationContext
        val cm = app.getSystemService(ConnectivityManager::class.java)
        val cb = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S)
            object : ConnectivityManager.NetworkCallback(FLAG_INCLUDE_LOCATION_INFO) { override fun onCapabilitiesChanged(n: Network, c: NetworkCapabilities) = caps(app, c) ; override fun onLinkPropertiesChanged(n: Network, lp: LinkProperties) = link(app, lp); override fun onLost(n: Network) = lost(app) }
        else
            object : ConnectivityManager.NetworkCallback() { override fun onCapabilitiesChanged(n: Network, c: NetworkCapabilities) = caps(app, c) ; override fun onLinkPropertiesChanged(n: Network, lp: LinkProperties) = link(app, lp); override fun onLost(n: Network) = lost(app) }
        runCatching {
            cm.registerNetworkCallback(NetworkRequest.Builder().addTransportType(NetworkCapabilities.TRANSPORT_WIFI).build(), cb)
            callback = cb
        }
    }

    fun stop(context: Context) {
        callback?.let { cb -> runCatching { context.getSystemService(ConnectivityManager::class.java).unregisterNetworkCallback(cb) } }
        callback = null
    }

    private fun caps(context: Context, c: NetworkCapabilities) {
        onWifi = true
        val info = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) c.transportInfo as? WifiInfo else null
        info?.ssid?.trim('"')?.takeIf { it.isNotBlank() && it != "<unknown ssid>" }?.let { ssid = it }
        check(context)
    }

    private fun link(context: Context, lp: LinkProperties) {
        onWifi = true
        fingerprint = fingerprintOf(lp)
        check(context)
    }

    private fun lost(context: Context) {
        onWifi = false
        ssid = null
        fingerprint = ""
        check(context)
    }

    /** Re-check (callbacks, and the service's 4-minute loop so "left" lands after LEAVE_MS). */
    fun check(context: Context) {
        val prefs = Prefs(context)
        if (!prefs.homeEnabled) return
        if (onWifi && fingerprint.isBlank()) current(context)?.let { (n, fp) -> if (n != null) ssid = n; fingerprint = fp }
        val home = onWifi && isHomeNetwork(ssid, fingerprint, prefs.homeSsid, prefs.homeFingerprint)
        val logic = HomeLogic(prefs.homeState, prefs.homeLeaveSince)
        val ev = logic.update(home, System.currentTimeMillis())
        prefs.homeState = logic.state
        prefs.homeLeaveSince = logic.leaveSince
        if (ev != null) scope.launch {
            Us.change(context, "POST", "/api/phone/place",
                      JSONObject().put("place", "home").put("event", ev.event).put("at_ms", ev.atMs))
        }
    }
}
