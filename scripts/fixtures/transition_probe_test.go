package main

import (
	"bytes"
	"io"
	"net"
	"testing"
	"time"
)

func TestHandoverProbeRejectsSuccessfulWrongSource(t *testing.T) {
	server, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	defer server.Close()
	go func() {
		for {
			conn, err := server.Accept()
			if err != nil {
				return
			}
			go func() { defer conn.Close(); _, _ = io.Copy(conn, conn) }()
		}
	}()
	var output bytes.Buffer
	r := watchTransition("tcp", server.Addr().String(), 200*time.Millisecond, &output)
	if r.Received == 0 || r.WrongSource != r.Attempts || r.OtherSource != r.WrongSource || r.ClashSource != 0 || r.Blocked != 0 || output.String() != "WATCH_READY\n" {
		t.Fatalf("wrong-path evidence lost: %+v %q", r, output.String())
	}
}

func TestHandoverProbeBoundsUnresponsiveFlow(t *testing.T) {
	server, err := net.ListenPacket("udp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	defer server.Close()
	var output bytes.Buffer
	r := watchTransition("udp", server.LocalAddr().String(), 200*time.Millisecond, &output)
	if r.Received != 0 || r.Blocked != r.Attempts || r.WrongSource == 0 || r.ElapsedMillis > 1000 || output.Len() != 0 {
		t.Fatalf("deadline/evidence failed: %+v", r)
	}
}
