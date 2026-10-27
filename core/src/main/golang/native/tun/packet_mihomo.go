//go:build (linux || android) && with_gvisor

package tun

import (
	"context"
	"io"
	"net/netip"
	"sync"
	"sync/atomic"

	router "github.com/DariusOne/ClashMetaForAndroid-EasyTier/native/packet-router"
	"github.com/metacubex/gvisor/pkg/buffer"
	"github.com/metacubex/gvisor/pkg/tcpip/header"
	"github.com/metacubex/gvisor/pkg/tcpip/link/channel"
	"github.com/metacubex/gvisor/pkg/tcpip/stack"
	C "github.com/metacubex/mihomo/constant"
	"github.com/metacubex/mihomo/listener/sing"
	"github.com/metacubex/mihomo/listener/sing_tun"
	"github.com/metacubex/mihomo/log"
	stun "github.com/metacubex/sing-tun"
)

// packetDevice gives gVisor a bounded L3 endpoint, not another OS TUN. Every FD
// has exactly one owner; Close cancels both packet pumps before returning.
type packetDevice struct {
	port     router.Port
	endpoint *channel.Endpoint
	ctx      context.Context
	cancel   context.CancelFunc
	once     sync.Once
	started  atomic.Bool
	wg       sync.WaitGroup
}

func newPacketDevice(port router.Port, mtu uint32) *packetDevice {
	ctx, cancel := context.WithCancel(context.Background())
	return &packetDevice{port: port, endpoint: channel.New(64, mtu, ""), ctx: ctx, cancel: cancel}
}
func (d *packetDevice) Read(b []byte) (int, error) { return d.port.ReadPacket(b) }
func (d *packetDevice) Write(b []byte) (int, error) {
	if err := d.port.WritePacket(b); err != nil {
		return 0, err
	}
	return len(b), nil
}
func (d *packetDevice) WritePacket(p *stack.PacketBuffer) (int, error) {
	v := p.ToView()
	defer v.Release()
	return d.Write(v.AsSlice())
}
func (d *packetDevice) NewEndpoint() (stack.LinkEndpoint, stack.NICOptions, error) {
	if !d.started.CompareAndSwap(false, true) {
		return nil, stack.NICOptions{}, router.ErrPort
	}
	d.wg.Add(2)
	go func() {
		defer d.wg.Done()
		b := make([]byte, 65535)
		for {
			n, err := d.port.ReadPacket(b)
			if err != nil {
				d.cancel()
				return
			}
			if n < 0 || n > len(b) {
				continue
			}
			ip, err := router.DestinationIP(b[:n])
			if err != nil {
				continue
			}
			protocol := header.IPv4ProtocolNumber
			if ip.Is6() {
				protocol = header.IPv6ProtocolNumber
			}
			p := stack.NewPacketBuffer(stack.PacketBufferOptions{Payload: buffer.MakeWithData(append([]byte(nil), b[:n]...))})
			d.endpoint.InjectInbound(protocol, p)
			p.DecRef()
		}
	}()
	go func() {
		defer d.wg.Done()
		for {
			p := d.endpoint.ReadContext(d.ctx)
			if p == nil {
				return
			}
			_, err := d.WritePacket(p)
			p.DecRef()
			if err != nil {
				d.cancel()
				d.port.Close()
				return
			}
		}
	}()
	return d.endpoint, stack.NICOptions{}, nil
}
func (d *packetDevice) Close() error {
	d.once.Do(func() { d.cancel(); d.port.Close(); d.endpoint.Close(); d.wg.Wait() })
	return nil
}

type packetMihomo struct {
	device *packetDevice
	stack  stun.Stack
	once   sync.Once
}

func (m *packetMihomo) Close() error {
	m.once.Do(func() { m.device.Close(); m.stack.Close() })
	return nil
}

// StartPacketMihomo adopts a packet endpoint. It reuses Mihomo's TUN handler and
// DNS interception; routing/rules are still supplied by the original C.Tunnel.
// This prototype does not yet install a post-Fake-IP mesh flow hook.
func StartPacketMihomo(fd int, gateway []netip.Prefix, dns []netip.AddrPort, mtu uint32, tunnel C.Tunnel) (io.Closer, error) {
	port, err := router.AdoptFD(fd)
	if err != nil {
		return nil, err
	}
	device := newPacketDevice(port, mtu)
	failed := true
	defer func() {
		if failed {
			device.Close()
		}
	}()
	if tunnel == nil || mtu < 1280 || mtu > 1380 || len(gateway) == 0 {
		return nil, ErrHybridStart
	}
	var v4, v6 []netip.Prefix
	for _, p := range gateway {
		if !p.IsValid() || p.Bits() == 0 {
			return nil, ErrHybridStart
		}
		if p.Addr().Is4() {
			v4 = append(v4, p)
		} else {
			v6 = append(v6, p)
		}
	}
	h, err := sing.NewListenerHandler(sing.ListenerConfig{Tunnel: tunnel, Type: C.TUN})
	if err != nil {
		return nil, ErrHybridStart
	}
	handler := &sing_tun.ListenerHandler{ListenerHandler: h, DnsAddrPorts: append([]netip.AddrPort(nil), dns...), Inet4Address: v4, Inet6Address: v6}
	s, err := stun.NewStack("gvisor", stun.StackOptions{
		Context: device.ctx, Tun: device, TunOptions: stun.Options{MTU: mtu, Inet4Address: v4, Inet6Address: v6},
		Handler: handler, Logger: log.SingLogger, UDPTimeout: sing.UDPTimeout, ICMPTimeout: sing.ICMPTimeout,
	})
	if err != nil {
		return nil, ErrHybridStart
	}
	if err = s.Start(); err != nil {
		s.Close()
		return nil, ErrHybridStart
	}
	failed = false
	return &packetMihomo{device: device, stack: s}, nil
}
