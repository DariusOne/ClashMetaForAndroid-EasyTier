package com.github.kr328.clash

import android.content.Intent
import android.net.VpnService
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.github.kr328.clash.remote.Remote
import com.github.kr328.clash.service.TunService
import com.github.kr328.clash.service.model.Profile
import com.github.kr328.clash.service.model.AccessControlMode
import com.github.kr328.clash.service.store.ServiceStore
import com.github.kr328.clash.service.util.pendingDir
import com.github.kr328.clash.util.stopClashService
import com.github.kr328.clash.util.withProfile
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
        check(BuildConfig.NATIVE_MESH_HARNESS && context.packageName == "com.github.metacubex.clash.meshprototype.meta")
        check(InstrumentationRegistry.getArguments().getString("disposableEmulator") == "true")
        check(android.os.Build.FINGERPRINT.contains("generic") || android.os.Build.MODEL.contains("sdk"))
        assertNull(VpnService.prepare(context))
        assertTrue(File(context.filesDir, "imported").listFiles().orEmpty().isEmpty())
        val folder = File(context.noBackupFilesDir, "native-mesh-acceptance")
        check(File(folder, "ci-peer-guard").readText() == "disposable-ci-only")
        check(File(folder, "mesh.toml").isFile)
        val rejectPort = File(folder, "ci-reject-port").readText().trim().toInt()
        check(rejectPort in 1024..65535)
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
            context.pendingDir.resolve(created.toString()).resolve("config.yaml").writeText("""
                mode: rule
                log-level: silent
                ipv6: false
                proxies:
                  - name: disposable-direct
                    type: direct
                proxy-groups: []
                rules:
                  - DST-PORT,$rejectPort,REJECT
                  - MATCH,DIRECT
            """.trimIndent())
            withTimeout(30_000) { withProfile { commit(created); setActive(queryByUUID(created)!!) } }
            File(folder, "status.json").delete()
            File(folder, "peer-ready").delete()
            File(folder, "peer-result.json").delete()
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
            withTimeout(180_000) {
                while (!File(folder, "peer-result.json").exists()) {
                    check(stage() == "active") { "Native peer stopped during packet probes" }
                    delay(100)
                }
            }
            val result = JSONObject(File(folder, "peer-result.json").readText())
            assertTrue("External packet probes failed", result.getBoolean("passed"))
            assertEquals("active", stage())
        } finally {
            context.stopClashService()
            withTimeoutOrNull(15_000) { while (stage() != "stopped") delay(100) }
            id?.let { withProfile { delete(it) } }
            for (name in listOf("enable", "mesh.toml", "ci-peer-guard", "ci-reject-port", "peer-ready", "peer-result.json")) File(folder, name).delete()
            Remote.service.unbind()
        }
    }
}
