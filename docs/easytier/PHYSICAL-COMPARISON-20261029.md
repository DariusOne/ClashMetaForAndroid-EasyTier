# Physical ordinary-app comparison, 2026-10-29

The Android 17 / API 37 arm64 phone completed a stronger finite-window test of
the **39ef3fe** integrated prototype. This does not close the Android 12+
interface-replacement gate or complete original-app parity.

## Evidence boundary

The separate, non-VPN diagnostic APK runs as an ordinary application UID,
different from each VPN owner. It uses Java NIO TCP/UDP and explicit AF_INET
TCP/UDP, eight-second windows, request deadlines and a maximum of 800 attempts
per mode. A private, expiring consent file restricts the owner and RFC1918 target.
No appops grant, battery exemption, always-on VPN or lockdown setting is used.

A controlled Windows listener and the isolated Linux mesh peer deliberately
share a destination address in their separate network namespaces. Correct mesh
traffic reaches Linux; direct bypass reaches Windows. The Windows observer
accepts only the authorized phone and records empty TCP accepts as well as UDP
datagrams. Its lifetime is at most ten minutes. Before and after controls prove
that the alternate path actually works. No host route, firewall or desktop
proxy/TUN setting was changed.

The mesh transport in this run is USB reverse TCP. This does not validate native
cellular transport, UDP/STUN/QUIC, IPv6, DNS/Fake-IP or generic discovery.

## Integrated prototype result

The successful fixture uses a shared virtual subnet for the phone and mesh peer.
The Android interface must actually change, keep the native generation, become
ready while the ordinary-app window is still running, and pass peer-source and
alternate-path checks.

| Check | Result |
| --- | --- |
| Ordinary-app unchanged-interface window | 1,444 attempts, 1,444 replies |
| Forced interface replacements | 3/3 |
| Ordinary-app transition attempts / replies | 4,159 / 4,140 |
| Peer-observed wrong sources | 0 |
| Alternate-path observations during steady/replacement windows | 0 |
| Bidirectional TCP, UDP and ICMP | 5/5 each |
| Bidirectional 4,096-byte ICMP | 5/5 each |
| TCP/UDP and reverse ICMP after each replacement | 5/5 each |
| Alternate-path controls before and after | passed, all four modes |
| Instrumentation / temporary-resource cleanup | passed |

This supports “not reproduced on this phone under these tested conditions.” It
does not prove that replacement is safe on all Android 12+ devices, nor does a
finite run establish a zero leak probability.

Provenance:

- Prototype APK SHA-256:
  `f6560523b63b9b9a437cd7b20be643dea47be7da538c6c7e86da254e28cf404a`.
- Matching instrumentation APK SHA-256:
  `96493fe9f66dc3ab5c509513a696ce5bc9d6af685d7bc372376175fc3f35c37c`.
- Separate physical diagnostic APK SHA-256:
  `2db5b8def2bcf4364f9bca3f7748ebca137781c885c2752367a5a67fd619bb04`.
- Successful private result JSON SHA-256:
  `7a83b394cfcc5ae3f4725b46c9fd54b04dacd43be0133b019ea36be84880272f`.

The diagnostic uses a bounded foreground data-sync service, automatically stopped
within 15 seconds. Without it, this phone froze the test process when the stock
VPN UI returned to the foreground: all four result files remained unfinished
after their first response. That invalid run is not a networking failure.

## Stock EasyTier and incomplete parity

Installed EasyTier 2.6.4, APK SHA-256
`53444ada74838e91504ae8d3ee2688bc91ee9cf43f36b969c07de6af696f723c`,
was tested with a newly created disposable network. The original network was
not edited. Its valid foreground-service steady window completed 1,521 attempts
and 1,518 replies, with zero wrong sources or direct-path observations.

A new auxiliary peer advertised an additional private route. The Linux core
confirmed the route, but it did not appear in the stock Android VPN and its
interface index remained unchanged. Therefore the successful traffic windows
**do not constitute a stock EasyTier interface-replacement test**. The prototype
uses a private forced-rebuild trigger, so the triggers are not matched.

Earlier invalid fixture attempts are retained separately:

- Restarting a Docker fixture changed its published port; stale USB forwarding
  prevented the stock network from connecting.
- The installed stock app round-tripped a `/32` manual route as a bare IP and
  failed VPN startup with `Invalid route cidr string`. A proper CIDR in the
  disposable fixture removed this setup error.
- A Linux return route was missing when the virtual peers used different subnets.
  Only the isolated container route was corrected.
- One route-announcement helper did not connect because it bound a loopback
  destination to its physical device. A separate container corrected that setup.

The prototype also failed basic connectivity in a different-virtual-subnet
layout, before any replacement. The failed result is retained. Its cause is not
established by the successful same-subnet test; arbitrary remote subnet/source
handling needs its own trace and acceptance case.

Stock CMFA was not modified or experimentally compared in this run. No claim of
complete original CMFA/EasyTier/prototype parity is made.

## Supported-range gate remains open

[Native run 40833169373](https://github.com/DariusOne/ClashMetaForAndroid-EasyTier/actions/runs/40833169373)
built and checked the same prototype. API 31 passed its first two forced
replacements but the third observed two wrong-source TCP connections, one Java
NIO and one AF_INET. The gate failed. Host/native/build checks passed; the
[normal build](https://github.com/DariusOne/ClashMetaForAndroid-EasyTier/actions/runs/40833175369)
also passed.

The verified APK was retained as `NOT-ACCEPTED-DIAGNOSTIC` to permit the explicitly
authorized phone comparison. It is not a release or an acceptance result. The
draft remains unmerged. Earlier independent discard-only API 31/35 controls
remain valid counterexamples; see [Android 12+ support](ANDROID12-SUPPORT.md).
