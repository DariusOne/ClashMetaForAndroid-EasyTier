package com.github.kr328.clash;

import android.app.Activity;
import android.content.pm.ApplicationInfo;
import android.os.Build;
import android.os.Bundle;
import android.os.Process;
import android.os.SystemClock;
import android.util.AtomicFile;
import android.util.Log;
import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;
import java.net.InetAddress;
import java.net.InetSocketAddress;
import java.nio.ByteBuffer;
import java.nio.channels.DatagramChannel;
import java.nio.channels.SelectionKey;
import java.nio.channels.Selector;
import java.nio.channels.SocketChannel;
import java.nio.charset.StandardCharsets;
import java.util.Arrays;
import java.util.concurrent.atomic.AtomicInteger;
import org.json.JSONException;
import org.json.JSONObject;

/** Independent test-APK UID. Only framework/JDK classes are used because AGP
 * removes dependencies already present in the target app from the test APK.
 * No arbitrary destination, production entry point or user profile is accepted.
 */
public final class HandoverProbeActivity extends Activity {
    private File directory;

    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        final int sequence = getIntent().getIntExtra("sequence", 0);
        final int tcp = getIntent().getIntExtra("tcpPort", 0);
        final int udp = getIntent().getIntExtra("udpPort", 0);
        final int owner;
        try {
            owner = getPackageManager().getApplicationInfo(
                    "com.github.metacubex.clash.meshprototype.meta", 0).uid;
        } catch (android.content.pm.PackageManager.NameNotFoundException e) {
            finish(); return;
        }
        if ((getApplicationInfo().flags & ApplicationInfo.FLAG_DEBUGGABLE) == 0 ||
                !"com.github.metacubex.clash.meshprototype.meta.test".equals(getPackageName()) ||
                !("ranchu".equals(Build.HARDWARE) || "goldfish".equals(Build.HARDWARE)) ||
                !"disposable-ci-only".equals(getIntent().getStringExtra("guard")) ||
                Process.myUid() < 10000 || Process.myUid() == owner ||
                sequence < 1 || sequence > 100 || tcp < 1024 || tcp > 65535 ||
                udp < 1024 || udp > 65535) {
            Log.w("HandoverProbe", "FIXTURE_GUARD_FAILED");
            finish(); return;
        }
        directory = new File(getNoBackupFilesDir(), "handover-probe");
        if (!directory.isDirectory() && !directory.mkdirs()) {
            Log.w("HandoverProbe", "FIXTURE_STORAGE_FAILED");
            finish(); return;
        }
        final AtomicInteger remaining = new AtomicInteger(2);
        for (String mode : new String[] {"tcp", "udp"}) {
            final int port = "tcp".equals(mode) ? tcp : udp;
            new Thread(() -> {
                try { probe(mode, port, sequence, owner); }
                finally {
                    if (remaining.decrementAndGet() == 0) runOnUiThread(this::finish);
                }
            }, "handover-" + mode).start();
        }
    }

    private void save(String mode, JSONObject value) throws IOException {
        AtomicFile file = new AtomicFile(new File(directory, mode + ".json"));
        FileOutputStream stream = file.startWrite();
        try {
            stream.write(value.toString().getBytes(StandardCharsets.UTF_8));
            file.finishWrite(stream);
        } catch (IOException | RuntimeException e) {
            file.failWrite(stream);
            throw e;
        }
    }

    private static void waitFor(Selector selector, SelectionKey key, int operation,
                                long deadline) throws IOException {
        key.interestOps(operation);
        long left = deadline - SystemClock.elapsedRealtime();
        if (left <= 0 || selector.select(left) == 0) throw new IOException("DEADLINE");
        selector.selectedKeys().clear();
    }

    private static final class Counts {
        int attempts, received, blocked, wrong, invalid, clash, other;
        boolean ready;
        String failure = "";
        final long started = SystemClock.elapsedRealtime();

        JSONObject result(int sequence, int owner, boolean done) throws JSONException {
            return new JSONObject().put("schema", 1).put("sequence", sequence)
                    .put("uid", Process.myUid()).put("vpn_owner_uid", owner)
                    .put("api", Build.VERSION.SDK_INT).put("ready", ready).put("done", done)
                    .put("attempts", attempts).put("received", received).put("blocked", blocked)
                    .put("wrong_source", wrong).put("invalid_payload", invalid)
                    .put("clash_gateway_source", clash).put("other_source", other)
                    .put("failure_code", failure)
                    .put("elapsed_ms", SystemClock.elapsedRealtime() - started);
        }

        void source(InetSocketAddress local) {
            String address = local.getAddress().getHostAddress();
            if (!"10.126.0.2".equals(address)) {
                wrong++;
                if ("172.19.0.1".equals(address)) clash++; else other++;
            }
        }
    }

    private void probe(String mode, int port, int sequence, int owner) {
        Counts c = new Counts();
        long finishAt = c.started + 8000;
        try {
            InetSocketAddress address = new InetSocketAddress(
                    InetAddress.getByAddress(new byte[] {10, 126, 0, 1}), port);
            save(mode, c.result(sequence, owner, false));
            while (SystemClock.elapsedRealtime() < finishAt && c.attempts < 800) {
                c.attempts++;
                long deadline = Math.min(finishAt, SystemClock.elapsedRealtime() + 200);
                byte[] request = ("android-uid-handover-" + c.attempts + "\n")
                        .getBytes(StandardCharsets.US_ASCII);
                ByteBuffer response = ByteBuffer.allocate(request.length);
                try (Selector selector = Selector.open()) {
                    if ("tcp".equals(mode)) {
                        try (SocketChannel channel = SocketChannel.open()) {
                            channel.configureBlocking(false);
                            SelectionKey key = channel.register(selector, SelectionKey.OP_CONNECT);
                            if (!channel.connect(address)) {
                                while (!channel.finishConnect()) waitFor(selector, key, SelectionKey.OP_CONNECT, deadline);
                            }
                            c.source((InetSocketAddress) channel.getLocalAddress());
                            ByteBuffer buffer = ByteBuffer.wrap(request);
                            while (buffer.hasRemaining()) {
                                if (SystemClock.elapsedRealtime() >= deadline) throw new IOException("DEADLINE");
                                if (channel.write(buffer) == 0) waitFor(selector, key, SelectionKey.OP_WRITE, deadline);
                            }
                            while (response.hasRemaining()) {
                                if (SystemClock.elapsedRealtime() >= deadline) throw new IOException("DEADLINE");
                                int count = channel.read(response);
                                if (count < 0) throw new IOException("EOF");
                                if (count == 0) waitFor(selector, key, SelectionKey.OP_READ, deadline);
                            }
                        }
                    } else {
                        try (DatagramChannel channel = DatagramChannel.open()) {
                            channel.configureBlocking(false);
                            SelectionKey key = channel.register(selector, SelectionKey.OP_WRITE);
                            channel.connect(address);
                            c.source((InetSocketAddress) channel.getLocalAddress());
                            while (channel.write(ByteBuffer.wrap(request)) == 0) waitFor(selector, key, SelectionKey.OP_WRITE, deadline);
                            while (channel.read(response) == 0) waitFor(selector, key, SelectionKey.OP_READ, deadline);
                        }
                    }
                    if (response.position() != request.length || !Arrays.equals(response.array(), request)) c.invalid++;
                    else {
                        c.received++;
                        if (!c.ready) { c.ready = true; save(mode, c.result(sequence, owner, false)); }
                    }
                } catch (IOException e) { c.blocked++; }
                Thread.sleep(10);
            }
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            c.failure = "INTERRUPTED";
        } catch (IOException | JSONException | RuntimeException e) {
            c.failure = "FIXTURE_RUNTIME_FAILED";
        } finally {
            try { save(mode, c.result(sequence, owner, true)); }
            catch (IOException | JSONException | RuntimeException e) {
                Log.w("HandoverProbe", "FIXTURE_RESULT_FAILED");
            }
        }
    }
}
