"""Collect a bounded system-setting comparison without waiving either gate."""
import os
import json
from pathlib import Path
import subprocess
import sys

if os.environ.get('GITHUB_ACTIONS') != 'true':
    raise RuntimeError('Disposable GitHub emulator only')
script=Path(__file__).with_name('test-packet-native-peer.py')
results=[]
for protected in (False,True):
    env={**os.environ,'CMFA_SYSTEM_LOCKDOWN_DIAGNOSTIC':'1' if protected else '0'}
    try:
        code=subprocess.run([sys.executable,str(script)],env=env,timeout=480).returncode
    except subprocess.TimeoutExpired:
        # Do not start another fixture if a process failed to clean itself up.
        raise RuntimeError('Handover matrix deadline exceeded') from None
    results.append(code)
    report=script.parent.parent/'app/build/reports'/('native-mesh-peer-lockdown' if protected else 'native-mesh-peer')/'result.json'
    state=json.loads(report.read_text())
    if state.get('fixture_cleanup_verified') is not True or state.get('system_lockdown_restore_failed'):
        raise RuntimeError('Disposable fixture cleanup failed; next mode must not run')
if any(results):
    raise SystemExit(1)
