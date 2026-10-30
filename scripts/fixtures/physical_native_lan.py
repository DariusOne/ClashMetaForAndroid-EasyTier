#!/usr/bin/env python3
"""Ten-minute TCP underlay for one authorized phone and a local disposable peer.

This is not a general proxy: bind and source must be private IPv4 addresses;
the only upstream is the explicitly selected loopback port. Payloads are never
logged. Shutdown closes both sides of every connection.
"""
import argparse
import ipaddress
import json
from pathlib import Path
import select
import socket
import threading
import time


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--bind', required=True)
    parser.add_argument('--phone', required=True)
    parser.add_argument('--peer-port', type=int, required=True)
    parser.add_argument('--directory', type=Path, required=True)
    args = parser.parse_args()
    for value in (args.bind, args.phone):
        a = ipaddress.IPv4Address(value)
        if not a.is_private or a.is_loopback or a.is_unspecified:
            parser.error('Explicit private LAN addresses required')
    if not 1024 <= args.peer_port <= 65535:
        parser.error('Invalid disposable peer port')
    root = args.directory.resolve(strict=True)
    stop = threading.Event()
    slots = threading.BoundedSemaphore(4)
    lock = threading.Lock()
    counts = {'accepted': 0, 'phone_to_peer': 0, 'peer_to_phone': 0}
    threads = []

    def record(key, amount):
        with lock:
            counts[key] += amount
            pending = root/'native-lan-counts.tmp'
            pending.write_text(json.dumps(counts), encoding='utf-8')
            pending.replace(root/'native-lan-counts.json')

    def forward(phone):
        try:
            with phone, socket.create_connection(('127.0.0.1', args.peer_port), timeout=3) as peer:
                phone.settimeout(2)
                peer.settimeout(2)
                record('accepted', 1)
                while not stop.is_set():
                    readable, _, _ = select.select([phone, peer], [], [], .25)
                    for current in readable:
                        data = current.recv(65536)
                        if not data:
                            return
                        other = peer if current is phone else phone
                        other.sendall(data)
                        record('phone_to_peer' if current is phone else 'peer_to_phone', len(data))
        except OSError:
            pass
        finally:
            phone.close()
            slots.release()

    with socket.socket() as listener:
        listener.bind((args.bind, 0))
        listener.listen(4)
        listener.settimeout(.25)
        record('accepted', 0)
        (root/'native-lan-ready.json').write_text(json.dumps({
            'host':args.bind, 'phone':args.phone, 'port':listener.getsockname()[1],
            'transport':'TCP', 'peer_port':args.peer_port,
        }), encoding='utf-8')
        print('Private native LAN fixture ready; selected phone only.', flush=True)
        deadline = time.monotonic()+600
        try:
            while time.monotonic()<deadline and not (root/'stop').exists():
                try:
                    phone, address = listener.accept()
                except socket.timeout:
                    continue
                if address[0] != args.phone or not slots.acquire(blocking=False):
                    phone.close()
                    continue
                thread = threading.Thread(target=forward, args=(phone,), daemon=True)
                threads.append(thread)
                thread.start()
        finally:
            stop.set()
            for thread in threads:
                thread.join(timeout=5)
    print('Private native LAN fixture stopped.', flush=True)


if __name__ == '__main__':
    main()
