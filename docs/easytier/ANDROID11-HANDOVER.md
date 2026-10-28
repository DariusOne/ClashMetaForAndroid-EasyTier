# Android 11 interface handover: unresolved compatibility gate

Historical record: on 2026-10-28 the user changed the integration's minimum
supported version to Android 12. Android 11 is therefore outside that range;
the failure evidence is preserved. Android 12+ still requires its own strict
handover verification, without changing existing user settings. The fresh
[Android 12/15 controls](ANDROID12-SUPPORT.md) also reproduced transition escapes.

The required behavior remains unchanged: only active EasyTier destinations use
the mesh; unrelated traffic keeps CMFA policy, including private-network bypass
and application exclusions. Do not require always-on/lockdown or explicit manual
reconnect. This investigation does not change real-phone settings or release a
completed integrated APK.

## Independent public-API control

Commit `b0ab6184a1626e902776fc5edfd0da4e6fb38e22`,
[run 40678664929](https://github.com/DariusOne/ClashMetaForAndroid-EasyTier/actions/runs/40678664929),
completed the complete control and cleanup. It compiled two tiny Java APKs with
no CMFA, Mihomo or EasyTier libraries. The VPN only reads and discards packets;
it opens no outgoing sockets and never writes to its TUN. The other app UID
issues bounded TCP/UDP requests to one synthetic host endpoint. No system
always-on or lockdown setting is enabled.

Test platform: API 30 x86_64, build `RSR1.210722.013.A2/10067904`, security patch
`2021-08-05`, on a newly created disposable emulator. This is evidence for that
build, not a claim that every Android 11 vendor image behaves identically.

| Phase | Interface replacements | Peer connections/datagrams | Successful requests |
| --- | ---: | ---: | ---: |
| Before VPN: positive control | 0 | 3,200 | 3,200 |
| Established discard VPN, no replacement | 0 | 0 | 0 |
| Six continuous observation windows | 12 | **23** | **13** |
| After stopping VPN: positive control | 0 | 3,200 | 3,200 |

Each replacement window retained the discard VPN and checked a different
interface's address/route readiness before the probes ended. Across the six
windows, 3,746 attempts yielded nine TCP accepts and fourteen UDP datagrams at
the peer. Two TCP requests and eleven UDP requests received their exact replies.
Every window exhibited escaped traffic. A TCP accept counts even if the client
does not receive a response. The before/after controls and different bound
endpoint ports rule out an unreachable target or stale previous-window traffic.

The run reports `fixture_valid: true`, `contained: false`, and
`cleanup_verified: true`; its failed CI status is intentional. The peer address
and both fixture packages were removed. Artifact `12812370697` is JSON only:
SHA-256 `e9bd770811b44fc5efab04e4908c9625793a864baef9d223225d1be14c93d7b1`.
It was downloaded and checked locally. No fixture APK was exported.

Earlier driver failures are not counted as completed controls: the SDK tool
path was missing in `40676757059`; synchronous Activity-frame waiting overran
the probe window in `40676995100` and `40677445004`; `40677999578` completed six
failing windows but not its post-stop control because the system's service
binding kept it alive. The final fixture closes its TUN before stopping itself.

## Implication and current implementation boundary

This independently reproduces an OS handover escape without either networking
engine. An application packet dispatcher cannot drop traffic that never enters
its TUN. Waiting for exact LinkProperties protects post-ready probes; it does
not make the system's interface/routing transition atomic. Android 11's
[VPN implementation](https://android.googlesource.com/platform/frameworks/base/+/android11-release/services/core/java/com/android/server/connectivity/Vpn.java)
sends updated LinkProperties and resets the former interface during establish;
ConnectivityService performs the route updates separately.

The implemented descriptor-retention fix still applies to ordinary physical
network changes with unchanged capture/address requirements. It passed six
Wi-Fi/cellular transitions in run `40655939624`, with zero observed wrong
sources and TCP/UDP 5/5 after each transition. It does not solve a change that
actually requires a different Android interface.

Pinned EasyTier 2.6.4's Android service also establishes a new interface, and
its mobile controller stops/starts VPN on address or route changes. It provides
no existing atomic public-API handover mechanism to copy. Freezing the system
address and translating packets would be a different architecture: arbitrary
applications' advertised addresses, incoming connections and discovery cannot
be assumed equivalent. That approach is not implemented or silently substituted.

No application-only fix satisfying all current dynamic-change requirements has
been validated. Keep the draft unmerged and the strict compatibility gate open.
Do not treat the passing host tests, normal CMFA build, Android 17 finite-window
test, or the rejected system-lockdown counterfactual as Android 11 acceptance.
