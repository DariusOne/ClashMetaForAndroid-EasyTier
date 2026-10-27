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

Gate A/B have not been executed for this custom build. ADB had no connected
device during initial development. Gate C is intentionally not rolled out.
