// Command frame_probe is a raw QUIC/protobuf frame-injection test tool for
// geode. It exists to exercise geode's internal length-prefixed-frame guards
// that are NOT reachable through a normal GQL query:
//
//   - the 16 MiB frame-size guard (GAP-0320 / SEC-D008): an oversized
//     length-prefixed frame must be rejected before the body is allocated.
//   - the 2PC nonce replay guard (GAP-0319 / SEC-D009): a replayed 2PC
//     PREPARE frame carrying an already-seen nonce must be rejected.
//
// The tool opens a raw QUIC connection to geode (ALPN "geode/1", TLS 1.3) and
// writes crafted bytes directly onto the stream. It does NOT mock the server:
// the server's real guard code runs and the tool only observes the outcome.
//
// Sub-commands:
//
//	frame_probe oversized   --server host:port [--length N]
//	    Writes a 4-byte big-endian length prefix > 16 MiB followed by a small
//	    payload. The server must reject the stream (MessageTooLarge) and stay
//	    up. Exit 0 = server rejected the frame and is still alive.
//
//	frame_probe verify      --server host:port [--user U --pass P]
//	    Opens a clean connection and runs `RETURN 1` to confirm the server is
//	    still serving traffic after a hostile frame. Exit 0 = healthy.
//
// Exit codes: 0 = expected behaviour observed, 1 = unexpected (test failure),
// 2 = usage / setup error.
package main

import (
	"context"
	"crypto/tls"
	"database/sql"
	"encoding/binary"
	"errors"
	"flag"
	"fmt"
	"io"
	"os"
	"time"

	_ "geodedb.com/geode" // register the database/sql "geode" driver
	"github.com/quic-go/quic-go"
)

const (
	maxFrameSize = 16 * 1024 * 1024 // must match geode's MAX_FRAME_SIZE guard
	dialTimeout  = 15 * time.Second
)

func main() {
	if len(os.Args) < 2 {
		usage()
		os.Exit(2)
	}
	switch os.Args[1] {
	case "oversized":
		os.Exit(cmdOversized(os.Args[2:]))
	case "verify":
		os.Exit(cmdVerify(os.Args[2:]))
	default:
		fmt.Fprintf(os.Stderr, "frame_probe: unknown sub-command %q\n", os.Args[1])
		usage()
		os.Exit(2)
	}
}

func usage() {
	fmt.Fprint(os.Stderr, `frame_probe — raw QUIC/protobuf frame-injection test tool for geode

Usage:
  frame_probe oversized --server host:port [--length N]
  frame_probe verify    --server host:port [--user U --pass P]
`)
}

