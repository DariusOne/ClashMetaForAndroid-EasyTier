#!/usr/bin/env python3
"""Lifecycle smoke test on a disposable CI emulator, never a user's phone."""
import json
import os
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = "com.github.metacubex.clash.meshprototype.meta"


def main():
    if os.environ.get("GITHUB_ACTIONS") != "true":
        raise RuntimeError("This script is restricted to a disposable CI emulator")
    devices = subprocess.check_output(["adb", "devices"], text=True)
    serials = re.findall(r"^(emulator-\d+)\s+device$", devices, re.M)
    if len(serials) != 1:
        raise RuntimeError("Expected exactly one ready CI emulator")
    adb = ["adb", "-s", serials[0]]
    def call(*args, timeout=90):
        return subprocess.check_output(adb + list(args), text=True, stderr=subprocess.STDOUT, timeout=timeout)
    if call("shell", "getprop", "ro.kernel.qemu").strip() != "1":
        raise RuntimeError("Refusing to operate on a real device")
    apk = list((ROOT / "app/build/outputs/apk/meta/debug").glob("*universal*.apk"))
    tests = list((ROOT / "app/build/outputs/apk/androidTest/meta/debug").glob("*.apk"))
    if len(apk) != 1 or len(tests) != 1:
        raise RuntimeError("Build both prototype and instrumentation APKs first")
    report = ROOT / "app/build/reports/native-mesh-emulator"
    report.mkdir(parents=True, exist_ok=True)
    result = {"kind": "disposable-emulator-lifecycle-smoke", "passed": False, "cycles": 10,
              "real_device_validated": False, "peer_network_validated": False, "complete_integration": False}
    try:
        call("install", "-r", str(apk[0]))
        call("install", "-r", str(tests[0]))
        call("shell", "appops", "set", PACKAGE, "ACTIVATE_VPN", "allow")
        call("shell", "am", "start", "-W", "-n", PACKAGE + "/com.github.kr328.clash.MainActivity")
        output = call("shell", "am", "instrument", "-w", "-r", "-e", "disposableEmulator", "true",
                      "-e", "class", "com.github.kr328.clash.NativeMeshSmokeTest",
                      PACKAGE + ".test/androidx.test.runner.AndroidJUnitRunner", timeout=360)
        (report / "instrumentation.txt").write_text(output, encoding="utf-8")
        if not re.search(r"OK \(1 test\)", output) or "FAILURES!!!" in output:
            # This fixture contains no user configuration. Surface the bounded
            # assertion/stack trace so lifecycle failures can be diagnosed
            # without exposing general logcat or private profile contents.
            print(output[-12000:], flush=True)
            raise RuntimeError("Android lifecycle smoke test failed; inspect instrumentation report")
        result["passed"] = True
    finally:
        (report / "result.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        (report / "logcat.txt").write_text(call("logcat", "-d", "-t", "2000"), encoding="utf-8")
        call("shell", "am", "force-stop", PACKAGE)
    print(json.dumps(result))


if __name__ == "__main__":
    main()
