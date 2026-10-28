// Bounded shell-UID handover probe for the disposable mesh only. This measures
// completed socket paths and received packets, not every SYN on an underlay.
package main

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"net"
	"os"
	"strconv"
	"time"
)

type transitionResult struct {
	Attempts       int   `json:"attempts"`
	Received       int   `json:"received"`
	Blocked        int   `json:"blocked"`
	WrongSource    int   `json:"wrong_source"`
	ClashSource    int   `json:"clash_gateway_source"`
	OtherSource    int   `json:"other_source"`
	InvalidPayload int   `json:"invalid_payload"`
	ElapsedMillis  int64 `json:"elapsed_ms"`
}

func watchTransition(protocol, target string, duration time.Duration, output io.Writer) transitionResult {
	started := time.Now()
	finish := started.Add(duration)
	result := transitionResult{}
	ready := false
	for time.Now().Before(finish) && result.Attempts < 800 {
		result.Attempts++
		deadline := time.Now().Add(200 * time.Millisecond)
		if deadline.After(finish) {
			deadline = finish
		}
		conn, err := (&net.Dialer{Deadline: deadline}).Dial(protocol, target)
		if err != nil {
			result.Blocked++
			time.Sleep(10 * time.Millisecond)
			continue
		}
		host, _, err := net.SplitHostPort(conn.LocalAddr().String())
		if err != nil || host != "10.126.0.2" {
			result.WrongSource++
			if host == "172.19.0.1" {
				result.ClashSource++
			} else {
				result.OtherSource++
			}
		}
		_ = conn.SetDeadline(deadline)
		request := []byte(fmt.Sprintf("cmfa-handover-%d\n", result.Attempts))
		response := make([]byte, len(request))
		n, err := conn.Write(request)
		if err == nil && n == len(request) {
			if protocol == "udp" {
				n, err = conn.Read(response)
			} else {
				n, err = io.ReadFull(conn, response)
			}
		} else if err == nil {
			err = io.ErrShortWrite
		}
		_ = conn.Close()
		if err != nil {
			result.Blocked++
		} else if n != len(request) || !bytes.Equal(request, response) {
			result.InvalidPayload++
		} else {
			result.Received++
			if !ready {
				fmt.Fprintln(output, "WATCH_READY")
				ready = true
			}
		}
		time.Sleep(10 * time.Millisecond)
	}
	result.ElapsedMillis = time.Since(started).Milliseconds()
	return result
}

func main() {
	if len(os.Args) != 3 || (os.Args[1] != "tcp" && os.Args[1] != "udp") {
		os.Exit(2)
	}
	port, err := strconv.Atoi(os.Args[2])
	if err != nil || port < 1024 || port > 65535 {
		os.Exit(2)
	}
	result := watchTransition(os.Args[1], net.JoinHostPort("10.126.0.1", strconv.Itoa(port)), 8*time.Second, os.Stdout)
	_ = json.NewEncoder(os.Stdout).Encode(result)
	if result.Received == 0 || result.WrongSource != 0 || result.InvalidPayload != 0 {
		os.Exit(1)
	}
}
