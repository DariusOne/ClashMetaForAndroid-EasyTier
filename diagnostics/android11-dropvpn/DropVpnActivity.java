package fixture.dropvpn;

import android.app.Activity;
import android.content.Intent;
import android.os.Bundle;

/** Only included in a throwaway APK built by the CI diagnostic. */
public final class DropVpnActivity extends Activity {
    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        if (DropVpnService.allowed(this) &&
                "disposable-ci-only".equals(getIntent().getStringExtra("guard"))) {
            Intent command = new Intent(this, DropVpnService.class);
            command.putExtra("sequence", getIntent().getIntExtra("sequence", -1));
            startService(command);
        }
        finish();
    }
}
