"""Bounded public-API control on a NEW GitHub Android 11 emulator only.

Builds two tiny Java APKs without Gradle, native libraries, Mihomo or EasyTier.
The first only discards packets; the second uses ordinary app-UID sockets.
No APK is exported. A failing containment result is NOT a product fix.
"""
from contextlib import ExitStack
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
import zipfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
from fixture_android_uid_watch import AndroidUidWatch, MODES
from importlib.util import spec_from_file_location, module_from_spec

# Reuse only the bounded synthetic echo server, not its native runner.
spec = spec_from_file_location('peer_fixture', ROOT / 'scripts/test-packet-native-peer.py')
peer_fixture = module_from_spec(spec)
spec.loader.exec_module(peer_fixture)
PACKAGE = 'com.github.metacubex.clash.meshprototype.meta'
TEST_PACKAGE = PACKAGE + '.test'
REPORT = ROOT / 'diagnostics/android11-dropvpn/result'


def run(command, **kwargs):
    return subprocess.run(command, check=True, text=True, capture_output=True, timeout=90, **kwargs).stdout


def build_apk(folder, sdk, package, sources, application, key):
    folder.mkdir()
    classes, dex = folder / 'classes', folder / 'dex'
    classes.mkdir(); dex.mkdir()
    jar = sdk / 'platforms/android-35/android.jar'
    tools = sdk / 'build-tools/35.0.0'
    manifest = folder / 'AndroidManifest.xml'
    manifest.write_text(f'''<manifest xmlns:android="http://schemas.android.com/apk/res/android" package="{package}">
<uses-sdk android:minSdkVersion="26" android:targetSdkVersion="35"/>
<uses-permission android:name="android.permission.INTERNET"/>
<uses-permission android:name="android.permission.ACCESS_NETWORK_STATE"/>
<uses-permission android:name="android.permission.FOREGROUND_SERVICE"/>
<queries><package android:name="com.github.metacubex.clash.meshprototype.meta"/></queries>
<application android:debuggable="true" android:label="Disposable VPN diagnostic">{application}</application>
</manifest>''', encoding='utf-8')
    run(['javac', '--release', '8', '-cp', str(jar), '-d', str(classes), *map(str, sources)])
    run([str(tools / 'd8'), '--min-api', '26', '--lib', str(jar), '--output', str(dex), *map(str, classes.rglob('*.class'))])
    apk, aligned = folder / 'unsigned.apk', folder / 'aligned.apk'
    run([str(tools / 'aapt'), 'package', '-f', '-M', str(manifest), '-I', str(jar), '-F', str(apk)])
    with zipfile.ZipFile(apk, 'a') as archive:
        for path in dex.glob('*.dex'): archive.write(path, path.name)
    run([str(tools / 'zipalign'), '-f', '4', str(apk), str(aligned)])
    # One-use, nonsecret signing key for these throwaway fixture packages only.
    run([str(tools / 'apksigner'), 'sign', '--ks', str(key), '--ks-pass', 'pass:fixture-only', str(aligned)])
    return aligned


