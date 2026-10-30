"""Host regression for finite, ordinary-app socket evidence and phone isolation."""
import json
import subprocess
import unittest
from unittest.mock import patch

from fixture_android_uid_watch import AndroidUidWatch, MODES, PACKAGE, PHYSICAL_PACKAGE


class AppUidWatchTests(unittest.TestCase):
    ports = dict(zip(MODES,(30111,30112,30113,30114)))
    token = '4df77777-7777-4777-8777-777777777777'

    def watch(self, **kwargs):
        with patch('fixture_android_uid_watch.subprocess.run', return_value=subprocess.CompletedProcess([],0,'','')):
            return AndroidUidWatch(['adb','-s','test-device'],1,self.ports,**kwargs)

    def result(self, **kwargs):
        value = dict(sequence=1,uid=10200,vpn_owner_uid=10100,ready=True,done=True,
            received=1,wrong_source=0,invalid_payload=0,failure_code='')
        value.update(kwargs)
        return value

    def test_default_retains_ci_package(self):
        self.assertEqual(PACKAGE,self.watch().package)

    def test_phone_uses_separate_non_instrumentation_package(self):
        self.assertEqual(PHYSICAL_PACKAGE,self.watch(physical_consent=self.token).package)

    def test_physical_launch_confirmation_has_separate_bounded_wait(self):
        for consent,expected in ((None,10),(self.token,60)):
            with self.subTest(consent=bool(consent)), patch('fixture_android_uid_watch.subprocess.run',return_value=subprocess.CompletedProcess([],0,'','')) as run:
                AndroidUidWatch(['adb'],1,self.ports,physical_consent=consent)
                self.assertEqual(expected,run.call_args.kwargs['timeout'])

    def test_invalid_arguments_do_not_launch(self):
        for ports in ({}, dict.fromkeys(MODES,30111), dict(self.ports,tcp=80)):
            with self.subTest(ports=ports), patch('fixture_android_uid_watch.subprocess.run') as run:
                with self.assertRaises(ValueError): AndroidUidWatch(['adb'],1,ports)
                run.assert_not_called()

    def test_read_rejects_stale_or_excluded_uid(self):
        watch=self.watch()
        for value in (self.result(sequence=2),self.result(uid=10100),self.result(uid=2000)):
            response=subprocess.CompletedProcess([],0,json.dumps(value),'')
            with patch('fixture_android_uid_watch.subprocess.run',return_value=response):
                self.assertIsNone(watch.read('tcp'))

    def test_peer_accept_without_reply_still_fails(self):
        watch=self.watch()
        with patch.object(watch,'read',side_effect=lambda mode:self.result()):
            result=watch.finish({mode:lambda:['10.126.0.2','192.168.1.7'] for mode in MODES})
        self.assertTrue(all(not v['passed'] and v['peer_wrong_source']==1 for v in result.values()))

    def test_success_and_configured_source(self):
        watch=self.watch(expected_source='172.19.0.1')
        with patch.object(watch,'read',side_effect=lambda mode:self.result()):
            result=watch.finish({mode:lambda:['172.19.0.1'] for mode in MODES})
        self.assertTrue(all(v['passed'] for v in result.values()))

    def test_client_replies_without_peer_evidence_cannot_pass(self):
        watch=self.watch()
        with patch.object(watch,'read',side_effect=lambda mode:self.result()):
            result=watch.finish({mode:lambda:[] for mode in MODES})
        self.assertTrue(all(not v['passed'] for v in result.values()))

    def test_finished_window_cannot_count_as_ready(self):
        watch=self.watch()
        with patch.object(watch,'read',return_value=self.result()):
            with self.assertRaises(RuntimeError): watch.ready()
            self.assertFalse(watch.running())

    def test_close_only_stops_fixture(self):
        watch=self.watch(physical_consent=self.token)
        with patch('fixture_android_uid_watch.subprocess.run') as run:
            watch.close()
            command=run.call_args.args[0]
            self.assertEqual(['shell','am','force-stop',PHYSICAL_PACKAGE],command[-4:])


if __name__=='__main__': unittest.main()
