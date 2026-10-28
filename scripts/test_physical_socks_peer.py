#!/usr/bin/env python3
"""Loopback regression for the disposable protocol fixture, not VPN acceptance."""
import contextlib
import importlib.util
import json
from pathlib import Path
import socket
import struct
import tempfile
import threading
import time
import types
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location(
    'physical_socks_peer', Path(__file__).parent / 'fixtures/physical_socks_peer.py')
fixture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixture)


def exact(stream, size):
    result = b''
    while len(result) < size:
        part = stream.recv(size - len(result))
        if not part:
            raise EOFError('Fixture closed the connection')
        result += part
    return result


@contextlib.contextmanager
def running(capacity):
    with tempfile.TemporaryDirectory(prefix='cmfa-socks-regression-') as folder:
        root = Path(folder)
        args = types.SimpleNamespace(bind='127.0.0.1', phone='127.0.0.1', directory=root)
        errors = []

        def serve():
            try:
                fixture.serve_fixture(args)
            except BaseException as error:
                errors.append(type(error).__name__)

        with patch.object(fixture, 'MAX_CLIENTS', capacity):
            worker = threading.Thread(target=serve, daemon=True)
            worker.start()
            controls = []
            try:
                until = time.monotonic() + 5
                while not (root / 'proxy-ready.json').exists():
                    if errors or time.monotonic() >= until:
                        raise RuntimeError('Loopback fixture did not start')
                    time.sleep(.01)
                # Atomic-ready creation is not required by the CLI; tolerate the
                # single local write completing before the test reads JSON.
                while True:
                    try:
                        info = json.loads((root / 'proxy-ready.json').read_text())
                        break
                    except ValueError:
                        if time.monotonic() >= until:
                            raise
                        time.sleep(.01)
                yield root, info, controls
            finally:
                for connection in controls:
                    connection.close()
                (root / 'stop').write_text('stop')
                worker.join(timeout=8)
                if worker.is_alive() or errors:
                    raise RuntimeError('Loopback fixture cleanup failed')


def authenticate(info, controls):
    connection = socket.create_connection((info['host'], info['port']), timeout=2)
    controls.append(connection)
    connection.sendall(b'\x05\x01\x02')
    if exact(connection, 2) != b'\x05\x02':
        raise RuntimeError('Fixture did not require authentication')
    user, password = info['username'].encode(), info['password'].encode()
    connection.sendall(b'\x01' + bytes([len(user)]) + user + bytes([len(password)]) + password)
    if exact(connection, 2) != b'\x01\x00':
        raise RuntimeError('Fixture authentication failed')
    return connection


def udp_association(info, controls):
    control = authenticate(info, controls)
    control.sendall(b'\x05\x03\x00\x01' + b'\x00' * 6)
    reply = exact(control, 10)
    if reply[:4] != b'\x05\x00\x00\x01':
        raise RuntimeError('Fixture association failed')
    address = socket.inet_ntoa(reply[4:8]), struct.unpack('!H', reply[8:])[0]
    target = socket.inet_aton(info['destination']) + struct.pack('!H', info['destination_port'])
    packet = b'\x00\x00\x00\x01' + target + b'cmfa-native-packet-regression\n'
    with socket.socket(type=socket.SOCK_DGRAM) as datagram:
        datagram.settimeout(2)
        datagram.sendto(packet, address)
        if datagram.recvfrom(256)[0] != packet:
            raise RuntimeError('Fixture datagram echo failed')
    return control


class CapacityRegression(unittest.TestCase):
    def test_old_eight_slot_limit_reproduces_second_phase_failure(self):
        with running(8) as (root, info, controls):
            for _ in range(8):
                udp_association(info, controls)
            with self.assertRaises((EOFError, ConnectionResetError, ConnectionAbortedError)):
                authenticate(info, controls)
            counts = json.loads((root / 'proxy-counts.json').read_text())
            self.assertEqual(counts['udp'], 8)
            self.assertEqual(counts['capacity_rejections'], 1)

    def test_ten_retained_udp_sessions_allow_tcp_and_remain_bounded(self):
        self.assertEqual(fixture.MAX_CLIENTS, 16)
        with running(fixture.MAX_CLIENTS) as (root, info, controls):
            for _ in range(10):
                udp_association(info, controls)
            target = socket.inet_aton(info['destination']) + struct.pack('!H', info['destination_port'])
            for _ in range(5):
                control = authenticate(info, controls)
                control.sendall(b'\x05\x01\x00\x01' + target)
                self.assertEqual(exact(control, 10)[:4], b'\x05\x00\x00\x01')
                payload = b'cmfa-native-packet-regression\n'
                control.sendall(payload)
                self.assertEqual(exact(control, len(payload)), payload)
                control.close()
            # Wait for all five completed TCP handlers to return their slot.
            until = time.monotonic() + 3
            while json.loads((root / 'proxy-counts.json').read_text())['active'] != 10:
                if time.monotonic() >= until:
                    self.fail('Completed TCP connections retained slots')
                time.sleep(.01)
            counts = json.loads((root / 'proxy-counts.json').read_text())
            self.assertEqual((counts['tcp'], counts['udp']), (5, 10))
            self.assertEqual(counts['capacity_rejections'], 0)
            for _ in range(6):
                udp_association(info, controls)
            with self.assertRaises((EOFError, ConnectionResetError, ConnectionAbortedError)):
                authenticate(info, controls)
            counts = json.loads((root / 'proxy-counts.json').read_text())
            self.assertEqual(counts['peak_active'], 16)
            self.assertEqual(counts['capacity_rejections'], 1)


if __name__ == '__main__':
    unittest.main()
