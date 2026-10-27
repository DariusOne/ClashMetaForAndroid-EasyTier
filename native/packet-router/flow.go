package packetrouter

import "net/netip"

// ResolvedFlow is consumed after the original Mihomo DNS/Fake-IP processing.
// This layer performs no DNS query, changes no metadata and supplies no DIRECT
// proxy. The Mihomo flow hook and packet router MUST share the same Policy.
type ResolvedFlow struct {
	Destination Destination
	Address     netip.Addr
}

// DecideResolved uses one immutable view for all answers. A mixed mesh/nonmesh
// answer or withdrawn/overlapping route is ambiguous and stays closed; it must
// not fall through to another address through a proxy's happy-eyeballs retry.
// Nonmesh results leave endpoint selection to the original Mihomo path.
func (p *Policy) DecideResolved(answers []netip.Addr) ResolvedFlow {
	if len(answers) == 0 || len(answers) > 64 {
		return ResolvedFlow{Destination: Drop}
	}
	v := p.v.Load()
	owner := Drop
	var selected netip.Addr
	for i, address := range answers {
		next := decide(v, address)
		if next == Drop || (i > 0 && owner != next) {
			return ResolvedFlow{Destination: Drop}
		}
		owner = next
		if i == 0 {
			selected = address.Unmap()
		}
	}
	if owner == Clash {
		return ResolvedFlow{Destination: Clash}
	}
	return ResolvedFlow{Destination: owner, Address: selected}
}
