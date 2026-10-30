//go:build (linux || android) && with_gvisor

package tun

import (
	"bytes"
	"encoding/json"
	"io"
	"net/netip"
	"syscall"

	router "github.com/DariusOne/ClashMetaForAndroid-EasyTier/native/packet-router"
	C "github.com/metacubex/mihomo/constant"
)

// PacketSessionConfig contains no credentials. The Kotlin VPN owner supplies
// literal addresses only after it has built the single interface and isolated
// native transport. This API is for the development acceptance harness.
type PacketSessionConfig struct {
	Policy  router.Config    `json:"policy"`
	Gateway []netip.Prefix   `json:"gateway"`
	DNS     []netip.AddrPort `json:"dns"`
	MTU     uint32           `json:"mtu"`
}

func ParsePacketSession(data []byte) (PacketSessionConfig, error) {
	var c PacketSessionConfig
	if len(data) == 0 || len(data) > 512*1024 {
		return c, ErrHybridStart
	}
	d := json.NewDecoder(bytes.NewReader(data))
	d.DisallowUnknownFields()
	if d.Decode(&c) != nil || d.Decode(new(any)) != io.EOF || c.MTU < 1280 || c.MTU > 1380 || len(c.Gateway) == 0 || len(c.Gateway) > 4 || len(c.DNS) > 4 {
		return PacketSessionConfig{}, ErrHybridStart
	}
	if c.Policy.Mode != router.Combined && c.Policy.Mode != router.MeshOnly {
		return PacketSessionConfig{}, ErrHybridStart
	}
	if _, err := router.NewPolicy(c.Policy); err != nil {
		return PacketSessionConfig{}, ErrHybridStart
	}
	for _, g := range c.Gateway {
		if !g.IsValid() || g.Bits() == 0 || !g.Addr().IsGlobalUnicast() {
			return PacketSessionConfig{}, ErrHybridStart
		}
	}
	for _, d := range c.DNS {
		if !d.IsValid() || d.Port() != 53 {
			return PacketSessionConfig{}, ErrHybridStart
		}
	}
	return c, nil
}

// StartPacketSession ALWAYS adopts both descriptors, even on failed validation.
// Native EasyTier receives the other end of meshFD, never the Android TUN.
func StartPacketSession(tunFD, meshFD int, c PacketSessionConfig, delegate C.Tunnel) (*Hybrid, error) {
	closeFDs := func() {
		if tunFD >= 0 {
			syscall.Close(tunFD)
		}
		if meshFD >= 0 && meshFD != tunFD {
			syscall.Close(meshFD)
		}
	}
	if tunFD < 0 || meshFD < 0 || tunFD == meshFD {
		closeFDs()
		return nil, ErrHybridStart
	}
	fds, err := syscall.Socketpair(syscall.AF_UNIX, syscall.SOCK_DGRAM|syscall.SOCK_CLOEXEC|syscall.SOCK_NONBLOCK, 0)
	if err != nil {
		closeFDs()
		return nil, ErrHybridStart
	}
	engine, err := StartPacketMihomo(fds[1], c.Gateway, c.DNS, c.MTU, delegate)
	if err != nil {
		syscall.Close(fds[0])
		closeFDs()
		return nil, ErrHybridStart
	}
	return StartHybrid(tunFD, fds[0], meshFD, engine, c.Policy)
}
