//go:build linux || android

package packetrouter

import (
	"io"
	"os"
	"syscall"
)

// FDPort owns one nonblocking Linux/Android L3 packet descriptor. The file
// poller, rather than a blocking syscall, makes Close interrupt pending I/O.
type FDPort struct{ file *os.File }

// AdoptFD transfers ownership even on error. The caller must never close fd
// after this call. This is for an Android TUN or an AF_UNIX SOCK_DGRAM endpoint.
func AdoptFD(fd int) (*FDPort, error) {
	if fd < 0 {
		return nil, ErrPort
	}
	if err := syscall.SetNonblock(fd, true); err != nil {
		syscall.Close(fd)
		return nil, ErrPort
	}
	return &FDPort{file: os.NewFile(uintptr(fd), "cmfa-packet-port")}, nil
}

func (p *FDPort) ReadPacket(b []byte) (int, error) { return p.file.Read(b) }
func (p *FDPort) WritePacket(b []byte) error {
	n, err := p.file.Write(b)
	if err == nil && n != len(b) {
		return io.ErrShortWrite
	}
	return err
}
func (p *FDPort) Close() error { return p.file.Close() }

// NewPacketPair keeps frame boundaries. The router owns the returned Port;
// the engine owns peerFD. Neither endpoint is a second OS VPN interface.
func NewPacketPair() (*FDPort, int, error) {
	fds, err := syscall.Socketpair(syscall.AF_UNIX, syscall.SOCK_DGRAM|syscall.SOCK_CLOEXEC|syscall.SOCK_NONBLOCK, 0)
	if err != nil {
		return nil, -1, ErrPort
	}
	port, err := AdoptFD(fds[0])
	if err != nil {
		syscall.Close(fds[1])
		return nil, -1, err
	}
	return port, fds[1], nil
}
