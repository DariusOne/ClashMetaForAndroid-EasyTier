//go:build linux || android

package tun

import (
	"context"
	"errors"
	"io"
	"net/netip"
	"sync"
	"syscall"

	router "github.com/DariusOne/ClashMetaForAndroid-EasyTier/native/packet-router"
)

var ErrHybridStart = errors.New("hybrid packet engine startup failed")

// Hybrid owns the one Android TUN and both router-side endpoints. The native
// EasyTier instance owns the peer of meshFD; Mihomo owns the peer of ClashPort.
// It is deliberately not wired into TunService until device acceptance passes.
type Hybrid struct {
	policy     *router.Policy
	dispatcher *router.Dispatcher
	mihomo     io.Closer
	cancel     context.CancelFunc
	done       chan struct{}
	once       sync.Once
	engineOnce sync.Once
}

// StartHybrid adopts three router-side descriptors and an already initialized
// Mihomo engine, including on error. The caller initializes each engine with the
// OTHER end of its packet pair. This separates descriptor ownership from engine
// initialization: no failed constructor can accidentally double-close a reused FD.
// It requires protected native transport; it does not establish a VPN.
func StartHybrid(fd, clashFD, meshFD int, engine io.Closer, config router.Config) (*Hybrid, error) {
	closeInputs := func() {
		if engine != nil {
			_ = engine.Close()
		}
		seen := make(map[int]bool)
		for _, f := range []int{fd, clashFD, meshFD} {
			if f >= 0 && !seen[f] {
				_ = syscall.Close(f)
				seen[f] = true
			}
		}
	}
	if engine == nil || fd < 0 || clashFD < 0 || meshFD < 0 || fd == meshFD || fd == clashFD || meshFD == clashFD || config.Mode != router.Combined {
		closeInputs()
		return nil, ErrHybridStart
	}
	p, err := router.NewPolicy(config)
	if err != nil {
		closeInputs()
		return nil, ErrHybridStart
	}
	tunPort, err := router.AdoptFD(fd)
	if err != nil {
		_ = syscall.Close(clashFD)
		_ = syscall.Close(meshFD)
		_ = engine.Close()
		return nil, ErrHybridStart
	}
	clashPort, err := router.AdoptFD(clashFD)
	if err != nil {
		tunPort.Close()
		_ = syscall.Close(meshFD)
		_ = engine.Close()
		return nil, ErrHybridStart
	}
	meshPort, err := router.AdoptFD(meshFD)
	if err != nil {
		tunPort.Close()
		clashPort.Close()
		_ = engine.Close()
		return nil, ErrHybridStart
	}
	ctx, cancel := context.WithCancel(context.Background())
	h := &Hybrid{policy: p, mihomo: engine, cancel: cancel, done: make(chan struct{})}
	h.dispatcher = &router.Dispatcher{Policy: p, Tun: tunPort, ClashPort: clashPort, MeshPort: meshPort, Session: config.Session, QueueSize: 64}
	go func() { defer close(h.done); _ = h.dispatcher.Run(ctx); h.stopEngine() }()
	return h, nil
}

func (h *Hybrid) ReplaceRoutes(session uint64, routes []netip.Prefix) error {
	return h.policy.ReplaceRoutes(session, routes)
}
func (h *Hybrid) SetReady(session uint64, ready bool) error { return h.policy.SetReady(session, ready) }
func (h *Hybrid) NetworkChanged(session uint64, network string, locals []netip.Prefix) error {
	return h.policy.NetworkChanged(session, network, locals)
}
func (h *Hybrid) Close() error {
	h.once.Do(func() { h.cancel(); h.stopEngine(); <-h.done })
	return nil
}

func (h *Hybrid) stopEngine() { h.engineOnce.Do(func() { _ = h.mihomo.Close() }) }

func (h *Hybrid) Done() <-chan struct{} { return h.done }
