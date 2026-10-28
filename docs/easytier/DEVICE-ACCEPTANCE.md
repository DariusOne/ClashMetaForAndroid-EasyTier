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
accepted no traffic at the test origin. These fixtures prove direct/reject parity;
a real nonmesh proxy exit and bypass-private toggles still need their own rows.

Generic IPv4 discovery probes passed 5/5 in BOTH directions for the disposable
mesh's directed broadcast, limited broadcast, `224.0.0.251` and `239.255.255.250`.
They verify virtual source IP and exact synthetic payload replies. They do not
implement or claim mDNS/SSDP application protocol discovery, all games, IPv6, or
parity against the original Android EasyTier application's discovery baseline.
That baseline comparison remains open; the result's full `discovery_validated`
flag deliberately remains false independently of the passing IPv4 packet probes.

Physical baseline-app, DNS/Fake-IP, HTTP/SOCKS, IPv6, native UDP/STUN/QUIC outer
transports, network-switch recovery and sustained-run rows remain unpassed.
Gate C is intentionally not rolled out.
