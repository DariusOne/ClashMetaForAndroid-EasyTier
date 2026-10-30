package packetrouter

import (
	"net/netip"
	"testing"
)

func TestPhysicalRefreshRetainsOwnershipAndResetsOnlyChangedConflictScope(t *testing.T) {
	p, _ := NewPolicy(Config{Mode: Combined, Session: 7, Profile: "fixture", Network: "wifi"})
	s := NativeSnapshot{Schema: 1, Generation: 7, Running: true, Attached: true, Addresses: []string{"10.77.0.2/24"}, Routes: []string{"192.168.12.0/24"}}
	installed := []netip.Prefix{netip.MustParsePrefix(s.Addresses[0])}
	locals := []netip.Prefix{netip.MustParsePrefix("10.77.0.0/24")}
	if err := p.RefreshNativeNetwork(s, installed, "wifi", locals); err != nil {
		t.Fatal(err)
	}
	choice := []Conflict{{Prefix: locals[0], Choice: UseClash}}
	if err := p.SetConflicts(7, "fixture", "wifi", choice); err != nil {
		t.Fatal(err)
	}
	if err := p.RefreshNativeNetwork(s, installed, "wifi", locals); err != nil {
		t.Fatal(err)
	}
	if p.Decide(netip.MustParseAddr("10.77.0.9")) != Clash {
		t.Fatal("same-network choice discarded")
	}
	s.Routes = nil
	if err := p.RefreshNativeNetwork(s, installed, "cell", locals); err != nil {
		t.Fatal(err)
	}
	if p.Decide(netip.MustParseAddr("10.77.0.9")) != Drop {
		t.Fatal("conflict crossed physical networks")
	}
	if p.Decide(netip.MustParseAddr("192.168.12.9")) != Drop {
		t.Fatal("withdrawal escaped on handover")
	}
	if p.Decide(netip.MustParseAddr("192.168.13.9")) != Clash {
		t.Fatal("unmanaged private destination changed")
	}
	if err := p.RefreshNativeNetwork(s, installed, "new-wifi", nil); err != nil {
		t.Fatal(err)
	}
	if p.Decide(netip.MustParseAddr("10.77.0.9")) != EasyTier {
		t.Fatal("mesh did not recover with unchanged interface")
	}
	before := p.v.Load()
	stale := s
	stale.Generation++
	if p.RefreshNativeNetwork(stale, installed, "bad-network", nil) == nil || p.v.Load() != before {
		t.Fatal("stale refresh changed policy")
	}
	if p.RefreshNativeNetwork(s, installed, "", nil) == nil || p.v.Load() != before {
		t.Fatal("invalid network changed policy")
	}
}

func TestSnapshotAddressChangeFailsClosedUntilInstalled(t *testing.T) {
	p, err := NewPolicy(Config{Mode: Combined, Session: 1, Profile: "fixture", Network: "wifi"})
	if err != nil {
		t.Fatal(err)
	}
	s := NativeSnapshot{Schema: 1, Generation: 1, Running: true, Attached: true, Addresses: []string{"10.77.0.2/24"}, Routes: []string{"192.168.12.0/24"}}
	old := []netip.Prefix{netip.MustParsePrefix(s.Addresses[0])}
	if err := p.ApplyNativeSnapshot(s, old); err != nil {
		t.Fatal(err)
	}
	if p.Decide(netip.MustParseAddr("192.168.12.5")) != EasyTier {
		t.Fatal("published network lost")
	}
	s.Addresses = []string{"10.78.0.2/24"}
	s.Routes = nil
	if err := p.ApplyNativeSnapshot(s, old); err != nil {
		t.Fatal(err)
	}
	for _, ip := range []string{"10.77.0.5", "10.78.0.5", "192.168.12.5"} {
		if p.Decide(netip.MustParseAddr(ip)) != Drop {
			t.Fatal("DHCP/withdrawal fell through")
		}
	}
	if p.Decide(netip.MustParseAddr("192.168.13.5")) != Clash {
		t.Fatal("unrelated LAN changed")
	}
	if err := p.ApplyNativeSnapshot(s, []netip.Prefix{netip.MustParsePrefix(s.Addresses[0])}); err != nil {
		t.Fatal(err)
	}
	if p.Decide(netip.MustParseAddr("10.78.0.5")) != EasyTier || p.Decide(netip.MustParseAddr("10.77.0.5")) != Drop {
		t.Fatal("address transaction")
	}
}

