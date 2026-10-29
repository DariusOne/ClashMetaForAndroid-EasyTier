"""Local-only evidence checks for the bounded alternate-path observer."""
import json
from pathlib import Path
import socket
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from fixtures import physical_underlay_echo as echo


class UnderlayTests(unittest.TestCase):
    def test_only_explicit_private_addresses(self):
        for address in ('10.1.2.3','172.31.4.5','192.168.2.3'):
            self.assertEqual(address,echo.private_address(address))
        for address in ('127.0.0.1','8.8.8.8','169.254.1.2','::1','localhost'):
            with self.subTest(address=address),self.assertRaises(ValueError):
                echo.private_address(address)

    def test_invalid_ports_and_deadline_fail_before_listening(self):
        with tempfile.TemporaryDirectory() as directory,patch.object(echo.socket,'socket') as factory:
            for ports in ({},dict.fromkeys(echo.MODES,30111),dict(echo.PORTS,tcp=80)):
                with self.assertRaises(ValueError):echo.serve('10.1.2.3','10.1.2.4',directory,ports=ports)
            for duration in (0,601):
                with self.assertRaises(ValueError):echo.serve('10.1.2.3','10.1.2.4',directory,duration=duration)
            factory.assert_not_called()

    def test_counts_empty_tcp_and_datagrams_and_closes_all_ports(self):
        # Loopback is allowed only inside this test; production validation is
        # exercised above. No LAN discovery, external traffic or firewall edit.
        reservations=[]
        try:
            for _ in echo.MODES:
                s=socket.socket();s.bind(('127.0.0.1',0));reservations.append(s)
            ports=dict(zip(echo.MODES,(s.getsockname()[1] for s in reservations)))
        finally:
            for s in reservations:s.close()
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);ready=threading.Event();errors=[]
            def server():
                try:echo.serve('127.0.0.1','127.0.0.1',root,ports=ports,duration=5,ready=ready)
                except Exception as error:errors.append(error)
            with patch.object(echo,'private_address',side_effect=lambda value:value):
                thread=threading.Thread(target=server);thread.start()
                try:
                    self.assertTrue(ready.wait(2))
                    with socket.create_connection(('127.0.0.1',ports['tcp']),timeout=1):pass
                    with socket.create_connection(('127.0.0.1',ports['tcp4']),timeout=1) as client:
                        client.sendall(b'bounded-test\n');self.assertEqual(b'bounded-test\n',client.recv(128))
                    for mode in ('udp','udp4'):
                        with socket.socket(type=socket.SOCK_DGRAM) as client:
                            client.settimeout(1);client.sendto(b'bounded-test',('127.0.0.1',ports[mode]))
                            self.assertEqual(b'bounded-test',client.recv(128))
                    with socket.socket(type=socket.SOCK_DGRAM) as outsider:
                        outsider.bind(('127.0.0.2',0));outsider.settimeout(.15)
                        outsider.sendto(b'unrelated-source',('127.0.0.1',ports['udp']))
                        with self.assertRaises(socket.timeout):outsider.recv(128)
                    with socket.socket() as outsider:
                        outsider.bind(('127.0.0.2',0));outsider.settimeout(1)
                        outsider.connect(('127.0.0.1',ports['tcp']))
                        self.assertEqual(b'',outsider.recv(128))
                    deadline=time.monotonic()+1
                    while time.monotonic()<deadline:
                        counts=json.loads((root/'underlay-counts.json').read_text())
                        if all(counts[m] for m in echo.MODES):break
                        time.sleep(.01)
                    self.assertEqual(dict.fromkeys(echo.MODES,['127.0.0.1']),counts)
                    with self.assertRaises(ValueError):echo.serve('127.0.0.1','127.0.0.1',root,ports=ports)
                finally:
                    (root/'stop').touch();thread.join(3)
                self.assertFalse(thread.is_alive());self.assertEqual([],errors)
                self.assertTrue(json.loads((root/'underlay-stopped.json').read_text())['clean'])


if __name__=='__main__':unittest.main()
