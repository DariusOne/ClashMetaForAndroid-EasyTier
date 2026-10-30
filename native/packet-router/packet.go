package packetrouter

import (
	"encoding/binary"
	"errors"
	"net/netip"
)

var ErrInvalidPacket = errors.New("invalid IP packet")

// DestinationIP validates the L3 frame boundary, including fragmented packets.
// Transport parsing belongs to each engine, so routing never requires a TCP/UDP
// header and also supports ICMP and noninitial fragments.
func DestinationIP(packet []byte) (netip.Addr, error) {
	if len(packet) == 0 {
		return netip.Addr{}, ErrInvalidPacket
	}
	switch packet[0] >> 4 {
	case 4:
		if len(packet) < 20 {
			return netip.Addr{}, ErrInvalidPacket
		}
		header := int(packet[0]&15) * 4
		if header < 20 || header > len(packet) || int(binary.BigEndian.Uint16(packet[2:4])) != len(packet) {
			return netip.Addr{}, ErrInvalidPacket
		}
		return netip.AddrFrom4([4]byte(packet[16:20])), nil
	case 6:
		if len(packet) < 40 || 40+int(binary.BigEndian.Uint16(packet[4:6])) != len(packet) {
			return netip.Addr{}, ErrInvalidPacket
		}
		return netip.AddrFrom16([16]byte(packet[24:40])), nil
	default:
		return netip.Addr{}, ErrInvalidPacket
	}
}
