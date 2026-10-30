"""Bounded ordinary-app socket comparison for CI or an authorized physical fixture."""
import json
import subprocess
import time

PACKAGE = 'com.github.metacubex.clash.meshprototype.meta.test'
COMPONENT = PACKAGE + '/com.github.kr328.clash.HandoverProbeActivity'
PHYSICAL_PACKAGE = 'com.github.metacubex.clash.socketprobe'
MODES = ('tcp','udp','tcp4','udp4')


class AndroidUidWatch:
    def __init__(self, adb, sequence, ports, *, physical_consent=None, expected_source='10.126.0.2'):
        import ipaddress
        import uuid
        if not isinstance(sequence, int) or not 1 <= sequence <= 100:
            raise ValueError('Invalid probe sequence')
        if set(ports) != set(MODES) or any(type(p) is not int or not 1024 <= p <= 65535 for p in ports.values()) or len(set(ports.values())) != 4:
            raise ValueError('Invalid probe ports')
        ipaddress.IPv4Address(expected_source)
        self.adb, self.sequence = adb, sequence
        self.package = PHYSICAL_PACKAGE if physical_consent else PACKAGE
        self.expected_source = expected_source
        guard = ['--es','guard','disposable-ci-only']
        if physical_consent:
            if str(uuid.UUID(physical_consent)) != physical_consent:
                raise ValueError('Invalid physical fixture consent')
            guard = ['--es','guard','authorized-physical-only','--es','consent',physical_consent]
        extras = [part for mode in MODES for part in ('--ei',mode+'Port',str(ports[mode]))]
        launch = subprocess.run(adb + ['shell','am','start','-W','-f','0x10008000',
            '-n',self.package+'/com.github.kr328.clash.HandoverProbeActivity','--ei','sequence',str(sequence),
            ] + guard + extras,
            # MIUI may require a visible, user-approved start confirmation on
            # physical phones. Bound that interaction separately; the socket
            # window and all network deadlines below remain unchanged.
            capture_output=True, text=True, timeout=60 if physical_consent else 10)
        if launch.returncode or 'Error:' in launch.stdout or 'Error type ' in launch.stdout:
            combined = launch.stdout + launch.stderr
            code = ('UNKNOWN_OPTION' if 'Unknown option' in combined else
                    'ACTIVITY_NOT_FOUND' if 'Error type 3' in combined else
                    'PERMISSION' if 'Permission Denial' in combined else 'FAILED')
            raise RuntimeError('Android app UID probe launch: '+code)

    def read(self, mode):
        output = subprocess.run(self.adb + ['shell','run-as',self.package,'cat','no_backup/handover-probe/'+mode+'.json'],
                                capture_output=True, text=True, timeout=3)
        try:
            result = json.loads(output.stdout)
            if result['sequence'] != self.sequence or result['uid'] == result['vpn_owner_uid'] or result['uid'] < 10000:
                return None
            return result
        except (ValueError, KeyError):
            return None

    def ready(self):
        deadline = time.monotonic()+10
        while time.monotonic() < deadline:
            values = [self.read(mode) or {} for mode in MODES]
            if any(v.get('done') for v in values): break
            if all(v.get('ready') for v in values): return
            time.sleep(.05)
        states = [self.read(mode) or {} for mode in MODES]
        codes = [state.get('failure_code') for state in states]
        code = next((x for x in codes if x in ('INTERRUPTED','FIXTURE_RUNTIME_FAILED')), 'NOT_READY')
        raise RuntimeError('Android app UID probe baseline failed: '+code)

    def running(self):
        states = [self.read(mode) or {} for mode in MODES]
        return all(state.get('ready') and not state.get('done') for state in states)

    def finish(self, sources):
        deadline = time.monotonic()+12
        while time.monotonic() < deadline:
            results = {mode:self.read(mode) for mode in MODES}
            if all(value and value.get('done') for value in results.values()): break
            time.sleep(.05)
        else: raise RuntimeError('Android app UID probe deadline failed')
        for mode,result in results.items():
            peer = sources[mode]()
            result.update(peer_observed=len(peer), peer_wrong_source=sum(ip != self.expected_source for ip in peer))
            result['passed'] = (result['received'] > 0 and len(peer) > 0 and result['wrong_source'] == 0 and
                result['invalid_payload'] == 0 and result['peer_wrong_source'] == 0 and not result.get('failure_code'))
        return results

    def close(self):
        subprocess.run(self.adb+['shell','am','force-stop',self.package], capture_output=True, timeout=5)
