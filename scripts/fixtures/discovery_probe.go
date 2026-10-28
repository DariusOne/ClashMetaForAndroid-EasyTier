//go:build linux

// A shell-UID IPv4 discovery fixture for the disposable 10.126.0.0/24 mesh.
// Uses ordinary UDP sockets (no root/raw socket), only synthetic payloads.
package main

import (
	"bytes"
	"fmt"
	"net"
	"os"
	"strconv"
	"syscall"
	"time"
)

func fail(code string) { fmt.Fprintln(os.Stderr, code); os.Exit(1) }

func main() {
	if len(os.Args) != 5 {
		fail("ARGUMENTS_INVALID")
	}
	mode, source, destination := os.Args[1], net.ParseIP(os.Args[2]).To4(), net.ParseIP(os.Args[3]).To4()
	port, err := strconv.Atoi(os.Args[4])
	if err != nil || port < 1024 || port > 65535 || source == nil || destination == nil {
		fail("ARGUMENTS_INVALID")
	}
	if source.String() != "10.126.0.1" && source.String() != "10.126.0.2" {
		fail("DISPOSABLE_SOURCE_REQUIRED")
	}
	if mode != "client" && mode != "server" {
		fail("MODE_INVALID")
	}
	if destination.String() != "10.126.0.255" && destination.String() != "255.255.255.255" && destination.String() != "224.0.0.251" && destination.String() != "239.255.255.250" {
		fail("DISPOSABLE_DESTINATION_REQUIRED")
	}
	local := &net.UDPAddr{IP: source}
	if mode == "server" {
		local = &net.UDPAddr{IP: net.IPv4zero, Port: port}
	}
	conn, err := net.ListenUDP("udp4", local)
	if err != nil {
		fail("BIND_FAILED")
	}
	defer conn.Close()
	raw, err := conn.SyscallConn()
	if err != nil {
		fail("SOCKET_FAILED")
	}
	var optionError error
	err = raw.Control(func(fd uintptr) {
		optionError = syscall.SetsockoptInt(int(fd), syscall.SOL_SOCKET, syscall.SO_BROADCAST, 1)
		if optionError == nil && destination.IsMulticast() {
			var address [4]byte
			copy(address[:], source)
			optionError = syscall.SetsockoptInet4Addr(int(fd), syscall.IPPROTO_IP, syscall.IP_MULTICAST_IF, address)
			if optionError == nil && mode == "server" {
				membership := &syscall.IPMreq{Interface: address}
				copy(membership.Multiaddr[:], destination)
				optionError = syscall.SetsockoptIPMreq(int(fd), syscall.IPPROTO_IP, syscall.IP_ADD_MEMBERSHIP, membership)
			}
		}
	})
	if err != nil || optionError != nil {
		fail("SOCKET_OPTIONS_FAILED")
	}
	peerIP := "10.126.0.1"
	if source.String() == peerIP {
		peerIP = "10.126.0.2"
	}
	if mode == "server" {
		fmt.Println("READY")
	}
	for i := 0; i < 5; i++ {
		conn.SetDeadline(time.Now().Add(8 * time.Second))
		payload := []byte(fmt.Sprintf("cmfa-discovery-%d", i))
		if mode == "client" {
			if _, err = conn.WriteToUDP(payload, &net.UDPAddr{IP: destination, Port: port}); err != nil {
				fail("SEND_FAILED")
			}
		}
		response := make([]byte, 128)
		n, remote, err := conn.ReadFromUDP(response)
		if err != nil {
			fail("RECEIVE_FAILED")
		}
		if remote.IP.String() != peerIP || !bytes.Equal(response[:n], payload) {
			fail("SOURCE_OR_PAYLOAD_MISMATCH")
		}
		if mode == "server" {
			if _, err = conn.WriteToUDP(response[:n], remote); err != nil {
				fail("REPLY_FAILED")
			}
		}
	}
	fmt.Println("PASS 5/5")
}
