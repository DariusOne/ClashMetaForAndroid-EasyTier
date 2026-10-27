#!/usr/bin/env python3
"""Stage an explicitly supplied disposable TOML into the prototype only.

Does not install an APK, start VPN, alter CMFA settings or read an existing mesh.
Payload bytes go to adb stdin, never arguments/log output. Not run by CI.
"""
import argparse
from pathlib import Path
import subprocess

PACKAGE = "com.github.metacubex.clash.meshprototype.meta"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--adb", default="adb")
    parser.add_argument("--serial", required=True)
    parser.add_argument("--profile", type=Path, required=True)
    args = parser.parse_args()
    data = args.profile.read_bytes()
    if not 0 < len(data) <= 1024*1024:
        parser.error("Profile must be between 1 byte and 1 MiB")
    data.decode("utf-8", errors="strict")
    base = [args.adb, "-s", args.serial, "shell", "-T", "run-as", PACKAGE, "sh", "-c"]
    # Fixed commands; only input file bytes travel through stdin.
    commands = [
        ("umask 077; mkdir -p no_backup/native-mesh-acceptance; cat > no_backup/native-mesh-acceptance/mesh.toml", data),
        ("umask 077; printf packet-path-only > no_backup/native-mesh-acceptance/enable", b""),
    ]
    for command, payload in commands:
        result = subprocess.run(base + ["'" + command + "'"], input=payload, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if result.returncode:
            raise SystemExit("Prototype staging failed; ensure USB authorization and the debug prototype are installed")
    print("Disposable profile staged in prototype-private storage. VPN was not started.")


if __name__ == "__main__":
    main()
