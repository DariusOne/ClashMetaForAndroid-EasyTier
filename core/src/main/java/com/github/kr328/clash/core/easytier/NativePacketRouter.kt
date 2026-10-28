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
    // Always adopts fd, on success AND failure, exactly as start does.
    external fun replaceInterface(fd: Int, request: String): Boolean
}
