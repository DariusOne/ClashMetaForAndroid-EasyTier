package com.github.kr328.clash.service.easytier

import android.net.ConnectivityManager
import android.net.NetworkCapabilities
import android.net.VpnService
import android.os.ParcelFileDescriptor
import android.system.Os
import android.system.OsConstants
import com.github.kr328.clash.common.log.Log
import com.github.kr328.clash.core.easytier.NativePacketRouter
import com.github.kr328.clash.service.BuildConfig
import com.github.kr328.clash.service.clash.module.TunModule
import java.io.File
import java.io.FileDescriptor
import java.net.InetAddress
import java.security.SecureRandom
import java.util.UUID
import kotlinx.coroutines.*
import org.json.JSONArray
import org.json.JSONObject

/** Packet-path acceptance harness, excluded from normal builds. This is NOT the
 * final profile UI, DNS/HTTP/SOCKS integration or a production combined mode.
 * A private opt-in file and an explicitly built prototype APK are both required.
 */
class PacketHarness private constructor(private val vpn: VpnService, private val scope: CoroutineScope) {
    data class Address(val ip: String, val bits: Int) {
        val cidr: String get() = "$ip/$bits"
        fun network(): String {
            val bytes = InetAddress.getByName(ip).address
            for (i in bytes.indices) {
                val remaining = (bits - i * 8).coerceIn(0, 8)
                bytes[i] = (bytes[i].toInt() and (0xff shl (8 - remaining))).toByte()
            }
            return "${InetAddress.getByAddress(bytes).hostAddress}/$bits"
        }
    }
    private val generation = (SecureRandom().nextLong() and Long.MAX_VALUE).coerceAtLeast(1)
    private var native: NativeMeshClient? = null
    private var monitor: Job? = null
    @Volatile private var failed = false
    private var installed = emptyList<Address>()
    private var networkKey = ""
    private var initialRoutes = emptySet<String>()
    private val directory get() = File(vpn.noBackupFilesDir, "native-mesh-acceptance")

    // Private, fixed-code diagnostics for the opt-in harness. No config,
    // endpoint, network secret or native exception is written here.
    @Synchronized private fun status(stage: String) {
        if (stage == "active" && failed) return
        runCatching {
            val temp = File(directory, "status.tmp")
            temp.writeText(JSONObject().put("schema", 1).put("generation", generation).put("stage", stage).toString())
            Os.chmod(temp.path, 384)
            check(temp.renameTo(File(directory, "status.json")))
        }
    }

    private fun failClosed(code: String) {
        NativePacketRouter.failClosed(generation)
        if (failed) return
        failed = true
        status(code)
        Log.w(code) // fixed code only, never a TOML/parser/endpoint error
        scope.launch(Dispatchers.IO) { native?.close() }
    }

    suspend fun open(tun: TunModule, allowRouteGrowth: Boolean, createVpn: (List<Address>, Set<String>) -> TunModule.TunDevice) {
        status("starting")
        val profile = File(directory, "mesh.toml")
        check(profile.isFile && profile.length() in 1..1024L * 1024) { "ET_PROFILE_REQUIRED" }
        val phone = File(directory, "phone-id")
        val phoneId = if (phone.isFile) UUID.fromString(phone.readText().trim()).toString() else {
            UUID.randomUUID().toString().also { phone.writeText(it); Os.chmod(phone.path, 384) }
        }
        // Bootstrap owns the VPN and excludes this UID BEFORE any native socket
        // is created. It is kept closed to application traffic while DHCP runs.
        val bootstrap = ParcelFileDescriptor.adoptFd(createVpn(emptyList(), emptySet()).fd)
        try {
            native = NativeMeshClient.bind(vpn) { failClosed("ET_ENGINE_LOST") }
            native!!.start(profile, phoneId, generation, ownUidExcluded = true)
            val first = withTimeout(30_000) {
                var state: JSONObject
                while (true) {
                    state = JSONObject(native!!.snapshot())
                    val addresses = readAddresses(state)
                    if (state.optBoolean("running") && addresses.isNotEmpty()) break
                    delay(250)
                }
                state
            }
            installed = readAddresses(first)
            initialRoutes = readRoutes(first) + installed.map { it.network() }
            val physical = physicalNetwork()
            networkKey = physical.first
            val device = createVpn(installed, initialRoutes)
            val deviceFd = ParcelFileDescriptor.adoptFd(device.fd)
            val pair = packetPair()
            try {
                native!!.attach(pair.second)
                val configuration = JSONObject().apply {
                    put("policy", JSONObject().apply {
                        put("Mode", 2); put("Session", generation)
                        put("Profile", "acceptance-profile"); put("Network", networkKey)
                        put("LocalNetworks", JSONArray(physical.second))
                        put("VirtualNetworks", JSONArray(installed.map { it.network() }))
                        put("DeviceAddresses", JSONArray(installed.map { it.ip }))
                        put("Reserved", JSONArray(listOf("172.19.0.0/30", "fdfe:dcba:9876::/126", "28.0.0.0/8")))
                        put("Broadcast", true)
                        put("Multicast", JSONArray(listOf("224.0.0.251", "239.255.255.250", "ff02::fb", "ff02::c")))
                    })
                    put("gateway", JSONArray(device.gateway.split(",")))
                    put("dns", JSONArray(device.dns.split(",").map { if (it.contains(":")) "[$it]:53" else "$it:53" }))
                    put("mtu", 1380)
                }
                // start adopts each detached FD, including on error.
                tun.attachPacket(deviceFd.detachFd(), pair.first.detachFd(), configuration.toString())
                check(!failed) { "ET_ENGINE_LOST" }
                val attached = native!!.snapshot()
                check(JSONObject(attached).let { it.getBoolean("running") && it.getBoolean("attached") }) { "ET_ENGINE_NOT_READY" }
                check(NativePacketRouter.update(attached, installed.joinToString(",") { it.cidr }))
                status("active")
            } finally { deviceFd.close(); pair.first.close(); pair.second.close() }
            monitor = scope.launch(Dispatchers.IO) {
                while (isActive && !failed) {
                    try {
                        val raw = native!!.snapshot()
                        val next = JSONObject(raw)
                        if (!next.getBoolean("running") || !next.getBoolean("attached")) {
                            failClosed("ET_ENGINE_NOT_READY")
                            break
                        }
                        // The harness closes on changes needing a new Android
                        // interface. Production transactional rebuild is gated.
                        if (readAddresses(next) != installed || (!allowRouteGrowth && readRoutes(next).any { !covered(it) }) || physicalNetwork().first != networkKey) {
                            failClosed("ET_INTERFACE_REBUILD_REQUIRED")
                            break
                        }
                        check(NativePacketRouter.update(raw, installed.joinToString(",") { it.cidr }))
                    } catch (e: CancellationException) { throw e }
                    catch (_: Exception) { failClosed("ET_STATUS_FAILED"); break }
                    delay(1_000)
                }
            }
        } catch (e: Throwable) {
            failClosed("ET_HARNESS_START_FAILED")
            withContext(NonCancellable + Dispatchers.IO) { native?.close(); native = null }
            throw IllegalStateException("ET_HARNESS_START_FAILED")
        } finally { bootstrap.close() }
    }

