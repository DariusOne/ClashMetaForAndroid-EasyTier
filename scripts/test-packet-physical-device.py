#!/usr/bin/env python3
"""Explicit physical-device fixture for a newly installed prototype only.

Precondition: user authorized this phone, both matching debug/test APKs installed,
and a disposable container peer prepared. Does not modify other apps, grant VPN
permission with appops, install packages, clear data, or read user profiles.
The operator must restore the recorded pre-test VPN state after finishing.
"""
import argparse
import json
from pathlib import Path
import queue
import re
import subprocess
import threading
import time
import uuid

PACKAGE = 'com.github.metacubex.clash.meshprototype.meta'
FOLDER = 'no_backup/native-mesh-acceptance/'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--adb', default='adb')
    parser.add_argument('--serial', required=True)
    parser.add_argument('--test-root', type=Path, required=True)
    parser.add_argument('--phase', choices=['lifecycle', 'peer'], required=True)
    parser.add_argument('--container')
    parser.add_argument('--probe', type=Path)
    parser.add_argument('--reverse-port', type=int, default=43179)
    parser.add_argument('--host-port', type=int)
    args = parser.parse_args()
    base = [args.adb, '-s', args.serial]
    root = args.test_root.resolve(strict=True)
    def call(*command, timeout=30, check=True):
        return subprocess.run(list(command), capture_output=True, encoding='utf-8', errors='replace', timeout=timeout, check=check)
    def adb(*command, **kwargs):
        return call(*base, *command, **kwargs)
    def stage(name, data):
        assert name in {'physical-consent', 'mesh.toml', 'ci-peer-guard', 'ci-reject-port', 'peer-result.json', 'mode-request.json'}
        command = "'umask 077; mkdir -p " + FOLDER + '; cat > ' + FOLDER + name + "'"
        subprocess.run(base + ['shell', '-T', 'run-as', PACKAGE, 'sh', '-c', command], input=data, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True, timeout=20)
    def read(name):
        assert name in {'peer-ready', 'status.json', 'mode-ready.json'}
        return adb('shell', 'run-as', PACKAGE, 'cat', FOLDER + name, check=False).stdout.strip()
    if adb('shell', 'getprop', 'ro.kernel.qemu').stdout.strip() == '1':
        raise RuntimeError('Physical device required')
    if adb('shell', 'pm', 'path', PACKAGE).stdout.strip() == '':
        raise RuntimeError('Separate prototype missing')
    # Fail on a profile store, rather than clearing any prior test/user state.
    count = adb('shell', 'run-as', PACKAGE, 'sh', '-c', "'find files/imported -mindepth 1 -maxdepth 1 2>/dev/null | wc -l'").stdout.strip()
    if count != '0':
        raise RuntimeError('Prototype contains profiles; nothing was deleted')
    token = str(uuid.uuid4())
    stage('physical-consent', token.encode())
    result = {'kind':'physical-android-native-packet-fixture', 'phase':args.phase, 'passed':False,
              'complete_integration':False, 'dns_fakeip_validated':False, 'discovery_validated':False,
              'ipv6_validated':False, 'physical_transport':'USB reverse to isolated Linux native peer', 'checks':{}}
    instrumentation = None
    helpers = []
    reverse_created = False
    log = (root / (args.phase + '-instrumentation.txt')).open('w', encoding='utf-8')
    try:
        if args.phase == 'peer':
            if not args.container or not re.fullmatch(r'cmfa-native-[a-z0-9-]+', args.container) or not args.probe or not args.host_port:
                raise RuntimeError('Explicit disposable peer and probe required')
            if not all(1024 <= p <= 65535 for p in (args.reverse_port, args.host_port)):
                raise RuntimeError('Invalid test port')
            previous = adb('reverse', '--list').stdout
            if f'tcp:{args.reverse_port} ' in previous:
                raise RuntimeError('Test reverse port already exists')
            adb('reverse', f'tcp:{args.reverse_port}', f'tcp:{args.host_port}')
            reverse_created = True
            adb('push', str(args.probe.resolve(strict=True)), '/data/local/tmp/cmfa-physical-probe')
            adb('shell', 'chmod', '700', '/data/local/tmp/cmfa-physical-probe')
            stage('mesh.toml', (root/'phone.toml').read_bytes())
            stage('ci-peer-guard', b'disposable-physical-only')
            stage('ci-reject-port', b'30103')
        test = 'NativeMeshSmokeTest' if args.phase == 'lifecycle' else 'NativeMeshPeerTest'
        adb('shell', 'am', 'start', '-W', '-n', PACKAGE+'/com.github.kr328.clash.MainActivity')
        instrumentation = subprocess.Popen(base + ['shell','am','instrument','-w','-r','-e','physicalDeviceConsent',token,'-e','class','com.github.kr328.clash.'+test,PACKAGE+'.test/androidx.test.runner.AndroidJUnitRunner'], stdout=log, stderr=subprocess.STDOUT)
        print('Waiting for prototype test; approve Android VPN prompt on the phone if shown.', flush=True)
        if args.phase == 'lifecycle':
            instrumentation.wait(timeout=420)
            result['checks']['requested_cycles'] = 10
        else:
            deadline = time.monotonic()+180
            while time.monotonic()<deadline:
                if instrumentation.poll() is not None:
                    raise RuntimeError('Physical peer harness exited during startup')
                if read('peer-ready') == 'ready': break
                try: status=json.loads(read('status.json'))
                except ValueError: status={}
                if status.get('stage','').startswith('ET_'):
                    raise RuntimeError('Physical peer startup: '+status['stage'])
                time.sleep(.5)
            else: raise RuntimeError('Physical peer startup timeout')
            def docker(*command, **kwargs):
                return call('docker','exec',args.container,*command,**kwargs)
            def counters():
                return json.loads(docker('cat','/tmp/packet-counts.json').stdout)
            for protocol, port in [('tcp',30101),('udp',30102)]:
                before=len(counters()[protocol])
                out=adb('shell','/data/local/tmp/cmfa-physical-probe',protocol+'-client','10.126.0.1',str(port),timeout=65).stdout
                sources=counters()[protocol][before:]
                if 'PASS 5/5' not in out or sources != ['10.126.0.2']*5:
                    raise RuntimeError('Physical outbound packet/source assertion failed: '+protocol)
                result['checks']['outbound_'+protocol]={'passed':5,'expected':5,'virtual_source_verified':True}
                print(protocol+' phone -> peer: 5/5, virtual source verified',flush=True)
            for protocol,port in [('tcp',27441),('udp',27442)]:
                helper=subprocess.Popen(base+['shell','/data/local/tmp/cmfa-physical-probe',protocol+'-server','0.0.0.0',str(port)],stdout=subprocess.PIPE,stderr=subprocess.STDOUT,encoding='utf-8',errors='replace')
                helpers.append(helper)
                events=queue.Queue()
                def consume(stream, events=events):
                    for line in stream: events.put(line.strip())
                thread=threading.Thread(target=consume,args=(helper.stdout,),daemon=True); thread.start()
                if events.get(timeout=10)!='READY': raise RuntimeError('Physical listener failed')
                out=docker('node','/fixtures/physical_peer_client.js',protocol,str(port),timeout=60).stdout
                helper.wait(timeout=10); thread.join(timeout=2)
                lines=[]
                while not events.empty(): lines.append(events.get_nowait())
                if 'PASS 5/5' not in out or 'PASS 5/5' not in lines or helper.returncode:
                    raise RuntimeError('Physical inbound packet assertion failed: '+protocol)
                result['checks']['inbound_'+protocol]={'passed':5,'expected':5}
                print(protocol+' peer -> phone: 5/5',flush=True)
            for direction, command in [('outbound',lambda:adb('shell','ping','-c','5','-W','2','10.126.0.1',timeout=30)),('inbound',lambda:docker('ping','-c','5','-W','2','10.126.0.2',timeout=30))]:
                output=command().stdout
                if not re.search(r'5 (?:packets )?received',output): raise RuntimeError('Physical ICMP assertion failed: '+direction)
                result['checks'][direction+'_icmp']={'passed':5,'expected':5}
                print('ICMP '+direction+': 5/5',flush=True)
            stage('peer-result.json', b'{"passed":true}')
            instrumentation.wait(timeout=45)
        log.flush()
        output=(root/(args.phase+'-instrumentation.txt')).read_text(encoding='utf-8')
        if instrumentation.returncode or 'OK (1 test)' not in output or 'FAILURES!!!' in output:
            raise RuntimeError('Physical instrumentation failed; inspect private report')
        result['passed']=True
        if args.phase=='lifecycle':
            result['checks']['completed_cycles']=10
            result['checks']['native_child_crash_isolation']=True
    except Exception as error:
        # Do not print raw CalledProcessError command/output; profiles are private.
        result['failure_type']=type(error).__name__
        if type(error) is RuntimeError: result['failure']=str(error)
        raise
    finally:
        if args.phase=='peer' and instrumentation and instrumentation.poll() is None:
            try: stage('peer-result.json', b'{"passed":false}'); instrumentation.wait(timeout=20)
            except Exception: pass
        cleanup_errors=[]
        try: adb('shell','am','force-stop',PACKAGE,check=False,timeout=15)
        except Exception: cleanup_errors.append('prototype_stop_unconfirmed')
        if instrumentation and instrumentation.poll() is None:
            instrumentation.terminate()
            try: instrumentation.wait(timeout=10)
            except subprocess.TimeoutExpired: instrumentation.kill(); instrumentation.wait()
        for helper in helpers:
            if helper.poll() is None:
                # The Android probe has its own 15-second idle deadline. Let
                # that child exit before terminating its host adb connection.
                try: helper.wait(timeout=18)
                except subprocess.TimeoutExpired:
                    helper.terminate()
                    try: helper.wait(timeout=5)
                    except subprocess.TimeoutExpired: helper.kill(); helper.wait()
        if reverse_created:
            try: adb('reverse','--remove',f'tcp:{args.reverse_port}',check=False,timeout=15)
            except Exception: cleanup_errors.append('usb_reverse_removal_unconfirmed')
        log.close()
        result['cleanup_errors']=cleanup_errors
        (root/(args.phase+'-result.json')).write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
        print(json.dumps(result),flush=True)


if __name__=='__main__': main()
