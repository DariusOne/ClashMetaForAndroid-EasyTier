#!/usr/bin/env python3
"""Bounded wrong-path detector for one authorized phone on a private LAN.

The disposable Linux peer uses the same destination address in its isolated
namespace. Correct mesh traffic reaches Linux; direct traffic reaches these
Windows/LAN listeners. No route, firewall or existing VPN is changed here.
"""
import argparse
from contextlib import ExitStack
import ipaddress
import json
from pathlib import Path
import socket
import threading
import time

MODES = ('tcp','udp','tcp4','udp4')
PORTS = dict(zip(MODES, (30111,30112,30113,30114)))
PRIVATE = tuple(map(ipaddress.ip_network, ('10.0.0.0/8','172.16.0.0/12','192.168.0.0/16')))


def private_address(value):
    address = ipaddress.IPv4Address(value)
    if not any(address in network for network in PRIVATE):
        raise ValueError('Explicit RFC1918 fixture address required')
    return str(address)


def serve(bind, phone, directory, *, ports=PORTS, duration=600, ready=None):
    bind, phone = private_address(bind), private_address(phone)
    if set(ports) != set(MODES) or len(set(ports.values())) != 4 or any(type(p) is not int or not 1024 <= p <= 65535 for p in ports.values()):
        raise ValueError('Four distinct fixture ports required')
    if not 1 <= duration <= 600: raise ValueError('Bounded fixture duration required')
    root = Path(directory).resolve(strict=True)
    if (root/'underlay-ready.json').exists(): raise ValueError('Do not reuse a live fixture directory')
    stop, lock = threading.Event(), threading.Lock()
    counts = {mode:[] for mode in MODES}
    workers = []
    def record(mode, source=None):
        with lock:
            if source is not None: counts[mode].append(source)
            temporary = root/'underlay-counts.pending'
            temporary.write_text(json.dumps(counts), encoding='utf-8')
            temporary.replace(root/'underlay-counts.json')
    def worker(listener, mode):
        while not stop.is_set():
            try:
                if mode.startswith('udp'):
                    data, source = listener.recvfrom(129)
                    if source[0] != phone: continue
                    record(mode, source[0])
                    if len(data) <= 128: listener.sendto(data,source)
                else:
                    client, source = listener.accept()
                    with client:
                        if source[0] != phone: continue
                        record(mode,source[0])  # Count an empty handshake too.
                        client.settimeout(.25)
                        data=b''
                        while len(data)<128 and not data.endswith(b'\n'):
                            chunk=client.recv(128-len(data))
                            if not chunk: break
                            data+=chunk
                        if data: client.sendall(data)
            except OSError:
                if stop.is_set(): return
    with ExitStack() as stack:
        for mode,port in ports.items():
            listener=stack.enter_context(socket.socket(type=socket.SOCK_DGRAM if mode.startswith('udp') else socket.SOCK_STREAM))
            # Never steal a listener by using SO_REUSEADDR on Windows.
            listener.bind((bind,port)); listener.settimeout(.1)
            if not mode.startswith('udp'): listener.listen(16)
            thread=threading.Thread(target=worker,args=(listener,mode),daemon=True)
            workers.append(thread)
        record('tcp')
        (root/'underlay-ready.json').write_text(json.dumps({'host':bind,'phone':phone,'ports':ports}),encoding='utf-8')
        for thread in workers: thread.start()
        if ready: ready.set()
        try:
            deadline=time.monotonic()+duration
            while time.monotonic()<deadline and not (root/'stop').exists(): stop.wait(.1)
        finally:
            stop.set()
            for thread in workers: thread.join(1)
            (root/'underlay-stopped.json').write_text(json.dumps({'clean':not any(t.is_alive() for t in workers)}),encoding='utf-8')


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--bind',required=True)
    parser.add_argument('--phone',required=True)
    parser.add_argument('--directory',required=True,type=Path)
    args=parser.parse_args()
    serve(args.bind,args.phone,args.directory)


if __name__=='__main__': main()
