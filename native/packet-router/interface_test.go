package packetrouter

import (
	"io"
	"testing"
	"time"
)

func TestInterfaceReplacementRetainsReaderAndDropsOldEpoch(t *testing.T) {
	old, next := newPort(), newPort()
	p := NewInterfacePort(old)
	defer p.Close()
	result := make(chan string, 1)
	go func() {
		b := make([]byte, 32)
		n, err := p.ReadPacket(b)
		if err != nil {
			result <- "error"
		} else {
			result <- string(b[:n])
		}
	}()
	if err := p.Pause(); err != nil {
		t.Fatal(err)
	}
	old.in <- []byte("stale")
	old.Close() // Android invalidates old TUN inside establish, before Replace.
	if err := p.WritePacket([]byte("must-drop")); err != nil {
		t.Fatal(err)
	}
	if err := p.Replace(next); err != nil {
		t.Fatal(err)
	}
	select {
	case <-result:
		t.Fatal("paused reader returned")
	case <-time.After(20 * time.Millisecond):
	}
	if err := p.Resume(); err != nil {
		t.Fatal(err)
	}
	next.in <- []byte("new-interface")
	select {
	case got := <-result:
		if got != "new-interface" {
			t.Fatal(got)
		}
	case <-time.After(time.Second):
		t.Fatal("reader did not recover")
	}
	if err := p.WritePacket([]byte("reply")); err != nil {
		t.Fatal(err)
	}
	select {
	case got := <-next.out:
		if string(got) != "reply" {
			t.Fatal(string(got))
		}
	case <-time.After(time.Second):
		t.Fatal("return lost")
	}
}

func TestInterfaceCloseUnblocksPausedReadAndRejectsLateReplacement(t *testing.T) {
	p := NewInterfacePort(newPort())
	p.Pause()
	done := make(chan error, 1)
	go func() { _, err := p.ReadPacket(make([]byte, 32)); done <- err }()
	p.Close()
	p.Close()
	select {
	case err := <-done:
		if err != io.ErrClosedPipe {
			t.Fatal(err)
		}
	case <-time.After(time.Second):
		t.Fatal("paused close blocked")
	}
	late := newPort()
	if p.Replace(late) == nil {
		t.Fatal("replacement after close")
	}
	select {
	case <-late.done:
	default:
		t.Fatal("replacement descriptor leaked")
	}
}

func TestInterfaceFailureOutsideRebuildIsNotHidden(t *testing.T) {
	old := newPort()
	p := NewInterfacePort(old)
	defer p.Close()
	old.Close()
	if _, err := p.ReadPacket(make([]byte, 32)); err == nil {
		t.Fatal("real failure hidden")
	}
	next := newPort()
	if p.Replace(next) == nil {
		t.Fatal("replacement without pause")
	}
	select {
	case <-next.done:
	default:
		t.Fatal("rejected replacement leaked")
	}
}
