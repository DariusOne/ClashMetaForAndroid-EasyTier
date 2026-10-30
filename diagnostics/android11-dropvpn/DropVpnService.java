package fixture.dropvpn;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.content.Context;
import android.content.Intent;
import android.content.pm.ApplicationInfo;
import android.net.ConnectivityManager;
import android.net.LinkProperties;
import android.net.Network;
import android.net.NetworkCapabilities;
import android.net.VpnService;
import android.os.Build;
import android.os.Handler;
import android.os.Looper;
import android.os.ParcelFileDescriptor;
import android.os.SystemClock;
import android.util.AtomicFile;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.nio.charset.StandardCharsets;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.atomic.AtomicLong;
import org.json.JSONObject;

/** No proxy or mesh code, no outgoing sockets and no writes to the TUN.
 * Every received IP packet is discarded. This class is outside all app source
 * sets and is never packaged in CMFA, including the opt-in prototype.
 */
public final class DropVpnService extends VpnService {
    private final ExecutorService worker = Executors.newSingleThreadExecutor();
    private final AtomicLong discarded = new AtomicLong();
    private ParcelFileDescriptor tun;
    private String installed;
    private int sequence;

    static boolean allowed(Context context) {
        return (Build.VERSION.SDK_INT == 30 || Build.VERSION.SDK_INT == 31 || Build.VERSION.SDK_INT == 35) &&
                ("ranchu".equals(Build.HARDWARE) || "goldfish".equals(Build.HARDWARE)) &&
                (context.getApplicationInfo().flags & ApplicationInfo.FLAG_DEBUGGABLE) != 0 &&
                "com.github.metacubex.clash.meshprototype.meta".equals(context.getPackageName());
    }

    @Override public void onCreate() {
        super.onCreate();
        if (!allowed(this)) { stopSelf(); return; }
        NotificationManager manager = getSystemService(NotificationManager.class);
        manager.createNotificationChannel(new NotificationChannel("fixture", "Disposable drop VPN", NotificationManager.IMPORTANCE_LOW));
        startForeground(1, new Notification.Builder(this, "fixture")
                .setSmallIcon(android.R.drawable.stat_sys_warning)
                .setContentTitle("Disposable emulator diagnostic").build());
        // Independent hard deadline, including a host runner crash.
        new Handler(Looper.getMainLooper()).postDelayed(this::stopFixture, 180_000);
    }

    @Override public int onStartCommand(Intent intent, int flags, int startId) {
        if (!allowed(this) || intent == null) { stopSelf(); return START_NOT_STICKY; }
        final int next = intent.getIntExtra("sequence", -1);
        if (next == -1) { stopFixture(); return START_NOT_STICKY; }
        if (next < 1 || next > 64) { stopSelf(); return START_NOT_STICKY; }
        worker.execute(() -> {
            try {
                if (next != sequence + 1 || VpnService.prepare(this) != null)
                    throw new IllegalStateException("FIXTURE_SEQUENCE_OR_CONSENT");
                ParcelFileDescriptor replacement = new Builder()
                        .setSession("Disposable public API drop VPN")
                        .setMtu(1380).setBlocking(true)
                        .addAddress("10.126.0.2", 24)
                        .addRoute("10.126.0.0", 24)
                        .addDisallowedApplication(getPackageName()).establish();
                if (replacement == null) throw new IllegalStateException("FIXTURE_ESTABLISH");
                ParcelFileDescriptor old = tun;
                tun = replacement;
                sequence = next;
                Thread drain = new Thread(() -> {
                    try (FileInputStream input = new FileInputStream(replacement.getFileDescriptor())) {
                        byte[] buffer = new byte[65535];
                        while (input.read(buffer) > 0) discarded.incrementAndGet();
                    } catch (Exception ignored) { /* Closing the replaced descriptor ends the drain. */ }
                }, "discard-only-tun");
                drain.setDaemon(true);
                drain.start();
                if (old != null) old.close();
                long deadline = SystemClock.elapsedRealtime() + 5000;
                String name = null;
                ConnectivityManager cm = getSystemService(ConnectivityManager.class);
                while (SystemClock.elapsedRealtime() < deadline && name == null) {
                    for (Network network : cm.getAllNetworks()) {
                        NetworkCapabilities cap = cm.getNetworkCapabilities(network);
                        LinkProperties link = cm.getLinkProperties(network);
                        if (cap == null || !cap.hasTransport(NetworkCapabilities.TRANSPORT_VPN) || link == null) continue;
                        String iface = link.getInterfaceName();
                        boolean address = link.getLinkAddresses().stream().anyMatch(a -> "10.126.0.2".equals(a.getAddress().getHostAddress()));
                        boolean route = link.getRoutes().stream().anyMatch(r -> "10.126.0.0/24".equals(r.getDestination().toString()));
                        if (iface != null && !iface.equals(installed) && address && route) name = iface;
                    }
                    if (name == null) Thread.sleep(5);
                }
                if (name == null) throw new IllegalStateException("FIXTURE_LINK_DEADLINE");
                installed = name;
                save(true, false, "");
            } catch (Exception e) {
                save(false, false, "FIXTURE_ESTABLISH_OR_READY_FAILED");
                stopSelf();
            }
        });
        return START_NOT_STICKY;
    }

    private synchronized void save(boolean ready, boolean stopped, String failure) {
        try {
            JSONObject value = new JSONObject().put("sequence", sequence).put("ready", ready)
                    .put("stopped", stopped).put("discarded_packets", discarded.get())
                    .put("failure", failure).put("interface", installed == null ? "" : installed);
            AtomicFile file = new AtomicFile(new File(getNoBackupFilesDir(), "drop-vpn.json"));
            FileOutputStream output = file.startWrite();
            try {
                output.write(value.toString().getBytes(StandardCharsets.UTF_8));
                file.finishWrite(output);
            } catch (Exception e) { file.failWrite(output); }
        } catch (Exception ignored) { /* Host requires a complete matching result. */ }
    }

    private void stopFixture() {
        worker.execute(() -> {
            // VpnService is also bound by the system. Waiting for onDestroy
            // before closing its TUN can keep that binding alive indefinitely.
            try { if (tun != null) tun.close(); } catch (Exception ignored) { }
            tun = null;
            save(false, true, "");
            stopForeground(true);
            stopSelf();
        });
    }

    @Override public void onDestroy() {
        worker.shutdownNow();
        try { if (tun != null) tun.close(); } catch (Exception ignored) { }
        save(false, true, "");
        stopForeground(true);
        super.onDestroy();
    }
}
