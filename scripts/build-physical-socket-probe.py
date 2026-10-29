#!/usr/bin/env python3
"""Build a separate, bounded, non-VPN phone diagnostic from the CI probe source.

Uses an already verified Android SDK. Does not download, install, or launch an
APK. The output has no profile access, VPN service, or production signing key.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = 'com.github.metacubex.clash.socketprobe'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--build-tools', type=Path, required=True)
    parser.add_argument('--android-jar', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    sdk = args.build_tools.resolve(strict=True)
    jar = args.android_jar.resolve(strict=True)
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    classes, dex = out/'classes', out/'dex'
    classes.mkdir(); dex.mkdir()
    def run(*command):
        value = subprocess.run(list(map(str, command)), capture_output=True, text=True, timeout=90)
        if value.returncode:
            # Only compiler diagnostics are printed; the input is fixture code.
            raise RuntimeError(value.stderr[:4000] or 'Fixture compiler failed')
    manifest = out/'AndroidManifest.xml'
    manifest.write_text(f'''<manifest xmlns:android="http://schemas.android.com/apk/res/android" package="{PACKAGE}">
<uses-sdk android:minSdkVersion="31" android:targetSdkVersion="35"/>
<uses-permission android:name="android.permission.INTERNET"/>
<queries><package android:name="com.github.metacubex.clash.meshprototype.meta"/>
<package android:name="com.github.metacubex.clash.meta"/><package android:name="com.kkrainbow.easytier"/></queries>
<application android:debuggable="true" android:label="CMFA socket diagnostic" android:allowBackup="false">
<activity android:name="com.github.kr328.clash.HandoverProbeActivity" android:exported="true" android:excludeFromRecents="true"/>
</application></manifest>''', encoding='utf-8')
    source = ROOT/'app/src/androidTest/java/com/github/kr328/clash/HandoverProbeActivity.java'
    run('javac', '--release', '8', '-cp', jar, '-d', classes, source)
    run('java', '-cp', sdk/'lib/d8.jar', 'com.android.tools.r8.D8', '--min-api', '31',
        '--lib', jar, '--output', dex, *sorted(classes.rglob('*.class')))
    exe = '.exe' if os.name == 'nt' else ''
    unsigned, aligned = out/'unsigned.apk', out/'socket-probe.apk'
    run(sdk/('aapt'+exe), 'package', '-f', '-M', manifest, '-I', jar, '-F', unsigned)
    with zipfile.ZipFile(unsigned, 'a') as archive:
        for path in sorted(dex.glob('*.dex')): archive.write(path, path.name)
    run(sdk/('zipalign'+exe), '-f', '4', unsigned, aligned)
    key = out/'fixture.p12'
    run('keytool', '-genkeypair', '-keystore', key, '-storepass', 'fixture-only',
        '-keypass', 'fixture-only', '-alias', 'fixture', '-dname', 'CN=Temporary socket diagnostic',
        '-keyalg', 'RSA', '-validity', '7')
    run('java', '-Djava.io.tmpdir='+str(out), '-jar', sdk/'lib/apksigner.jar', 'sign', '--ks', key,
        '--ks-pass', 'pass:fixture-only', aligned)
    run('java', '-jar', sdk/'lib/apksigner.jar', 'verify', aligned)
    result = {'package': PACKAGE, 'vpn_service': False, 'min_sdk': 31,
              'source_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
              'apk_sha256': hashlib.sha256(aligned.read_bytes()).hexdigest(),
              'android_jar_sha256': hashlib.sha256(jar.read_bytes()).hexdigest()}
    (out/'provenance.json').write_text(json.dumps(result, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(result))


if __name__ == '__main__': main()
