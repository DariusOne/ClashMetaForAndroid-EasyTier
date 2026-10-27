package packetrouter

import (
	"encoding/binary"
	"net/netip"
	"sync"
	"testing"
)

func pfx(s string) netip.Prefix { return netip.MustParsePrefix(s) }
func addr(s string) netip.Addr  { return netip.MustParseAddr(s) }
func testConfig() Config {
	return Config{Mode: Combined, Session: 1, Profile: "test-mesh", Network: "wifi-a", VirtualNetworks: []netip.Prefix{pfx("10.88.99.0/24")}, DeviceAddresses: []netip.Addr{addr("10.88.99.2")}, Reserved: []netip.Prefix{pfx("198.18.0.0/15"), pfx("172.19.0.0/30")}}
}
func readyPolicy(t *testing.T) *Policy {
	t.Helper()
	p, err := NewPolicy(testConfig())
	if err != nil {
		t.Fatal(err)
	}
	_ = p.SetReady(1, true)
	return p
}

func TestOnlyManagedDestinations(t *testing.T) {
	p := readyPolicy(t)
	if err := p.ReplaceRoutes(1, []netip.Prefix{pfx("192.168.100.0/24"), pfx("fd42:1234::/64")}); err != nil {
		t.Fatal(err)
	}
	for _, ip := range []string{"10.88.99.20", "192.168.100.8", "fd42:1234::9"} {
		if p.Decide(addr(ip)) != EasyTier {
			t.Fatal(ip)
		}
	}
	// These must be delegated, not rewritten DIRECT, REJECT or a proxy choice.
	for _, ip := range []string{"192.168.111.8", "10.0.0.7", "172.16.5.2", "8.8.8.8", "127.0.0.1", "fd42:4321::1", "2001:4860::8888", "198.18.2.3", "172.19.0.2"} {
		if p.Decide(addr(ip)) != Clash {
			t.Fatal(ip)
		}
	}
}

func TestFailureAndWithdrawalDoNotLeak(t *testing.T) {
	p := readyPolicy(t)
	remote := []netip.Prefix{pfx("192.168.100.0/24")}
	_ = p.ReplaceRoutes(1, remote)
	_ = p.SetReady(1, false)
	if p.Decide(addr("192.168.100.3")) != Drop || p.Decide(addr("10.88.99.3")) != Drop || p.Decide(addr("192.168.111.3")) != Clash {
		t.Fatal("failure policy")
	}
	_ = p.SetReady(1, true)
	_ = p.ReplaceRoutes(1, nil)
	if p.Decide(addr("192.168.100.3")) != Drop {
		t.Fatal("withdrawal leaked")
	}
	_ = p.ReplaceRoutes(1, remote)
	if p.Decide(addr("192.168.100.3")) != EasyTier {
		t.Fatal("restore")
	}
}

func TestOverlapDecisionsAreNetworkScoped(t *testing.T) {
	c := testConfig()
	c.LocalNetworks = []netip.Prefix{pfx("192.168.100.0/25")}
	p, _ := NewPolicy(c)
	_ = p.ReplaceRoutes(1, []netip.Prefix{pfx("192.168.100.0/24")})
	_ = p.SetReady(1, true)
	if p.Decide(addr("192.168.100.10")) != Drop || p.Decide(addr("192.168.100.200")) != EasyTier {
		t.Fatal("intersection scope")
	}
	c.Conflicts = []Conflict{{pfx("192.168.100.0/25"), UseClash}}
	_ = p.Begin(c)
	_ = p.ReplaceRoutes(1, []netip.Prefix{pfx("192.168.100.0/24")})
	_ = p.SetReady(1, true)
	if p.Decide(addr("192.168.100.10")) != Clash {
		t.Fatal("delegate to original Clash")
	}
	_ = p.NetworkChanged(1, "wifi-b", c.LocalNetworks)
	if p.Decide(addr("192.168.100.10")) != Drop {
		t.Fatal("stale network choice")
	}
	c.Conflicts[0].Choice = UseEasyTier
	_ = p.Begin(c)
	_ = p.ReplaceRoutes(1, []netip.Prefix{pfx("192.168.100.0/24")})
	_ = p.SetReady(1, true)
	if p.Decide(addr("192.168.100.10")) != EasyTier {
		t.Fatal("explicit mesh")
	}
}

