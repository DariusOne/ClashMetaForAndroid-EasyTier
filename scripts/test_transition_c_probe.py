"""Real loopback tests of C probe deadlines and source/payload assertions."""
from contextlib import contextmanager
import json
from pathlib import Path
import socket
import subprocess
import tempfile
import threading
import unittest

ROOT = Path(__file__).resolve().parents[1]


@contextmanager
def echo(udp, corrupt=False):
    server = socket.socket(type=socket.SOCK_DGRAM if udp else socket.SOCK_STREAM)
    server.bind(('127.0.0.1', 0))
    server.settimeout(.1)
    if not udp: server.listen(8)
    stopped = threading.Event()
    def serve():
        while not stopped.is_set():
            try:
                if udp:
                    data, source = server.recvfrom(128)
                    server.sendto(b'invalid\n' if corrupt else data, source)
                else:
                    conn, _ = server.accept()
                    with conn:
                        conn.settimeout(.2)
                        data = b''
                        while not data.endswith(b'\n') and len(data) < 128:
                            chunk = conn.recv(128-len(data))
                            if not chunk: break
                            data += chunk
                        conn.sendall(b'invalid\n' if corrupt else data)
            except OSError:
                if stopped.is_set(): return
    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    try: yield server.getsockname()[1]
    finally:
        stopped.set(); server.close(); thread.join(2)
        if thread.is_alive(): raise RuntimeError('test echo did not stop')


class BionicProbeBounds(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix='cmfa-c-probe-')
        cls.addClassCleanup(cls.temp.cleanup)
        cls.probe = Path(cls.temp.name)/'probe'
        subprocess.run(['cc','-Wall','-Wextra','-Werror','-O2','-DTRANSITION_PROBE_UNIT_TEST',
            str(ROOT/'scripts/fixtures/transition_probe.c'),'-o',str(cls.probe)],check=True)

    def probe_result(self, mode, port):
        run = subprocess.run([str(self.probe), mode, str(port)],capture_output=True,text=True,timeout=2)
        self.assertEqual(1, run.returncode)  # loopback is deliberately the wrong source
        result = json.loads(run.stdout.splitlines()[-1])
        self.assertLess(result['elapsed_ms'],1000)
        return result,run.stdout

    def test_successful_wrong_source_is_rejected_for_both_protocols(self):
        for mode in ('tcp','udp'):
            with self.subTest(mode=mode), echo(mode == 'udp') as port:
                result, output = self.probe_result(mode,port)
                self.assertGreater(result['received'],0)
                self.assertGreaterEqual(result['wrong_source'],result['received'])
                self.assertEqual(result['wrong_source'],result['other_source'])
                self.assertEqual(0,result['clash_gateway_source'])
                self.assertIn('WATCH_READY\n',output)

    def test_unresponsive_datagram_has_total_deadline(self):
        with socket.socket(type=socket.SOCK_DGRAM) as server:
            server.bind(('127.0.0.1',0))
            result,output=self.probe_result('udp',server.getsockname()[1])
            self.assertEqual(0,result['received'])
            self.assertEqual(result['attempts'],result['blocked'])
            self.assertNotIn('WATCH_READY',output)

    def test_corrupt_reply_cannot_establish_baseline(self):
        with echo(True,True) as port:
            result,output=self.probe_result('udp',port)
            self.assertEqual(0,result['received'])
            self.assertGreater(result['invalid_payload'],0)
            self.assertNotIn('WATCH_READY',output)

    def test_invalid_endpoint_is_rejected_before_network(self):
        for port in ('','0','-1','65536','1024x'):
            run=subprocess.run([str(self.probe),'tcp',port],capture_output=True,text=True,timeout=2)
            self.assertEqual(2,run.returncode)
            self.assertEqual('',run.stdout)


if __name__ == '__main__': unittest.main()
