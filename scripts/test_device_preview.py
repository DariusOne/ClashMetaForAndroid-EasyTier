"""Two-device distribution: exact APK selection, integrity, and no silent expansion."""
import contextlib
import copy
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import device_preview as preview


class DevicePreviewTests(unittest.TestCase):
    def adb(self, target="android11-mi10pro", **override):
        device = preview.ENTRIES[target]
        values = {"ro.kernel.qemu": "0", "ro.build.version.sdk": str(device["api"]),
                  "ro.build.version.release": device["android"], "ro.product.cpu.abi": device["abi"],
                  "ro.product.model": device["model"]}
        values.update(override)
        adb = preview.Adb(serial="fixture-device")
        adb.read = lambda args, **kwargs: ("List of devices attached\nfixture-device\tdevice\n"
                                         if args == ["devices"] else values[args[-1]])
        return adb

    def test_manifest_matches_committed_exact_identity(self):
        manifest = json.loads((Path(__file__).resolve().parents[1]/"delivery/device-preview.json").read_text())
        preview.validate_manifest(manifest)

    def test_manifest_cannot_expand_scope_or_replace_apk(self):
        changes = [lambda m: m.update(schema=True), lambda m: m.update(complete_integration=True),
                   lambda m: m.update(emulator_failures_retained=False), lambda m: m.update(production_ui_complete=0),
                   lambda m: m["devices"]["android11-mi10pro"].update(apk="../other.apk"),
                   lambda m: m["devices"]["android11-mi10pro"].update(api=31),
                   lambda m: m["devices"]["android17-25060rk16c"].update(sha256="0"*64),
                   lambda m: m["devices"].update(extra={})]
        for change in changes:
            value=copy.deepcopy(preview.expected_manifest());change(value)
            with self.subTest(change=change), self.assertRaises(preview.PreviewError):
                preview.validate_manifest(value)

    def test_each_device_selects_its_own_exact_apk(self):
        apks={target:Path(value["apk"]) for target,value in preview.ENTRIES.items()}
        for target in preview.ENTRIES:
            adb=self.adb(target)
            with self.subTest(target=target), patch.object(adb,"_run",return_value=subprocess.CompletedProcess([],0,"Success\n","")) as run:
                self.assertEqual(target,adb.install(apks))
                self.assertEqual(["install","-r",str(apks[target].resolve())],run.call_args.args[0])
                self.assertEqual(1,run.call_count)

    def test_other_api_model_architecture_and_emulator_cannot_install(self):
        cases=[{"ro.build.version.sdk":str(api)} for api in (29,31,35,36,38)]
        cases += [{"ro.product.model":"another-model"},{"ro.product.cpu.abi":"x86_64"},
                  {"ro.kernel.qemu":"1"},{"ro.build.version.release":"12"},
                  {"ro.build.version.sdk":"37","ro.build.version.release":"17"}]
        for values in cases:
            adb=self.adb(**values)
            with self.subTest(values=values),patch.object(adb,"_run") as run:
                with self.assertRaises(preview.PreviewError): adb.install({})
                run.assert_not_called()

    def test_missing_or_modified_bundle_stops_before_adb(self):
        with tempfile.TemporaryDirectory() as directory,patch.object(preview,"Adb") as adb:
            root=Path(directory)
            (root/"device-preview.json").write_text(json.dumps(preview.expected_manifest()))
            for contents in (None,b"wrong APK"):
                if contents: (root/preview.ENTRIES["android11-mi10pro"]["apk"]).write_bytes(contents)
                with contextlib.redirect_stderr(io.StringIO()):
                    self.assertEqual(1,preview.main(["--bundle",directory,"--install"]))
            adb.assert_not_called()

    def test_same_size_wrong_digest_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/"device-preview.json").write_text(json.dumps(preview.expected_manifest()))
            item=preview.ENTRIES["android11-mi10pro"]
            with (root/item["apk"]).open("wb") as f: f.truncate(item["bytes"])
            with self.assertRaisesRegex(preview.PreviewError,"PREVIEW_APK_DIGEST_MISMATCH"):
                preview.verify_bundle(root)

    def test_offline_default_never_calls_adb(self):
        with patch.object(preview,"verify_bundle",return_value={}),patch.object(preview,"Adb") as adb,contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(0,preview.main([]));adb.assert_not_called()

    def test_device_check_never_installs(self):
        adb=self.adb()
        with patch.object(preview,"verify_bundle",return_value={}),patch.object(preview,"Adb",return_value=adb),patch.object(adb,"_run") as run,contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(0,preview.main(["--device-check"]));run.assert_not_called()

    def test_ambiguous_or_unauthorized_devices_are_not_chosen(self):
        for devices in ("", "one\tunauthorized", "one\tdevice\ntwo\tdevice"):
            adb=preview.Adb();adb.read=lambda *args,**kwargs:"List of devices attached\n"+devices
            with self.subTest(devices=devices),self.assertRaises(preview.PreviewError): adb.check_platform()

    def test_install_failure_never_uninstalls_or_exposes_adb_output(self):
        adb=self.adb();private="private device/profile identity"
        with patch.object(adb,"_run",return_value=subprocess.CompletedProcess([],1,private,private)) as run:
            with self.assertRaisesRegex(preview.PreviewError,"PREVIEW_INSTALL_FAILED_NO_UNINSTALL_ATTEMPTED"):
                adb.install({"android11-mi10pro":Path("verified.apk")})
            self.assertEqual(1,run.call_count)

    def test_adb_timeout_is_redacted(self):
        adb=preview.Adb(serial="private-device")
        with patch("android17_preview.subprocess.run",side_effect=subprocess.TimeoutExpired("private command",1)):
            with self.assertRaisesRegex(preview.PreviewError,"PREVIEW_ADB_UNAVAILABLE_OR_TIMEOUT"):
                adb.check_platform()

    def test_mutually_exclusive_actions_do_not_touch_adb(self):
        with patch.object(preview,"Adb") as adb,contextlib.redirect_stderr(io.StringIO()),self.assertRaises(SystemExit):
            preview.main(["--install","--device-check"])
        adb.assert_not_called()


if __name__ == "__main__": unittest.main()
