# Packet-path prototype (not the finished application)

This harness exists to make the native packet path testable before UI/generator
rollout. Normal builds do not enable it. CI builds the opt-in variant with:

```
python3 scripts/build-easytier-android.py --abi arm64-v8a
python3 scripts/build-easytier-android.py --abi x86_64
./gradlew -PnativeMeshHarness=true app:assembleMetaDebug
```

Gradle runs `scripts/prepare-mihomo.py` before compiling Go. This applies two
reviewed buffer releases to the pinned Mihomo `reject.go`, verifies the complete
source digest, and fails on unrelated upstream edits. It does not upgrade the
submodule or alter the Go module cache. Direct Go test users must run that script
first. The `native/compat` regression runs with `debug` enabled: rejected writes
must consume their buffer and retain EOF semantics without panicking.

The package is **com.github.metacubex.clash.meshprototype.meta**, different from
working CMFA. It has one VpnService and a separate, unexported native engine
process. Its native JNI libraries are verified before packaging. Compile success
and the APK manifest check are not phone or networking acceptance.

CI also contains an Android API 30 x86_64 emulator lifecycle test: a newly
created local-only profile starts and stops the single VPN ten times, checks
native startup and Android mesh address installation/removal, kills only the
disposable native child on the last cycle to check VPN-owner survival, and saves its
result separately. A subsequent CI fixture starts a checksum-pinned, disposable
Linux EasyTier peer and probes TCP/UDP/ICMP in both directions. The Android
probe runs under shell UID (captured by the VPN), not the VPN application's
excluded UID. It also checks nonmesh TCP/UDP and an original Mihomo REJECT rule.
These are executable tests, not a claim that they have passed: inspect the run's
separate lifecycle and peer result JSON files. DNS/Fake-IP, phone compatibility
and discovery still require their acceptance rows. Never run these disposable
data tests on a phone containing user configuration.

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

## Explicit physical-device fixture

CI also publishes the matching instrumentation APK and arm64 probe as
`physical-device-test-tools-NOT-acceptance-results`. This is executable test
equipment, not proof of a phone test. Verify the archive digests and use the
prototype and test APK from the same run (their debug signing keys must match).

`scripts/test-packet-physical-device.py` supports a real phone only when explicitly
selected with `--serial`, with an empty separate prototype profile store and a
one-use private consent marker. It requests Android's normal VPN permission;
it does not use appops to bypass that prompt. Record and restore the existing
VPN state. Never clear the original CMFA or EasyTier app to make a fixture pass.

The peer fixture uses a disposable Linux container with its own network/TUN,
not a production mesh. Only localhost publishes the native peer's TCP listener;
an explicitly tracked adb reverse mapping carries that underlay to the phone.
`physical_peer.js` and `physical_peer_client.js` provide synthetic echo traffic.
Both sets of network identities remain in a local user-only test directory.
USB underlay success does not prove Wi-Fi/cellular recovery or physical LAN
discovery. The result keeps DNS/Fake-IP, discovery, IPv6 and complete integration
false until their separate cases have actually run.

For a Wi-Fi TCP underlay, `physical_native_lan.py` can expose the disposable peer's
loopback port on one private host address, accepting only the selected phone. It
has a ten-minute deadline, four-connection bound and closes active streams on
shutdown. `--native-lan-fixture` verifies the private profile matches that endpoint
and does not create an adb reverse mapping. This tests TCP outer transport only.
`physical_lan_peer.py` separately provides nonmesh echo/reject counters.

`--discovery-probes-dir` accepts the synthetic arm64/amd64 `discovery_probe.go`
binaries from a private fixture directory. The physical runner checks both
directions of directed/limited IPv4 broadcast and two multicast destinations;
matching payloads and the peer's virtual source are required. These are generic
UDP packet tests, not game/mDNS/SSDP protocol tests or a standalone-app comparison.
The runner records `generic_ipv4_discovery_validated` separately and removes its
temporary probe executables. Test evidence must name the exact APK commit and
local fixture revision; an unexecuted fixture is not acceptance evidence.

To return this separate prototype to normal CMFA behavior, stop its VPN and
remove only `no_backup/native-mesh-acceptance/enable` using run-as, or clear the
prototype's app data. Neither action is needed for the user's original CMFA.
