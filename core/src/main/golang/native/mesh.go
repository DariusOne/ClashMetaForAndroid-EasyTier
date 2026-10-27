package main

//#include "bridge.h"
import "C"

import (
	"net/netip"
	"strings"
	"syscall"
	"unsafe"

	"cfa/native/app"
	"cfa/native/tun"
	router "github.com/DariusOne/ClashMetaForAndroid-EasyTier/native/packet-router"
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
