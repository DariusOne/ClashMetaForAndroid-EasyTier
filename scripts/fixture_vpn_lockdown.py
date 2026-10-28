"""System-settings diagnostic on the disposable API 30 emulator only.

Uses the visible Android settings controls, never hidden API exemptions or a
production app permission. Restore before the disposable VPN/profile is stopped.
"""
import os
import re
import subprocess
import time
import xml.etree.ElementTree as ET

PACKAGE = 'com.github.metacubex.clash.meshprototype.meta'
UI_FILE = '/data/local/tmp/cmfa-lockdown-ui.xml'


class EmulatorLockdown:
    def __init__(self, adb):
        self.adb = adb
        self.changed = False
        if os.environ.get('GITHUB_ACTIONS') != 'true' or self.call('shell','getprop','ro.kernel.qemu') != '1':
            raise RuntimeError('Lockdown diagnostic requires disposable emulator')
        if self.call('shell','getprop','ro.build.version.sdk') != '30':
            raise RuntimeError('Lockdown diagnostic requires API 30')
        if self.setting('always_on_vpn_app') not in ('null','') or self.setting('always_on_vpn_lockdown') not in ('null','','0'):
            raise RuntimeError('Existing always-on configuration must not be changed')

    def call(self, *args):
        return subprocess.check_output(self.adb+list(args),stderr=subprocess.STDOUT,text=True,timeout=15).strip()

    def setting(self, name):
        return self.call('shell','settings','get','secure',name)

    def tree(self):
        self.call('shell','uiautomator','dump',UI_FILE)
        raw = self.call('shell','cat',UI_FILE)
        if len(raw)>256*1024: raise RuntimeError('Settings hierarchy exceeds diagnostic limit')
        return ET.fromstring(raw)

    def tap(self, node):
        values=re.fullmatch(r'\[(\d+),(\d+)\]\[(\d+),(\d+)\]',node.get('bounds',''))
        if not values: raise RuntimeError('Settings control has no bounds')
        left,top,right,bottom=map(int,values.groups())
        if right<=left or bottom<=top: raise RuntimeError('Settings control is not visible')
        self.call('shell','input','tap',str((left+right)//2),str((top+bottom)//2))

    def open(self):
        self.call('shell','am','start','-W','-a','android.settings.VPN_SETTINGS')
        tree=self.tree()
        controls=[n for n in tree.iter('node') if n.get('resource-id','').endswith(':id/settings_button')]
        # This fresh fixture has exactly one consented VPN application. Never
        # select by row index or operate if another VPN entry is present.
        if len(controls)!=1: raise RuntimeError('Expected exactly one disposable VPN settings entry')
        self.tap(controls[0])

    def switch(self, title, enabled):
        tree=self.tree()
        parent={child:node for node in tree.iter() for child in node}
        labels=[n for n in tree.iter('node') if n.get('text')==title]
        if len(labels)!=1: raise RuntimeError('Expected system VPN switch is absent')
        row=labels[0]
        while row in parent and not any(n.get('checkable')=='true' for n in row.iter('node')):
            row=parent[row]
        switches=[n for n in row.iter('node') if n.get('checkable')=='true']
        if len(switches)!=1:
            raise RuntimeError('System VPN switch is unavailable')
        if (switches[0].get('checked')=='true') == enabled: return
        if switches[0].get('enabled')!='true':
            raise RuntimeError('System VPN switch is unavailable')
        self.tap(labels[0])
        tree=self.tree()
        buttons=[n for n in tree.iter('node') if n.get('resource-id')=='android:id/button1']
        if buttons:
            # Only the system VPN confirmation, observed after this exact
            # switch, may be accepted. Other dialogs fail the diagnostic.
            text=' '.join(n.get('text','') for n in tree.iter('node'))
            if len(buttons)!=1 or 'VPN' not in text or not any(word in text.lower() for word in ('block','connection')):
                raise RuntimeError('Unexpected system confirmation')
            self.tap(buttons[0])

    def verify(self, enabled):
        deadline=time.monotonic()+5
        while time.monotonic()<deadline:
            app=self.setting('always_on_vpn_app')
            blocked=self.setting('always_on_vpn_lockdown')
            if enabled and app==PACKAGE and blocked=='1': return
            if not enabled and app in ('null','') and blocked in ('0','null',''): return
            time.sleep(.1)
        raise RuntimeError('System VPN setting verification failed')

    def enable(self):
        self.open()
        self.changed=True
        self.switch('Always-on VPN',True)
        if self.setting('always_on_vpn_app')!=PACKAGE:
            raise RuntimeError('Settings did not select the disposable VPN')
        self.switch('Block connections without VPN',True)
        self.verify(True)
        self.call('shell','am','start','-W','-n',PACKAGE+'/com.github.kr328.clash.MainActivity')

    def restore(self):
        if self.changed:
            if self.setting('always_on_vpn_app') not in ('null','',PACKAGE):
                raise RuntimeError('Refusing to modify another VPN setting')
            self.open()
            self.switch('Block connections without VPN',False)
            self.switch('Always-on VPN',False)
            self.verify(False)
            self.changed=False
        self.call('shell','rm','-f',UI_FILE)
