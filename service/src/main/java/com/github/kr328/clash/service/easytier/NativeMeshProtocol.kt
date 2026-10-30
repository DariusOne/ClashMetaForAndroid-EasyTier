package com.github.kr328.clash.service.easytier

import android.os.IBinder

internal object NativeMeshProtocol {
    const val DESCRIPTOR = "com.github.kr328.clash.native-mesh.v1"
    const val START = IBinder.FIRST_CALL_TRANSACTION
    const val ATTACH = START + 1
    const val SNAPSHOT = START + 2
    const val STOP = START + 3
    const val MAX_PROFILE_BYTES = 1024 * 1024

    // Exact allowlist, not an ET_* regex: imported text must never become an
    // exception message merely because it resembles one of our error codes.
    private val safeCodes = setOf(
        "ET_CONFIG_SIZE", "ET_CONFIG_SYNTAX", "ET_UNSUPPORTED_HOST_OPTION",
        "ET_CONFIG_INVALID", "ET_FLAGS_INVALID", "ET_FLAG_UNKNOWN", "ET_MTU_INVALID",
        "ET_DEFAULT_ROUTE_FORBIDDEN", "ET_PACKET_DEVICE_REQUIRED", "ET_NETWORK_REQUIRED",
        "ET_ADDRESS_INVALID", "ET_JNI_STRING", "ET_TRANSPORT_NOT_ISOLATED",
        "ET_PHONE_ID_INVALID", "ET_STATE_UNAVAILABLE", "ET_ALREADY_RUNNING",
        "ET_START_FAILED", "ET_STALE_SESSION", "ET_PACKET_FD_INVALID",
        "ET_STATUS_UNAVAILABLE", "ET_ATTACH_FAILED", "ET_PACKET_DEVICE_FAILED",
        "ET_PACKET_DEVICE_TIMEOUT", "ET_ANDROID_REQUIRED", "ET_STATUS_INVALID",
        "ET_STATUS_TOO_LARGE", "ET_NATIVE_LINK_FAILED", "ET_ENGINE_UNAVAILABLE",
        "ET_ENGINE_COMMAND_FAILED", "ET_ENGINE_LOST"
    )

    fun safeError(error: Throwable): String = when {
        error is UnsatisfiedLinkError -> "ET_NATIVE_LINK_FAILED"
        error.message in safeCodes -> error.message!!
        else -> "ET_ENGINE_COMMAND_FAILED"
    }
}
