"""Fixed emulator-only Android test-APK socket comparison; no secret inputs."""
import json
import subprocess
import time

PACKAGE = 'com.github.metacubex.clash.meshprototype.meta.test'
COMPONENT = PACKAGE + '/com.github.kr328.clash.HandoverProbeActivity'


class AndroidUidWatch:
    def __init__(self, adb, sequence, tcp_port, udp_port):
        self.adb, self.sequence = adb, sequence
        launch = subprocess.run(adb + ['shell','am','start','-W','-f','0x10008000',
            '-n',COMPONENT,'--es','guard','disposable-ci-only','--ei','sequence',str(sequence),
            '--ei','tcpPort',str(tcp_port),'--ei','udpPort',str(udp_port)],
            capture_output=True, text=True, timeout=10)
        if launch.returncode:
            combined = launch.stdout + launch.stderr
            code = ('UNKNOWN_OPTION' if 'Unknown option' in combined else
                    'ACTIVITY_NOT_FOUND' if 'Error type 3' in combined else
                    'PERMISSION' if 'Permission Denial' in combined else 'FAILED')
            raise RuntimeError('Android app UID probe launch: '+code)

    def read(self, mode):
        output = subprocess.run(self.adb + ['shell','run-as',PACKAGE,'cat','no_backup/handover-probe/'+mode+'.json'],
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
            if all((self.read(mode) or {}).get('ready') for mode in ('tcp','udp')): return
            time.sleep(.05)
        states = [self.read(mode) or {} for mode in ('tcp','udp')]
        codes = [state.get('failure_code') for state in states]
        code = next((x for x in codes if x in ('INTERRUPTED','FIXTURE_RUNTIME_FAILED')), 'NOT_READY')
        raise RuntimeError('Android app UID probe baseline failed: '+code)

    def running(self):
        states = [self.read(mode) or {} for mode in ('tcp','udp')]
        return all(state.get('ready') and not state.get('done') for state in states)

    def finish(self, sources):
        deadline = time.monotonic()+12
        while time.monotonic() < deadline:
            results = {mode:self.read(mode) for mode in ('tcp','udp')}
            if all(value and value.get('done') for value in results.values()): break
            time.sleep(.05)
        else: raise RuntimeError('Android app UID probe deadline failed')
        for mode,result in results.items():
            peer = sources[mode]()
            result.update(peer_observed=len(peer), peer_wrong_source=sum(ip != '10.126.0.2' for ip in peer))
            result['passed'] = (result['received'] > 0 and result['wrong_source'] == 0 and
                result['invalid_payload'] == 0 and result['peer_wrong_source'] == 0 and not result.get('failure_code'))
        return results

    def close(self):
        subprocess.run(self.adb+['shell','am','force-stop',PACKAGE], capture_output=True, timeout=5)
