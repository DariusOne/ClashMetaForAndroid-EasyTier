package com.github.kr328.clash.service.easytier

import android.app.Service
import android.content.Intent
import android.os.Binder
import android.os.IBinder
import android.os.Parcel
import android.os.ParcelFileDescriptor
import android.os.Process
import com.github.kr328.clash.core.easytier.NativeEasyTier
import java.nio.ByteBuffer
import java.nio.charset.CodingErrorAction
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit

/** Bound, unexported engine process. It owns NO VpnService or Android TUN.
 * The caller must exclude this application's UID in the active VPN before start.
 * Native failure is contained here; the owner retains its VPN and closes only
 * mesh ownership on binder death. No credentials are carried in Intent extras.
 */
class NativeMeshService : Service() {
    private val lock = Any()
    private var generation = 0L
    private var owner: IBinder? = null
    private val watchdog = Executors.newSingleThreadScheduledExecutor { r -> Thread(r, "mesh-command-watchdog").apply { isDaemon = true } }
    private val ownerDeath = IBinder.DeathRecipient { synchronized(lock) { stopLocked() } }

    private val endpoint = object : Binder() {
        override fun onTransact(code: Int, data: Parcel, reply: Parcel?, flags: Int): Boolean {
            if (code == INTERFACE_TRANSACTION) {
                reply?.writeString(NativeMeshProtocol.DESCRIPTOR)
                return true
            }
            if (Binder.getCallingUid() != Process.myUid()) {
                reply?.writeException(SecurityException("ET_CALLER_DENIED"))
                return true
            }
            if (code !in NativeMeshProtocol.START..NativeMeshProtocol.STOP || reply == null) return false
            data.enforceInterface(NativeMeshProtocol.DESCRIPTOR)
            val deadline = watchdog.schedule({ Process.killProcess(Process.myPid()) }, 15, TimeUnit.SECONDS)
            try { synchronized(lock) {
                // Always return fixed errors. Native TOML/URI parser exceptions
                // may contain a network secret and must never reach logcat/IPC.
                try {
                    when (code) {
                        NativeMeshProtocol.START -> {
                            check(generation == 0L) { "ET_ALREADY_RUNNING" }
                            val session = data.readLong()
                            val phoneId = data.readString() ?: error("ET_PHONE_ID")
                            val isolated = data.readInt() == 1
                            val token = data.readStrongBinder() ?: error("ET_OWNER_MISSING")
                            check(session > 0 && isolated && token.isBinderAlive) { "ET_TRANSPORT_NOT_ISOLATED" }
                            val profile = ParcelFileDescriptor.CREATOR.createFromParcel(data)
                            val text = ParcelFileDescriptor.AutoCloseInputStream(profile).use { stream ->
                                val bytes = stream.readBytesBounded(NativeMeshProtocol.MAX_PROFILE_BYTES)
                                Charsets.UTF_8.newDecoder().onMalformedInput(CodingErrorAction.REPORT)
                                    .onUnmappableCharacter(CodingErrorAction.REPORT)
                                    .decode(ByteBuffer.wrap(bytes)).toString()
                            }
                            token.linkToDeath(ownerDeath, 0)
                            owner = token
                            generation = session
                            try {
                                check(NativeEasyTier.start(text, phoneId, session, true))
                            } catch (e: Throwable) {
                                stopLocked()
                                throw e
                            }
                            reply.writeNoException()
                        }
                        NativeMeshProtocol.ATTACH -> {
                            val session = data.readLong()
                            val profile = ParcelFileDescriptor.CREATOR.createFromParcel(data)
                            profile.use { packet ->
                                check(session == generation && generation > 0)
                                check(NativeEasyTier.attachPacketFd(session, packet.fd))
                            }
                            reply.writeNoException()
                        }
                        NativeMeshProtocol.SNAPSHOT -> {
                            val session = data.readLong()
                            check(session == generation && generation > 0)
                            val snapshot = NativeEasyTier.snapshot(session)
                            check(snapshot.length <= 512 * 1024)
                            reply.writeNoException()
                            reply.writeString(snapshot)
                        }
                        NativeMeshProtocol.STOP -> {
                            val session = data.readLong()
                            check(generation == 0L || session == generation)
                            stopLocked()
                            reply.writeNoException()
                        }
                    }
                } catch (_: Throwable) {
                    reply.writeException(IllegalStateException("ET_ENGINE_COMMAND_FAILED"))
                }
            } } finally { deadline.cancel(false) }
            return true
        }
    }

    override fun onBind(intent: Intent): IBinder = endpoint

    private fun stopLocked() {
        val current = generation
        generation = 0
        owner?.let { runCatching { it.unlinkToDeath(ownerDeath, 0) } }
        owner = null
        if (current != 0L) {
            val deadline = watchdog.schedule({ Process.killProcess(Process.myPid()) }, 5, TimeUnit.SECONDS)
            try { runCatching { NativeEasyTier.stop(current) } } finally { deadline.cancel(false) }
        }
    }

    override fun onDestroy() {
        synchronized(lock) { stopLocked() }
        watchdog.shutdown()
        super.onDestroy()
    }
}

private fun java.io.InputStream.readBytesBounded(limit: Int): ByteArray {
    val result = java.io.ByteArrayOutputStream()
    val buffer = ByteArray(8192)
    while (true) {
        val n = read(buffer)
        if (n < 0) break
        check(n <= limit - result.size()) { "ET_CONFIG_SIZE" }
        result.write(buffer, 0, n)
    }
    check(result.size() > 0) { "ET_CONFIG_SIZE" }
    return result.toByteArray()
}
