#!/usr/bin/env python3
"""Verify/install the exact physically tested preview; never configure/start VPN.

Default is an offline integrity check. Device output is deliberately not echoed.
Only the separate prototype is installed; signatures are never bypassed and no
package is uninstalled. The APK retains its original manifest/target behavior.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

API = 37
ABI = "arm64-v8a"
PACKAGE = "com.github.metacubex.clash.meshprototype.meta"
APK_NAME = "cmfa-easytier-android17-preview.apk"
APK_SHA256 = "f6560523b63b9b9a437cd7b20be643dea47be7da538c6c7e86da254e28cf404a"
SOURCE_COMMIT = "39ef3fe5c8381dc2c25e0422cca9712866060f4e"


class PreviewError(Exception):
    """Fixed messages only; never include ADB output or supplied identifiers."""


def validate_manifest(value):
    expected = {
        "schema": 1, "channel": "android17-physical-preview",
        "supported_api": API, "supported_abi": ABI, "package": PACKAGE,
        "apk": APK_NAME, "apk_sha256": APK_SHA256,
        "apk_source_commit": SOURCE_COMMIT,
        "manifest_min_sdk": 31, "manifest_target_sdk": 35,
        "complete_integration": False, "production_ui_complete": False,
    }
    if not isinstance(value, dict) or any(
        type(value.get(k)) is not type(v) or value.get(k) != v
        for k, v in expected.items()
    ):
        raise PreviewError("PREVIEW_MANIFEST_MISMATCH")


def verify_bundle(directory):
    try:
        manifest = json.loads((directory / "android17-preview.json").read_text(encoding="utf-8"))
        validate_manifest(manifest)
        apk = directory / APK_NAME
        with apk.open("rb") as source:
            digest = hashlib.file_digest(source, "sha256").hexdigest()
    except PreviewError:
        raise
    except (OSError, ValueError):
        raise PreviewError("PREVIEW_BUNDLE_UNREADABLE") from None
    if digest != APK_SHA256:
        raise PreviewError("PREVIEW_APK_DIGEST_MISMATCH")
    return apk


class Adb:
    def __init__(self, executable="adb", serial=None):
        self.executable = executable
        self.serial = serial

    def _run(self, args, *, selected=True, timeout=30):
        command = [self.executable]
        if selected:
            if not self.serial:
                raise PreviewError("PREVIEW_DEVICE_NOT_SELECTED")
            command += ["-s", self.serial]
        command += args
        try:
            return subprocess.run(command, capture_output=True, text=True,
                                  encoding="utf-8", errors="replace", timeout=timeout)
        except (OSError, subprocess.TimeoutExpired):
            raise PreviewError("PREVIEW_ADB_UNAVAILABLE_OR_TIMEOUT") from None

    def read(self, args, *, selected=True):
        result = self._run(args, selected=selected)
        if result.returncode:
            raise PreviewError("PREVIEW_ADB_READ_FAILED")
        return result.stdout.strip()

    def select(self):
        output = self.read(["devices"], selected=False)
        devices = [m[1] for line in output.splitlines()
                   if (m := re.fullmatch(r"(\S+)\s+device", line.strip()))]
        if self.serial:
            if self.serial not in devices:
                raise PreviewError("PREVIEW_DEVICE_UNAVAILABLE_OR_UNAUTHORIZED")
        elif len(devices) == 1:
            self.serial = devices[0]
        else:
            raise PreviewError("PREVIEW_SELECT_ONE_AUTHORIZED_DEVICE")

    def check_platform(self):
        self.select()
        if self.read(["shell", "getprop", "ro.build.version.sdk"]) != str(API):
            raise PreviewError("PREVIEW_REQUIRES_ANDROID_17_API_37")
        if self.read(["shell", "getprop", "ro.product.cpu.abi"]) != ABI:
            raise PreviewError("PREVIEW_REQUIRES_ARM64_V8A")
        if self.read(["shell", "getprop", "ro.kernel.qemu"]) == "1":
            raise PreviewError("PREVIEW_EMULATOR_NOT_ACCEPTED")

    def install(self, apk):
        self.check_platform()
        result = self._run(["install", "-r", str(apk.resolve())], timeout=180)
        if result.returncode or not re.search(r"(?m)^Success\s*$", result.stdout):
            raise PreviewError("PREVIEW_INSTALL_FAILED_NO_UNINSTALL_ATTEMPTED")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument("--adb", default="adb")
    parser.add_argument("--serial", help="Only needed when multiple devices are connected")
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--device-check", action="store_true", help="Read-only API/ABI check")
    modes.add_argument("--install", action="store_true", help="Install the separate preview only")
    args = parser.parse_args(argv)
    try:
        apk = verify_bundle(args.bundle)
        if args.install:
            Adb(args.adb, args.serial).install(apk)
            print("PREVIEW_INSTALLED: separate application; VPN not started; profiles not imported.")
        elif args.device_check:
            Adb(args.adb, args.serial).check_platform()
            print("PREVIEW_DEVICE_OK: API 37 / arm64-v8a. No device changes made.")
        else:
            print("PREVIEW_APK_VERIFIED: exact physically tested APK. No ADB/network/device actions.")
        return 0
    except PreviewError as error:
        print(str(error), file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("PREVIEW_CANCELLED", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
