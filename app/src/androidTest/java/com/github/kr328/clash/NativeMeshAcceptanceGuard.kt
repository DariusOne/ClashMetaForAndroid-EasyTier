package com.github.kr328.clash

import android.content.Intent
import android.net.VpnService
import androidx.test.core.app.ActivityScenario
import androidx.test.platform.app.InstrumentationRegistry
import java.io.File
import java.util.UUID
import kotlinx.coroutines.delay
import kotlinx.coroutines.withTimeout

/** The real-device entry point requires a one-run marker in this separate
 * prototype's private storage. It never grants VPN consent with appops, accesses
 * another application's data, or accepts a populated prototype profile store. */
internal object NativeMeshAcceptanceGuard {
    private var foreground: ActivityScenario<MainActivity>? = null

    fun closeForeground() { foreground?.close(); foreground = null }

    suspend fun verify(): Boolean {
        val registry = InstrumentationRegistry.getInstrumentation()
        val context = registry.targetContext
        val arguments = InstrumentationRegistry.getArguments()
        check(BuildConfig.NATIVE_MESH_HARNESS && context.packageName == "com.github.metacubex.clash.meshprototype.meta")
        check(File(context.filesDir, "imported").listFiles().orEmpty().isEmpty()) { "ET_TEST_PROFILE_STORE_NOT_EMPTY" }
        val emulator = android.os.Build.FINGERPRINT.contains("generic") || android.os.Build.MODEL.contains("sdk")
        if (arguments.getString("disposableEmulator") == "true") {
            check(emulator) { "ET_TEST_EMULATOR_REQUIRED" }
            check(VpnService.prepare(context) == null) { "ET_TEST_VPN_CONSENT_REQUIRED" }
            return false
        }
        check(!emulator) { "ET_TEST_PHYSICAL_DEVICE_REQUIRED" }
        val token = arguments.getString("physicalDeviceConsent") ?: error("ET_TEST_CONSENT_REQUIRED")
        check(runCatching { UUID.fromString(token).toString() == token }.getOrDefault(false)) { "ET_TEST_CONSENT_INVALID" }
        val marker = File(context.noBackupFilesDir, "native-mesh-acceptance/physical-consent")
        check(marker.isFile && marker.length() <= 64 && marker.readText().trim() == token) { "ET_TEST_CONSENT_INVALID" }
        // Single use: repeating a destructive fixture requires explicit staging.
        check(marker.delete()) { "ET_TEST_CONSENT_INVALID" }
        try {
            // VPN confirmation identifies its caller through an Activity result;
            // a background Context.startActivity has no such caller and may be
            // blocked or immediately dismissed by a physical device's system UI.
            foreground = ActivityScenario.launch(Intent(context, MainActivity::class.java))
            VpnService.prepare(context)?.let { request ->
                foreground!!.onActivity { it.startActivityForResult(request, 20052) }
                withTimeout(120_000) { while (VpnService.prepare(context) != null) delay(250) }
            }
        } catch (e: Throwable) { closeForeground(); throw e }
        return true
    }
}
