//go:build linux || android

package packetrouter

import (
	"bytes"
	"testing"
	"time"
)

func TestDatagramPortPreservesFramesAndCancels(t *testing.T) {
	left, fd, err := NewPacketPair()
	if err != nil {
		t.Fatal(err)
	}
	defer left.Close()
	right, err := AdoptFD(fd)
	if err != nil {
		t.Fatal(err)
	}
	defer right.Close()
	for _, ip := range []string{"10.88.99.2", "fd42::1"} {
		if err = left.WritePacket(packet(ip)); err != nil {
			t.Fatal(err)
		}
	}
	buf := make([]byte, 65535)
	for _, ip := range []string{"10.88.99.2", "fd42::1"} {
		n, e := right.ReadPacket(buf)
		if e != nil || !bytes.Equal(buf[:n], packet(ip)) {
			t.Fatal("frame merged/truncated", e)
		}
	}
	done := make(chan error, 1)
	go func() { _, e := right.ReadPacket(buf); done <- e }()
	right.Close()
	select {
	case e := <-done:
		if e == nil {
			t.Fatal("read returned no close error")
		}
	case <-time.After(2 * time.Second):
		t.Fatal("read stuck after close")
	}
}

func TestRealPacketPortsThroughDispatcher(t *testing.T) {
	tun, phoneFD, e := NewPacketPair()
	if e != nil {
		t.Fatal(e)
	}
	phone, e := AdoptFD(phoneFD)
	if e != nil {
		t.Fatal(e)
	}
	defer phone.Close()
	clash, clashFD, e := NewPacketPair()
	if e != nil {
		t.Fatal(e)
	}
	mihomo, e := AdoptFD(clashFD)
	if e != nil {
		t.Fatal(e)
	}
	defer mihomo.Close()
	mesh, meshFD, e := NewPacketPair()
	if e != nil {
		t.Fatal(e)
	}
	native, e := AdoptFD(meshFD)
	if e != nil {
		t.Fatal(e)
	}
	defer native.Close()
	runRealPorts(t, tun, phone, clash, mihomo, mesh, native)
}