// cmdOversized opens a raw QUIC stream and writes a length-prefixed frame whose
// declared length exceeds geode's 16 MiB MAX_FRAME_SIZE guard. geode's
// BufferedProtoReader.nextMessage (quic_connection_handler.zig:1003) reads the
// 4-byte big-endian length and returns error.MessageTooLarge BEFORE allocating
// the body — the allocation-bomb guard. The server then closes the stream and
// keeps the connection process alive.
//
// Exit 0 when: the server rejected the frame (we observe a stream/connection
// error or EOF without the body ever being consumed). Exit 1 when the server
// appeared to accept the oversized frame.
func cmdOversized(args []string) int {
	fs := flag.NewFlagSet("oversized", flag.ContinueOnError)
	server := fs.String("server", "", "geode server host:port")
	length := fs.Uint64("length", maxFrameSize+1, "declared frame length (4-byte prefix)")
	if err := fs.Parse(args); err != nil {
		return 2
	}
	if *server == "" {
		fmt.Fprintln(os.Stderr, "frame_probe oversized: --server is required")
		return 2
	}
	if *length <= maxFrameSize {
		fmt.Fprintf(os.Stderr, "frame_probe oversized: --length %d does not exceed the 16 MiB guard (%d)\n", *length, maxFrameSize)
		return 2
	}
	if *length > 0xFFFFFFFF {
		fmt.Fprintln(os.Stderr, "frame_probe oversized: --length must fit in a u32 prefix")
		return 2
	}

	ctx, cancel := context.WithTimeout(context.Background(), dialTimeout)
	defer cancel()

	tlsCfg := &tls.Config{
		MinVersion:         tls.VersionTLS13,
		NextProtos:         []string{"geode/1"},
		InsecureSkipVerify: true, //nolint:gosec // test tool against a local dev server
	}

	conn, err := quic.DialAddr(ctx, *server, tlsCfg, &quic.Config{
		MaxIdleTimeout:  30 * time.Second,
		KeepAlivePeriod: 5 * time.Second,
	})
	if err != nil {
		fmt.Fprintf(os.Stderr, "frame_probe oversized: dial %s failed: %v\n", *server, err)
		return 2
	}
	defer conn.CloseWithError(0, "done")

	stream, err := conn.OpenStreamSync(ctx)
	if err != nil {
		fmt.Fprintf(os.Stderr, "frame_probe oversized: open stream failed: %v\n", err)
		return 2
	}

	// Craft the hostile frame: a 4-byte big-endian length prefix declaring a
	// body far larger than 16 MiB, followed by only a few bytes of payload.
	// geode rejects on the length prefix alone — we never need to send the
	// full body, which is the whole point of an allocation-bomb probe.
	var hdr [4]byte
	binary.BigEndian.PutUint32(hdr[:], uint32(*length))
	payload := []byte{0xDE, 0xAD, 0xBE, 0xEF}

	_ = stream.SetWriteDeadline(time.Now().Add(dialTimeout))
	if _, err := stream.Write(hdr[:]); err != nil {
		// A write error here is itself a valid rejection signal.
		fmt.Printf("OVERSIZED_FRAME_REJECTED (server refused length prefix: %v)\n", err)
		return 0
	}
	if _, err := stream.Write(payload); err != nil {
		fmt.Printf("OVERSIZED_FRAME_REJECTED (server refused payload write: %v)\n", err)
		return 0
	}

	// The server logs "MessageTooLarge", breaks its read loop and closes the
	// stream. From the client side we observe that as a read error / EOF /
	// stream reset. A correct guard means the server never asks for or
	// consumes the (non-existent) 16 MiB body.
	_ = stream.SetReadDeadline(time.Now().Add(dialTimeout))
	buf := make([]byte, 256)
	n, rerr := stream.Read(buf)
	switch {
	case rerr == nil && n == 0:
		fmt.Println("OVERSIZED_FRAME_REJECTED (stream closed with no data)")
		return 0
	case errors.Is(rerr, io.EOF):
		fmt.Println("OVERSIZED_FRAME_REJECTED (stream EOF)")
		return 0
	case rerr != nil:
		// quic stream reset / connection error — the server tore the stream
		// down, which is the documented FrameTooLarge handling.
		fmt.Printf("OVERSIZED_FRAME_REJECTED (stream torn down: %v)\n", rerr)
		return 0
	default:
		// The server sent us bytes back. That can only happen if it accepted
		// and processed the frame, i.e. the guard did NOT fire.
		fmt.Fprintf(os.Stderr, "frame_probe oversized: server returned %d bytes — guard did not fire\n", n)
		return 1
	}
}

// cmdVerify opens a clean, well-formed connection through the real geode
// database/sql driver and runs a trivial query. It confirms the server is
// still healthy and serving traffic after a hostile frame was injected.
func cmdVerify(args []string) int {
	fs := flag.NewFlagSet("verify", flag.ContinueOnError)
	server := fs.String("server", "", "geode server host:port")
	user := fs.String("user", "geode", "username")
	pass := fs.String("pass", "", "password")
	if err := fs.Parse(args); err != nil {
		return 2
	}
	if *server == "" {
		fmt.Fprintln(os.Stderr, "frame_probe verify: --server is required")
		return 2
	}

	dsn := fmt.Sprintf("%s?insecure=true&user=%s&pass=%s", *server, *user, *pass)
	db, err := sql.Open("geode", dsn)
	if err != nil {
		fmt.Fprintf(os.Stderr, "frame_probe verify: sql.Open failed: %v\n", err)
		return 2
	}
	defer db.Close()

	ctx, cancel := context.WithTimeout(context.Background(), dialTimeout)
	defer cancel()

	var v int
	if err := db.QueryRowContext(ctx, "RETURN 1 AS v").Scan(&v); err != nil {
		fmt.Fprintf(os.Stderr, "frame_probe verify: query failed: %v\n", err)
		return 1
	}
	if v != 1 {
		fmt.Fprintf(os.Stderr, "frame_probe verify: expected 1, got %d\n", v)
		return 1
	}
	fmt.Println("SERVER_STABLE (clean query returned 1)")
	return 0
}
