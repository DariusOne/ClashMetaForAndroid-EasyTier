# Native EasyTier integration — implementation gate

This branch is an **unfinished packet-path prototype**, not an installable combined
VPN. The existing CMFA service has not been switched to it. Do not label a normal
CMFA build from this branch as an EasyTier-integrated APK.

## Locked sources

| Component | Revision |
| --- | --- |
| CMFA baseline 2.11.36 | `1a4f949213fcbb7f0c9e2a4a21138642d84b8f22` |
| Mihomo submodule | `3f27ef39f8c96bbfbc8b0b9bb10f5c9ef60149d8` |
| Native EasyTier 2.6.4 | `8428a89d2dabc94c97d370ec607c6ca142473626` |
| EasyTier Android packet descriptor implementation | rust-tun `12378839e7985283df0e4fb536b7137230356db5` |
| Rust / Android NDK | `1.95.0` / `29.0.14206865` |

The upstream fork's main branch is retained as the baseline. Only this branch
contains integration work. Upstream licenses continue to apply; EasyTier's license
is available in `native/easytier-upstream/easytier/LICENSE`.

## Implemented foundation

- A destination ownership policy with transactional route snapshots and session
  isolation. Only the active mesh's virtual/published routes select EasyTier.
- All other IPv4/IPv6 addresses delegate to Mihomo, including other private LANs.
  No automatic `DIRECT` rule is introduced. Proxy-only and mesh-only decisions are
  distinct; in mesh-only mode Android must capture only the mesh's routes.
- Overlap choices are scoped to a profile and physical network. Undecided overlap
  drops only the intersection. Explicit "Clash" means original Clash semantics.
- Disconnection and withdrawn routes stay closed instead of falling back to a
  proxy or direct connection. A new profile/session discards old ownership.
- A single-reader packet dispatcher, separate bounded queues, serialized TUN
  writes and cancellation/FD ownership. Native endpoints use AF_UNIX datagrams;
  no endpoint creates another system VPN.
- A JNI native EasyTier adapter with one active instance, independent phone ID,
  borrowed packet descriptor duplication, generation checks and fixed errors.
  Status projection excludes TOML, secrets, public peer endpoints and raw events.
- A dormant CMFA Go lifecycle adapter and a gVisor packet endpoint reusing the
  real Mihomo inbound handler. The host TCP/UDP echo test exercises packet decode
  and return framing; its mock policy delegate does not prove Android routing.
- Imported native flags are validated before upstream's infallible deserializer;
  invalid fields cannot intentionally abort the Java process. Host file sources,
  management portals, exit routes and phone gateway advertisements are rejected.
- Native build script and CI for Linux transport/race/fuzz tests and Android
  arm64/x86_64 native-library compilation.

## Mandatory remaining packet-path work

1. Integrate Android VPN lifecycle and outer-socket protection. A Boolean argument
   in the JNI adapter is a host precondition, **not evidence of actual protection**.
   Audit all native TCP/UDP/STUN/QUIC/DNS sockets before enabling combined mode.
2. Connect the dispatcher to Mihomo and native EasyTier, retain correct virtual
   source addresses and MTU, handle DHCP/address/route changes transactionally.
3. Route HTTP/SOCKS and post-Fake-IP/resolution flows through the same ownership
   policy. A raw destination classifier alone does not cover these flows.
4. Confirm generic bidirectional TCP/UDP/ICMP, fragmentation and supported
   broadcast/multicast delivery against standalone EasyTier on a real device.
5. Validate nonmesh Rule/Global/Direct, DNS and bypass-private parity, conflict
   prompts, failures, network switches, sleep and restart cleanup.

Only after these pass: complete independent YAML/TOML profile UI, mode selection,
status/overlap controls and mobile generator artifacts. No VPS, Cloudflare,
desktop VPN configuration or private generator input is part of this branch.

## Validation boundaries

Run host policy tests: `cd native/packet-router && go test ./...`.
On Linux also run `go test -race ./...` for real datagram transport and cancellation.
Native builds require the declared SDK/NDK, Rust targets and protobuf compiler:
`python3 scripts/build-easytier-android.py --abi arm64-v8a` (or `x86_64`).

Passing these tests proves components/compilation only. Packet fixtures do not
prove Android VPN behavior, real peer communication or game discovery. CI
artifacts explicitly carry `device_validated: false` until real acceptance.
