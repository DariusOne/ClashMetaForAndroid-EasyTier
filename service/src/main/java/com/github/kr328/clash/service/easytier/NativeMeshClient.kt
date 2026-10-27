package com.github.kr328.clash.service.easytier

import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.content.ServiceConnection
import android.os.Binder
import android.os.IBinder
import android.os.Parcel
import android.os.ParcelFileDescriptor
import java.io.Closeable
import java.io.File
import java.util.concurrent.atomic.AtomicBoolean
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.coroutines.withTimeout

/** One owner/session, explicit descriptor ownership, and a death notification
 * that must call NativePacketRouter.failClosed. No auto-reconnect/fallback.
 * These calls run off the UI thread; native failures have fixed messages only.
 */
class NativeMeshClient private constructor(
    private val context: Context,
    private val onEngineLost: () -> Unit
) : Closeable {
    private val connected = CompletableDeferred<IBinder>()
    private val closed = AtomicBoolean()
    private val owner = Binder()
    @Volatile private var remote: IBinder? = null
    @Volatile private var generation = 0L
    private val death = IBinder.DeathRecipient { lost() }
    private val connection = object : ServiceConnection {
        override fun onServiceConnected(name: ComponentName, binder: IBinder) {
            if (closed.get()) return
            try {
                binder.linkToDeath(death, 0)
                remote = binder
                connected.complete(binder)
            } catch (_: Exception) { lost() }
        }
        override fun onServiceDisconnected(name: ComponentName) = lost()
        override fun onBindingDied(name: ComponentName) = lost()
        override fun onNullBinding(name: ComponentName) = lost()
    }

    private fun lost() {
        remote = null
        connected.completeExceptionally(IllegalStateException("ET_ENGINE_UNAVAILABLE"))
        if (!closed.get()) onEngineLost()
    }

    suspend fun start(profile: File, phoneId: String, session: Long, ownUidExcluded: Boolean) = withContext(Dispatchers.IO) {
        check(!closed.get() && session > 0 && ownUidExcluded && generation == 0L) { "ET_START_PRECONDITION" }
        ParcelFileDescriptor.open(profile, ParcelFileDescriptor.MODE_READ_ONLY).use { file ->
            call(NativeMeshProtocol.START, {
                writeLong(session); writeString(phoneId); writeInt(1); writeStrongBinder(owner)
                file.writeToParcel(this, 0)
            })
        }
        generation = session
    }

    suspend fun attach(packet: ParcelFileDescriptor) = withContext(Dispatchers.IO) {
        check(generation > 0 && !closed.get()) { "ET_NO_SESSION" }
        // Binder duplicates the descriptor. Caller still owns packet; the Rust
        // adapter duplicates again, and the service closes the Binder copy.
        call(NativeMeshProtocol.ATTACH, { writeLong(generation); packet.writeToParcel(this, 0) })
    }

    suspend fun snapshot(): String = withContext(Dispatchers.IO) {
        check(generation > 0 && !closed.get()) { "ET_NO_SESSION" }
        call(NativeMeshProtocol.SNAPSHOT, { writeLong(generation) }, { readString() ?: error("ET_EMPTY_STATUS") })!!
    }

    private fun call(code: Int, input: Parcel.() -> Unit, output: (Parcel.() -> String)? = null): String? {
        val binder = remote ?: error("ET_ENGINE_UNAVAILABLE")
        val data = Parcel.obtain()
        val reply = Parcel.obtain()
        try {
            data.writeInterfaceToken(NativeMeshProtocol.DESCRIPTOR)
            input(data)
            check(binder.transact(code, data, reply, 0)) { "ET_IPC_FAILED" }
            reply.readException()
            return output?.invoke(reply)
        } catch (_: Exception) {
            onEngineLost()
            throw IllegalStateException("ET_ENGINE_COMMAND_FAILED")
        } finally { data.recycle(); reply.recycle() }
    }

    override fun close() {
        if (!closed.compareAndSet(false, true)) return
        // The VPN owner closes the route before invoking this potentially
        // blocking native shutdown. Do not release the active Android TUN here.
        if (generation != 0L) runCatching { call(NativeMeshProtocol.STOP, { writeLong(generation) }) }
        generation = 0
        remote?.let { runCatching { it.unlinkToDeath(death, 0) } }
        remote = null
        runCatching { context.unbindService(connection) }
    }

    companion object {
        suspend fun bind(context: Context, onEngineLost: () -> Unit): NativeMeshClient {
            val client = NativeMeshClient(context.applicationContext, onEngineLost)
            try {
                check(client.context.bindService(Intent(client.context, NativeMeshService::class.java), client.connection, Context.BIND_AUTO_CREATE)) { "ET_BIND_FAILED" }
                withTimeout(10_000) { client.connected.await() }
                return client
            } catch (e: Throwable) { client.close(); throw e }
        }
    }
}
