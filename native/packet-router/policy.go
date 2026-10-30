// Package packetrouter owns only the choice between native EasyTier and Mihomo.
// Clash means delegate unchanged, including Global/Direct mode and LAN rules.
package packetrouter

import (
	"errors"
	"net/netip"
	"slices"
	"sort"
	"sync"
	"sync/atomic"
)

type Destination uint8

const (
	Drop Destination = iota
	Clash
	EasyTier
)

type Mode uint8

const (
	ProxyOnly Mode = iota
	MeshOnly
	Combined
)

type Choice uint8

const (
	Ask Choice = iota
	UseEasyTier
	UseClash
)

var (
	ErrInvalidPolicy = errors.New("invalid routing policy")
	ErrStaleSession  = errors.New("stale mesh session")
)

// Conflict choices are scoped to a profile AND the current physical network.
// A LAN change therefore cannot inherit a decision for the previous LAN.
type Conflict struct {
	Prefix netip.Prefix
	Choice Choice
}

type Config struct {
	Mode            Mode
	Session         uint64
	Profile         string
	Network         string
	LocalNetworks   []netip.Prefix
	VirtualNetworks []netip.Prefix
	DeviceAddresses []netip.Addr
	Reserved        []netip.Prefix // Mihomo DNS, Fake-IP and internal TUN ranges
	Conflicts       []Conflict
	Broadcast       bool
	Multicast       []netip.Addr // explicitly enabled by the selected mesh profile
}

type view struct {
	config  Config
	active  []netip.Prefix
	claimed []netip.Prefix // withdrawn routes remain closed until a new session
	ready   bool
}

type Policy struct {
	mu sync.Mutex
	v  atomic.Pointer[view]
}

func NewPolicy(config Config) (*Policy, error) {
	p := &Policy{}
	if err := p.Begin(config); err != nil {
		return nil, err
	}
	return p, nil
}

// Begin is a configuration transaction. Invalid input leaves the old view intact.
func (p *Policy) Begin(c Config) error {
	if c.Mode > Combined || (c.Mode != ProxyOnly && (c.Session == 0 || c.Profile == "" || c.Network == "")) {
		return ErrInvalidPolicy
	}
	var err error
	if c.LocalNetworks, err = prefixes(c.LocalNetworks, false); err != nil {
		return err
	}
	if c.Reserved, err = prefixes(c.Reserved, false); err != nil {
		return err
	}
	if c.VirtualNetworks, err = prefixes(c.VirtualNetworks, true); err != nil {
		return err
	}
	for _, r := range c.VirtualNetworks {
		if overlapsAny(r, c.Reserved) {
			return ErrInvalidPolicy
		}
	}
	c.DeviceAddresses = append([]netip.Addr(nil), c.DeviceAddresses...)
	for _, a := range c.DeviceAddresses {
		if !a.IsValid() || a.Zone() != "" || a.Is4In6() || !a.IsGlobalUnicast() {
			return ErrInvalidPolicy
		}
	}
	c.Multicast = append([]netip.Addr(nil), c.Multicast...)
	for _, a := range c.Multicast {
		if !a.IsMulticast() || a.Zone() != "" || a.Is4In6() {
			return ErrInvalidPolicy
		}
	}
	c.Conflicts = append([]Conflict(nil), c.Conflicts...)
	seen := make(map[netip.Prefix]bool)
	for _, x := range c.Conflicts {
		if !x.Prefix.IsValid() || x.Prefix != x.Prefix.Masked() || x.Prefix.Bits() == 0 || x.Choice > UseClash || seen[x.Prefix] {
			return ErrInvalidPolicy
		}
		seen[x.Prefix] = true
	}
	sort.Slice(c.Conflicts, func(i, j int) bool { return c.Conflicts[i].Prefix.Bits() > c.Conflicts[j].Prefix.Bits() })
	p.mu.Lock()
	defer p.mu.Unlock()
	p.v.Store(&view{config: c, active: c.VirtualNetworks, claimed: c.VirtualNetworks})
	return nil
}

// ReplaceRoutes accepts routes only from the active native instance. No default
// route is accepted: the mesh is not allowed to become the general Internet exit.
func (p *Policy) ReplaceRoutes(session uint64, routes []netip.Prefix) error {
	routes, err := prefixes(routes, true)
	if err != nil {
		return err
	}
	p.mu.Lock()
	defer p.mu.Unlock()
	old := p.v.Load()
	if old == nil || old.config.Mode == ProxyOnly || old.config.Session != session {
		return ErrStaleSession
	}
	for _, r := range routes {
		if overlapsAny(r, old.config.Reserved) {
			return ErrInvalidPolicy
		}
	}
	active, err := mergePrefixes(old.config.VirtualNetworks, routes)
	if err != nil {
		return err
	}
	claimed, err := mergePrefixes(old.claimed, active)
	if err != nil {
		return err
	}
	next := *old
	next.active, next.claimed = active, claimed
	p.v.Store(&next)
	return nil
}

func (p *Policy) SetReady(session uint64, ready bool) error {
	p.mu.Lock()
	defer p.mu.Unlock()
	old := p.v.Load()
	if old == nil || old.config.Mode == ProxyOnly || old.config.Session != session {
		return ErrStaleSession
	}
	next := *old
	next.ready = ready
	p.v.Store(&next)
	return nil
}

