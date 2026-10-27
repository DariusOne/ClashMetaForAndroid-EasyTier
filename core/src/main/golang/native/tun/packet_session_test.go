//go:build linux && with_gvisor

package tun

import (
	"encoding/binary"
	"encoding/json"
	"net/netip"
	"os"
	"syscall"
	"testing"
	"time"

	router "github.com/DariusOne/ClashMetaForAndroid-EasyTier/native/packet-router"
	C "github.com/metacubex/mihomo/constant"
)

func sessionConfig() PacketSessionConfig {
	return PacketSessionConfig{
		Policy:  router.Config{Mode: router.Combined, Session: 42, Profile: "fixture", Network: "wifi", VirtualNetworks: []netip.Prefix{netip.MustParsePrefix("10.77.0.0/24")}, DeviceAddresses: []netip.Addr{netip.MustParseAddr("10.77.0.2")}},
		Gateway: []netip.Prefix{netip.MustParsePrefix("172.19.0.1/30")}, MTU: 1380,
	}
}

func packetPair(t *testing.T) (int, *os.File) {
	t.Helper()
	fds, err := syscall.Socketpair(syscall.AF_UNIX, syscall.SOCK_DGRAM|syscall.SOCK_CLOEXEC|syscall.SOCK_NONBLOCK, 0)
	if err != nil {
		t.Fatal(err)
	}
	f := os.NewFile(uintptr(fds[1]), "fixture-peer")
	t.Cleanup(func() { f.Close() })
	return fds[0], f
}

func ipFrame(src, dst [4]byte) []byte {
	p := make([]byte, 28)
	p[0], p[8], p[9] = 0x45, 64, 1
	binary.BigEndian.PutUint16(p[2:4], uint16(len(p)))
	copy(p[12:16], src[:])
	copy(p[16:20], dst[:])
	p[20] = 8
	return p
}

func TestPacketSessionLifecycleTenRestarts(t *testing.T) {
	before, err := os.ReadDir("/proc/self/fd")
	if err != nil {
		t.Fatal(err)
	}
	for i := 0; i < 10; i++ {
		tunFD, app := packetPair(t)
		meshFD, native := packetPair(t)
		h, err := StartPacketSession(tunFD, meshFD, sessionConfig(), &echoTunnel{seen: make(chan *C.Metadata, 8)})
		if err != nil {
			t.Fatal(err)
		}
		s := router.NativeSnapshot{Schema: 1, Generation: 42, Running: true, Attached: true, Addresses: []string{"10.77.0.2/24"}}
		if err := h.ApplySnapshot(s, []netip.Prefix{netip.MustParsePrefix("10.77.0.2/24")}); err != nil {
			h.Close()
			t.Fatal(err)
		}
		native.SetReadDeadline(time.Now().Add(time.Second))
		outgoing := ipFrame([4]byte{10, 77, 0, 2}, [4]byte{10, 77, 0, 9})
		if _, err := app.Write(outgoing); err != nil {
			h.Close()
			t.Fatal(err)
		}
		buf := make([]byte, 128)
		n, err := native.Read(buf)
		if err != nil || string(buf[:n]) != string(outgoing) {
			h.Close()
			t.Fatalf("mesh delivery %v", err)
		}
		incoming := ipFrame([4]byte{10, 77, 0, 9}, [4]byte{10, 77, 0, 2})
		app.SetReadDeadline(time.Now().Add(time.Second))
		if _, err := native.Write(incoming); err != nil {
			h.Close()
			t.Fatal(err)
		}
		n, err = app.Read(buf)
		if err != nil || string(buf[:n]) != string(incoming) {
			h.Close()
			t.Fatalf("mesh return %v", err)
		}
		// After failure there is no mesh->Clash retry and no return to Android.
		h.SetReady(42, false)
		native.SetReadDeadline(time.Now().Add(20 * time.Millisecond))
		app.Write(outgoing)
		if _, err := native.Read(buf); err == nil {
			h.Close()
			t.Fatal("not closed")
		}
		done := make(chan struct{})
		go func() { h.Close(); h.Close(); close(done) }()
		select {
		case <-done:
		case <-time.After(2 * time.Second):
			t.Fatal("shutdown stranded a descriptor")
		}
		app.Close()
		native.Close()
	}
	after, _ := os.ReadDir("/proc/self/fd")
	// The first Go netpoll registration may lazily allocate two process-wide FDs.
	if len(after) > len(before)+2 {
		t.Fatalf("descriptor leak: before %d after %d", len(before), len(after))
	}
}

func TestPacketSessionParser(t *testing.T) {
	c := sessionConfig()
	data, _ := json.Marshal(c)
	if _, err := ParsePacketSession(data); err != nil {
		t.Fatal(err)
	}
	for _, bad := range [][]byte{[]byte(`{}`), append(data, []byte(` {}`)...), []byte(`{"credential":"never-accepted"}`)} {
		if _, err := ParsePacketSession(bad); err == nil {
			t.Fatal("invalid session accepted")
		}
	}
	c.MTU = 9000
	data, _ = json.Marshal(c)
	if _, err := ParsePacketSession(data); err == nil {
		t.Fatal("oversized mtu")
	}
}
