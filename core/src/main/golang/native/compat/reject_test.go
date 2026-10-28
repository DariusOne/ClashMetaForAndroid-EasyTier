package compat

import (
	"bytes"
	"context"
	"errors"
	"io"
	"testing"

	"github.com/metacubex/mihomo/adapter/outbound"
	"github.com/metacubex/mihomo/common/buf"
	C "github.com/metacubex/mihomo/constant"
	"github.com/metacubex/sing/common/bufio"
)

// A rejected write still consumes the pooled buffer. Leaving it owned by the
// caller makes sing's debug copy path panic and kills Android's VPN process.
func TestRejectConsumesBuffer(t *testing.T) {
	for _, reject := range []*outbound.Reject{outbound.NewReject(), outbound.NewRejectDrop()} {
		t.Run(reject.Name(), func(t *testing.T) {
			conn, err := reject.DialContext(context.Background(), &C.Metadata{NetWork: C.TCP})
			if err != nil {
				t.Fatal(err)
			}
			defer conn.Close()
			buffer := buf.NewSize(32)
			_, _ = buffer.Write([]byte("disposable-rejected-payload"))
			if err := conn.WriteBuffer(buffer); !errors.Is(err, io.EOF) {
				t.Fatalf("reject semantics changed: %v", err)
			}
			if buffer.Cap() != 0 {
				buffer.Release()
				t.Fatal("rejected WriteBuffer did not release its owned buffer")
			}
		})
	}
}

func TestRejectCopyDoesNotPanic(t *testing.T) {
	for _, reject := range []*outbound.Reject{outbound.NewReject(), outbound.NewRejectDrop()} {
		t.Run(reject.Name(), func(t *testing.T) {
			conn, err := reject.DialContext(context.Background(), &C.Metadata{NetWork: C.TCP})
			if err != nil {
				t.Fatal(err)
			}
			defer conn.Close()
			defer func() {
				if value := recover(); value != nil {
					t.Fatalf("reject copy panicked: %v", value)
				}
			}()
			n, err := bufio.Copy(conn, bytes.NewReader([]byte("rejected-payload")))
			if n != 0 || !errors.Is(err, io.EOF) {
				t.Fatalf("reject copy semantics changed: bytes=%d error=%v", n, err)
			}
		})
	}
}
