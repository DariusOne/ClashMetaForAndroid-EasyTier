# Packet-path prototype (not the finished application)

This harness exists to make the native packet path testable before UI/generator
rollout. The integrated APK requires **Android 12 / API 31 or later**, enforced
in its manifest and at native-harness entry. The independent upstream-like
proxy-only build retains its existing minimum API. Normal builds do not enable
the integration. CI builds the opt-in variant with:

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

CI also contains an Android API 31 x86_64 emulator lifecycle test: a newly
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
invalid snapshots closes mesh traffic, with no redirect to Clash. Physical-network,
address and route-capture changes rebuild the Android interface while retaining
the native instance and route ownership. The reader pauses before establish and
resumes only after the new interface and policy acknowledge the same snapshot.
Offline periods keep the VPN established and close mesh traffic. A failed rebuild
stays closed. This is still the opt-in harness, not production mode/profile UI.

The prototype currently supports raw-IP packet-path investigation only. In
particular, the post-resolution DNS/Fake-IP and HTTP/SOCKS hook is NOT connected.
No production combined-mode, proxy-only/mesh-only switching, profile editor
or generator release is claimed. Keep these
rows unpassed in DEVICE-ACCEPTANCE.md. Do not distribute this artifact as a
completed CMFA/EasyTier replacement.

Android 11 evidence below is historical and remains available for diagnosis;
it is outside the newly requested native integration support range. Raising
the minimum does not prove that Android 12+ handover is safe. The ordinary
settings test remains strict, with no always-on/lockdown prerequisite. The
small independent control additionally runs on API 31 and API 35. Both fresh
controls reproduced a transition escape; see [support-range evidence](ANDROID12-SUPPORT.md).

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

`--rebuild-cycles 3` requests three real Android interface replacements using a
private fixture file. Each must retain the native generation and recover TCP,
UDP and reverse ICMP. `--wifi-return-cycles 3` is a separate, explicitly selected
physical test: with Wi-Fi already on, temporarily disable it, observe the network
change, enable it again and verify the same packet paths. Its finally block
restores Wi-Fi even on failure. A private LAN peer cannot validate mesh traffic
over cellular; do not label this as cellular peer acceptance. Neither option
changes the original apps or desktop network settings.

`--proxy-fixture` consumes private metadata from `physical_socks_peer.py`. That
helper accepts only the selected phone, requires a fresh one-use SOCKS identity,
and echoes one fixed synthetic target without forwarding arbitrary traffic.
The test checks TCP/UDP 5/5 on the proxy, direct and restored-proxy paths while
toggling only the disposable prototype's bypass-private setting. Mesh ownership
must remain intact. The finite sixteen-client bound accommodates ten retained
UDP associations; capacity rejections invalidate a run. Loopback regression covers
the former eight-client failure, the complete two-phase workload and overflow.
This does not validate public proxy exits or the combined HTTP/SOCKS inbound hook.

Both host runners publish private control/completion files with a same-directory
temporary write and atomic rename. Existence of the completion file must never
mean only that `cat` has opened an empty destination. A staged-stdin regression
holds the writer midway through JSON and checks both new and replaced files;
the command has also been exercised on the physical Android shell without a VPN.

The Android 11 CI emulator exposed a handover readiness race: `establish()`
returned before ConnectivityService applied the replacement interface/routes.
Some immediately started probes used a nonmesh source despite receiving replies.
The harness now obtains the exact TUN name from the borrowed descriptor and waits
for matching VPN LinkProperties, addresses and unicast routes before returning
the replacement or reporting active. Stale properties from an identically
addressed previous interface cannot acknowledge it. The wait is bounded and
cancellable; five source-checked requests still have to succeed without retries.
This is a readiness barrier, **not an OS-wide lockdown guarantee during the
handover itself**. Continuous traffic during transitions remains an acceptance
gate; the prototype is not ready for production rollout. Header-only captures
are restricted to the disposable CI mesh, not the user's network.

To return this separate prototype to normal CMFA behavior, stop its VPN and
remove only `no_backup/native-mesh-acceptance/enable` using run-as, or clear the
prototype's app data. Neither action is needed for the user's original CMFA.

`--transition-probe` optionally adds the bounded `transition_probe.go` executable
to a physical run with `--rebuild-cycles`. CI runs it for all three rebuilds.
It starts before replacement, counts failed requests as blocked, and rejects
wrong source addresses even if payloads succeed. It must still be running when
the readiness barrier acknowledges the replacement. These are additional
observations; they do not relax the subsequent 5/5 recovery requirements.
