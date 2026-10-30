package fixture.phone;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.Service;
import android.content.Intent;
import android.os.Handler;
import android.os.IBinder;
import android.os.Looper;

/** Keeps this ordinary application runnable while the stock VPN UI is active.
 * No VPN, socket protection, routing, restart, or battery exemption is used.
 * Started only after the Activity validates its private, expiring consent. */
public final class ProbeKeepAliveService extends Service {
    private final Handler timer = new Handler(Looper.getMainLooper());
    @Override public int onStartCommand(Intent intent, int flags, int startId) {
        NotificationManager manager = getSystemService(NotificationManager.class);
        manager.createNotificationChannel(new NotificationChannel(
                "physical-fixture", "Temporary network diagnostic", NotificationManager.IMPORTANCE_LOW));
        startForeground(1, new Notification.Builder(this, "physical-fixture")
                .setSmallIcon(android.R.drawable.stat_notify_sync)
                .setContentTitle("Temporary network diagnostic")
                .setContentText("Stops automatically within 15 seconds")
                .setOngoing(true).build());
        timer.removeCallbacksAndMessages(null);
        timer.postDelayed(this::stopSelf, 15000);
        return START_NOT_STICKY;
    }
    @Override public void onDestroy() {
        timer.removeCallbacksAndMessages(null);
        stopForeground(STOP_FOREGROUND_REMOVE);
        super.onDestroy();
    }
    @Override public IBinder onBind(Intent intent) { return null; }
}
