package packetrouter

import (
	"context"
	"io"
	"sync"
	"testing"
	"time"
)

type memoryPort struct {
	in, out chan []byte
	done    chan struct{}
	once    sync.Once
}

func newPort() *memoryPort {
	return &memoryPort{in: make(chan []byte, 32), out: make(chan []byte, 32), done: make(chan struct{})}
}
func (p *memoryPort) ReadPacket(b []byte) (int, error) {
	select {
	case <-p.done:
		return 0, io.EOF
	case pkt := <-p.in:
		return copy(b, pkt), nil
	}
}
func (p *memoryPort) WritePacket(b []byte) error {
	select {
	case <-p.done:
		return io.ErrClosedPipe
	case p.out <- append([]byte(nil), b...):
		return nil
	}
}
func (p *memoryPort) Close() error { p.once.Do(func() { close(p.done) }); return nil }
func receive(t *testing.T, ch <-chan []byte, want string) {
	t.Helper()
	select {
	case b := <-ch:
		got, err := DestinationIP(b)
		if err != nil || got != addr(want) {
			t.Fatal(got, err)
		}
	case <-time.After(2 * time.Second):
		t.Fatal("packet not delivered")
	}
}
func noReceive(t *testing.T, ch <-chan []byte) {
	t.Helper()
	select {
	case <-ch:
		t.Fatal("packet leaked")
	case <-time.After(20 * time.Millisecond):
	}
}

func TestBidirectionalDispatcherAndFailureIsolation(t *testing.T) {
	p := readyPolicy(t)
	tun, clash, mesh := newPort(), newPort(), newPort()
	d := &Dispatcher{Policy: p, Tun: tun, ClashPort: clash, MeshPort: mesh, Session: 1, QueueSize: 8}
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	done := make(chan error, 1)
	go func() { done <- d.Run(ctx) }()
	tun.in <- packet("10.88.99.3")
	receive(t, mesh.out, "10.88.99.3")
	noReceive(t, clash.out)
	tun.in <- packet("192.168.111.3")
	receive(t, clash.out, "192.168.111.3")
	mesh.in <- packet("10.88.99.2")
	receive(t, tun.out, "10.88.99.2")
	clash.in <- packet("172.19.0.1")
	receive(t, tun.out, "172.19.0.1")
	mesh.in <- packet("8.8.8.8")
	noReceive(t, tun.out)
	mesh.Close()
	deadline := time.Now().Add(2 * time.Second)
	for p.Decide(addr("10.88.99.3")) != Drop && time.Now().Before(deadline) {
		time.Sleep(time.Millisecond)
	}
	if p.Decide(addr("10.88.99.3")) != Drop {
		t.Fatal("mesh failure not closed")
	}
	tun.in <- packet("10.88.99.3")
	tun.in <- packet("8.8.8.8")
	receive(t, clash.out, "8.8.8.8")
	noReceive(t, clash.out)
	cancel()
	select {
	case <-done:
	case <-time.After(2 * time.Second):
		t.Fatal("cancel leaked worker")
	}
	for _, port := range []*memoryPort{tun, clash, mesh} {
		select {
		case <-port.done:
		default:
			t.Fatal("unclosed port")
		}
	}
}

func TestCongestedMeshDoesNotBlockClash(t *testing.T) {
	p := readyPolicy(t)
	tun, clash, mesh := newPort(), newPort(), newPort()
	mesh.out = make(chan []byte) // block writes
	d := &Dispatcher{Policy: p, Tun: tun, ClashPort: clash, MeshPort: mesh, Session: 1, QueueSize: 1}
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	done := make(chan error, 1)
	go func() { done <- d.Run(ctx) }()
	for i := 0; i < 20; i++ {
		tun.in <- packet("10.88.99.3")
	}
	tun.in <- packet("192.168.1.3")
	receive(t, clash.out, "192.168.1.3")
	if d.Counters.QueueDrop.Load() == 0 {
		t.Fatal("unbounded queue")
	}
	cancel()
	select {
	case <-done:
	case <-time.After(2 * time.Second):
		t.Fatal("blocked writer not cancelled")
	}
}

func TestStopRestartDoesNotReuseClosedPorts(t *testing.T) {
	for i := 0; i < 10; i++ {
		d := &Dispatcher{Policy: readyPolicy(t), Tun: newPort(), ClashPort: newPort(), MeshPort: newPort(), Session: 1, QueueSize: 1}
		ctx, cancel := context.WithCancel(context.Background())
		cancel()
		done := make(chan error, 1)
		go func() { done <- d.Run(ctx) }()
		select {
		case <-done:
		case <-time.After(2 * time.Second):
			t.Fatal("stop blocked")
		}
		if d.Run(context.Background()) != ErrPort {
			t.Fatal("reused dispatcher")
		}
	}
}