def main():
    if os.environ.get('GITHUB_ACTIONS') != 'true' or os.name != 'posix':
        raise RuntimeError('New disposable GitHub emulator only')
    devices = re.findall(r'^(emulator-\d+)\s+device$', run(['adb', 'devices']), re.M)
    if len(devices) != 1: raise RuntimeError('One disposable emulator required')
    adb = ['adb', '-s', devices[0]]
    def present(package):
        value = subprocess.run(adb + ['shell', 'pm', 'path', package], text=True, capture_output=True, timeout=10)
        if value.returncode not in (0, 1): raise RuntimeError('Package inventory failed')
        return 'package:' in value.stdout
    if run(adb + ['shell', 'getprop', 'ro.kernel.qemu']).strip() != '1' or run(adb + ['shell', 'getprop', 'ro.build.version.sdk']).strip() != '30':
        raise RuntimeError('Real devices and other platforms forbidden')
    for package in (PACKAGE, TEST_PACKAGE):
        if present(package):
            raise RuntimeError('Pre-existing package: never replace user or other fixture data')
    for setting in ('always_on_vpn_app', 'always_on_vpn_lockdown'):
        if run(adb + ['shell', 'settings', 'get', 'secure', setting]).strip() not in ('null', '0', ''):
            raise RuntimeError('System VPN settings must be unset')
    addresses = json.loads(run(['ip', '-j', 'address']))
    if any(a.get('local') == '10.126.0.1' for row in addresses for a in row.get('addr_info', [])):
        raise RuntimeError('Synthetic fixture address already exists')
    REPORT.mkdir(parents=True, exist_ok=True)
    result = {'kind': 'public-api-drop-only-vpn', 'api': 30, 'engines_loaded': [],
              'system_settings_changed': False, 'contained': False, 'complete_integration': False,
              'real_device_validated': False, 'windows': []}
    installed, alias = [], False
    watch = None
    try:
        with tempfile.TemporaryDirectory(prefix='public-vpn-only-') as tmp, ExitStack() as stack:
            tmp = Path(tmp)
            sdk = Path(os.environ.get('ANDROID_SDK_ROOT') or os.environ['ANDROID_HOME'])
            result['image'] = {p: run(adb + ['shell', 'getprop', p]).strip() for p in (
                'ro.build.fingerprint', 'ro.build.version.security_patch', 'ro.build.version.incremental')}
            key = tmp / 'fixture.p12'
            run(['keytool', '-genkeypair', '-keystore', str(key), '-storepass', 'fixture-only', '-keypass', 'fixture-only',
                 '-alias', 'fixture', '-dname', 'CN=Disposable fixture', '-keyalg', 'RSA', '-validity', '1'])
            apk = build_apk(tmp / 'vpn', sdk, PACKAGE, list(Path(__file__).parent.glob('*.java')),
                '<activity android:name="fixture.dropvpn.DropVpnActivity" android:exported="true"/>'
                '<service android:name="fixture.dropvpn.DropVpnService" android:permission="android.permission.BIND_VPN_SERVICE" android:exported="false">'
                '<intent-filter><action android:name="android.net.VpnService"/></intent-filter></service>', key)
            probe = build_apk(tmp / 'probe', sdk, TEST_PACKAGE,
                [ROOT / 'app/src/androidTest/java/com/github/kr328/clash/HandoverProbeActivity.java'],
                '<activity android:name="com.github.kr328.clash.HandoverProbeActivity" android:exported="true"/>', key)
            for package, binary in ((PACKAGE, apk), (TEST_PACKAGE, probe)):
                run(adb + ['install', '-t', str(binary)]); installed.append(package)
            run(['sudo', '-n', 'ip', 'address', 'add', '10.126.0.1/32', 'dev', 'lo']); alias = True
            # Grant consent only on this verified empty disposable emulator.
            run(adb + ['shell', 'appops', 'set', PACKAGE, 'ACTIVATE_VPN', 'allow'])
            sequence = 0

            def status():
                try: return json.loads(run(adb + ['shell', 'run-as', PACKAGE, 'cat', 'no_backup/drop-vpn.json']))
                except (subprocess.SubprocessError, ValueError): return {}

            def command(value):
                run(adb + ['shell', 'am', 'start', '-W', '-f', '0x10008000', '-n', PACKAGE + '/fixture.dropvpn.DropVpnActivity',
                           '--es', 'guard', 'disposable-ci-only', '--ei', 'sequence', str(value)])

            def replace():
                nonlocal sequence
                sequence += 1
                previous = status().get('interface')
                command(sequence)
                deadline = time.monotonic() + 6
                while time.monotonic() < deadline:
                    value = status()
                    if value.get('failure'): raise RuntimeError('Public API VPN failed')
                    if value.get('sequence') == sequence and value.get('ready'):
                        if previous == value.get('interface'): raise RuntimeError('Interface was not replaced')
                        return value
                    time.sleep(.02)
                raise RuntimeError('Public API VPN ready timeout')

            def window(label, changes):
                nonlocal watch
                echoes = {mode: peer_fixture.Echo(mode.startswith('udp')) for mode in MODES}
                for echo in echoes.values(): stack.callback(echo.close)
                watch = AndroidUidWatch(adb, len(result['windows']) + 60, {mode:e.port for mode,e in echoes.items()})
                deadline = time.monotonic() + 3
                while time.monotonic() < deadline:
                    states = [watch.read(mode) for mode in MODES]
                    if all(s is not None and not s['done'] for s in states): break
                    time.sleep(.02)
                else: raise RuntimeError('App UID probes did not start')
                replacements = []
                for _ in range(changes):
                    if any((watch.read(mode) or {}).get('done') for mode in MODES):
                        raise RuntimeError('Probe ended before replacements')
                    replacements.append(replace())
                row = {'label':label, 'replacements':replacements,
                       'probes':watch.finish({mode:lambda e=e:list(e.sources) for mode,e in echoes.items()})}
                for value in row['probes'].values():
                    if value.get('failure_code') or value['attempts'] < 1: raise RuntimeError('Invalid app probe result')
                row['received'] = sum(v['received'] for v in row['probes'].values())
                row['peer_connections_or_datagrams'] = sum(len(e.sources) for e in echoes.values())
                row['peer_sources'] = sorted({ip for e in echoes.values() for ip in e.sources})
                row['vpn_state'] = status()
                result['windows'].append(row)
                watch.close(); watch = None
                return row

            control = window('reachable-before-vpn', 0)
            if any(v['received'] < 1 for v in control['probes'].values()): raise RuntimeError('Positive control failed')
            replace()
            baseline = window('drop-only-without-replacement', 0)
            if baseline['received'] or baseline['peer_connections_or_datagrams']:
                raise RuntimeError('Drop-only baseline invalid')
            for _ in range(3): window('drop-only-during-replacement', 8)
            if status().get('discarded_packets', 0) < 1: raise RuntimeError('No discarded TUN packets observed')
            command(-1)
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline and not status().get('stopped'): time.sleep(.05)
            if not status().get('stopped'): raise RuntimeError('Drop VPN did not stop')
            control = window('reachable-after-vpn', 0)
            if any(v['received'] < 1 for v in control['probes'].values()): raise RuntimeError('Post-control failed')
            result['contained'] = all(row['received'] == 0 and row['peer_connections_or_datagrams'] == 0
                for row in result['windows'] if row['label'] == 'drop-only-during-replacement')
            result['fixture_valid'] = True
    finally:
        if watch is not None: watch.close()
        for package in reversed(installed):
            run(adb + ['shell', 'am', 'force-stop', package])
            run(adb + ['uninstall', package])
        if alias: run(['sudo', '-n', 'ip', 'address', 'del', '10.126.0.1/32', 'dev', 'lo'])
        result['cleanup_verified'] = all(not present(p) for p in installed)
        (REPORT / 'result.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
        print(json.dumps(result))
    if not result['contained']: raise SystemExit(1)


if __name__ == '__main__': main()