func TestSessionsAndTransactions(t *testing.T) {
	p := readyPolicy(t)
	for _, route := range []string{"0.0.0.0/0", "::/0", "10.0.0.1/24", "198.18.1.0/24", "224.0.0.0/4", "::ffff:192.168.1.0/120"} {
		if p.ReplaceRoutes(1, []netip.Prefix{pfx(route)}) == nil {
			t.Fatalf("accepted %s", route)
		}
		if p.Decide(addr("10.88.99.1")) != EasyTier {
			t.Fatal("failed transaction mutated state")
		}
	}
	if p.ReplaceRoutes(2, []netip.Prefix{pfx("192.168.1.0/24")}) != ErrStaleSession {
		t.Fatal("accepted another instance")
	}
	c := testConfig()
	c.Session = 2
	c.VirtualNetworks = []netip.Prefix{pfx("10.90.0.0/24")}
	_ = p.Begin(c)
	if p.SetReady(1, true) != ErrStaleSession {
		t.Fatal("old callback")
	}
	if p.Decide(addr("10.88.99.1")) != Clash || p.Decide(addr("10.90.0.1")) != Drop {
		t.Fatal("profile isolation")
	}
	// Caller-owned slices must not mutate the active configuration.
	c.VirtualNetworks[0] = pfx("10.99.0.0/24")
	if p.Decide(addr("10.90.0.1")) != Drop {
		t.Fatal("alias")
	}
}

func TestModesAndDiscovery(t *testing.T) {
	c := testConfig()
	c.Broadcast = true
	c.Multicast = []netip.Addr{addr("239.255.255.250"), addr("ff02::fb")}
	p, _ := NewPolicy(c)
	_ = p.SetReady(1, true)
	for _, ip := range []string{"10.88.99.255", "255.255.255.255", "239.255.255.250", "ff02::fb"} {
		if p.Decide(addr(ip)) != EasyTier || !p.AcceptMeshReturn(addr(ip)) {
			t.Fatal(ip)
		}
	}
	if p.Decide(addr("224.0.0.251")) != Clash {
		t.Fatal("unselected multicast intercepted")
	}
	if p.AcceptMeshReturn(addr("8.8.8.8")) || !p.AcceptMeshReturn(addr("10.88.99.2")) {
		t.Fatal("mesh transit/phone")
	}
	c.Mode = ProxyOnly
	_ = p.Begin(c)
	if p.Decide(addr("10.88.99.3")) != Clash {
		t.Fatal("proxy mode")
	}
	c.Mode = MeshOnly
	_ = p.Begin(c)
	_ = p.SetReady(1, true)
	if p.Decide(addr("10.88.99.3")) != EasyTier || p.Decide(addr("8.8.8.8")) != Drop {
		t.Fatal("mesh mode captures only mesh routes")
	}
}

func TestConcurrentPolicyReplacement(t *testing.T) {
	p := readyPolicy(t)
	var wg sync.WaitGroup
	for i := 0; i < 8; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			for j := 0; j < 2000; j++ {
				_ = p.Decide(addr("10.88.99.3"))
				_ = p.ReplaceRoutes(1, []netip.Prefix{pfx("192.168.100.0/24")})
				_ = p.SetReady(1, j%2 == 0)
			}
		}()
	}
	wg.Wait()
}

func packet(ip string) []byte {
	a := addr(ip)
	if a.Is4() {
		b := make([]byte, 28)
		b[0] = 0x45
		b[9] = 17
		binary.BigEndian.PutUint16(b[2:4], uint16(len(b)))
		a4 := a.As4()
		copy(b[16:20], a4[:])
		return b
	}
	b := make([]byte, 48)
	b[0] = 0x60
	b[6] = 17
	binary.BigEndian.PutUint16(b[4:6], 8)
	a6 := a.As16()
	copy(b[24:40], a6[:])
	return b
}

func TestPacketValidation(t *testing.T) {
	for _, ip := range []string{"10.88.99.3", "fd42:1234::9"} {
		b := packet(ip)
		got, err := DestinationIP(b)
		if err != nil || got != addr(ip) {
			t.Fatal(got, err)
		}
		if _, err = DestinationIP(b[:len(b)-1]); err == nil {
			t.Fatal("truncation")
		}
	}
	b := packet("10.88.99.3")
	b[6] = 1 // noninitial fragment: still routed by IP
	if _, err := DestinationIP(b); err != nil {
		t.Fatal(err)
	}
	b[0] = 0x44
	if _, err := DestinationIP(b); err == nil {
		t.Fatal("bad IHL")
	}
	for _, b := range [][]byte{nil, {0}, {0x45}, {0x60}, make([]byte, 100)} {
		if _, err := DestinationIP(b); err == nil {
			t.Fatal("bad packet")
		}
	}
}

func FuzzDestinationIP(f *testing.F) {
	f.Add(packet("10.88.99.3"))
	f.Add(packet("fd42::1"))
	f.Add([]byte{})
	f.Fuzz(func(t *testing.T, b []byte) {
		a, e := DestinationIP(b)
		if e == nil && !a.IsValid() {
			t.Fatal("invalid accepted address")
		}
	})
}
