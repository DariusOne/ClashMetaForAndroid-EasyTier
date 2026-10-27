package packetrouter

import (
	"context"
	"errors"
	"io"
	"sync"
	"sync/atomic"
)

// Port preserves one IP packet per read/write. Close MUST unblock outstanding
// reads and writes. It is owned by Dispatcher after Run starts. Engines never
// read the Android TUN directly.
type Port interface {
	ReadPacket([]byte) (int, error)
	WritePacket([]byte) error
	Close() error
}

var ErrPort = errors.New("packet port failed")

type Counters struct {
	Clash, Mesh, Returned, Malformed, PolicyDrop, QueueDrop, EngineDrop atomic.Uint64
}

type Dispatcher struct {
	Policy                   *Policy
	Tun, ClashPort, MeshPort Port
	Session                  uint64
	QueueSize                int
	Counters                 Counters
	started                  atomic.Bool
	writeMu                  sync.Mutex
}

// Run has separate bounded engine queues; a congested or failed EasyTier engine
// cannot stall nonmesh traffic. Errors never redirect a mesh packet to Mihomo.
func (d *Dispatcher) Run(parent context.Context) error {
	if d.Policy == nil || d.Tun == nil || d.ClashPort == nil || d.MeshPort == nil || d.QueueSize < 1 || d.QueueSize > 1024 {
		return ErrPort
	}
	if !d.started.CompareAndSwap(false, true) {
		return ErrPort
	}
	ctx, cancel := context.WithCancel(parent)
	defer cancel()
	var wg sync.WaitGroup
	var closeOnce sync.Once
	closeAll := func() { closeOnce.Do(func() { d.Tun.Close(); d.ClashPort.Close(); d.MeshPort.Close() }) }
	defer func() { cancel(); closeAll(); wg.Wait() }()
	wg.Add(1)
	go func() { defer wg.Done(); <-ctx.Done(); closeAll() }()
	clashQueue, meshQueue := make(chan []byte, d.QueueSize), make(chan []byte, d.QueueSize)
	var clashDead, meshDead atomic.Bool
	startEngine := func(port Port, queue chan []byte, dead *atomic.Bool, mesh bool) {
		fail := func() {
			if dead.CompareAndSwap(false, true) {
				if mesh {
					_ = d.Policy.SetReady(d.Session, false)
				}
				port.Close()
			}
		}
		wg.Add(2)
		go func() {
			defer wg.Done()
			for {
				select {
				case <-ctx.Done():
					return
				case packet := <-queue:
					if dead.Load() {
						d.Counters.EngineDrop.Add(1)
						continue
					}
					if err := port.WritePacket(packet); err != nil {
						d.Counters.EngineDrop.Add(1)
						fail()
					}
				}
			}
		}()
		go func() {
			defer wg.Done()
			buffer := make([]byte, 65535)
			for {
				n, err := port.ReadPacket(buffer)
				if err != nil {
					fail()
					return
				}
				if n < 0 || n > len(buffer) {
					d.Counters.Malformed.Add(1)
					continue
				}
				addr, err := DestinationIP(buffer[:n])
				if err != nil {
					d.Counters.Malformed.Add(1)
					continue
				}
				if mesh && !d.Policy.AcceptMeshReturn(addr) {
					d.Counters.PolicyDrop.Add(1)
					continue
				}
				d.writeMu.Lock()
				err = d.Tun.WritePacket(buffer[:n])
				d.writeMu.Unlock()
				if err != nil {
					cancel()
					return
				}
				d.Counters.Returned.Add(1)
			}
		}()
	}
	startEngine(d.ClashPort, clashQueue, &clashDead, false)
	startEngine(d.MeshPort, meshQueue, &meshDead, true)
	buffer := make([]byte, 65535)
	for {
		n, err := d.Tun.ReadPacket(buffer)
		if err != nil {
			cancel()
			if parent.Err() != nil {
				return parent.Err()
			}
			if errors.Is(err, io.EOF) {
				return nil
			}
			return ErrPort
		}
		if n < 0 || n > len(buffer) {
			d.Counters.Malformed.Add(1)
			continue
		}
		addr, err := DestinationIP(buffer[:n])
		if err != nil {
			d.Counters.Malformed.Add(1)
			continue
		}
		var queue chan []byte
		switch d.Policy.Decide(addr) {
		case Clash:
			if !clashDead.Load() {
				queue = clashQueue
				d.Counters.Clash.Add(1)
			}
		case EasyTier:
			if !meshDead.Load() {
				queue = meshQueue
				d.Counters.Mesh.Add(1)
			}
		default:
			d.Counters.PolicyDrop.Add(1)
			continue
		}
		if queue == nil {
			d.Counters.EngineDrop.Add(1)
			continue
		}
		packet := append([]byte(nil), buffer[:n]...)
		select {
		case queue <- packet:
		default:
			d.Counters.QueueDrop.Add(1)
		}
	}
}