    private fun covered(route: String): Boolean {
        val child = parseAddress(route)
        val ip = InetAddress.getByName(child.ip).address
        return initialRoutes.any { prefix ->
            val parent = parseAddress(prefix)
            parent.bits <= child.bits && InetAddress.getByName(parent.ip).address.size == ip.size &&
                Address(child.ip, parent.bits).network() == parent.network()
        }
    }

    suspend fun close() {
        NativePacketRouter.failClosed(generation)
        monitor?.cancelAndJoin(); monitor = null
        withContext(Dispatchers.IO) { native?.close(); native = null }
        status("stopped")
    }

    private fun physicalNetwork(): Pair<String, List<String>> {
        val cm = vpn.getSystemService(android.content.Context.CONNECTIVITY_SERVICE) as ConnectivityManager
        val networks = cm.allNetworks.filter { n -> cm.getNetworkCapabilities(n)?.let { it.hasCapability(NetworkCapabilities.NET_CAPABILITY_NOT_VPN) && it.hasCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET) } == true }
        val n = networks.minByOrNull { n -> if (cm.getNetworkCapabilities(n)?.hasTransport(NetworkCapabilities.TRANSPORT_WIFI) == true) 0 else 1 } ?: error("ET_NO_PHYSICAL_NETWORK")
        val local = cm.getLinkProperties(n)?.linkAddresses.orEmpty().filter { !it.address.isLinkLocalAddress && !it.address.isLoopbackAddress }.map { Address(it.address.hostAddress!!, it.prefixLength).network() }
        return n.toString() to local
    }

    private fun readAddresses(state: JSONObject): List<Address> {
        check(state.getInt("schema") == 1 && state.getLong("generation") == generation)
        val a = state.getJSONArray("addresses")
        check(a.length() <= 2)
        return (0 until a.length()).map { parseAddress(a.getString(it)) }
    }
    private fun readRoutes(state: JSONObject): Set<String> {
        val routes = state.getJSONArray("routes")
        check(routes.length() <= 4096)
        return (0 until routes.length()).map { parseAddress(routes.getString(it)).network() }.toSet()
    }
    private fun parseAddress(value: String): Address {
        val parts = value.split("/")
        check(parts.size == 2 && parts[0].all { it in "0123456789abcdefABCDEF:." })
        if (!parts[0].contains(":")) {
            val octets = parts[0].split(".")
            check(octets.size == 4 && octets.all { it.isNotEmpty() && it.all(Char::isDigit) && (it.toIntOrNull() ?: -1) in 0..255 })
        }
        val ip = InetAddress.getByName(parts[0])
        check(!parts[0].contains(":") || ip.address.size == 16)
        val bits = parts[1].toInt()
        check(bits in 1..ip.address.size * 8 && !ip.isAnyLocalAddress && !ip.isLoopbackAddress && !ip.isMulticastAddress && !ip.isLinkLocalAddress)
        return Address(ip.hostAddress!!, bits)
    }
    private fun packetPair(): Pair<ParcelFileDescriptor, ParcelFileDescriptor> {
        val left = FileDescriptor(); val right = FileDescriptor()
        Os.socketpair(OsConstants.AF_UNIX, OsConstants.SOCK_DGRAM, 0, left, right)
        try {
            val a = ParcelFileDescriptor.dup(left)
            try { return a to ParcelFileDescriptor.dup(right) } catch (e: Throwable) { a.close(); throw e }
        } finally { Os.close(left); Os.close(right) }
    }

    companion object {
        fun configured(vpn: VpnService, scope: CoroutineScope): PacketHarness? {
            if (!BuildConfig.NATIVE_MESH_HARNESS) return null
            val marker = File(vpn.noBackupFilesDir, "native-mesh-acceptance/enable")
            return if (marker.isFile && marker.length() < 64 && marker.readText().trim() == "packet-path-only") PacketHarness(vpn, scope) else null
        }
    }
}
