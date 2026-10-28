#!/usr/bin/env python3
"""Bounded authenticated SOCKS protocol fixture, NOT a forwarding proxy.

Only the selected phone may connect. The single synthetic destination is echoed
inside this process: there is no outbound connect/sendto to the requested target.
Private credentials are generated per run and never printed or counted in logs.
"""
import argparse
import hmac
import ipaddress
import json
from pathlib import Path
import secrets
import socket
import struct
import threading
import time


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--bind',required=True)
    parser.add_argument('--phone',required=True)
    parser.add_argument('--directory',type=Path,required=True)
    args=parser.parse_args()
    for v in (args.bind,args.phone):
        a=ipaddress.IPv4Address(v)
        if not a.is_private or a.is_loopback or a.is_unspecified: parser.error('Explicit private addresses required')
    root=args.directory.resolve(strict=True)
    username,password=secrets.token_hex(8),secrets.token_hex(16)
    destination=args.bind
    direct_tcp=socket.socket()
    direct_udp=socket.socket(type=socket.SOCK_DGRAM)
    direct_tcp.bind((args.bind,0))
    port=direct_tcp.getsockname()[1]
    direct_udp.bind((args.bind,port))
    direct_tcp.listen(8)
    direct_tcp.settimeout(.25);direct_udp.settimeout(.25)
    target=socket.inet_aton(destination)+struct.pack('!H',port)
    stop=threading.Event()
    lock=threading.Lock()
    slots=threading.BoundedSemaphore(8)
    threads=[]
    counts={'tcp':0,'udp':0,'authenticated':0,'direct_tcp':0,'direct_udp':0}
    def record(key):
        with lock:
            if key: counts[key]+=1
            pending=root/'proxy-counts.tmp'
            pending.write_text(json.dumps(counts),encoding='utf-8')
            pending.replace(root/'proxy-counts.json')
    def exact(s,n):
        data=b''
        while len(data)<n:
            part=s.recv(n-len(data))
            if not part: raise EOFError
            data+=part
        return data
    def address(s,kind):
        if kind==1: return exact(s,6)
        if kind==3:
            size=exact(s,1)[0]; exact(s,size+2)
        elif kind==4: exact(s,18)
        raise ValueError('Unsupported fixture target')
    def direct(listener,udp):
        while not stop.is_set():
            try:
                if udp:
                    data,remote=listener.recvfrom(128)
                    if remote[0]==args.phone and data.startswith(b'cmfa-native-packet-'):
                        record('direct_udp');listener.sendto(data,remote)
                else:
                    client,remote=listener.accept()
                    with client:
                        if remote[0]!=args.phone: continue
                        client.settimeout(2)
                        record('direct_tcp')
                        data=b''
                        while len(data)<128 and not data.endswith(b'\n'): data+=exact(client,1)
                        if data.startswith(b'cmfa-native-packet-'):client.sendall(data)
            except (OSError,EOFError):
                if stop.is_set():break
    def serve(client):
        udp=None
        try:
            with client:
                client.settimeout(3)
                version,count=exact(client,2)
                if version!=5 or not 1<=count<=16 or 2 not in exact(client,count): return
                client.sendall(b'\x05\x02')
                version,size=exact(client,2)
                user=exact(client,size)
                secret=exact(client,exact(client,1)[0])
                if version!=1 or not hmac.compare_digest(user,username.encode()) or not hmac.compare_digest(secret,password.encode()):
                    client.sendall(b'\x01\x01');return
                client.sendall(b'\x01\x00');record('authenticated')
                version,command,reserved,kind=exact(client,4)
                requested=address(client,kind)
                if version!=5 or reserved!=0: return
                if command==1 and requested==target:
                    record('tcp')
                    client.sendall(b'\x05\x00\x00\x01'+b'\x00'*6)
                    data=b''
                    while len(data)<128 and not data.endswith(b'\n'):
                        data+=exact(client,1)
                    if data.startswith(b'cmfa-native-packet-') and data.endswith(b'\n'):
                        client.sendall(data)
                elif command==3:
                    udp=socket.socket(type=socket.SOCK_DGRAM)
                    udp.bind((args.bind,0));udp.settimeout(.2)
                    client.sendall(b'\x05\x00\x00\x01'+socket.inet_aton(args.bind)+struct.pack('!H',udp.getsockname()[1]))
                    client.setblocking(False)
                    expires=time.monotonic()+40
                    source=None
                    while not stop.is_set() and time.monotonic()<expires:
                        try:
                            if client.recv(1)==b'': break
                        except BlockingIOError: pass
                        try: data,remote=udp.recvfrom(256)
                        except socket.timeout: continue
                        if remote[0]!=args.phone or (source and source!=remote): continue
                        if data[:4]!=b'\x00\x00\x00\x01' or data[4:10]!=target: continue
                        if not data[10:].startswith(b'cmfa-native-packet-') or not data.endswith(b'\n'): continue
                        source=remote
                        record('udp');udp.sendto(data,remote)
                else:
                    client.sendall(b'\x05\x02\x00\x01'+b'\x00'*6)
        except (OSError,EOFError,ValueError): pass
        finally:
            if udp: udp.close()
            client.close();slots.release()
    record(None)
    for listener,udp in [(direct_tcp,False),(direct_udp,True)]:
        t=threading.Thread(target=direct,args=(listener,udp),daemon=True);threads.append(t);t.start()
    with socket.socket() as listener:
        listener.bind((args.bind,0));listener.listen(8);listener.settimeout(.25)
        (root/'proxy-ready.json').write_text(json.dumps({'host':args.bind,'phone':args.phone,'port':listener.getsockname()[1],'username':username,'password':password,'destination':destination,'destination_port':port}),encoding='utf-8')
        print('Authenticated fixed-destination SOCKS fixture ready.',flush=True)
        deadline=time.monotonic()+600
        try:
            while time.monotonic()<deadline and not (root/'stop').exists():
                try: client,remote=listener.accept()
                except socket.timeout: continue
                if remote[0]!=args.phone or not slots.acquire(blocking=False): client.close();continue
                t=threading.Thread(target=serve,args=(client,),daemon=True);threads.append(t);t.start()
        finally:
            stop.set()
            direct_tcp.close();direct_udp.close()
            for t in threads: t.join(timeout=4)
    print('SOCKS fixture stopped.',flush=True)


if __name__=='__main__': main()
