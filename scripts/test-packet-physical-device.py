#!/usr/bin/env python3
"""Explicit physical-device fixture for a newly installed prototype only.

Precondition: user authorized this phone, both matching debug/test APKs installed,
and a disposable container peer prepared. Does not modify other apps, grant VPN
permission with appops, install packages, clear data, or read user profiles.
The operator must restore the recorded pre-test VPN state after finishing.
"""
import argparse
import ipaddress
import json
from pathlib import Path
import queue
import re
import shlex
import subprocess
import threading
import time
import tomllib
import uuid
from fixture_file_stage import atomic_stage_script
from fixture_transition_watch import TransitionWatch
from fixture_android_uid_watch import AndroidUidWatch, MODES as APP_MODES, PHYSICAL_PACKAGE

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
    parser.add_argument('--lan-fixture', type=Path)
    parser.add_argument('--native-lan-fixture', type=Path)
    parser.add_argument('--discovery-probes-dir', type=Path)
    parser.add_argument('--rebuild-cycles', type=int, choices=range(0,4), default=0)
    parser.add_argument('--wifi-return-cycles', type=int, choices=range(0,4), default=0)
    parser.add_argument('--proxy-fixture', type=Path)
    parser.add_argument('--transition-probe', type=Path)
    parser.add_argument('--mesh-peer-address', default='10.126.0.1')
    parser.add_argument('--mesh-phone-address', default='10.126.0.2')
    parser.add_argument('--underlay-fixture', type=Path)
    parser.add_argument('--android-app-probe', action='store_true', help='Use the separately installed, consent-gated ordinary-app diagnostic')
    args = parser.parse_args()
    if args.transition_probe and (args.phase != 'peer' or not args.rebuild_cycles):
        parser.error('Transition probe requires peer phase and interface rebuild cycles')
    if args.android_app_probe and (args.phase != 'peer' or not args.rebuild_cycles):
        parser.error('Ordinary-app probe requires peer phase and interface rebuild cycles')
    peer_address = str(ipaddress.IPv4Address(args.mesh_peer_address))
    phone_address = str(ipaddress.IPv4Address(args.mesh_phone_address))
    if not any(ipaddress.IPv4Address(peer_address) in ipaddress.ip_network(cidr) for cidr in ('10.0.0.0/8','172.16.0.0/12','192.168.0.0/16')):
        parser.error('Private controlled peer address required')
    if not any(ipaddress.IPv4Address(phone_address) in ipaddress.ip_network(cidr) for cidr in ('10.0.0.0/8','172.16.0.0/12','192.168.0.0/16')) or phone_address == peer_address:
        parser.error('Distinct private mesh phone address required')
    if args.transition_probe and (peer_address != '10.126.0.1' or phone_address != '10.126.0.2'):
        parser.error('The legacy shell probe has a fixed target; use the ordinary-app probe here')
    if args.underlay_fixture and not args.android_app_probe:
        parser.error('Underlay control requires the ordinary-app probe')
    base = [args.adb, '-s', args.serial]
    root = args.test_root.resolve(strict=True)
    if args.phase == 'peer':
        profile_address = ipaddress.ip_interface(tomllib.loads((root/'phone.toml').read_text(encoding='utf-8'))['ipv4'])
        if str(profile_address.ip) != phone_address:
            parser.error('Disposable profile and expected phone address differ')
        broadcast_address = str(profile_address.network.broadcast_address)
    underlay = None
    if args.underlay_fixture:
        args.underlay_fixture = args.underlay_fixture.resolve(strict=True)
        underlay = json.loads((args.underlay_fixture/'underlay-ready.json').read_text(encoding='utf-8'))
        if underlay['host'] != peer_address or underlay['ports'] != dict(zip(APP_MODES,(30111,30112,30113,30114))):
            parser.error('Underlay and mesh must test exactly the same destination and ports')
        ipaddress.IPv4Address(underlay['phone'])
    lan = None
    native_lan = None
    proxy = None
    if args.proxy_fixture:
        if args.phase != 'peer': parser.error('Proxy fixture requires peer phase')
        args.proxy_fixture=args.proxy_fixture.resolve(strict=True)
        proxy=json.loads((args.proxy_fixture/'proxy-ready.json').read_text(encoding='utf-8'))
        address=ipaddress.IPv4Address(proxy['host'])
        if not address.is_private or address.is_loopback or proxy['destination']!=proxy['host']:
            parser.error('Invalid controlled proxy destination')
        if not all(type(proxy[k]) is int and 1024<=proxy[k]<=65535 for k in ('port','destination_port')):
            parser.error('Invalid proxy fixture ports')
        if not re.fullmatch('[0-9a-f]{16}',proxy['username']) or not re.fullmatch('[0-9a-f]{32}',proxy['password']):
            parser.error('Invalid one-use proxy identity')
    if args.native_lan_fixture:
        if args.phase != 'peer':
            parser.error('Native LAN transport requires the peer phase')
        args.native_lan_fixture = args.native_lan_fixture.resolve(strict=True)
        native_lan = json.loads((args.native_lan_fixture/'native-lan-ready.json').read_text(encoding='utf-8'))
        address = ipaddress.IPv4Address(native_lan['host'])
        if not address.is_private or address.is_loopback or not 1024 <= native_lan['port'] <= 65535:
            parser.error('Invalid native LAN transport')
        # Read only the disposable profile; never expose its random identity.
        profile = tomllib.loads((root/'phone.toml').read_text(encoding='utf-8'))
        if profile.get('peer') != [{'uri':f"tcp://{native_lan['host']}:{native_lan['port']}"}]:
            parser.error('Disposable profile does not match selected LAN fixture')
    if args.wifi_return_cycles and not native_lan:
        parser.error('Wi-Fi interruption tests require the private native LAN fixture')
    if args.lan_fixture:
        if args.phase != 'peer':
            parser.error('LAN fixture requires the peer phase')
        args.lan_fixture = args.lan_fixture.resolve(strict=True)
        lan = json.loads((args.lan_fixture/'lan-ready.json').read_text(encoding='utf-8'))
        for key in ('host', 'phone'):
            address = ipaddress.IPv4Address(lan[key])
            if not address.is_private or address.is_loopback or address.is_unspecified:
                parser.error('Invalid LAN fixture address')
        if set(lan['ports']) != {'tcp','udp','reject'} or not all(type(p) is int and 1024 <= p <= 65535 for p in lan['ports'].values()):
            parser.error('Invalid LAN fixture ports')
        if len(set(lan['ports'].values())) != 3:
            parser.error('LAN fixture ports must differ')
    def call(*command, timeout=30, check=True):
        return subprocess.run(list(command), capture_output=True, encoding='utf-8', errors='replace', timeout=timeout, check=check)
    def adb(*command, **kwargs):
        return call(*base, *command, **kwargs)
    def stage(name, data):
        command = shlex.quote(atomic_stage_script(name))
        subprocess.run(base + ['shell', '-T', 'run-as', PACKAGE, 'sh', '-c', command], input=data, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True, timeout=20)
    def read(name):
        assert name in {'peer-ready', 'status.json', 'mode-ready.json','network-options-ready.json'}
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
              'generic_ipv4_discovery_validated':False,
              'ipv6_validated':False, 'ipv4_large_packet_validated':False,
              'physical_transport':('none (local lifecycle)' if args.phase=='lifecycle' else ('Wi-Fi TCP through private LAN fixture to isolated Linux native peer' if native_lan else 'USB reverse to isolated Linux native peer')), 'checks':{}}
    instrumentation = None
    helpers = []
    transition_watches = []
    app_watch = None
    app_consent_staged = False
    reverse_created = False
    discovery_staged = False
    restore_wifi = False
    log = (root / (args.phase + '-instrumentation.txt')).open('w', encoding='utf-8')
    def stage_app_consent(expected_source):
        nonlocal app_consent_staged
        consent = json.dumps({'token':token, 'expires_ms':int(time.time()*1000)+600000,
            'owner_package':PACKAGE, 'destination':peer_address, 'expected_source':expected_source}).encode()
        app_consent_staged = True
        subprocess.run(base+['shell','-T','run-as',PHYSICAL_PACKAGE,'sh','-c',
            shlex.quote('umask 077; mkdir -p no_backup; cat > no_backup/physical-probe-consent.pending; mv no_backup/physical-probe-consent.pending no_backup/physical-probe-consent.json')],
            input=consent, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True, timeout=10)
    def underlay_counts():
        if (args.underlay_fixture/'underlay-stopped.json').exists():
            raise RuntimeError('Underlay observation fixture expired')
        value=json.loads((args.underlay_fixture/'underlay-counts.json').read_text(encoding='utf-8'))
        if set(value)!=set(APP_MODES): raise RuntimeError('Underlay counter schema mismatch')
        return value
    def positive_control(sequence):
        nonlocal app_watch
        stage_app_consent(underlay['phone'])
        before={mode:len(values) for mode,values in underlay_counts().items()}
        app_watch=AndroidUidWatch(base,sequence,underlay['ports'],physical_consent=token,expected_source=underlay['phone'])
        app_watch.ready()
        values=app_watch.finish({mode:lambda mode=mode:underlay_counts()[mode][before[mode]:] for mode in APP_MODES})
        app_watch.close(); app_watch=None
        if not all(v['passed'] and v['peer_observed']>0 for v in values.values()):
            raise RuntimeError('Alternate physical path positive control failed')
        return values
    try:
        if args.android_app_probe:
            if not adb('shell','pm','path',PHYSICAL_PACKAGE).stdout.strip():
                raise RuntimeError('Separate ordinary-app diagnostic is not installed')
            if underlay:
                result['checks']['underlay_before']=positive_control(91)
            stage_app_consent(phone_address)
        if args.phase == 'peer':
            if not args.container or not re.fullmatch(r'cmfa-native-[a-z0-9-]+', args.container) or not args.probe or not args.host_port:
                raise RuntimeError('Explicit disposable peer and probe required')
            if not all(1024 <= p <= 65535 for p in (args.reverse_port, args.host_port)):
                raise RuntimeError('Invalid test port')
            if not native_lan:
                previous = adb('reverse', '--list').stdout
                if f'tcp:{args.reverse_port} ' in previous:
                    raise RuntimeError('Test reverse port already exists')
                adb('reverse', f'tcp:{args.reverse_port}', f'tcp:{args.host_port}')
                reverse_created = True
            adb('push', str(args.probe.resolve(strict=True)), '/data/local/tmp/cmfa-physical-probe')
            adb('shell', 'chmod', '700', '/data/local/tmp/cmfa-physical-probe')
            if args.transition_probe:
                adb('push', str(args.transition_probe.resolve(strict=True)), '/data/local/tmp/cmfa-transition-probe')
                adb('shell', 'chmod', '700', '/data/local/tmp/cmfa-transition-probe')
            if args.discovery_probes_dir:
                probes=args.discovery_probes_dir.resolve(strict=True)
                discovery_staged=True
                adb('push',str((probes/'discovery-probe-arm64').resolve(strict=True)),'/data/local/tmp/cmfa-discovery-probe')
                adb('shell','chmod','700','/data/local/tmp/cmfa-discovery-probe')
                call('docker','cp',str((probes/'discovery-probe-amd64').resolve(strict=True)),args.container+':/tmp/cmfa-discovery-probe')
                call('docker','exec',args.container,'chmod','700','/tmp/cmfa-discovery-probe')
            stage('mesh.toml', (root/'phone.toml').read_bytes())
            stage('ci-peer-guard', b'disposable-physical-only')
            stage('ci-reject-port', str(lan['ports']['reject'] if lan else 30103).encode())
            if proxy: stage('ci-proxy.json',json.dumps(proxy).encode())
        test = 'NativeMeshSmokeTest' if args.phase == 'lifecycle' else 'NativeMeshPeerTest'
        instrumentation = subprocess.Popen(base + ['shell','am','instrument','-w','-r','-e','physicalDeviceConsent',token,'-e','class','com.github.kr328.clash.'+test,PACKAGE+'.test/androidx.test.runner.AndroidJUnitRunner'], stdout=log, stderr=subprocess.STDOUT)
        # Instrumentation restarts its target. Opening the Activity before that
        # restart can leave a physical phone on its launcher. Wait for the test
        # start event, then open only our prototype's normal Activity.
        launch_deadline = time.monotonic()+20
        while time.monotonic()<launch_deadline:
            if instrumentation.poll() is not None:
                raise RuntimeError('Physical instrumentation exited before foreground launch')
            if 'INSTRUMENTATION_STATUS_CODE: 1' in (root/(args.phase+'-instrumentation.txt')).read_text(encoding='utf-8'):
                break
            time.sleep(.1)
        else:
            raise RuntimeError('Physical instrumentation did not start')
        adb('shell','am','start','-W','-n',PACKAGE+'/com.github.kr328.clash.MainActivity')
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
                out=adb('shell','/data/local/tmp/cmfa-physical-probe',protocol+'-client',peer_address,str(port),timeout=65).stdout
                sources=counters()[protocol][before:]
                if 'PASS 5/5' not in out or sources != [phone_address]*5:
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
                out=docker('node','/fixtures/physical_peer_client.js',protocol,str(port),phone_address,timeout=60).stdout
                helper.wait(timeout=10); thread.join(timeout=2)
                lines=[]
                while not events.empty(): lines.append(events.get_nowait())
                if 'PASS 5/5' not in out or 'PASS 5/5' not in lines or helper.returncode:
                    raise RuntimeError('Physical inbound packet assertion failed: '+protocol)
                result['checks']['inbound_'+protocol]={'passed':5,'expected':5}
                print(protocol+' peer -> phone: 5/5',flush=True)
            for direction, command in [('outbound',lambda:adb('shell','ping','-c','5','-W','2',peer_address,timeout=30)),('inbound',lambda:docker('ping','-c','5','-W','2',phone_address,timeout=30))]:
                output=command().stdout
                if not re.search(r'5 (?:packets )?received',output): raise RuntimeError('Physical ICMP assertion failed: '+direction)
                result['checks'][direction+'_icmp']={'passed':5,'expected':5}
                print('ICMP '+direction+': 5/5',flush=True)
            # 4096 bytes exceeds both virtual interface MTUs. Check intact
            # ICMP payload delivery in both directions, not merely tiny echo.
            for direction, command in [
                ('outbound',lambda:adb('shell','ping','-c','5','-W','2','-s','4096',peer_address,timeout=30)),
                ('inbound',lambda:docker('ping','-c','5','-W','2','-s','4096',phone_address,timeout=30)),
            ]:
                output=command().stdout
                if not re.search(r'5 (?:packets )?received',output):
                    raise RuntimeError('Physical large ICMP assertion failed: '+direction)
                result['checks'][direction+'_icmp_4096']={'passed':5,'expected':5,'payload_bytes':4096}
                print('4096-byte ICMP '+direction+': 5/5',flush=True)
            result['ipv4_large_packet_validated']=True
            if lan:
                def lan_counters():
                    return json.loads((args.lan_fixture/'lan-counts.json').read_text(encoding='utf-8'))
                def lan_probe(kind, allowed):
                    before = len(lan_counters()[kind])
                    protocol = 'udp' if kind == 'udp' else 'tcp'
                    probe = adb('shell','/data/local/tmp/cmfa-physical-probe',protocol+'-client',lan['host'],str(lan['ports'][kind]),check=False,timeout=45)
                    sources = lan_counters()[kind][before:]
                    if allowed:
                        if probe.returncode or 'PASS 5/5' not in probe.stdout or sources != [lan['phone']]*5:
                            raise RuntimeError('Physical nonmesh direct assertion failed: '+kind)
                    elif probe.returncode == 0 or sources:
                        raise RuntimeError('Physical nonmesh rejection assertion failed: '+kind)
                lan_probe('tcp', True)
                lan_probe('udp', True)
                lan_probe('reject', False)
                result['checks']['nonmesh_rule']={'tcp':'5/5','udp':'5/5','reject_accepted_connections':0}
                for sequence, mode in enumerate(('direct','global','rule'),1):
                    stage('mode-request.json',json.dumps({'sequence':sequence,'mode':mode}).encode())
                    deadline = time.monotonic()+20
                    while time.monotonic()<deadline:
                        try: ready_sequence=json.loads(read('mode-ready.json')).get('sequence')
                        except (ValueError,AttributeError): ready_sequence=None
                        if ready_sequence==sequence: break
                        time.sleep(.2)
                    else: raise RuntimeError('Physical CMFA mode did not apply: '+mode)
                    before=len(counters()['tcp'])
                    probe=adb('shell','/data/local/tmp/cmfa-physical-probe','tcp-client',peer_address,'30101',timeout=60,check=False)
                    if probe.returncode or 'PASS 5/5' not in probe.stdout or counters()['tcp'][before:] != [phone_address]*5:
                        result['checks']['failed_mode_probe']={
                            'mode':mode,'exit_code':probe.returncode,
                            'probe_codes':re.findall(r'\b[A-Z][A-Z_]{3,}\b',probe.stderr),
                            'peer_accepted_connections':len(counters()['tcp'])-before,
                        }
                        diagnostics = {
                            'status':read('status.json'),
                            'route_to_test_peer':adb('shell','ip','-4','route','get',peer_address,check=False).stdout,
                            'underlay_test_sockets':docker('ss','-tnp',check=False).stdout,
                        }
                        vpn=adb('shell','dumpsys','vpn_management',check=False).stdout
                        diagnostics['vpn_owners']=[line.strip() for line in vpn.splitlines() if 'Active package name:' in line or 'Active vpn type:' in line]
                        (root/'failed-mode-diagnostics.json').write_text(json.dumps(diagnostics,indent=2)+'\n',encoding='utf-8')
                        raise RuntimeError('Physical mesh path changed with CMFA mode: '+mode)
                    lan_probe('reject',mode=='direct')
                    if mode=='global': lan_probe('udp',False)
                    result['checks']['mode_'+mode]={'mesh_tcp':'5/5','nonmesh_expected':'direct' if mode=='direct' else 'reject','passed':True}
                    print('Nonmesh '+mode+' semantics and independent mesh path: passed',flush=True)
            if native_lan:
                transport_counts=json.loads((args.native_lan_fixture/'native-lan-counts.json').read_text(encoding='utf-8'))
                if not all(transport_counts.get(k,0)>0 for k in ('accepted','phone_to_peer','peer_to_phone')):
                    raise RuntimeError('Native LAN transport did not carry bidirectional traffic')
                result['checks']['native_lan_tcp']=transport_counts
            if discovery_staged:
                discovery={}
                for destination in (broadcast_address,'255.255.255.255','224.0.0.251','239.255.255.250'):
                    for direction in ('outbound','inbound'):
                        phone=base+['shell','/data/local/tmp/cmfa-discovery-probe']
                        peer=['docker','exec',args.container,'/tmp/cmfa-discovery-probe']
                        server=(peer+['server',peer_address,destination,'27443'] if direction=='outbound' else phone+['server',phone_address,destination,'27443'])
                        client=(phone+['client',phone_address,destination,'27443'] if direction=='outbound' else peer+['client',peer_address,destination,'27443'])
                        helper=subprocess.Popen(server,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,encoding='utf-8',errors='replace')
                        helpers.append(helper)
                        events=queue.Queue()
                        def consume_discovery(stream,events=events):
                            for line in stream: events.put(line.strip())
                        thread=threading.Thread(target=consume_discovery,args=(helper.stdout,),daemon=True);thread.start()
                        if events.get(timeout=10)!='READY':
                            raise RuntimeError('Discovery listener failed')
                        probe=call(*client,timeout=50,check=False)
                        helper.wait(timeout=12);thread.join(timeout=2)
                        lines=[]
                        while not events.empty(): lines.append(events.get_nowait())
                        passed=probe.returncode==0 and 'PASS 5/5' in probe.stdout and helper.returncode==0 and 'PASS 5/5' in lines
                        discovery[destination+'/'+direction]={'passed':passed,'expected':5}
                        result['checks']['discovery_ipv4']=discovery
                        if not passed:
                            raise RuntimeError('IPv4 generic discovery failed: '+destination+'/'+direction)
                        print('IPv4 discovery '+destination+' '+direction+': 5/5',flush=True)
                result['generic_ipv4_discovery_validated']=True
            rebuilds=[]
            result['checks']['interface_rebuilds']=rebuilds
            if args.android_app_probe:
                app_before = {mode:len(counters()['app_'+mode]) for mode in APP_MODES}
                if underlay: underlay_before={mode:len(v) for mode,v in underlay_counts().items()}
                app_watch = AndroidUidWatch(base, 90, dict(zip(APP_MODES,(30111,30112,30113,30114))), physical_consent=token,expected_source=phone_address)
                app_watch.ready()
                result['checks']['android_app_steady'] = app_watch.finish({mode:lambda mode=mode:counters()['app_'+mode][app_before[mode]:] for mode in APP_MODES})
                app_watch.close(); app_watch = None
                if not all(x['passed'] for x in result['checks']['android_app_steady'].values()):
                    raise RuntimeError('Ordinary-app unchanged-interface baseline failed')
                if underlay:
                    observed={mode:len(v)-underlay_before[mode] for mode,v in underlay_counts().items()}
                    result['checks']['underlay_steady']=observed
                    if any(observed.values()): raise RuntimeError('Unchanged mesh escaped to the physical listener')
            for sequence in range(1,args.rebuild_cycles+1):
                cycle={'cycle':sequence,'passed':False}
                rebuilds.append(cycle)
                original=json.loads(read('status.json'))
                watches=[]
                if args.transition_probe:
                    for protocol,port in [('tcp',30101),('udp',30102)]:
                        before=len(counters()[protocol])
                        watch=TransitionWatch(base+['shell','/data/local/tmp/cmfa-transition-probe',protocol,str(port)])
                        transition_watches.append(watch)
                        watches.append((protocol,before,watch))
                    for _,_,watch in watches: watch.ready()
                if args.android_app_probe:
                    app_before = {mode:len(counters()['app_'+mode]) for mode in APP_MODES}
                    if underlay: underlay_before={mode:len(v) for mode,v in underlay_counts().items()}
                    app_watch = AndroidUidWatch(base, sequence, dict(zip(APP_MODES,(30111,30112,30113,30114))), physical_consent=token,expected_source=phone_address)
                    app_watch.ready()
                stage('rebuild-request',str(sequence).encode())
                deadline=time.monotonic()+20
                while time.monotonic()<deadline:
                    state=json.loads(read('status.json'))
                    if state.get('stage')=='active' and state.get('rebuild_request')==sequence: break
                    if state.get('stage','').startswith('ET_'): raise RuntimeError('Interface rebuild failed')
                    time.sleep(.2)
                else: raise RuntimeError('Interface rebuild timed out')
                if state['generation']!=original['generation'] or state['interface_revision']<=original['interface_revision']:
                    raise RuntimeError('Rebuild replaced session or did not replace interface')
                covered=all(w.process.poll() is None for _,_,w in watches)
                if app_watch:
                    cycle['android_app_covered_ready'] = app_watch.running()
                    cycle['android_app_transition'] = app_watch.finish({mode:lambda mode=mode:counters()['app_'+mode][app_before[mode]:] for mode in APP_MODES})
                    app_watch.close(); app_watch = None
                    if underlay:
                        cycle['underlay_observations']={mode:len(v)-underlay_before[mode] for mode,v in underlay_counts().items()}
                if watches:
                    cycle['transition']={}
                    for protocol,before,watch in watches:
                        cycle['transition'][protocol]=watch.finish(lambda protocol=protocol,before=before:counters()[protocol][before:])
                    cycle['transition_covered_ready']=covered
                    if not covered or not all(x['passed'] for x in cycle['transition'].values()):
                        raise RuntimeError('Continuous handover packet/source assertion failed')
                if args.android_app_probe and (not cycle['android_app_covered_ready'] or not all(x['passed'] for x in cycle['android_app_transition'].values())):
                    raise RuntimeError('Ordinary-app handover packet/source assertion failed')
                if underlay and any(cycle['underlay_observations'].values()):
                    raise RuntimeError('Ordinary-app handover reached the physical listener')
                for protocol,port in [('tcp',30101),('udp',30102)]:
                    before=len(counters()[protocol])
                    probe=adb('shell','/data/local/tmp/cmfa-physical-probe',protocol+'-client',peer_address,str(port),timeout=60)
                    if 'PASS 5/5' not in probe.stdout or counters()[protocol][before:]!=[phone_address]*5:
                        raise RuntimeError('Mesh did not recover after interface rebuild')
                probe=docker('ping','-c','5','-W','2',phone_address,timeout=30)
                if not re.search(r'5 (?:packets )?received',probe.stdout): raise RuntimeError('Inbound ICMP failed after rebuild')
                if lan: lan_probe('tcp',True); lan_probe('reject',False)
                cycle.update({'passed':True,'outbound_tcp':'5/5','outbound_udp':'5/5','inbound_icmp':'5/5','session_preserved':True})
                result['checks']['interface_rebuilds']=rebuilds
                print('Android interface rebuild '+str(sequence)+': TCP/UDP/ICMP 5/5; same mesh session',flush=True)
            if args.wifi_return_cycles:
                if adb('shell','settings','get','global','wifi_on').stdout.strip()!='1':
                    raise RuntimeError('Wi-Fi must already be enabled before the explicit interruption fixture')
                cycles=[]
                for cycle in range(1,args.wifi_return_cycles+1):
                    original=json.loads(read('status.json'))
                    restore_wifi=True
                    adb('shell','svc','wifi','disable')
                    deadline=time.monotonic()+25
                    while time.monotonic()<deadline:
                        state=json.loads(read('status.json'))
                        if state.get('stage')=='waiting-network' or state.get('network_revision',0)>original.get('network_revision',0): break
                        if state.get('stage','').startswith('ET_'): raise RuntimeError('Network interruption failed closed permanently')
                        time.sleep(.3)
                    else: raise RuntimeError('Physical network loss was not observed')
                    disconnected=state.get('stage')
                    adb('shell','svc','wifi','enable')
                    # Readiness probes do not count toward the strict 5/5 below.
                    deadline=time.monotonic()+75
                    while time.monotonic()<deadline:
                        state=json.loads(read('status.json'))
                        if state.get('stage','').startswith('ET_'): raise RuntimeError('Network return failed permanently')
                        if state.get('stage')=='active' and state.get('physical_transport')=='wifi' and state.get('network_revision',0)>original.get('network_revision',0):
                            ready=adb('shell','ping','-c','1','-W','1',peer_address,check=False,timeout=5)
                            if ready.returncode==0: break
                        time.sleep(.5)
                    else: raise RuntimeError('Mesh did not recover after Wi-Fi return')
                    if state['generation']!=original['generation']: raise RuntimeError('Network return changed mesh identity/session')
                    if state['interface_revision']!=original['interface_revision']: raise RuntimeError('Physical handover unnecessarily replaced the VPN interface')
                    for protocol,port in [('tcp',30101),('udp',30102)]:
                        before=len(counters()[protocol])
                        probe=adb('shell','/data/local/tmp/cmfa-physical-probe',protocol+'-client',peer_address,str(port),timeout=60)
                        if 'PASS 5/5' not in probe.stdout or counters()[protocol][before:]!=[phone_address]*5:
                            raise RuntimeError('Mesh packets failed after Wi-Fi return')
                    probe=docker('ping','-c','5','-W','2',phone_address,timeout=30)
                    if not re.search(r'5 (?:packets )?received',probe.stdout): raise RuntimeError('Inbound Wi-Fi recovery failed')
                    if lan: lan_probe('tcp',True); lan_probe('reject',False)
                    cycles.append({'cycle':cycle,'observed_disconnect_stage':disconnected,'outbound_tcp':'5/5','outbound_udp':'5/5','inbound_icmp':'5/5','session_preserved':True,'interface_preserved':True,'cellular_mesh_transport_validated':False})
                    result['checks']['wifi_return_cycles']=cycles
                    print('Wi-Fi interruption/return '+str(cycle)+': TCP/UDP/ICMP 5/5; same mesh session',flush=True)
            if proxy:
                def proxy_counts():return json.loads((args.proxy_fixture/'proxy-counts.json').read_text(encoding='utf-8'))
                def proxy_probe(direct):
                    for protocol in ('tcp','udp'):
                        before=proxy_counts()
                        out=adb('shell','/data/local/tmp/cmfa-physical-probe',protocol+'-client',proxy['destination'],str(proxy['destination_port']),timeout=60,check=False)
                        after=proxy_counts()
                        selected=('direct_'+protocol) if direct else protocol
                        other=protocol if direct else ('direct_'+protocol)
                        if out.returncode or 'PASS 5/5' not in out.stdout or after[selected]-before[selected]!=5 or after[other]!=before[other]:
                            raise RuntimeError('Nonmesh proxy/direct path mismatch: '+protocol)
                proxy_probe(False)
                result['checks']['nonmesh_socks_proxy']={'tcp':'5/5','udp':'5/5','direct_origin_connections':0,'authentication_required':True}
                for sequence,bypass in ((10,True),(11,False)):
                    stage('network-options-request.json',json.dumps({'sequence':sequence,'bypass_private':bypass}).encode())
                    deadline=time.monotonic()+20
                    while time.monotonic()<deadline:
                        try: ready=json.loads(read('network-options-ready.json')).get('sequence')
                        except (ValueError,AttributeError): ready=None
                        if ready==sequence:break
                        time.sleep(.2)
                    else:raise RuntimeError('Private-network bypass setting did not apply')
                    proxy_probe(bypass)
                    before=len(counters()['tcp'])
                    mesh=adb('shell','/data/local/tmp/cmfa-physical-probe','tcp-client',peer_address,'30101',timeout=60)
                    if 'PASS 5/5' not in mesh.stdout or counters()['tcp'][before:]!=[phone_address]*5:
                        raise RuntimeError('Private-network bypass lost mesh ownership')
                    result['checks']['bypass_private_'+str(bypass).lower()]={'nonmesh_expected':'direct' if bypass else 'authenticated-proxy','tcp':'5/5','udp':'5/5','mesh_tcp':'5/5'}
                    print('bypass-private '+str(bypass)+': original nonmesh path and mesh capture passed',flush=True)
                counts=proxy_counts()
                if counts.get('capacity_rejections',0):
                    raise RuntimeError('Controlled proxy fixture exhausted its capacity')
                result['checks']['proxy_fixture_capacity']={'peak_active':counts.get('peak_active'),'capacity_rejections':0}
            stage('peer-result.json', b'{"passed":true}')
            instrumentation.wait(timeout=45)
        log.flush()
        output=(root/(args.phase+'-instrumentation.txt')).read_text(encoding='utf-8')
        if instrumentation.returncode or 'OK (1 test)' not in output or 'FAILURES!!!' in output:
            raise RuntimeError('Physical instrumentation failed; inspect private report')
        if underlay:
            result['checks']['underlay_after']=positive_control(92)
            result['alternate_path_validated_before_and_after']=True
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
        if app_watch is not None: app_watch.close()
        for watch in transition_watches: watch.close()
        if not result['passed']:
            try:
                crash=adb('shell','run-as',PACKAGE,'dd','if=files/clash/native-mesh-crash.txt','bs=65536','count=64',check=False,timeout=15).stdout
                if crash:
                    (root/(args.phase+'-go-crash-private.txt')).write_text(crash,encoding='utf-8')
                    result['private_crash_saved']=True
            except Exception:
                result['private_crash_unavailable']=True
        if args.phase=='peer' and instrumentation and instrumentation.poll() is None:
            try: stage('peer-result.json', b'{"passed":false}'); instrumentation.wait(timeout=20)
            except Exception: pass
        cleanup_errors=[]
        if app_consent_staged:
            try:
                adb('shell','am','force-stop',PHYSICAL_PACKAGE,timeout=10)
                adb('shell','run-as',PHYSICAL_PACKAGE,'rm','-f','no_backup/physical-probe-consent.json','no_backup/physical-probe-consent.pending',timeout=10)
            except Exception: cleanup_errors.append('app_probe_cleanup_unconfirmed')
        if restore_wifi:
            try:
                adb('shell','svc','wifi','enable',timeout=15)
                result['wifi_enabled_restored']=adb('shell','settings','get','global','wifi_on').stdout.strip()=='1'
                if not result['wifi_enabled_restored']: cleanup_errors.append('wifi_restore_unconfirmed')
            except Exception: cleanup_errors.append('wifi_restore_unconfirmed')
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
        if args.phase=='peer':
            try: adb('shell','rm','-f','/data/local/tmp/cmfa-physical-probe',timeout=15)
            except Exception: cleanup_errors.append('test_probe_removal_unconfirmed')
        if args.transition_probe:
            try: adb('shell','rm','-f','/data/local/tmp/cmfa-transition-probe',timeout=15)
            except Exception: cleanup_errors.append('transition_probe_removal_unconfirmed')
        if discovery_staged:
            try:
                adb('shell','rm','-f','/data/local/tmp/cmfa-discovery-probe',timeout=15)
                call('docker','exec',args.container,'rm','-f','/tmp/cmfa-discovery-probe',timeout=15)
            except Exception: cleanup_errors.append('discovery_probe_removal_unconfirmed')
        log.close()
        result['cleanup_errors']=cleanup_errors
        (root/(args.phase+'-result.json')).write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
        print(json.dumps(result),flush=True)


if __name__=='__main__':
    try: main()
    except Exception as error:
        # ADB command exceptions can contain a physical device identifier.
        print(json.dumps({'fixture_failed':type(error).__name__}),flush=True)
        raise SystemExit(1) from None
