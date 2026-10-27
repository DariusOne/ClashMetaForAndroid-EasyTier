package packetrouter

import (
	"net/netip"
	"testing"
)

func TestResolvedOwnershipIsSameAsPackets(t *testing.T) {
	p, _ := NewPolicy(Config{Mode: Combined, Session: 5, Profile: "fixture", Network: "wifi", VirtualNetworks: []netip.Prefix{netip.MustParsePrefix("10.77.0.0/24")}, Reserved: []netip.Prefix{netip.MustParsePrefix("28.0.0.0/8")}})
	p.SetReady(5, true)
	for _, text := range []string{"10.77.0.9", "192.168.55.3", "172.16.3.4", "fd12::3", "198.51.100.8", "28.0.0.8"} {
		ip := netip.MustParseAddr(text)
		r := p.DecideResolved([]netip.Addr{ip})
		if r.Destination != p.Decide(ip) {
			t.Fatal("raw/resolved ownership differs")
		}
		if r.Destination == Clash && r.Address.IsValid() {
			t.Fatal("nonmesh resolution was pinned")
		}
	}
	mixed := []netip.Addr{netip.MustParseAddr("10.77.0.9"), netip.MustParseAddr("198.51.100.8")}
	if p.DecideResolved(mixed).Destination != Drop {
		t.Fatal("mixed answer fallback")
	}
	p.SetReady(5, false)
	if p.DecideResolved(mixed[:1]).Destination != Drop {
		t.Fatal("mesh failure fallback")
	}
	if p.DecideResolved(mixed[1:]).Destination != Clash {
		t.Fatal("unrelated flow changed")
	}
}

func TestResolvedAnswerBoundsAndModes(t *testing.T) {
	p, _ := NewPolicy(Config{Mode: ProxyOnly})
	if p.DecideResolved(nil).Destination != Drop || p.DecideResolved(make([]netip.Addr, 65)).Destination != Drop {
		t.Fatal("answer bound")
	}
	ip := netip.MustParseAddr("10.77.0.9")
	if p.DecideResolved([]netip.Addr{ip}).Destination != Clash {
		t.Fatal("proxy-only changed")
	}
	p.Begin(Config{Mode: MeshOnly, Session: 1, Profile: "fixture", Network: "wifi"})
	if p.DecideResolved([]netip.Addr{ip}).Destination != Drop {
		t.Fatal("mesh-only forwarded nonmesh")
	}
}
