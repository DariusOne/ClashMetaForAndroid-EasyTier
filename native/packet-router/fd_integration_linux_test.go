//go:build linux || android

package packetrouter

import (
	"context"
	"testing"
	"time"
)

func runRealPorts(t *testing.T, tun, phone, clash, mihomo, mesh, native *FDPort) {
	t.Helper()
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	d := &Dispatcher{Policy: readyPolicy(t), Tun: tun, ClashPort: clash, MeshPort: mesh, Session: 1, QueueSize: 8}
	done := make(chan error, 1)
	go func() { done <- d.Run(ctx) }()
	read := func(p *FDPort, want string) {
		t.Helper()
		result := make(chan []byte, 1)
		go func() {
			b := make([]byte, 65535)
			n, e := p.ReadPacket(b)
			if e != nil {
				result <- nil
			} else {
				result <- b[:n]
			}
		}()
		receive(t, result, want)
	}
	for i := 0; i < 5; i++ {
		if e := phone.WritePacket(packet("10.88.99.3")); e != nil {
			t.Fatal(e)
		}
		read(native, "10.88.99.3")
		if e := native.WritePacket(packet("10.88.99.2")); e != nil {
			t.Fatal(e)
		}
		read(phone, "10.88.99.2")
		if e := phone.WritePacket(packet("192.168.111.3")); e != nil {
			t.Fatal(e)
		}
		read(mihomo, "192.168.111.3")
		if e := mihomo.WritePacket(packet("172.19.0.1")); e != nil {
			t.Fatal(e)
		}
		read(phone, "172.19.0.1")
	}
	cancel()
	select {
	case <-done:
	case <-time.After(2 * time.Second):
		t.Fatal("FD workers not cancelled")
	}
}
