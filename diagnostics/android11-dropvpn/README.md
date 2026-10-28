# Android 11 drop-only public API control

The directory name preserves the original reproduction. The active CI matrix
now uses API 31 and API 35 for the requested Android 12+ integration target.
`CMFA_CONTROL_API` selects only a disposable test image (30, 31 or 35), never a
phone or product setting. Historical API 30 evidence is retained. The Java
fixture's foreground-service declaration also supports the API 35 control.

This is a diagnostic, not a new product mode or workaround. The user rejected
always-on/lockdown prerequisites, disabling private-network bypass, disabling
app exclusions and manual reconnect. Those requirements remain unchanged.

The dedicated workflow creates a new explicitly selected emulator, compiles two tiny Java
APKs without CMFA, Mihomo or EasyTier libraries, and uses only public VPN APIs.
The VPN discards every packet it receives and never writes to its interface or
opens an outgoing socket. An independent app UID runs TCP/UDP requests to one
fixed synthetic endpoint on the disposable runner. The existing probe's
`passed` field means ordinary mesh success and is NOT the control verdict here.
Instead, **any accepted TCP connection or UDP datagram while the dropping VPN
is established is a containment failure**, even if the requesting app times out.

Before/after reachability, no-replacement drop baseline, exact new interface
readiness, packet-discard counters and bounded replacement windows are checked.
All APKs, the synthetic host address and the VPN are removed afterwards. The
workflow exports only JSON, never its APKs. Consent pre-grant is confined to
the verified empty CI emulator; the runner refuses a real device, an existing
package, or existing always-on settings. No system VPN setting is changed.

This helps distinguish OS handover routing from an engine/dispatcher bug. A
finite all-zero run would not prove absence of every escaped SYN or compatibility
on other Android builds. The native strict acceptance gate remains separate.
