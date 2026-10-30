package com.github.kr328.clash.core.easytier

import androidx.annotation.Keep

/** Native packet engine. Not an EasyTier outbound and not a second VPN owner.
 * Integration remains gated on the packet-path/device acceptance checklist.
 * TOML and snapshots must stay in app-private storage; never log their contents.
 */
@Keep
object NativeEasyTier {
    init { System.loadLibrary("cmfa_easytier") }

    external fun validate(toml: String): Boolean
    external fun start(toml: String, phoneId: String, generation: Long, transportIsolated: Boolean): Boolean
    /** Borrows fd and duplicates it; the caller retains ownership of the original. */
    external fun attachPacketFd(generation: Long, fd: Int): Boolean
    external fun snapshot(generation: Long): String
    external fun stop(generation: Long)
}
