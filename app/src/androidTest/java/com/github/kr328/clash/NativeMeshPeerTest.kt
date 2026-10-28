package com.github.kr328.clash

import android.content.Intent
import android.net.VpnService
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.github.kr328.clash.remote.Remote
import com.github.kr328.clash.core.Clash
import com.github.kr328.clash.core.model.TunnelState
import com.github.kr328.clash.service.TunService
import com.github.kr328.clash.service.model.Profile
import com.github.kr328.clash.service.model.AccessControlMode
import com.github.kr328.clash.service.store.ServiceStore
import com.github.kr328.clash.service.util.pendingDir
import com.github.kr328.clash.util.stopClashService
import com.github.kr328.clash.util.withProfile
import com.github.kr328.clash.util.withClash
import java.io.File
import kotlinx.coroutines.*
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith

/** Coordinates external shell-UID probes against a disposable Linux peer.
 * No application-UID sockets are used as evidence of Android VPN capture. */
@RunWith(AndroidJUnit4::class)
class NativeMeshPeerTest {
    @Test fun realPeerPacketPath() = runBlocking {
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        val physicalDevice = NativeMeshAcceptanceGuard.verify()
        assertNull(VpnService.prepare(context))
        assertTrue(File(context.filesDir, "imported").listFiles().orEmpty().isEmpty())
        val folder = File(context.noBackupFilesDir, "native-mesh-acceptance")
        check(File(folder, "ci-peer-guard").readText() == if (physicalDevice) "disposable-physical-only" else "disposable-ci-only")
        check(File(folder, "mesh.toml").isFile)
        val rejectPort = File(folder, "ci-reject-port").readText().trim().toInt()
        check(rejectPort in 1024..65535)
        val proxyFile = File(folder, "ci-proxy.json")
        val proxy = if (proxyFile.isFile) {
            check(physicalDevice && proxyFile.length() in 1..4096)
            JSONObject(proxyFile.readText()).also {
                check(it.getString("host") == it.getString("destination"))
                check(it.getString("host").matches(Regex("[0-9.]{7,15}")))
                check(it.getInt("port") in 1024..65535 && it.getInt("destination_port") in 1024..65535)
                check(it.getInt("port") != it.getInt("destination_port") && it.getInt("destination_port") != rejectPort)
                check(it.getString("username").matches(Regex("[0-9a-f]{16}")))
                check(it.getString("password").matches(Regex("[0-9a-f]{32}")))
            }
        } else null
        ServiceStore(context).apply {
            systemProxy = false; bypassPrivateNetwork = false; allowBypass = false
            allowIpv6 = false; dynamicNotification = false; accessControlMode = AccessControlMode.AcceptAll
        }
        fun stage() = runCatching { JSONObject(File(folder, "status.json").readText()).optString("stage") }.getOrDefault("")
        Remote.service.bind()
        var id: java.util.UUID? = null
        try {
            val created = withTimeout(30_000) { withProfile { create(Profile.Type.File, "disposable-peer-probe") } }
            id = created
            val config = buildString {
                append("mode: rule\nlog-level: silent\nipv6: false\nproxies:\n  - name: disposable-direct\n    type: direct\n")
                if (proxy != null) {
                    append("  - name: disposable-proxy\n    type: socks5\n    udp: true\n")
                    for (key in listOf("server", "port", "username", "password")) {
                        val value = if (key == "port") proxy.getInt(key).toString() else JSONObject.quote(proxy.getString(if (key == "server") "host" else key))
                        append("    $key: $value\n")
                    }
                }
                append("proxy-groups: []\nrules:\n  - DST-PORT,$rejectPort,REJECT\n")
                if (proxy != null) append("  - DST-PORT,${proxy.getInt("destination_port")},disposable-proxy\n")
                append("  - MATCH,DIRECT\n")
            }
            context.pendingDir.resolve(created.toString()).resolve("config.yaml").writeText(config)
            withTimeout(30_000) { withProfile { commit(created); setActive(queryByUUID(created)!!) } }
            File(folder, "status.json").delete()
            File(folder, "peer-ready").delete()
            File(folder, "peer-result.json").delete()
            File(folder, "mode-request.json").delete()
            File(folder, "mode-ready.json").delete()
            File(folder, "rebuild-request").delete()
            File(folder, "network-options-request.json").delete()
            File(folder, "network-options-ready.json").delete()
            File(folder, "enable").writeText("packet-path-only")
            context.startForegroundService(Intent(context, TunService::class.java))
            withTimeout(45_000) {
                while (stage() != "active") {
                    val current = stage()
                    check(!current.startsWith("ET_")) { current }
                    delay(100)
                }
            }
            File(folder, "peer-ready").writeText("ready")
            var sequence = 0
            var optionsSequence = 0
            withTimeout(if (physicalDevice) 600_000 else 240_000) {
                while (!File(folder, "peer-result.json").exists()) {
                    check(stage() in listOf("active", "waiting-network", "rebuilding-interface")) { "Native peer stopped during packet probes" }
                    val request = runCatching { JSONObject(File(folder, "mode-request.json").readText()) }.getOrNull()
                    if (request != null && request.optInt("sequence") > sequence) {
                        val mode = when (request.getString("mode")) {
                            "direct" -> TunnelState.Mode.Direct
                            "global" -> TunnelState.Mode.Global
                            "rule" -> TunnelState.Mode.Rule
                            else -> error("Invalid disposable test mode")
                        }
                        withClash {
                            val options = queryOverride(Clash.OverrideSlot.Session)
                            options.mode = mode
                            patchOverride(Clash.OverrideSlot.Session, options)
                        }
                        withTimeout(15_000) {
                            while (withClash { queryTunnelState().mode } != mode) delay(100)
                            if (mode == TunnelState.Mode.Global) {
                                while (!withClash { patchSelector("GLOBAL", "REJECT") }) delay(100)
                            }
                        }
                        sequence = request.getInt("sequence")
                        File(folder, "mode-ready.json").writeText(JSONObject().put("sequence", sequence).toString())
                    }
                    val options = runCatching { JSONObject(File(folder, "network-options-request.json").readText()) }.getOrNull()
                    if (options != null && options.optInt("sequence") > optionsSequence) {
                        check(physicalDevice && proxy != null && options.getInt("sequence") in 10..100)
                        ServiceStore(context).bypassPrivateNetwork = options.getBoolean("bypass_private")
                        optionsSequence = options.getInt("sequence")
                        File(folder, "rebuild-request").writeText(optionsSequence.toString())
                        withTimeout(15_000) {
                            while (true) {
                                val state = JSONObject(File(folder, "status.json").readText())
                                check(!state.getString("stage").startsWith("ET_"))
                                if (state.getString("stage") == "active" && state.getInt("rebuild_request") == optionsSequence) break
                                delay(100)
                            }
                        }
                        File(folder, "network-options-ready.json").writeText(JSONObject().put("sequence", optionsSequence).toString())
                    }
                    delay(100)
                }
            }
            val result = JSONObject(File(folder, "peer-result.json").readText())
            assertTrue("External packet probes failed", result.getBoolean("passed"))
            assertEquals("active", stage())
        } finally {
            context.stopClashService()
            withTimeoutOrNull(15_000) { while (stage() != "stopped") delay(100) }
            withClash { clearOverride(Clash.OverrideSlot.Session) }
            id?.let { withProfile { delete(it) } }
            ServiceStore(context).bypassPrivateNetwork = false
            for (name in listOf("enable", "mesh.toml", "ci-peer-guard", "ci-reject-port", "peer-ready", "peer-result.json", "mode-request.json", "mode-ready.json", "rebuild-request", "ci-proxy.json", "network-options-request.json", "network-options-ready.json")) File(folder, name).delete()
            Remote.service.unbind()
            NativeMeshAcceptanceGuard.closeForeground()
        }
    }
}