// NetworkChanged discards overlap choices when the physical network changes.
// Rebuilding the Android interface on the same network preserves its choices.
func (p *Policy) NetworkChanged(session uint64, network string, locals []netip.Prefix) error {
	if network == "" {
		return ErrInvalidPolicy
	}
	locals, err := prefixes(locals, false)
	if err != nil {
		return err
	}
	p.mu.Lock()
	defer p.mu.Unlock()
	old := p.v.Load()
	if old == nil || old.config.Session != session {
		return ErrStaleSession
	}
	if old.config.Network == network && slices.Equal(old.config.LocalNetworks, locals) {
		return nil
	}
	next := *old
	next.config.Network, next.config.LocalNetworks, next.config.Conflicts = network, locals, nil
	p.v.Store(&next)
	return nil
}

func (p *Policy) Decide(addr netip.Addr) Destination {
	return decide(p.v.Load(), addr)
}

func decide(v *view, addr netip.Addr) Destination {
	if v == nil || !addr.IsValid() || addr.Zone() != "" {
		return Drop
	}
	addr = addr.Unmap()
	if v.config.Mode == ProxyOnly {
		return Clash
	}
	// Synthetic DNS and Fake-IP packets must reach Mihomo unchanged. Its flow
	// adapter must use this SAME policy again after resolving the real destination.
	if contains(v.config.Reserved, addr) {
		return fallback(v.config.Mode)
	}
	if discovery(v.config, addr) {
		if v.ready {
			return EasyTier
		}
		return Drop
	}
	if !contains(v.claimed, addr) {
		return fallback(v.config.Mode)
	}
	if contains(v.config.LocalNetworks, addr) {
		choice := Ask
		for _, x := range v.config.Conflicts {
			if x.Prefix.Contains(addr) {
				choice = x.Choice
				break
			}
		}
		switch choice {
		case UseClash:
			return fallback(v.config.Mode)
		case Ask:
			return Drop
		}
	}
	if v.ready && contains(v.active, addr) {
		return EasyTier
	}
	return Drop
}

// AcceptMeshReturn permits native mesh delivery only to addresses owned by the
// phone or explicitly enabled discovery destinations, never as a transit router.
func (p *Policy) AcceptMeshReturn(addr netip.Addr) bool {
	v := p.v.Load()
	if v == nil || !v.ready || v.config.Mode == ProxyOnly {
		return false
	}
	for _, a := range v.config.DeviceAddresses {
		if a == addr {
			return true
		}
	}
	return discovery(v.config, addr)
}

func fallback(mode Mode) Destination {
	if mode == MeshOnly {
		return Drop
	}
	return Clash
}

func discovery(c Config, a netip.Addr) bool {
	for _, group := range c.Multicast {
		if a == group {
			return true
		}
	}
	if !c.Broadcast || !a.Is4() {
		return false
	}
	if a == netip.MustParseAddr("255.255.255.255") {
		return true
	}
	x := a.As4()
	value := uint32(x[0])<<24 | uint32(x[1])<<16 | uint32(x[2])<<8 | uint32(x[3])
	for _, r := range c.VirtualNetworks {
		if r.Addr().Is4() && r.Bits() <= 30 && r.Contains(a) {
			mask := uint32(0xffffffff) >> r.Bits()
			if value&mask == mask {
				return true
			}
		}
	}
	return false
}

func contains(rs []netip.Prefix, a netip.Addr) bool {
	for _, r := range rs {
		if r.Contains(a) {
			return true
		}
	}
	return false
}
func overlapsAny(r netip.Prefix, rs []netip.Prefix) bool {
	for _, other := range rs {
		if r.Overlaps(other) {
			return true
		}
	}
	return false
}

func prefixes(rs []netip.Prefix, managed bool) ([]netip.Prefix, error) {
	if len(rs) > 4096 {
		return nil, ErrInvalidPolicy
	}
	seen := make(map[netip.Prefix]bool)
	result := make([]netip.Prefix, 0, len(rs))
	for _, r := range rs {
		if !r.IsValid() || r != r.Masked() || r.Addr().Is4In6() || r.Addr().Zone() != "" {
			return nil, ErrInvalidPolicy
		}
		if managed && (r.Bits() == 0 || !r.Addr().IsGlobalUnicast() || r.Addr().IsLinkLocalUnicast()) {
			return nil, ErrInvalidPolicy
		}
		if !seen[r] {
			result = append(result, r)
			seen[r] = true
		}
	}
	sort.Slice(result, func(i, j int) bool {
		if result[i].Bits() != result[j].Bits() {
			return result[i].Bits() > result[j].Bits()
		}
		return result[i].Addr().Less(result[j].Addr())
	})
	return result, nil
}

// The bound applies to unique owned routes. A repeat of the same large route
// snapshot must not fail simply because the old and new lists share entries.
func mergePrefixes(a, b []netip.Prefix) ([]netip.Prefix, error) {
	seen := make(map[netip.Prefix]struct{}, len(a))
	for _, list := range [][]netip.Prefix{a, b} {
		for _, p := range list {
			seen[p] = struct{}{}
			if len(seen) > 4096 {
				return nil, ErrInvalidPolicy
			}
		}
	}
	result := make([]netip.Prefix, 0, len(seen))
	for p := range seen {
		result = append(result, p)
	}
	return prefixes(result, true)
}
