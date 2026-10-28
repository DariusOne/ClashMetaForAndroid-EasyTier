# Android 12+ native integration support

The native integrated prototype requires Android 12 / API 31 from commit
`6e6f6681fcf8861524033984afb44e6f80399221`. This is a build/install boundary,
not a claim that every Android 12+ device passes packet-path acceptance. The
normal proxy-only CMFA build retains its independent compatibility contract.

The package check requires `sdkVersion: 31`, the separate prototype application
ID, exactly one VPN service and both supported native payloads. A runtime guard
also rejects pre-31 native startup. Target SDK, routing semantics, private-network
bypass, application exclusions and system VPN settings are unchanged.

## Public-API control on the supported range

[Run 40690226334](https://github.com/DariusOne/ClashMetaForAndroid-EasyTier/actions/runs/40690226334)
uses two independent Java-only fixture APKs on disposable Google API emulators.
The VPN reads and discards packets; it opens no outbound sockets, writes no TUN
packets and includes no CMFA, Mihomo or EasyTier library. Another ordinary app UID
continuously opens Java NIO and explicit AF_INET TCP/UDP sockets before and during
each interface replacement. No always-on/lockdown settings are enabled.

| Observation | Android 12 / API 31 | Android 15 / API 35 |
| --- | ---: | ---: |
| Eight-second transition windows | 6 | 6 |
| Interface replacements | 12 | 12 |
| Socket attempts during those windows | 3,654 | 3,573 |
| Peer-observed TCP accepts | 3 | 23 |
| Peer-observed UDP datagrams | 4 | 33 |
| Replies received by the probe | 6 | 49 |
| Peer observations with unchanged drop-only VPN | 0 | 0 |
| Before/after reachability controls | passed | passed |
| Fixture completion and cleanup | passed | passed |
| Strict transition containment | **failed** | **failed** |

Peer observations include TCP accepts without a completed response. A timed-out
request is not automatically safe. These finite tests prove a counterexample on
these images; they neither characterize every vendor build nor measure a general
leak probability. The larger number on API 35 is not a platform ranking.

Image identity:

- API 31: `SE1A.220826.008/10564458`, security patch `2022-10-01`.
- API 35: `AE3A.240806.043/12960925`, security patch `2024-09-05`.

Evidence ZIP SHA-256:

- API 31: `156a0521f68cfb1932df0e5eb3d5f9761ac72a368c663c54ef029c7c91e85afb`.
- API 35: `63db2340f5db4def04737f4fd1c21b18b502e55d02017f826d5448bb0c8af3b6`.

## Integrated prototype gate

The [native suite](https://github.com/DariusOne/ClashMetaForAndroid-EasyTier/actions/runs/40690226349)
now targets API 31 and completed at commit `6e6f6681fcf8861524033984afb44e6f80399221`.
Host policy, race/fuzz, native configuration and Mihomo packet adapter checks
passed. The APK compiled and its actual manifest check reported `min_sdk: 31`,
one VPN owner and six native libraries across the two ABIs. The separate normal
CMFA build also passed [run 40690236412](https://github.com/DariusOne/ClashMetaForAndroid-EasyTier/actions/runs/40690236412).

On the API 31 emulator:

- Ten native VPN start/stop cycles and native-child crash isolation passed.
- Bidirectional TCP, UDP and ICMP each passed 5/5. Nonmesh TCP/UDP and original
  REJECT behavior passed; Rule/Direct/Global preserved their expected behavior.
- All six Wi-Fi/cellular transitions retained the interface and native session,
  observed zero wrong sources, and passed TCP/UDP 5/5 after each transition.
- The first forced interface replacement **failed**. The peer accepted two
  wrong-source TCP connections from the ordinary app UID: one Java NIO and one
  explicit AF_INET probe. Neither returned a successful response; counting only
  client replies would have missed both. Shell Go/Bionic probes happened to see
  zero wrong sources in this window and do not override the ordinary-app failure.
- The fixture stopped at that strict failure, so later replacements and the
  first replacement's post-ready 5/5 were not run. Cleanup passed. The failed
  integrated APK was not uploaded/released.

Native evidence ZIP SHA-256:
`52b8b22d6ec1cc55ece7518b72b789d9443b1b97edf9f126b3d30f2ddf968403`.

Physical-network changes retain the existing TUN when addresses/capture routes
have not changed. Changes that actually require a new interface remain a separate
acceptance case. Post-ready 5/5 success cannot override traffic that escaped
during replacement. Android 11 is outside the new native support range, while
its original evidence remains in [the historical investigation](ANDROID11-HANDOVER.md).

The minimum-version change therefore does not close the dynamic handover gate.
No failed APK is released, no system setting workaround is silently adopted,
and UI/generator rollout remains behind the [device gate](DEVICE-ACCEPTANCE.md).
