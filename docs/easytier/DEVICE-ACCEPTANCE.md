# Device acceptance gate (not yet passed)

As requested on 2026-10-28, native integration now targets **Android 12+ (API 31)**.
The integrated APK's minimum API and runtime guard reject older versions. The
independent normal CMFA build is unchanged. Android 11 results below remain
historical evidence, not a current support requirement. Fresh API 31 native
handover and API 31/35 public-API controls are required before proceeding;
raising the minimum alone is not acceptance. Existing routing, bypass-private,
per-app selection and no-extra-system-setting requirements remain unchanged.

The fresh API 31/35 public-API controls both reproduced transition escapes;
see [Android 12+ support and evidence](ANDROID12-SUPPORT.md). Higher minimum
version does not waive the strict continuous-handover gate.

Use a separate test APK/application ID and a disposable mesh profile. Never copy
real subscriptions, mesh secrets, endpoint lists, TOTP or VPS keys into this repo,
CI, command-line arguments or logs. Do not install over the user's working CMFA.

Before running: verify the phone's ADB authorization, record OS/device/API/ABI,
CMFA and EasyTier source commits, baseline APK digests, and physical network.
Keep secret-bearing input files under app-private storage and the local ignored
`private-device/` directory. Do not silently enable TUN/proxy settings elsewhere.

## Gate A — original apps

On the same phone and peer, record original CMFA proxy behavior and standalone
EasyTier behavior independently. Include a listener on the phone. Record which
generic UDP discovery/broadcast/multicast scenarios standalone EasyTier supports;
the integration must match those results, not promise all L2 protocols.

## Gate B — combined packet path

| Case | Required observation |
| --- | --- |
| Single VPN owner | Exactly one VpnService/TUN; engines use packet endpoints |
| Managed IPv4/IPv6 | Only active instance routes select native EasyTier |
| Other LAN/private/public IP | Same proxy/direct/reject as original CMFA |
| Rule / Global / Direct | Nonmesh behavior unchanged in all three |
| Bypass-private on/off | Explicit mesh ranges remain captured; other ranges unchanged |
| Fake-IP / real DNS / cache expiry | Same ownership after resolution; no synthetic IP sent to EasyTier |
| HTTP and SOCKS | Same ownership as packets from the Android VPN |
| TCP phone -> peer / peer -> phone | Five consecutive successes each; expected virtual source |
| UDP multi-peer | Echo counters and loss/duplication/reorder compared with baseline |
| ICMP and fragmented traffic | Bidirectional delivery and intact frame boundaries |
| Native discovery | Match the standalone supported cases, without game-specific rules |
| Physical/mesh CIDR overlap | Ask/Clash/EasyTier choices scoped to profile and physical network |
| Native outer sockets | TCP/UDP/STUN/QUIC/DNS cannot recursively enter VPN |
| Native crash / route withdrawn | Affected mesh traffic stays closed; nonmesh CMFA still works |
| Ten start/stop cycles | No extra VPN, worker, socket or FD remains |
| Three Wi-Fi/cellular switches | Re-protect transports, invalidate stale overlap decisions |
| Lock screen / 30-minute run | Stable routes/identity, bounded memory, no service death |

Record actual packet counts, exit path, timestamps, failures and skipped cases.
Source review, mocked packets, a `running` status and compilation are insufficient
to pass any real-device row. If a core row fails, stop feature rollout, preserve
the last working configuration and fix/retest the failing path.

## Gate C — UI and generators (after B)

- Separate saved YAML and TOML profiles, one active profile per engine.
- Proxy-only, mesh-only, combined mode; stable independent phone instance ID.
- Route/status view, overlap decisions, config validation and rollback.
- All three generators add `mihomo-mobile.yaml` and `easytier-mobile.toml` while
  preserving their current outputs. No embedded server/admin/Cloudflare secrets.
- Private files retain Windows user-only ACL or Linux 0600/0700.

## Prior validation history

Commit `ea1673b62fdb7cd9d2666fa7bb7fd4cb4c4d3cf2` passed Native CI
`40647125042`, normal build `40647131073`, and the matching physical Android
retest. The latter covered bidirectional TCP/UDP/ICMP and 4096-byte ICMP,
nonmesh Direct/Global/Rule, authenticated proxy and bypass-private off/on/off,
and three interface rebuilds. Every post-ready five-request assertion passed,
including virtual-source checks. The prototype VPN, profile, probes and owned
LAN/container fixtures were cleaned up. This is NOT continuous-handover proof.

