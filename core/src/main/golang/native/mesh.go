package main

//#include "bridge.h"
import "C"

import (
	"bytes"
	"encoding/json"
	"io"
	"net/netip"
	"os"
	"path/filepath"
	"runtime/debug"
	"strings"
	"syscall"
	"unsafe"

	"cfa/native/app"
	"cfa/native/tun"
	router "github.com/DariusOne/ClashMetaForAndroid-EasyTier/native/packet-router"
	"github.com/metacubex/mihomo/constant"
	"github.com/metacubex/mihomo/tunnel"
	"golang.org/x/sync/semaphore"
)

//export startPacketTun
func startPacketTun(fd, meshFD C.int, configJSON C.c_string, callback unsafe.Pointer) C.int {
	rTunLock.Lock()
	defer rTunLock.Unlock()
	if rTun != nil {
		rTun.close()
		rTun = nil
	}
	remote := &remoteTun{callback: callback, limit: semaphore.NewWeighted(4)}
	c, err := tun.ParsePacketSession([]byte(C.GoString(configJSON)))
	if err != nil {
		if fd >= 0 {
			syscall.Close(int(fd))
		}
		if meshFD >= 0 && meshFD != fd {
			syscall.Close(int(meshFD))
		}
		remote.close()
		return 1
	}
	app.ApplyTunContext(remote.markSocket, remote.querySocketUid)
	// This entry point is used only by the opt-in packet harness. Android can
	// discard Go's stderr, leaving only runtime.tgkill in a native tombstone.
	// Preserve crash diagnostics privately for explicitly staged fixture runs;
	// normal CMFA startup does not enable this capture.
	if file, err := os.OpenFile(filepath.Join(constant.Path.HomeDir(), "native-mesh-crash.txt"), os.O_WRONLY|os.O_CREATE|os.O_TRUNC, 0600); err == nil {
		debug.SetTraceback("system")
		_ = debug.SetCrashOutput(file, debug.CrashOptions{})
		_ = file.Close() // SetCrashOutput owns a duplicate descriptor.
	}
	h, err := tun.StartPacketSession(int(fd), int(meshFD), c, tunnel.Tunnel)
	if err != nil {
		remote.close()
		return 1
	}
	remote.closer = h
	rTun = remote
	return 0
}

//export updatePacketMesh
func updatePacketMesh(snapshotJSON, installedCSV C.c_string) C.int {
	rTunLock.Lock()
	defer rTunLock.Unlock()
	if rTun == nil {
		return 1
	}
	h, ok := rTun.closer.(*tun.Hybrid)
	if !ok {
		return 1
	}
	s, err := router.ParseNativeSnapshot([]byte(C.GoString(snapshotJSON)))
	if err != nil {
		return 1
	}
	var addresses []netip.Prefix
	for _, text := range strings.Split(C.GoString(installedCSV), ",") {
		if text == "" {
			continue
		}
		p, err := netip.ParsePrefix(text)
		if err != nil {
			return 1
		}
		addresses = append(addresses, p)
	}
	if len(addresses) > 2 || h.ApplySnapshot(s, addresses) != nil {
		return 1
	}
	return 0
}

//export closePacketMesh
func closePacketMesh(generation C.longlong) {
	rTunLock.Lock()
	defer rTunLock.Unlock()
	if rTun != nil {
		if h, ok := rTun.closer.(*tun.Hybrid); ok {
			_ = h.SetReady(uint64(generation), false)
		}
	}
}

//export suspendPacketInterface
func suspendPacketInterface(generation C.longlong) C.int {
	rTunLock.Lock()
	defer rTunLock.Unlock()
	if rTun != nil {
		if h, ok := rTun.closer.(*tun.Hybrid); ok && h.SuspendInterface(uint64(generation)) == nil {
			return 0
		}
	}
	return 1
}

//export replacePacketInterface
func replacePacketInterface(fd C.int, requestJSON C.c_string) C.int {
	rTunLock.Lock()
	defer rTunLock.Unlock()
	var request struct {
		Snapshot      router.NativeSnapshot `json:"snapshot"`
		Installed     []netip.Prefix        `json:"installed"`
		Network       string                `json:"network"`
		LocalNetworks []netip.Prefix        `json:"localNetworks"`
	}
	data := []byte(C.GoString(requestJSON))
	decoder := json.NewDecoder(bytes.NewReader(data))
	decoder.DisallowUnknownFields()
	if len(data) > 512*1024 || decoder.Decode(&request) != nil || decoder.Decode(new(any)) != io.EOF || len(request.Installed) > 2 || len(request.LocalNetworks) > 64 || len(request.Network) > 256 || rTun == nil {
		if fd >= 0 {
			syscall.Close(int(fd))
		}
		return 1
	}
	h, ok := rTun.closer.(*tun.Hybrid)
	if !ok {
		if fd >= 0 {
			syscall.Close(int(fd))
		}
		return 1
	}
	if h.ReplaceInterface(int(fd), request.Snapshot, request.Installed, request.Network, request.LocalNetworks) != nil {
		return 1
	}
	return 0
}

//export refreshPacketNetwork
func refreshPacketNetwork(requestJSON C.c_string) C.int {
	rTunLock.Lock()
	defer rTunLock.Unlock()
	var request struct {
		Snapshot      router.NativeSnapshot `json:"snapshot"`
		Installed     []netip.Prefix        `json:"installed"`
		Network       string                `json:"network"`
		LocalNetworks []netip.Prefix        `json:"localNetworks"`
	}
	data := []byte(C.GoString(requestJSON))
	decoder := json.NewDecoder(bytes.NewReader(data))
	decoder.DisallowUnknownFields()
	if len(data) > 512*1024 || decoder.Decode(&request) != nil || decoder.Decode(new(any)) != io.EOF || len(request.Installed) > 2 || len(request.LocalNetworks) > 64 || len(request.Network) > 256 || rTun == nil {
		return 1
	}
	h, ok := rTun.closer.(*tun.Hybrid)
	if !ok || h.RefreshNetwork(request.Snapshot, request.Installed, request.Network, request.LocalNetworks) != nil {
		return 1
	}
	return 0
}
