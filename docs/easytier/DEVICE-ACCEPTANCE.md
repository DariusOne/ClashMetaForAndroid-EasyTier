# Device acceptance gate (not yet passed)

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

## Current status

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
Until its results are recorded, continuous handover remains unaccepted.

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
