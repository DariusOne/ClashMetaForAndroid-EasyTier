# Packet-path prototype (not the finished application)

This harness exists to make the native packet path testable before UI/generator
rollout. Normal builds do not enable it. CI builds the opt-in variant with:

```
python3 scripts/build-easytier-android.py --abi arm64-v8a
python3 scripts/build-easytier-android.py --abi x86_64
./gradlew -PnativeMeshHarness=true app:assembleMetaDebug
```

The package is **com.github.metacubex.clash.meshprototype.meta**, different from
working CMFA. It has one VpnService and a separate, unexported native engine
process. Its native JNI libraries are verified before packaging. Compile success
and the APK manifest check are not phone or networking acceptance.

After installing that debug APK on an explicitly approved test device, import a
disposable Clash YAML through its existing UI. Keep its system HTTP proxy off.
Prepare a disposable EasyTier TOML in an ignored private directory. Do not use a
production mesh for first testing and do not put a password in adb arguments.

```
python scripts/prepare-packet-harness.py --serial DEVICE --profile /private/mesh.toml
```

This only stages an app-private file. It does not start a VPN. The user starts the
prototype from its normal VPN button and approves Android's VPN prompt. The
harness first establishes the single VPN with its own UID excluded, then starts
the native process, obtains its addresses and replaces the interface using the
same VPN owner. The packet router and native engine receive separate AF_UNIX
datagram endpoints; only the router reads the Android TUN.

An independent phone instance ID is generated under no-backup app storage.
Native commands have a watchdog confined to the native service process. Death or
invalid snapshots closes mesh traffic, with no redirect to Clash. Changes that
require rebuilding the Android interface currently stop mesh traffic with the
fixed `ET_INTERFACE_REBUILD_REQUIRED` message; automatic recovery is unfinished.

The prototype currently supports raw-IP packet-path investigation only. In
particular, the post-resolution DNS/Fake-IP and HTTP/SOCKS hook is NOT connected.
No production combined-mode, proxy-only/mesh-only switching, profile editor,
automatic network-switch recovery or generator release is claimed. Keep these
rows unpassed in DEVICE-ACCEPTANCE.md. Do not distribute this artifact as a
completed CMFA/EasyTier replacement.

To return this separate prototype to normal CMFA behavior, stop its VPN and
remove only `no_backup/native-mesh-acceptance/enable` using run-as, or clear the
prototype's app data. Neither action is needed for the user's original CMFA.
