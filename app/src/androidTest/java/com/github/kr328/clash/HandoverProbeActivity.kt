package com.github.kr328.clash

import android.app.Activity
import android.content.pm.ApplicationInfo
import android.os.Build
import android.os.Bundle
import android.os.Process
import android.os.SystemClock
import android.util.AtomicFile
import java.io.File
import java.io.IOException
import java.net.InetAddress
import java.net.InetSocketAddress
import java.nio.ByteBuffer
import java.nio.channels.DatagramChannel
import java.nio.channels.SelectionKey
import java.nio.channels.Selector
import java.nio.channels.SocketChannel
import java.util.concurrent.atomic.AtomicInteger
import org.json.JSONObject

/** Separate TEST-APK activity, not instrumentation's excluded VPN-owner UID.
 * Fixed disposable mesh destination, eight seconds/800 attempts, no secrets,
 * arbitrary destinations, raw exceptions or production-app entry points.
 */
class HandoverProbeActivity : Activity() {
    private val directory get() = File(noBackupFilesDir, "handover-probe")

    override fun onCreate(state: Bundle?) {
        super.onCreate(state)
        val sequence = intent.getIntExtra("sequence", 0)
        val tcp = intent.getIntExtra("tcpPort", 0)
        val udp = intent.getIntExtra("udpPort", 0)
        val owner = packageManager.getApplicationInfo("com.github.metacubex.clash.meshprototype.meta", 0).uid
        if (applicationInfo.flags and ApplicationInfo.FLAG_DEBUGGABLE == 0 ||
            packageName != "com.github.metacubex.clash.meshprototype.meta.test" ||
            Build.HARDWARE !in listOf("ranchu", "goldfish") ||
            intent.getStringExtra("guard") != "disposable-ci-only" ||
            Process.myUid() < 10_000 || Process.myUid() == owner ||
            sequence !in 1..100 || tcp !in 1024..65535 || udp !in 1024..65535) {
            finish(); return
        }
        directory.mkdirs()
        val remaining = AtomicInteger(2)
        for ((mode, port) in listOf("tcp" to tcp, "udp" to udp)) {
            Thread {
                try { probe(mode, port, sequence, owner) }
                finally { if (remaining.decrementAndGet() == 0) runOnUiThread { finish() } }
            }.start()
        }
    }

    private fun save(mode: String, value: JSONObject) {
        val file = AtomicFile(File(directory, "$mode.json"))
        val stream = file.startWrite()
        try {
            stream.write(value.toString().toByteArray(Charsets.UTF_8))
            file.finishWrite(stream)
        } catch (failure: Throwable) {
            file.failWrite(stream)
            throw failure
        }
    }

    private fun waitFor(selector: Selector, key: SelectionKey, operation: Int, deadline: Long) {
        key.interestOps(operation)
        val left = deadline - SystemClock.elapsedRealtime()
        if (left <= 0 || selector.select(left) == 0) throw IOException("DEADLINE")
        selector.selectedKeys().clear()
    }

    private fun probe(mode: String, port: Int, sequence: Int, owner: Int) {
        val started = SystemClock.elapsedRealtime()
        val finishAt = started + 8_000
        val address = InetSocketAddress(InetAddress.getByAddress(byteArrayOf(10,126,0,1)), port)
        var attempts = 0; var received = 0; var blocked = 0; var wrong = 0; var invalid = 0
        var clashSource = 0; var otherSource = 0; var ready = false
        fun result(done: Boolean) = JSONObject().put("schema",1).put("sequence",sequence)
            .put("uid", Process.myUid()).put("vpn_owner_uid", owner).put("api",Build.VERSION.SDK_INT)
            .put("ready",ready).put("done",done).put("attempts",attempts).put("received",received)
            .put("blocked",blocked).put("wrong_source",wrong).put("invalid_payload",invalid)
            .put("clash_gateway_source",clashSource).put("other_source",otherSource)
            .put("elapsed_ms",SystemClock.elapsedRealtime()-started)
        fun source(local: InetSocketAddress) {
            when (local.address.hostAddress) {
                "10.126.0.2" -> Unit
                "172.19.0.1" -> { wrong++; clashSource++ }
                else -> { wrong++; otherSource++ }
            }
        }
        while (SystemClock.elapsedRealtime() < finishAt && attempts < 800) {
            attempts++
            val deadline = minOf(finishAt, SystemClock.elapsedRealtime()+200)
            val request = "android-uid-handover-$attempts\n".toByteArray(Charsets.US_ASCII)
            val response = ByteBuffer.allocate(request.size)
            try {
                Selector.open().use { selector ->
                    if (mode == "tcp") {
                        SocketChannel.open().use { channel ->
                            channel.configureBlocking(false)
                            val key = channel.register(selector, SelectionKey.OP_CONNECT)
                            if (!channel.connect(address)) while (!channel.finishConnect()) waitFor(selector,key,SelectionKey.OP_CONNECT,deadline)
                            source(channel.localAddress as InetSocketAddress)
                            val buffer = ByteBuffer.wrap(request)
                            while (buffer.hasRemaining()) {
                                if (SystemClock.elapsedRealtime() >= deadline) throw IOException("DEADLINE")
                                if (channel.write(buffer) == 0) waitFor(selector,key,SelectionKey.OP_WRITE,deadline)
                            }
                            while (response.hasRemaining()) {
                                if (SystemClock.elapsedRealtime() >= deadline) throw IOException("DEADLINE")
                                val count = channel.read(response)
                                if (count < 0) throw IOException("EOF")
                                if (count == 0) waitFor(selector,key,SelectionKey.OP_READ,deadline)
                            }
                        }
                    } else {
                        DatagramChannel.open().use { channel ->
                            channel.configureBlocking(false)
                            val key = channel.register(selector, SelectionKey.OP_WRITE)
                            channel.connect(address)
                            source(channel.localAddress as InetSocketAddress)
                            while (channel.write(ByteBuffer.wrap(request)) == 0) waitFor(selector,key,SelectionKey.OP_WRITE,deadline)
                            while (channel.read(response) == 0) waitFor(selector,key,SelectionKey.OP_READ,deadline)
                        }
                    }
                }
                if (response.position() != request.size || !response.array().contentEquals(request)) invalid++
                else {
                    received++
                    if (!ready) { ready = true; save(mode,result(false)) }
                }
            } catch (_: IOException) { blocked++ }
            Thread.sleep(10)
        }
        save(mode,result(true))
    }
}
