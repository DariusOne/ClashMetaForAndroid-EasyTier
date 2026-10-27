package com.github.kr328.clash

import android.app.ActivityManager
import android.content.Context
import android.content.Intent
import android.net.VpnService
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.github.kr328.clash.remote.Remote
import com.github.kr328.clash.service.TunService
import com.github.kr328.clash.service.model.AccessControlMode
import com.github.kr328.clash.service.model.Profile
import com.github.kr328.clash.service.store.ServiceStore
import com.github.kr328.clash.service.util.pendingDir
import com.github.kr328.clash.util.stopClashService
import com.github.kr328.clash.util.withProfile
import java.io.File
import java.net.NetworkInterface
import java.util.UUID
import kotlinx.coroutines.*
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith

/** Disposable emulator-only lifecycle test. No production peer, subscription
 * or user's VPN is accessed. This is NOT device/peer packet acceptance. */
@RunWith(AndroidJUnit4::class)
class NativeMeshSmokeTest {
    private val context: Context get() = InstrumentationRegistry.getInstrumentation().targetContext
    private val folder get() = File(context.noBackupFilesDir, "native-mesh-acceptance")

    @Test fun singleOwnerStartsAndStopsTenTimes() = runBlocking {
        check(BuildConfig.NATIVE_MESH_HARNESS && context.packageName == "com.github.metacubex.clash.meshprototype.meta")
        check(InstrumentationRegistry.getArguments().getString("disposableEmulator") == "true")
        check(android.os.Build.FINGERPRINT.contains("generic") || android.os.Build.MODEL.contains("sdk"))
        assertNull("CI must grant VPN consent only to the disposable prototype", VpnService.prepare(context))
        assertFalse("Pre-existing profile means this is not a disposable test", File(context.filesDir, "imported").listFiles().orEmpty().isNotEmpty())
        folder.mkdirs()
        val token = UUID.randomUUID().toString()
        File(folder, "mesh.toml").writeText("""
            ipv4 = '10.126.0.2/24'
            dhcp = false
            listeners = []
            [network_identity]
            network_name = 'ci-disposable-$token'
            network_secret = '$token'
            [flags]
            mtu = 1380
        """.trimIndent())
        File(folder, "enable").writeText("packet-path-only")
        val store = ServiceStore(context)
        store.systemProxy = false
        store.bypassPrivateNetwork = false
        store.allowBypass = false
        store.allowIpv6 = false
        store.dynamicNotification = false
        store.accessControlMode = AccessControlMode.AcceptAll
        Remote.service.bind()
        try {
            val id = withTimeout(30_000) { withProfile { create(Profile.Type.File, "disposable-native-smoke") } }
            context.pendingDir.resolve(id.toString()).resolve("config.yaml").writeText("""
                mode: rule
                log-level: silent
                ipv6: false
                proxies:
                  - name: disposable-direct
                    type: direct
                proxy-groups: []
                rules:
                  - MATCH,DIRECT
            """.trimIndent())
            withTimeout(30_000) { withProfile { commit(id); setActive(queryByUUID(id)!!) } }
            var previous = 0L
            repeat(10) {
                File(folder, "status.json").delete()
                context.startForegroundService(Intent(context, TunService::class.java))
                val active = awaitStage("active", 45_000)
                assertNotEquals(previous, active.getLong("generation"))
                previous = active.getLong("generation")
                assertTrue("Mesh address missing from Android interface", ownsMeshAddress())
                delay(1_500)
                assertEquals("Native monitor must still be healthy", "active", readStage().getString("stage"))
                if (it == 9) {
                    // Kill only our disposable native process, never the VPN
                    // owner. The caller UID/package and emulator are checked.
                    val am = context.getSystemService(Context.ACTIVITY_SERVICE) as ActivityManager
                    val child = am.runningAppProcesses.single { process -> process.processName == "${context.packageName}:native_mesh" }
                    assertEquals(context.applicationInfo.uid, child.uid)
                    InstrumentationRegistry.getInstrumentation().uiAutomation.executeShellCommand("run-as ${context.packageName} kill -9 ${child.pid}").use { fd ->
                        android.os.ParcelFileDescriptor.AutoCloseInputStream(fd).use { stream -> stream.readBytes() }
                    }
                    withTimeout(15_000) { while (!readStage().optString("stage").startsWith("ET_")) delay(100) }
                    delay(1_500)
                    assertTrue("Native death must not remove the VPN owner", ownsMeshAddress())
                    assertTrue("Engine death must remain closed", readStage().optString("stage").startsWith("ET_"))
                }
                context.stopClashService()
                awaitStage("stopped", 15_000)
                withTimeout(15_000) { while (ownsMeshAddress() || File(context.filesDir, "service_running.lock").exists()) delay(100) }
            }
            withProfile { delete(id) }
        } finally {
            context.stopClashService()
            File(folder, "enable").delete()
            File(folder, "mesh.toml").delete()
            Remote.service.unbind()
        }
    }

    private fun readStage(): JSONObject = runCatching { JSONObject(File(folder, "status.json").readText()) }.getOrElse { JSONObject() }
    private suspend fun awaitStage(expected: String, timeout: Long): JSONObject = withTimeout(timeout) {
        var state: JSONObject
        while (true) {
            state = readStage()
            val stage = state.optString("stage")
            check(expected == "stopped" || !stage.startsWith("ET_")) { stage }
            if (stage == expected) break
            delay(100)
        }
        state
    }
    private fun ownsMeshAddress(): Boolean = NetworkInterface.getNetworkInterfaces().toList().any { network ->
        network.inetAddresses.toList().any { it.hostAddress == "10.126.0.2" }
    }
}