func TestSnapshotValidationIsTransactional(t *testing.T) {
	p, _ := NewPolicy(Config{Mode: Combined, Session: 3, Profile: "fixture", Network: "wifi", VirtualNetworks: []netip.Prefix{netip.MustParsePrefix("10.77.0.0/24")}})
	p.SetReady(3, true)
	for _, text := range []string{
		`{"schema":1,"generation":3,"running":true,"addresses":["0.0.0.0/0"]}`,
		`{"schema":1,"generation":3,"routes":["0.0.0.0/0"]}`,
		`{"schema":1,"generation":3,"addresses":["10.1.0.2/24","10.2.0.2/24"]}`,
		`{"schema":1,"generation":3,"secret":"must-not-cross"}`,
		`{"schema":1,"generation":3} {}`,
	} {
		if _, err := ParseNativeSnapshot([]byte(text)); err == nil {
			t.Fatal("invalid snapshot accepted")
		}
	}
	if err := p.ApplyNativeSnapshot(NativeSnapshot{Schema: 1, Generation: 2}, nil); err != ErrStaleSession {
		t.Fatal(err)
	}
	if p.Decide(netip.MustParseAddr("10.77.0.9")) != EasyTier {
		t.Fatal("old policy changed")
	}
}

func TestOverlapChoiceCannotCrossNetworkOrProfile(t *testing.T) {
	p, _ := NewPolicy(Config{Mode: Combined, Session: 4, Profile: "fixture", Network: "wifi", VirtualNetworks: []netip.Prefix{netip.MustParsePrefix("10.77.0.0/24")}, LocalNetworks: []netip.Prefix{netip.MustParsePrefix("10.77.0.0/24")}})
	p.SetReady(4, true)
	choices := []Conflict{{Prefix: netip.MustParsePrefix("10.77.0.0/24"), Choice: UseClash}}
	if p.SetConflicts(4, "other", "wifi", choices) != ErrStaleSession || p.SetConflicts(4, "fixture", "cell", choices) != ErrStaleSession {
		t.Fatal("scope escaped")
	}
	if p.Decide(netip.MustParseAddr("10.77.0.5")) != Drop {
		t.Fatal("unresolved conflict leaked")
	}
	if err := p.SetConflicts(4, "fixture", "wifi", choices); err != nil {
		t.Fatal(err)
	}
	if p.Decide(netip.MustParseAddr("10.77.0.5")) != Clash {
		t.Fatal("original clash not selected")
	}
	p.NetworkChanged(4, "cell", []netip.Prefix{netip.MustParsePrefix("10.77.0.0/24")})
	if p.Decide(netip.MustParseAddr("10.77.0.5")) != Drop {
		t.Fatal("old decision reused")
	}
}

func TestAdvertisedFamilyWithoutPhoneAddressStaysClosed(t *testing.T) {
	p, _ := NewPolicy(Config{Mode: Combined, Session: 1, Profile: "fixture", Network: "wifi"})
	s := NativeSnapshot{Schema: 1, Generation: 1, Running: true, Attached: true, Addresses: []string{"10.77.0.2/24"}, Routes: []string{"fd77::/64"}}
	if err := p.ApplyNativeSnapshot(s, []netip.Prefix{netip.MustParsePrefix(s.Addresses[0])}); err != nil {
		t.Fatal(err)
	}
	if p.Decide(netip.MustParseAddr("fd77::9")) != Drop {
		t.Fatal("unowned IPv6 source admitted")
	}
	if p.Decide(netip.MustParseAddr("fd78::9")) != Clash {
		t.Fatal("other IPv6 LAN changed")
	}
}
