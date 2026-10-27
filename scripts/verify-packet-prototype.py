#!/usr/bin/env python3
"""Check prototype APK identity and native payload; no device claims."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def main():
    output = Path(sys.argv[1])
    apks = list(output.glob("*universal*.apk"))
    if len(apks) != 1:
        raise RuntimeError("Expected one universal prototype APK")
    sdk = Path(os.environ.get("ANDROID_SDK_ROOT") or os.environ["ANDROID_HOME"])
    tools = sorted(sdk.glob("build-tools/*/aapt*"))
    tools = [p for p in tools if p.name in ("aapt", "aapt.exe")]
    if not tools:
        raise RuntimeError("Android build-tools aapt is required")
    apk = apks[0]
    badging = subprocess.check_output([str(tools[-1]), "dump", "badging", str(apk)], text=True)
    package = re.search(r"^package: name='([^']+)'", badging, re.M)
    if not package or package[1] != "com.github.metacubex.clash.meshprototype.meta":
        raise RuntimeError("Prototype must have a separate application identity")
    manifest = subprocess.check_output([str(tools[-1]), "dump", "xmltree", str(apk), "AndroidManifest.xml"], text=True)
    if sum('"android.net.VpnService"' in line for line in manifest.splitlines()) != 1 or '":native_mesh"' not in manifest:
        raise RuntimeError("Unexpected VPN/engine process manifest")
    libraries = {}
    with zipfile.ZipFile(apk) as archive:
        for abi in ("arm64-v8a", "x86_64"):
            for name in ("libclash.so", "libbridge.so", "libcmfa_easytier.so"):
                data = archive.read(f"lib/{abi}/{name}")
                if len(data) < 10_000:
                    raise RuntimeError("Truncated native payload")
                digest = hashlib.sha256(data).hexdigest()
                if name == "libcmfa_easytier.so":
                    # AGP may strip debug symbols again; compare the ELF payload
                    # with the actual packaged build output, not an APK label.
                    stamp = json.loads((ROOT / f"core/build/native-jni/{abi}/build-info.json").read_text())
                    original = ROOT / f"core/build/native-jni/{abi}/{name}"
                    if hashlib.sha256(original.read_bytes()).hexdigest() != stamp["sha256"]:
                        raise RuntimeError("Input native artifact changed")
                libraries[f"{abi}/{name}"] = {"sha256": digest, "bytes": len(data)}
    result = {"schema": 1, "package": package[1], "apk_sha256": hashlib.sha256(apk.read_bytes()).hexdigest(),
              "native_libraries": libraries, "kind": "packet-path-development-prototype",
              "complete_integration": False, "device_validated": False}
    (output / "prototype-verification.json").write_text(json.dumps(result, indent=2)+"\n", encoding="utf-8")
    print(json.dumps({"package": package[1], "native_payloads": len(libraries), "device_validated": False}))


if __name__ == "__main__":
    main()