The continuous transition fixture starts bounded TCP/UDP probes before asking
for a rebuild and requires them to remain active until the new interface is
ready. It records blocked requests separately and rejects any wrong source in
completed sockets or peer-observed connections/datagrams. Post-ready strict
5/5 tests remain separate. This finite fixture does not inspect every rejected
SYN on an underlay and does not establish an OS-wide lockdown guarantee.
The Android 17 physical fixture recorded 1,102 attempts across three rebuilds,
1,087 replies, 15 uncompleted requests and no incorrect source. Android 11 CI
40650254407 failed with five wrong-source TCP requests. Distinct NetworkAgent
handover did not solve it (run 40653152921: ten incorrect TCP sources); that
experiment was removed. Run 40654434328 classified seven wrong TCP sources as
neither the mesh address nor the Clash virtual gateway, while its mesh-NIC
header filter saw no packets with those sources. None of these failures is
overridden by a later post-ready or newer-platform pass.

Physical-network changes with unchanged VPN addresses/routes now retain the
Android descriptor. Network scope, overlap decisions and native readiness are
updated in one policy commit. The emulator fixture separately tests actual
Wi-Fi/cellular changes and forced interface replacements with the same strict
continuous-source assertions. Address/route changes still require replacement;
those Android 11 results are historical. The same strict gate applies to the
new Android 12+ support range.

Commit `5dcea88` / run `40655939624` passed six actual emulator Wi-Fi/cellular
transitions with the same interface and mesh generation: 7,416 attempts,
7,365 replies, 51 uncompleted requests, zero incorrect sources, and TCP/UDP
5/5 after every transition. Forced replacement still failed (five incorrect
TCP sources in its second cycle), so the complete job failed and no APK was
released. Explicit reconnect/degraded dynamic behavior was not accepted by
the user. A separate test-APK activity compares ordinary Android app-UID Java
socket behavior against the existing shell-UID Go probe in the same replacement
window. Both gates remain strict; this comparison is diagnostic, not a waiver.

The comparison has now reproduced this in several implementations. Run
`40663378467` recorded one wrong-source TCP connection from Android NDK/Bionic,
also observed by the peer. Run `40666685143` then recorded one wrong-source TCP
connection at the peer from the ordinary application UID's Java socket. Explicit
AF_INET application probes run alongside Java NIO and shell Go/Bionic probes;
zeros in one finite window do not establish immunity. The Linux header filter
did not observe the application's wrong-source connection, so that capture is
not a complete underlay monitor and cannot prove absence of escaped SYNs.

A separate system always-on/lockdown comparison uses visible Settings controls
on the disposable API 30 emulator only. The initial guarded run was invalid:
prematurely terminated instrumentation left a stale profile and ready marker.
The fixture now waits for Android cleanup and requires an empty profile store
and absent run markers before another mode. Both ordinary and guarded verdicts
remain required; no real-phone setting is enabled. Lockdown can change excluded
application and bypass-private behavior, which must not silently replace CMFA's
policy contract even if the handover comparison passes.

Run `40668680639` reproduced two peer-observed wrong-source application TCP
connections in ordinary mode (one Java NIO, one explicit AF_INET); that fixture
cleaned up correctly. The guarded comparison reached all three replacements:
15,164 attempts, 15,104 replies, 60 incomplete requests and no wrong sources
across the eight socket probes. Its Settings teardown failed, so the whole run
remains failed and no APK was released. The next fixture separates release of
blocking from disabling always-on, which itself can stop the VPN, and checks
whether bypass-private on/off preserves ordinary nonmesh LAN connectivity.

The first physical arm64 Android 17 fixture was executed on 2026-10-28 using
prototype commit `46f358e0dd3ed3288e31186567fba2224db5ff13` and a private,
disposable Linux peer. Ten start/stop cycles and native-child crash isolation
passed. A short TCP/UDP/ICMP fixture passed 5/5 in both directions, including
verification of the phone's virtual source address. Its underlay used USB
reverse, so this does not validate native Wi-Fi transport protection.

The extended LAN fixture observed 4096-byte ICMP 5/5 each way, nonmesh TCP/UDP
5/5 and zero accepted connections for its explicit REJECT rule. However, the
VPN owner crashed during extended mode-switch runs. Android tombstones identify
SIGABRT in `libclash.so` (`runtime.tgkill`), not a completed mode-parity pass.
Private Go crash capture identified `panic: leaking buffer`. The pinned Mihomo
REJECT and REJECT-DROP writers failed to release the buffer on EOF. A local debug
regression reproduced both panics before the fix and passed after both releases
were added; the original EOF/rejection behavior is retained. The build prepares
this compatibility fix using a complete source hash check.

