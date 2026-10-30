package com.github.kr328.clash.core.easytier

import androidx.annotation.Keep
import com.github.kr328.clash.core.bridge.Bridge
import com.github.kr328.clash.core.bridge.TunInterface

/** Development packet-path interface; never starts a second VpnService.
 * Native start adopts both descriptors on SUCCESS AND FAILURE. The caller must
 * detach ownership once and must not close a detached integer after the call.
 */
@Keep
object NativePacketRouter {
    init { Bridge.nativeCoreVersion() }

    external fun start(fd: Int, meshFd: Int, configuration: String, callback: TunInterface): Boolean
    external fun update(snapshot: String, installedAddresses: String): Boolean
    external fun failClosed(generation: Long)
    external fun suspendInterface(generation: Long): Boolean
    // Borrows fd without closing or changing it. Never infer readiness from an
    // old VPN interface which happens to have the same addresses and routes.
    external fun interfaceName(fd: Int): String?
    // Always adopts fd, on success AND failure, exactly as start does.
    external fun replaceInterface(fd: Int, request: String): Boolean
    // Physical handover with unchanged addresses/routes retains the same TUN.
    external fun refreshNetwork(request: String): Boolean
}
