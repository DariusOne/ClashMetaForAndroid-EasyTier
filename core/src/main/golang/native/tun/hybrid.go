//go:build linux || android

package tun

import (
	"context"
	"errors"
	"io"
	"net/netip"
	"sync"
	"sync/atomic"
	"syscall"

	router "github.com/DariusOne/ClashMetaForAndroid-EasyTier/native/packet-router"
)

var ErrHybridStart = errors.New("hybrid packet engine startup failed")

// Hybrid owns the one Android TUN and both router-side endpoints. The native
// EasyTier instance owns the peer of meshFD; Mihomo owns the peer of ClashPort.
// It is deliberately not wired into TunService until device acceptance passes.
type Hybrid struct {
	policy          *router.Policy
	dispatcher      *router.Dispatcher
	mihomo          io.Closer
	cancel          context.CancelFunc
	done            chan struct{}
	once            sync.Once
	engineOnce      sync.Once
	updates         sync.Mutex
	interfacePort   *router.InterfacePort
	interfacePaused bool
	stopped         atomic.Bool
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
	if engine == nil || fd < 0 || clashFD < 0 || meshFD < 0 || fd == meshFD || fd == clashFD || meshFD == clashFD || (config.Mode != router.Combined && config.Mode != router.MeshOnly) {
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
	h.interfacePort = router.NewInterfacePort(tunPort)
	h.dispatcher = &router.Dispatcher{Policy: p, Tun: h.interfacePort, ClashPort: clashPort, MeshPort: meshPort, Session: config.Session, QueueSize: 64}
	go func() { defer close(h.done); _ = h.dispatcher.Run(ctx); h.stopEngine() }()
	return h, nil
}

func (h *Hybrid) ReplaceRoutes(session uint64, routes []netip.Prefix) error {
	return h.policy.ReplaceRoutes(session, routes)
}
func (h *Hybrid) SetReady(session uint64, ready bool) error {
	h.updates.Lock()
	defer h.updates.Unlock()
	if h.stopped.Load() || (ready && h.interfacePaused) {
		return ErrHybridStart
	}
	return h.policy.SetReady(session, ready)
}
func (h *Hybrid) ApplySnapshot(snapshot router.NativeSnapshot, installed []netip.Prefix) error {
	h.updates.Lock()
	defer h.updates.Unlock()
	if h.stopped.Load() || h.interfacePaused {
		return ErrHybridStart
	}
	return h.policy.ApplyNativeSnapshot(snapshot, installed)
}

// RefreshNetwork changes only packet policy, never the Android descriptor or
// either engine. Network disappearance retains the VPN; recovery reopens mesh
// destinations only after the current network scope and snapshot are committed.
func (h *Hybrid) RefreshNetwork(snapshot router.NativeSnapshot, installed []netip.Prefix, network string, locals []netip.Prefix) error {
	h.updates.Lock()
	defer h.updates.Unlock()
	if h.stopped.Load() || h.interfacePaused {
		return ErrHybridStart
	}
	return h.policy.RefreshNativeNetwork(snapshot, installed, network, locals)
}

// SuspendInterface must complete before Android Builder.establish replaces the
// old TUN. Keep both engines and the SAME policy (including withdrawn routes).
func (h *Hybrid) SuspendInterface(session uint64) error {
	h.updates.Lock()
	defer h.updates.Unlock()
	if h.stopped.Load() {
		return ErrHybridStart
	}
	if err := h.policy.SetReady(session, false); err != nil {
		return err
	}
	if err := h.interfacePort.Pause(); err != nil {
		return err
	}
	h.interfacePaused = true
	return nil
}

// ReplaceInterface ALWAYS adopts fd, including stale-session/error paths.
// The reader remains paused until the new physical-network conflict scope and
// native snapshot have been committed. No engine is restarted or re-identified.
func (h *Hybrid) ReplaceInterface(fd int, snapshot router.NativeSnapshot, installed []netip.Prefix, network string, locals []netip.Prefix) error {
	port, err := router.AdoptFD(fd)
	if err != nil {
		return ErrHybridStart
	}
	h.updates.Lock()
	defer h.updates.Unlock()
	if h.stopped.Load() || !h.interfacePaused {
		port.Close()
		return ErrHybridStart
	}
	if err := h.policy.NetworkChanged(snapshot.Generation, network, locals); err != nil {
		port.Close()
		return err
	}
	// Validate the snapshot while still closed. Only the final acknowledgement
	// may make it ready; a failed replacement never reopens the previous device.
	closed := snapshot
	closed.Attached = false
	if err := h.policy.ApplyNativeSnapshot(closed, installed); err != nil {
		port.Close()
		return err
	}
	if err := h.interfacePort.Replace(port); err != nil {
		return err
	}
	if err := h.policy.ApplyNativeSnapshot(snapshot, installed); err != nil {
		return err
	}
	if err := h.interfacePort.Resume(); err != nil {
		_ = h.policy.SetReady(snapshot.Generation, false)
		return err
	}
	h.interfacePaused = false
	return nil
}
func (h *Hybrid) SetConflicts(session uint64, profile, network string, choices []router.Conflict) error {
	return h.policy.SetConflicts(session, profile, network, choices)
}
func (h *Hybrid) NetworkChanged(session uint64, network string, locals []netip.Prefix) error {
	return h.policy.NetworkChanged(session, network, locals)
}
func (h *Hybrid) Close() error {
	h.once.Do(func() { h.cancel(); h.stopEngine(); <-h.done })
	return nil
}

func (h *Hybrid) stopEngine() {
	h.engineOnce.Do(func() { h.stopped.Store(true); _ = h.mihomo.Close() })
}

func (h *Hybrid) Done() <-chan struct{} { return h.done }
