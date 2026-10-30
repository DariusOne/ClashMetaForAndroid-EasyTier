//go:build linux && with_gvisor

package tun

import (
	"context"
	"io"
	"net"
	"net/netip"
	"testing"
	"time"

	router "github.com/DariusOne/ClashMetaForAndroid-EasyTier/native/packet-router"
	"github.com/metacubex/gvisor/pkg/tcpip"
	"github.com/metacubex/gvisor/pkg/tcpip/adapters/gonet"
	"github.com/metacubex/gvisor/pkg/tcpip/header"
	"github.com/metacubex/gvisor/pkg/tcpip/network/ipv4"
	"github.com/metacubex/gvisor/pkg/tcpip/stack"
	"github.com/metacubex/gvisor/pkg/tcpip/transport/tcp"
	"github.com/metacubex/gvisor/pkg/tcpip/transport/udp"
	"github.com/metacubex/mihomo/component/nat"
	C "github.com/metacubex/mihomo/constant"
)

type echoTunnel struct {
	seen chan *C.Metadata
	nat  nat.Table
}

func (e *echoTunnel) HandleTCPConn(c net.Conn, m *C.Metadata) {
	defer c.Close()
	e.seen <- m
	_, _ = io.Copy(c, c)
}
func (e *echoTunnel) HandleUDPPacket(p C.UDPPacket, m *C.Metadata) {
	defer p.Drop()
	e.seen <- m
	_, _ = p.WriteBack(p.Data(), net.UDPAddrFromAddrPort(netip.AddrPortFrom(m.DstIP, m.DstPort)))
}
func (e *echoTunnel) NatTable() C.NatTable { return &e.nat }

// Real gVisor TCP/UDP -> datagram adapter -> Mihomo inbound -> response. The
// delegate is an in-process echo, so this is NOT Android or real-peer acceptance.
func TestPacketMihomoTCPUDP(t *testing.T) {
	for _, source := range [][4]byte{{172, 19, 0, 1}, {10, 77, 0, 2}} {
		t.Run(netip.AddrFrom4(source).String(), func(t *testing.T) { packetMihomoTCPUDP(t, source) })
	}
}

func packetMihomoTCPUDP(t *testing.T, source [4]byte) {
	peer, fd, err := router.NewPacketPair()
	if err != nil {
		t.Fatal(err)
	}
	echo := &echoTunnel{seen: make(chan *C.Metadata, 32)}
	engine, err := StartPacketMihomo(fd, []netip.Prefix{netip.MustParsePrefix("172.19.0.1/30")}, nil, 1380, echo)
	if err != nil {
		peer.Close()
		t.Fatal(err)
	}
	t.Cleanup(func() { engine.Close() })
	dev := newPacketDevice(peer, 1380)
	endpoint, _, err := dev.NewEndpoint()
	if err != nil {
		t.Fatal(err)
	}
	s := stack.New(stack.Options{NetworkProtocols: []stack.NetworkProtocolFactory{ipv4.NewProtocol}, TransportProtocols: []stack.TransportProtocolFactory{tcp.NewProtocol, udp.NewProtocol}})
	t.Cleanup(func() { dev.Close(); s.Close(); s.Wait() })
	if err := s.CreateNIC(1, endpoint); err != nil {
		t.Fatal(err)
	}
	a := tcpip.AddrFrom4(source)
	if err := s.AddProtocolAddress(1, tcpip.ProtocolAddress{Protocol: ipv4.ProtocolNumber, AddressWithPrefix: tcpip.AddressWithPrefix{Address: a, PrefixLen: 30}}, stack.AddressProperties{}); err != nil {
		t.Fatal(err)
	}
	s.SetRouteTable([]tcpip.Route{{Destination: header.IPv4EmptySubnet, NIC: 1}})
	ctx, cancel := context.WithTimeout(context.Background(), 15*time.Second)
	defer cancel()
	// An unrelated private address is handed to the original Mihomo delegate,
	// exactly like a public address; the bridge never chooses DIRECT itself.
	for _, ip := range [][4]byte{{198, 51, 100, 20}, {192, 168, 90, 20}} {
		addr := tcpip.FullAddress{NIC: 1, Addr: tcpip.AddrFrom4(ip), Port: 23456}
		for i := 0; i < 5; i++ {
			c, err := gonet.DialContextTCP(ctx, s, addr, ipv4.ProtocolNumber)
			if err != nil {
				t.Fatal(err)
			}
			c.SetDeadline(time.Now().Add(2 * time.Second))
			_, err = c.Write([]byte("mesh-bridge-fixture"))
			if err != nil {
				c.Close()
				t.Fatal(err)
			}
			b := make([]byte, 19)
			_, err = io.ReadFull(c, b)
			c.Close()
			if err != nil || string(b) != "mesh-bridge-fixture" {
				t.Fatalf("TCP roundtrip: %v", err)
			}
			select {
			case m := <-echo.seen:
				if m.DstIP != netip.AddrFrom4(ip) {
					t.Fatal("destination changed")
				}
			case <-ctx.Done():
				t.Fatal(ctx.Err())
			}
		}
		c, err := gonet.DialUDP(s, nil, &addr, ipv4.ProtocolNumber)
		if err != nil {
			t.Fatal(err)
		}
		c.SetDeadline(time.Now().Add(2 * time.Second))
		for i := 0; i < 5; i++ {
			_, err = c.Write([]byte("udp-fixture"))
			if err != nil {
				c.Close()
				t.Fatal(err)
			}
			b := make([]byte, 32)
			n, err := c.Read(b)
			if err != nil || string(b[:n]) != "udp-fixture" {
				c.Close()
				t.Fatalf("UDP roundtrip: %v", err)
			}
			select {
			case <-echo.seen:
			case <-ctx.Done():
				t.Fatal(ctx.Err())
			}
		}
		c.Close()
	}
}
