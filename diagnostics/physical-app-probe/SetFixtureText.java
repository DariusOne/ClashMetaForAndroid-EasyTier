package fixture.phone;

import android.app.Instrumentation;
import android.app.UiAutomation;
import android.os.Bundle;
import android.os.SystemClock;
import android.view.accessibility.AccessibilityNodeInfo;
import java.io.File;
import java.io.FileInputStream;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import org.json.JSONObject;

/** Exact-content guarded editor input for the temporary original-app fixture.
 * Does not access the clipboard, change IMEs, or save a configuration. */
public final class SetFixtureText extends Instrumentation {
    @Override public void onCreate(Bundle arguments) { super.onCreate(arguments); start(); }
    private AccessibilityNodeInfo editor(AccessibilityNodeInfo node) {
        if (node == null) return null;
        if (node.isEditable() && "com.kkrainbow.easytier".contentEquals(node.getPackageName())) return node;
        for (int i=0;i<node.getChildCount();i++) {
            AccessibilityNodeInfo found=editor(node.getChild(i));
            if (found!=null) return found;
        }
        return null;
    }
    private String digest(String text) throws Exception {
        StringBuilder result=new StringBuilder();
        for(byte b:MessageDigest.getInstance("SHA-256").digest(text.getBytes(StandardCharsets.UTF_8)))
            result.append(String.format("%02x",b & 255));
        return result.toString();
    }
    @Override public void onStart() {
        Bundle result=new Bundle(); int code=1;
        File file=new File(getTargetContext().getNoBackupFilesDir(),"fixture-editor.json");
        try {
            if (!"com.github.metacubex.clash.socketprobe".equals(getTargetContext().getPackageName()) ||
                    file.length()<1 || file.length()>8192) throw new Exception();
            byte[] bytes=new byte[(int)file.length()];
            try(FileInputStream stream=new FileInputStream(file)) {
                int offset=0,n;
                while(offset<bytes.length && (n=stream.read(bytes,offset,bytes.length-offset))>0) offset+=n;
                if(offset!=bytes.length) throw new Exception();
            }
            JSONObject input=new JSONObject(new String(bytes,StandardCharsets.UTF_8));
            if(input.getLong("expires_ms")<System.currentTimeMillis()) throw new Exception();
            String replacement=input.getString("text");
            if(replacement.length()>4096 || !replacement.contains("fixture-")) throw new Exception();
            UiAutomation automation=getUiAutomation(UiAutomation.FLAG_DONT_SUPPRESS_ACCESSIBILITY_SERVICES);
            AccessibilityNodeInfo current=editor(automation.getRootInActiveWindow());
            if(current==null || !digest(String.valueOf(current.getText())).equals(input.getString("expected_sha256")))
                throw new Exception();
            Bundle args=new Bundle(); args.putCharSequence(AccessibilityNodeInfo.ACTION_ARGUMENT_SET_TEXT_CHARSEQUENCE,replacement);
            if(!current.performAction(AccessibilityNodeInfo.ACTION_SET_TEXT,args)) throw new Exception();
            SystemClock.sleep(300);
            AccessibilityNodeInfo updated=editor(automation.getRootInActiveWindow());
            if(updated==null || !replacement.equals(String.valueOf(updated.getText()))) throw new Exception();
            result.putBoolean("exact_match",true); code=0;
        } catch(Exception error) { result.putString("failure_code","FIXTURE_EDITOR_FAILED"); }
        finally { file.delete(); finish(code,result); }
    }
}
