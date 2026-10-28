package com.github.kr328.clash.service.easytier

/** Android 11 compares application LISTS to choose its asynchronous in-place
 * update, but resolves those lists to a SET of UIDs when enforcing capture.
 * Repeating an already verified entry changes that handover choice without
 * adding/removing any captured UID or enabling bypass. Scope is API 30 only;
 * this must retain the continuous packet/source acceptance gate.
 */
internal class LegacyVpnHandover {
    private var repeated = false

    fun repeatEntry(api: Int, nativeMesh: Boolean, verified: List<String>): String? =
        if (api == 30 && nativeMesh && repeated) verified.firstOrNull() else null

    fun committed(api: Int, nativeMesh: Boolean) {
        if (api == 30 && nativeMesh) repeated = !repeated
    }
}
