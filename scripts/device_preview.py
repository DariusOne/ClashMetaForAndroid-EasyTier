#!/usr/bin/env python3
"""Verify two branded previews; install only for a matching physical device.

Default is offline. No VPN startup, configuration import, uninstall, signature
bypass or access to another application's data. Older evidence is not erased.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys

from android17_preview import Adb as BaseAdb, PreviewError, PACKAGE


ENTRIES = {
    "android11-mi10pro": {
        "api": 30, "android": "11", "abi": "arm64-v8a", "model": "Mi 10 Pro",
        "apk": "clash-easytier-android11-preview.apk", "bytes": 230189321,
        "sha256": "90faa07c4e1db51abb1d08b33d433992fe8f947ac0b259ac4b3de7fbc62fb14f",
        "tested_baseline_sha256": "01906d5b2366e24fe993f1f09d27a84f21eb3a415e716c713435785b2b9bee4f",
        "source_commit": "07d848b8edae1df68e6ba8d4743bb7051058c38d",
        "manifest_min_sdk": 30, "manifest_target_sdk": 35,
        "result_sha256": "f7cd61152bad3c058c769adf68618f29da38362b6e1c9db7a4ced6aec3300a44",
    },
    "android17-25060rk16c": {
        "api": 37, "android": "17", "abi": "arm64-v8a", "model": "25060RK16C",
        "apk": "clash-easytier-android17-preview.apk", "bytes": 230086881,
        "sha256": "84b66b14025e30203751008be9a18f97ae13894122b7409017f989dacab6c8fe",
        "tested_baseline_sha256": "f6560523b63b9b9a437cd7b20be643dea47be7da538c6c7e86da254e28cf404a",
        "source_commit": "39ef3fe5c8381dc2c25e0422cca9712866060f4e",
        "manifest_min_sdk": 31, "manifest_target_sdk": 35,
        "result_sha256": "7a83b394cfcc5ae3f4725b46c9fd54b04dacd43be0133b019ea36be84880272f",
    },
}


def expected_manifest():
    return {
        "schema": 2, "channel": "two-physical-devices-branded-preview", "package": PACKAGE,
        "application_name": "Clash Easytier",
        "branding_only": True, "executable_entries_unchanged": True,
        "branded_network_retested": False,
        "devices": ENTRIES, "complete_integration": False, "production_ui_complete": False,
        "acceptance_basis": "resource-only derivatives of two physical-device finite-window baselines",
        "emulator_failures_retained": True,
    }


def validate_manifest(value):
    if not isinstance(value, dict) or type(value.get("schema")) is not int:
        raise PreviewError("PREVIEW_MANIFEST_MISMATCH")
    if value != expected_manifest():
        raise PreviewError("PREVIEW_MANIFEST_MISMATCH")
    for flag in ("complete_integration", "production_ui_complete", "emulator_failures_retained",
                 "branding_only", "executable_entries_unchanged", "branded_network_retested"):
        if type(value[flag]) is not bool:
            raise PreviewError("PREVIEW_MANIFEST_MISMATCH")


def verify_bundle(directory):
    try:
        value = json.loads((directory / "device-preview.json").read_text(encoding="utf-8"))
        validate_manifest(value)
        verified = {}
        for target, record in ENTRIES.items():
            apk = directory / record["apk"]
            if apk.stat().st_size != record["bytes"]:
                raise PreviewError("PREVIEW_APK_SIZE_MISMATCH")
            with apk.open("rb") as stream:
                digest = hashlib.file_digest(stream, "sha256").hexdigest()
            if digest != record["sha256"]:
                raise PreviewError("PREVIEW_APK_DIGEST_MISMATCH")
            verified[target] = apk
        return verified
    except PreviewError:
        raise
    except (OSError, ValueError):
        raise PreviewError("PREVIEW_BUNDLE_UNREADABLE") from None


class Adb(BaseAdb):
    def check_platform(self):
        self.select()
        if self.read(["shell", "getprop", "ro.kernel.qemu"]) not in ("", "0"):
            raise PreviewError("PREVIEW_EMULATOR_NOT_ACCEPTED")
        values = {
            key: self.read(["shell", "getprop", prop])
            for key, prop in (("api", "ro.build.version.sdk"), ("android", "ro.build.version.release"),
                              ("abi", "ro.product.cpu.abi"), ("model", "ro.product.model"))
        }
        for target, record in ENTRIES.items():
            if all(values[key] == str(record[key]) for key in values):
                return target
        raise PreviewError("PREVIEW_DEVICE_OUTSIDE_TESTED_MODELS_AND_API")

    def install(self, apks):
        target = self.check_platform()
        apk = apks[target]
        result = self._run(["install", "-r", str(apk.resolve())], timeout=180)
        if result.returncode or not re.search(r"(?m)^Success\s*$", result.stdout):
            raise PreviewError("PREVIEW_INSTALL_FAILED_NO_UNINSTALL_ATTEMPTED")
        return target


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument("--adb", default="adb")
    parser.add_argument("--serial", help="Select explicitly when multiple devices are connected")
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--device-check", action="store_true", help="Read-only device and APK selection check")
    modes.add_argument("--install", action="store_true", help="Install only the device's resource-branded preview APK")
    args = parser.parse_args(argv)
    try:
        apks = verify_bundle(args.bundle)
        if args.install:
            target = Adb(args.adb, args.serial).install(apks)
            print("PREVIEW_INSTALLED: " + target + "; separate application, VPN and profiles untouched.")
        elif args.device_check:
            target = Adb(args.adb, args.serial).check_platform()
            print("PREVIEW_DEVICE_OK: " + target + "; no device changes made.")
        else:
            print("PREVIEW_APKS_VERIFIED: both branded APKs; network evidence belongs to their unchanged-code baselines; no ADB/device actions.")
        return 0
    except PreviewError as error:
        print(str(error), file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("PREVIEW_CANCELLED", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