The fixed APK (`ff929e84247c74da6636769f4b5d6f5466932444`) then passed the complete
extended physical fixture, including instrumentation cleanup, through USB and
through actual Wi-Fi TCP underlay. The Wi-Fi fixture permits only the selected
phone and forwards only to a local disposable native peer; no USB reverse mapping
was present. Bidirectional TCP/UDP/ICMP and 4096-byte ICMP passed 5/5 each. Nonmesh
LAN TCP/UDP passed 5/5; REJECT accepted zero connections. Direct/Global/Rule
semantics and independent mesh routing all passed. Global UDP rejection also
accepted no traffic at the test origin. That fixture proved direct/reject parity;
the controlled proxy/bypass rows were subsequently tested as recorded below.

Generic IPv4 discovery probes passed 5/5 in BOTH directions for the disposable
mesh's directed broadcast, limited broadcast, `224.0.0.251` and `239.255.255.250`.
They verify virtual source IP and exact synthetic payload replies. They do not
implement or claim mDNS/SSDP application protocol discovery, all games, IPv6, or
parity against the original Android EasyTier application's discovery baseline.
That baseline comparison remains open; the result's full `discovery_validated`
flag deliberately remains false independently of the passing IPv4 packet probes.

The subsequent APK (`830248f10b3456540efb5343590cb48faaceaa07`) passed the same
Wi-Fi/IPv4/mode/discovery fixture, plus three forced Android interface rebuilds
and three actual Wi-Fi disable/return cycles. Every cycle retained the same native
generation, verified outgoing TCP/UDP 5/5 and reverse ICMP 5/5, and rechecked
nonmesh LAN DIRECT/REJECT. The private peer was reachable only on Wi-Fi. Although
the phone had a physical network during each interruption, no cellular mesh
connectivity is claimed. Wi-Fi was restored; the test VPN, profile, probes and
private Docker/LAN helpers were cleaned up. The Linux race tests also verify
withdrawal retention, stale replacement rejection, FD cleanup and overlap scope.

The APK `08a63b95c69be6000b50d6f4da8125dd64821c95` passed the physical controlled
SOCKS and bypass-private fixture. With bypass off, unmanaged private TCP/UDP used
the authenticated SOCKS path 5/5 and made zero direct-origin connections. With
bypass on, both used direct 5/5 without increasing proxy counters. Turning bypass
off restored the proxy path 5/5; managed mesh TCP remained 5/5 in both settings.
The fixture is a fixed-destination synthetic echo service, not an arbitrary
forwarding proxy, a public proxy-exit test, or an original-CMFA app comparison.

An earlier retry correctly failed: the fixture's eight-client semaphore rejected
the second phase because five first-phase UDP associations remained open in the
normal Mihomo NAT table. The failure evidence is retained. A loopback regression
reproduces the eight-client limit and checks ten retained UDP sessions plus TCP
with a finite sixteen-client limit. The complete physical rerun passed with peak
ten active clients and zero capacity rejections. The APK/routing code was unchanged
between these attempts. All temporary phone and host resources were cleaned up.

Physical baseline-app, DNS/Fake-IP, HTTP/SOCKS inbounds, IPv6, native UDP/STUN/QUIC outer
transports, cellular peer connectivity, DHCP/published-route rebuilds and sustained
run rows remain unpassed.
Gate C is intentionally not rolled out.

The user rejected settings-dependent lockdown and explicit-reconnect workarounds.
Preserve bypass-private and application exclusions; no production setting or
real-phone configuration was changed. Run `40673276524` confirms both diagnostic
modes now clean up and restore correctly. Ordinary mode still failed on its
first forced replacement (eight shell Go TCP wrong sources and one peer-observed
ordinary app TCP wrong source); the guarded comparison again broke bypass-private
LAN access. No failed APK was released.

The pinned EasyTier 2.6.4 Android implementation also stops/re-establishes its VPN
when addresses/routes change; it does not supply an atomic public address/route
update mechanism to reuse. A separate `diagnostics/android11-dropvpn` workflow
now removes both engines from the experiment and tests a discard-only public-API
VPN. Its result is diagnostic and cannot relax the native acceptance gate.

That control is now complete: `b0ab618` / run `40678664929` passed fixture
validity, before/after reachability and cleanup, but failed containment. Its
discard-only VPN allowed 23 peer connections/datagrams and 13 replies during
12 interface replacements; the no-replacement baseline allowed zero. See
[the full evidence and limits](ANDROID11-HANDOVER.md). No setting-dependent
workaround was adopted. Android 11 remains a historical failure outside the
new support range; fresh Android 12+ results are tracked separately above.
