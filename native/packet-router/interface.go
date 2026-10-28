package packetrouter

import (
	"io"
	"sync"
)

// InterfacePort keeps one dispatcher/mesh session alive across Android TUN
// replacement. Pause MUST precede Builder.establish(): Android can invalidate
// the old TUN before the new descriptor is returned. Only the owning controller
// calls Pause/Replace/Resume. It never pauses or replaces either engine port.
type InterfacePort struct {
	mu             sync.Mutex
	port           Port
	changed        chan struct{}
	epoch          uint64
	paused, closed bool
}

func NewInterfacePort(port Port) *InterfacePort {
	return &InterfacePort{port: port, changed: make(chan struct{})}
}

func (p *InterfacePort) signal() {
	close(p.changed)
	p.changed = make(chan struct{})
	p.epoch++
}

// Pause retains the descriptor (and therefore the existing Android VPN) while
// the owner constructs the replacement. In-flight packets from the old epoch
// are discarded. Engine return traffic is dropped, never sent to another port.
func (p *InterfacePort) Pause() error {
	p.mu.Lock()
	defer p.mu.Unlock()
	if p.closed {
		return io.ErrClosedPipe
	}
	p.paused = true
	p.signal()
	return nil
}

// Replace always adopts next, including errors, and leaves the reader paused
// until policy and installed-address acknowledgement are committed by Resume.
func (p *InterfacePort) Replace(next Port) error {
	p.mu.Lock()
	if p.closed || !p.paused || next == nil {
		p.mu.Unlock()
		if next != nil {
			next.Close()
		}
		return io.ErrClosedPipe
	}
	old := p.port
	p.port = next
	p.signal()
	p.mu.Unlock()
	if old != nil {
		old.Close()
	}
	return nil
}

func (p *InterfacePort) Resume() error {
	p.mu.Lock()
	defer p.mu.Unlock()
	if p.closed || p.port == nil {
		return io.ErrClosedPipe
	}
	p.paused = false
	p.signal()
	return nil
}

func (p *InterfacePort) ReadPacket(b []byte) (int, error) {
	for {
		p.mu.Lock()
		if p.closed {
			p.mu.Unlock()
			return 0, io.ErrClosedPipe
		}
		if p.paused {
			changed := p.changed
			p.mu.Unlock()
			<-changed
			continue
		}
		port, epoch := p.port, p.epoch
		p.mu.Unlock()
		n, err := port.ReadPacket(b)
		p.mu.Lock()
		stale := p.epoch != epoch || p.paused
		closed := p.closed
		p.mu.Unlock()
		if closed {
			return 0, io.ErrClosedPipe
		}
		if stale {
			continue
		}
		return n, err
	}
}

func (p *InterfacePort) WritePacket(b []byte) error {
	p.mu.Lock()
	if p.closed {
		p.mu.Unlock()
		return io.ErrClosedPipe
	}
	if p.paused {
		p.mu.Unlock()
		return nil
	}
	port, epoch := p.port, p.epoch
	p.mu.Unlock()
	err := port.WritePacket(b)
	p.mu.Lock()
	stale := p.epoch != epoch || p.paused
	closed := p.closed
	p.mu.Unlock()
	if closed {
		return io.ErrClosedPipe
	}
	if stale {
		return nil
	}
	return err
}

func (p *InterfacePort) Close() error {
	p.mu.Lock()
	if p.closed {
		p.mu.Unlock()
		return nil
	}
	p.closed = true
	p.signal()
	port := p.port
	p.port = nil
	p.mu.Unlock()
	if port != nil {
		return port.Close()
	}
	return nil
}
