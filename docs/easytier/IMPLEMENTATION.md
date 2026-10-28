# Native EasyTier integration — implementation gate

This branch is an **unfinished packet-path prototype**, not a completed combined
VPN. Normal builds retain the original service behavior. An explicit development
build and private opt-in marker connect a raw-packet acceptance harness to the
existing VPN owner; see [prototype instructions](PACKET-PROTOTYPE.md). Neither a
normal CMFA build nor that development APK is a completed integration.

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
  Attachment waits for the matching native device-ready event; merely enqueuing
  an FD does not mark the mesh ready. Initialization errors remain fixed codes.
- An opt-in CMFA Go lifecycle adapter and a gVisor packet endpoint reusing the
  real Mihomo inbound handler. The host TCP/UDP echo test exercises packet decode
  and return framing; its mock policy delegate does not prove Android routing.
- A JNI packet-session entry point and a private bound Android engine service in
  its own process. Binder death notifies the owner to close mesh ownership;
  profile contents travel through an FD, not an Intent or log. These entry points
  are used only by the explicit packet acceptance harness. Native startup follows
  VPN establishment with its own UID excluded; runtime protection still needs
  Android packet-level verification.
- Versioned, credential-free native snapshots. DHCP addresses, published routes,
  readiness and route withdrawal are committed together. A new phone address is
  unusable until the owner acknowledges it is installed on the Android interface.
- Shared post-resolution ownership classification with mixed-answer rejection;
  this is an API/tested decision, **not yet a wired Mihomo DNS/HTTP/SOCKS hook**.
- Experimental Android-interface replacement retains both engines and the same
  route policy. Pause precedes `Builder.establish`; old descriptor errors and
  stale packets cannot tear down the dispatcher during replacement. Address,
  route-capture and physical-network changes trigger a rebuild; offline periods
  retain the VPN and close mesh ownership. Withdrawn routes remain captured and
  closed. Physical recovery validation for this addition is still pending.
- Imported native flags are validated before upstream's infallible deserializer;
  invalid fields cannot intentionally abort the Java process. Host file sources,
  management portals, exit routes and phone gateway advertisements are rejected.
- Native build script and CI for Linux transport/race/fuzz tests and Android
  arm64/x86_64 native-library compilation.

## Mandatory remaining packet-path work

1. Actual Wi-Fi TCP outer transport now passes the physical fixture. Audit and
   validate native UDP/STUN/QUIC/DNS transports too; this TCP result is not blanket
   evidence for every native transport or network-switch recovery.
2. Validate experimental interface replacement on Android and real network
   transitions. Forced rebuild tests are not Wi-Fi/cellular transport tests;
   IPv4 virtual source/MTU already pass on the prior physical APK.
3. Route HTTP/SOCKS and post-Fake-IP/resolution flows through the same ownership
   policy. A raw destination classifier alone does not cover these flows.
4. Physical IPv4 TCP/UDP/ICMP, 4096-byte ICMP and generic broadcast/multicast packet
   probes pass in both directions. Compare discovery against standalone Android
   EasyTier and complete IPv6/multi-peer tests; no all-games claim follows from echo.
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
