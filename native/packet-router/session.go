package packetrouter

import (
	"bytes"
	"encoding/json"
	"io"
	"net/netip"
)

// NativeSnapshot is the deliberately small native IPC contract. No peer URI,
// network secret or raw native event is allowed across this boundary.
type NativeSnapshot struct {
	Schema     int      `json:"schema"`
	Generation uint64   `json:"generation"`
	Running    bool     `json:"running"`
	Attached   bool     `json:"attached"`
	Addresses  []string `json:"addresses"`
	Routes     []string `json:"routes"`
}

func ParseNativeSnapshot(data []byte) (NativeSnapshot, error) {
	var s NativeSnapshot
	if len(data) == 0 || len(data) > 512*1024 {
		return s, ErrInvalidPolicy
	}
	d := json.NewDecoder(bytes.NewReader(data))
	d.DisallowUnknownFields()
	if d.Decode(&s) != nil || s.Schema != 1 || s.Generation == 0 || len(s.Addresses) > 2 || len(s.Routes) > 4096 {
		return NativeSnapshot{}, ErrInvalidPolicy
	}
	if d.Decode(new(any)) != io.EOF {
		return NativeSnapshot{}, ErrInvalidPolicy
	}
	if _, _, err := s.parsed(); err != nil {
		return NativeSnapshot{}, err
	}
	return s, nil
}

func (s NativeSnapshot) parsed() ([]netip.Prefix, []netip.Prefix, error) {
	addresses := make([]netip.Prefix, 0, len(s.Addresses))
	routes := make([]netip.Prefix, 0, len(s.Routes))
	families := map[bool]bool{}
	for _, text := range s.Addresses {
		p, err := netip.ParsePrefix(text)
		if err != nil || p.Bits() == 0 || !p.Addr().IsGlobalUnicast() || p.Addr().Is4In6() || p.Addr().IsLinkLocalUnicast() || families[p.Addr().Is4()] {
			return nil, nil, ErrInvalidPolicy
		}
		families[p.Addr().Is4()] = true
		addresses = append(addresses, p)
	}
	for _, text := range s.Routes {
		p, err := netip.ParsePrefix(text)
		if err != nil {
			return nil, nil, ErrInvalidPolicy
		}
		routes = append(routes, p)
	}
	routes, err := prefixes(routes, true)
	return addresses, routes, err
}

// ApplyNativeSnapshot is one transaction: withdrawal, DHCP changes, destination
// ownership and readiness never become visible as unrelated partial updates.
// Address changes need a new Android interface; until acknowledged all mesh
// traffic stays closed, including known routes withdrawn by the new snapshot.
func (p *Policy) ApplyNativeSnapshot(s NativeSnapshot, installedAddresses []netip.Prefix) error {
	addresses, routes, err := s.parsed()
	if err != nil || s.Schema != 1 || len(s.Addresses) > 2 || len(s.Routes) > 4096 {
		return ErrInvalidPolicy
	}
	virtual := make([]netip.Prefix, 0, len(addresses))
	device := make([]netip.Addr, 0, len(addresses))
	installed := len(addresses) > 0 && len(addresses) == len(installedAddresses)
	for _, a := range addresses {
		virtual = append(virtual, a.Masked())
		device = append(device, a.Addr())
		found := false
		for _, i := range installedAddresses {
			found = found || i == a
		}
		installed = installed && found
	}
	p.mu.Lock()
	defer p.mu.Unlock()
	old := p.v.Load()
	if old == nil || old.config.Mode == ProxyOnly || old.config.Session != s.Generation {
		return ErrStaleSession
	}
	active, err := mergePrefixes(virtual, routes)
	if err != nil {
		return err
	}
	for _, r := range active {
		if overlapsAny(r, old.config.Reserved) {
			return ErrInvalidPolicy
		}
	}
	claimed, err := mergePrefixes(old.claimed, active)
	if err != nil {
		return err
	}
	// A peer may advertise IPv6 while this phone owns only IPv4 (or vice
	// versa). Keep that ownership closed rather than emitting a packet using
	// the unrelated Mihomo gateway as the mesh source address.
	usable := make([]netip.Prefix, 0, len(active))
	for _, route := range active {
		for _, address := range addresses {
			if address.Addr().Is4() == route.Addr().Is4() {
				usable = append(usable, route)
				break
			}
		}
	}
	next := *old
	next.config.VirtualNetworks, next.config.DeviceAddresses = virtual, device
	next.active, next.claimed = usable, claimed
	next.ready = s.Running && s.Attached && installed
	p.v.Store(&next)
	return nil
}

// SetConflicts never replaces routes and refuses a stale physical-network choice.
func (p *Policy) SetConflicts(session uint64, profile, network string, choices []Conflict) error {
	p.mu.Lock()
	defer p.mu.Unlock()
	old := p.v.Load()
	if old == nil || old.config.Session != session || old.config.Profile != profile || old.config.Network != network {
		return ErrStaleSession
	}
	c := old.config
	c.Conflicts = choices
	validated, err := NewPolicy(c)
	if err != nil {
		return err
	}
	next := *old
	next.config.Conflicts = validated.v.Load().config.Conflicts
	p.v.Store(&next)
	return nil
}
