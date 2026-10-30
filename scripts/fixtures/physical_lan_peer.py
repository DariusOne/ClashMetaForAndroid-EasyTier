#!/usr/bin/env python3
"""Bounded echo fixture on one explicitly selected private LAN address.

Accepts only the authorized phone IP. No proxy, file access or external traffic.
All listeners exit after ten minutes or when the fixture's stop file is created.
"""
import argparse
import ipaddress
import json
from pathlib import Path
import socket
import threading
import time


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--bind', required=True)
    parser.add_argument('--phone', required=True)
    parser.add_argument('--directory', required=True, type=Path)
    args = parser.parse_args()
    for value in (args.bind, args.phone):
        address = ipaddress.IPv4Address(value)
        if not address.is_private or address.is_loopback or address.is_unspecified:
            parser.error('Explicit private LAN addresses required')
    root = args.directory.resolve(strict=True)
    stop = threading.Event()
    lock = threading.Lock()
    counts = {'tcp': [], 'udp': [], 'reject': []}

    def record(kind, address):
        with lock:
            counts[kind].append(address)
            pending = root / 'lan-counts.tmp'
            pending.write_text(json.dumps(counts), encoding='utf-8')
            pending.replace(root / 'lan-counts.json')

    def serve(listener, kind):
        while not stop.is_set():
            try:
                if kind == 'udp':
                    data, source = listener.recvfrom(128)
                    if source[0] != args.phone:
                        continue
                    record(kind, source[0])
                    listener.sendto(data, source)
                else:
                    connection, source = listener.accept()
                    with connection:
                        if source[0] != args.phone:
                            continue
                        # Count the handshake even when the client sends no data.
                        record(kind, source[0])
                        connection.settimeout(2)
                        data = b''
                        while len(data) < 128 and not data.endswith(b'\n'):
                            part = connection.recv(128 - len(data))
                            if not part:
                                break
                            data += part
                        if data:
                            connection.sendall(data)
            except (socket.timeout, ConnectionError):
                continue
            except OSError:
                if not stop.is_set():
                    stop.set()

    sockets, threads, ports = [], [], {}
    try:
        (root / 'lan-counts.json').write_text(json.dumps(counts), encoding='utf-8')
        for kind in counts:
            listener = socket.socket(type=socket.SOCK_DGRAM if kind == 'udp' else socket.SOCK_STREAM)
            sockets.append(listener)
            listener.bind((args.bind, 0))
            listener.settimeout(.25)
            if kind != 'udp':
                listener.listen(8)
            ports[kind] = listener.getsockname()[1]
            thread = threading.Thread(target=serve, args=(listener, kind), daemon=True)
            threads.append(thread)
            thread.start()
        ready = {'host': args.bind, 'phone': args.phone, 'ports': ports}
        (root / 'lan-ready.json').write_text(json.dumps(ready), encoding='utf-8')
        print('LAN echo fixture ready; only the selected phone is accepted.', flush=True)
        deadline = time.monotonic() + 600
        while time.monotonic() < deadline and not (root / 'stop').exists() and not stop.wait(.25):
            pass
    finally:
        stop.set()
        for listener in sockets:
            listener.close()
        for thread in threads:
            thread.join(timeout=3)
        print('LAN echo fixture stopped.', flush=True)


if __name__ == '__main__':
    main()
