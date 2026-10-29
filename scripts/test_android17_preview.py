"""Distribution boundary: no unsupported install, no uninstall, no raw ADB logs."""
import contextlib
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import android17_preview as preview


class PreviewTests(unittest.TestCase):
    def manifest(self):
        return json.loads((Path(__file__).resolve().parents[1] /
                           "delivery/android17-preview.json").read_text(encoding="utf-8"))

    def adb(self, api="37", abi="arm64-v8a", emulator="0", devices="private-device\tdevice"):
        adb = preview.Adb()
        def read(args, **kwargs):
            if args == ["devices"]:
                return "List of devices attached\n" + devices
            return {"ro.build.version.sdk": api, "ro.product.cpu.abi": abi,
                    "ro.kernel.qemu": emulator}[args[-1]]
        adb.read = read
        return adb

    def test_committed_manifest_is_locked_to_tested_apk(self):
        preview.validate_manifest(self.manifest())
        for key, value in (("supported_api", 31), ("complete_integration", True),
                           ("package", "com.github.metacubex.clash.meta"),
                           ("apk", "../foreign.apk"), ("schema", True)):
            bad = self.manifest()
            bad[key] = value
            with self.subTest(key=key), self.assertRaises(preview.PreviewError):
                preview.validate_manifest(bad)

    def test_mutated_or_missing_apk_fails_before_adb(self):
        with tempfile.TemporaryDirectory() as root, patch.object(preview.Adb, "install") as install:
            path = Path(root)
            (path / "android17-preview.json").write_text(json.dumps(self.manifest()))
            for data in (None, b"different-apk"):
                if data:
                    (path / preview.APK_NAME).write_bytes(data)
                with contextlib.redirect_stderr(io.StringIO()):
                    self.assertEqual(1, preview.main(["--bundle", root, "--install"]))
            install.assert_not_called()

    def test_offline_check_never_calls_adb(self):
        with patch.object(preview, "verify_bundle", return_value=Path("verified.apk")), \
             patch.object(preview, "Adb") as adb, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(0, preview.main([]))
            adb.assert_not_called()

    def test_unsupported_platforms_never_install(self):
        cases = [dict(api=str(api)) for api in (30, 31, 35, 36, 38)]
        cases += [dict(abi="x86_64"), dict(emulator="1")]
        for case in cases:
            adb = self.adb(**case)
            with self.subTest(case=case), patch.object(adb, "_run") as run:
                with self.assertRaises(preview.PreviewError):
                    adb.install(Path("verified.apk"))
                run.assert_not_called()

    def test_exact_supported_platform_passes(self):
        self.adb().check_platform()

    def test_zero_or_ambiguous_devices_rejected(self):
        for devices in ("", "first\tdevice\nsecond\tdevice", "first\tunauthorized"):
            with self.subTest(devices=devices), self.assertRaises(preview.PreviewError):
                self.adb(devices=devices).check_platform()

    def test_explicit_selection_must_be_authorized(self):
        adb = self.adb()
        adb.serial = "unrelated-device"
        with self.assertRaises(preview.PreviewError):
            adb.check_platform()

    def test_install_failure_never_uninstalls_or_echoes_output(self):
        adb = self.adb()
        result = subprocess.CompletedProcess([], 1, "private diagnostic", "private identity")
        with patch.object(adb, "_run", return_value=result) as run:
            with self.assertRaises(preview.PreviewError) as error:
                adb.install(Path("verified.apk"))
            self.assertEqual("PREVIEW_INSTALL_FAILED_NO_UNINSTALL_ATTEMPTED", str(error.exception))
            self.assertEqual(1, run.call_count)
            self.assertEqual(["install", "-r"], run.call_args.args[0][:2])

    def test_install_success_does_not_start_vpn(self):
        adb = self.adb()
        with patch.object(adb, "_run", return_value=subprocess.CompletedProcess([], 0, "Success\n", "")) as run:
            adb.install(Path("verified.apk"))
            self.assertEqual(1, run.call_count)

    def test_timeout_never_exposes_device_or_subprocess_text(self):
        adb = preview.Adb(serial="private-device")
        with patch("android17_preview.subprocess.run", side_effect=subprocess.TimeoutExpired("private command", 1)):
            with self.assertRaises(preview.PreviewError) as error:
                adb.read(["shell", "getprop"])
            self.assertEqual("PREVIEW_ADB_UNAVAILABLE_OR_TIMEOUT", str(error.exception))


if __name__ == "__main__":
    unittest.main()
