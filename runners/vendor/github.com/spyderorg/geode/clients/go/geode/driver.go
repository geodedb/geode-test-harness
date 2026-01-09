package geodesql

import (
	"bufio"
	"context"
	"crypto/tls"
	"crypto/x509"
	"database/sql"
	"database/sql/driver"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"strings"
	"sync"
	"unicode/utf16"
	"unicode/utf8"

	quic "github.com/quic-go/quic-go"
)

func init() {
	sql.Register("geode", &drv{})
}

type drv struct{}

func (d *drv) Open(name string) (driver.Conn, error) {
	cfg, err := parseDSN(name)
	if err != nil {
		return nil, err
	}
	return newConn(cfg)
}

type dsnConfig struct {
	Mode        string // "process" (default) or "quic"
	Path        string // path to geoded (process)
	Addr        string // host:port for quic
	PageSize    int
	ResultFmt   string // json|txt (json default)
	HelloName   string
	HelloVer    string
	Conformance string
	TLS         bool
	TLSCA       string
	TLSCert     string
	TLSKey      string
}

func parseDSN(dsn string) (*dsnConfig, error) {
	cfg := &dsnConfig{
		Mode:        "process",
		Path:        "./zig-out/bin/geoded",
		PageSize:    1000,
		ResultFmt:   "json",
		HelloName:   "geode-go",
		HelloVer:    "0.1",
		Conformance: "min",
	}
	dsn = strings.TrimSpace(dsn)
	if dsn == "" {
		if p := os.Getenv("GEODE_SERVER_PATH"); p != "" {
			cfg.Path = p
		}
		return cfg, nil
	}
	// format: process:<path>?... or quic:<host:port>?...
	parts := strings.SplitN(dsn, ":", 2)
	if len(parts) == 2 && (parts[0] == "process" || parts[0] == "proc") {
		cfg.Mode = "process"
		rest := parts[1]
		var q string
		if i := strings.Index(rest, "?"); i >= 0 {
			cfg.Path = rest[:i]
			q = rest[i+1:]
		} else {
			cfg.Path = rest
		}
		if q != "" {
			applyQuery(q, cfg)
		}
		return cfg, nil
	}
	if len(parts) == 2 && parts[0] == "quic" {
		cfg.Mode = "quic"
		rest := parts[1]
		var q string
		if i := strings.Index(rest, "?"); i >= 0 {
			cfg.Addr = rest[:i]
			q = rest[i+1:]
		} else {
			cfg.Addr = rest
		}
		if cfg.Addr == "" {
			cfg.Addr = "127.0.0.1:8443"
		}
		if q != "" {
			applyQuery(q, cfg)
		}
		return cfg, nil
	}
	if len(parts) == 2 && parts[0] == "tcp" {
		return nil, fmt.Errorf("unsupported DSN: tcp (use quic:<host:port> or process:<path>)")
	}
	return nil, fmt.Errorf("unsupported DSN: %s", dsn)
}

func applyQuery(q string, cfg *dsnConfig) {
	for _, kv := range strings.Split(q, "&") {
		if kv == "" {
			continue
		}
		p := strings.SplitN(kv, "=", 2)
		key := p[0]
		val := ""
		if len(p) == 2 {
			val = p[1]
		}
		switch key {
		case "page_size":
			if n, err := strconv.Atoi(val); err == nil && n > 0 {
				cfg.PageSize = n
			}
		case "format":
			if val == "txt" || val == "text" {
				cfg.ResultFmt = "txt"
			}
		case "hello_name":
			if val != "" {
				cfg.HelloName = val
			}
		case "hello_ver":
			if val != "" {
				cfg.HelloVer = val
			}
		case "conformance":
			if val != "" {
				cfg.Conformance = val
			}
		case "tls":
			cfg.TLS = (val == "true" || val == "1")
		case "ca":
			cfg.TLSCA = val
		case "cert":
			cfg.TLSCert = val
		case "key":
			cfg.TLSKey = val
		}
	}
}

type conn struct {
	cfg *dsnConfig
	// process mode
	cmd    *exec.Cmd
	stdin  io.WriteCloser
	stdout io.ReadCloser
	// quic mode
	qConn      *quic.Conn
	qStream    *quic.Stream
	br         *bufio.Reader
	mu         sync.Mutex // serialize requests; server supports only one active result
	closed     bool
	activeRows *rows // only one at a time
}

// Unicode helpers (client-side convenience)
// CANARY: REQ=REQ-GQL-UNICODE-012; FEATURE="UTF-8 -> UTF-16 Conversion"; ASPECT=ClientWrapperGo; STATUS=IMPL; TEST=TestCANARY_ClientGo_Utf8Utf16RoundTrip; OWNER=clients; UPDATED=2025-09-27
func Utf8ToUtf16(s string) []uint16 { return utf16.Encode([]rune(s)) }

// CANARY: REQ=REQ-GQL-UNICODE-013; FEATURE="UTF-16 -> UTF-8 Conversion"; ASPECT=ClientWrapperGo; STATUS=IMPL; TEST=TestCANARY_ClientGo_Utf8Utf16RoundTrip; OWNER=clients; UPDATED=2025-09-27
func Utf16ToUtf8(u []uint16) string { return string(utf16.Decode(u)) }

// CANARY: REQ=REQ-GQL-UNICODE-014; FEATURE="WTF-8 Lossy Decode"; ASPECT=ClientWrapperGo; STATUS=IMPL; TEST=TestCANARY_ClientGo_Wtf8Lossy; OWNER=clients; UPDATED=2025-09-27
func Wtf8Lossy(b []byte) string { // treat invalid sequences with replacement
	var out []rune
	i := 0
	for i < len(b) {
		r, size := utf8.DecodeRune(b[i:])
		if r == utf8.RuneError && size == 1 { // invalid
			out = append(out, '\uFFFD') // replacement character
			i++
			continue
		}
		out = append(out, r)
		i += size
	}
	return string(out)
}

func newConn(cfg *dsnConfig) (*conn, error) {
	if cfg.Mode == "quic" {
		// Try to load test harness CA certificate
		tlsConf := &tls.Config{InsecureSkipVerify: true, NextProtos: []string{"geode/1"}, MinVersion: tls.VersionTLS13}

		if caPool := loadTLSRoots(cfg); caPool != nil {
			tlsConf.RootCAs = caPool
			tlsConf.InsecureSkipVerify = false
		}

		qConn, err := quic.DialAddr(context.Background(), cfg.Addr, tlsConf, nil)
		if err != nil {
			return nil, err
		}
		qStream, err := qConn.OpenStreamSync(context.Background())
		if err != nil {
			_ = qConn.CloseWithError(0, "open stream failed")
			return nil, err
		}
		c := &conn{cfg: cfg, qConn: qConn, qStream: qStream, br: bufio.NewReaderSize(qStream, 64<<10)}
		// HELLO then read/ignore HELLO response
		hello := map[string]any{"type": "HELLO", "client_name": cfg.HelloName, "client_ver": cfg.HelloVer, "wanted_conformance": cfg.Conformance}
		if err := c.writeJSONLine(hello); err != nil {
			_ = c.Close()
			return nil, err
		}
		// discard HELLO response
		_, _ = c.readLine(context.Background())
		return c, nil
	}
	// process mode
	path := cfg.Path
	if !filepath.IsAbs(path) {
		if wd, _ := os.Getwd(); wd != "" {
			path = filepath.Join(wd, path)
		}
	}
	cmd := exec.Command(path)
	stdin, err := cmd.StdinPipe()
	if err != nil {
		return nil, err
	}
	stdout, err := cmd.StdoutPipe()
	if err != nil {
		return nil, err
	}
	cmd.Stderr = os.Stderr
	if err := cmd.Start(); err != nil {
		return nil, err
	}
	c := &conn{cfg: cfg, cmd: cmd, stdin: stdin, stdout: stdout, br: bufio.NewReaderSize(stdout, 64<<10)}
	hello := map[string]any{"type": "HELLO", "client_name": cfg.HelloName, "client_ver": cfg.HelloVer, "wanted_conformance": cfg.Conformance}
	if err := c.writeJSONLine(hello); err != nil {
		_ = c.Close()
		return nil, err
	}
	return c, nil
}

func (c *conn) writeJSONLine(v any) error {
	b, err := json.Marshal(v)
	if err != nil {
		return err
	}
	b = append(b, '\n')
	if c.qStream != nil {
		_, err = c.qStream.Write(b)
		return err
	}
	_, err = c.stdin.Write(b)
	return err
}

func (c *conn) readLine(ctx context.Context) ([]byte, error) {
	ch := make(chan struct {
		line []byte
		err  error
	}, 1)
	go func() {
		line, err := c.br.ReadBytes('\n')
		if err == nil {
			line = bytesTrimNewline(line)
		}
		ch <- struct {
			line []byte
			err  error
		}{line, err}
	}()
	select {
	case <-ctx.Done():
		return nil, ctx.Err()
	case r := <-ch:
		return r.line, r.err
	}
}

func bytesTrimNewline(b []byte) []byte {
	if n := len(b); n > 0 && b[n-1] == '\n' {
		return b[:n-1]
	}
	return b
}

func (c *conn) Prepare(query string) (driver.Stmt, error) { return nil, driver.ErrSkip }
func (c *conn) Close() error {
	c.mu.Lock()
	defer c.mu.Unlock()
	if c.closed {
		return nil
	}
	c.closed = true
	if c.qConn != nil {
		if c.qStream != nil {
			_ = c.qStream.Close()
		}
		_ = c.qConn.CloseWithError(0, "closing")
		c.qConn = nil
		c.qStream = nil
		return nil
	}
	_ = c.stdin.Close()
	_ = c.stdout.Close()
	return c.cmd.Wait()
}

func loadTLSRoots(cfg *dsnConfig) *x509.CertPool {
	candidates := []string{}
	if cfg.TLSCA != "" {
		candidates = append(candidates, cfg.TLSCA)
	}
	if env := os.Getenv("GEODE_TLS_CA"); env != "" {
		candidates = append(candidates, env)
	}
	if harness := detectHarnessCA(); harness != "" {
		candidates = append(candidates, harness)
	}

	for _, path := range candidates {
		if path == "" {
			continue
		}
		data, err := os.ReadFile(path)
		if err != nil {
			continue
		}
		pool := x509.NewCertPool()
		if pool.AppendCertsFromPEM(data) {
			fmt.Fprintf(os.Stderr, "[geode-go] Loaded TLS CA bundle: %s\n", path)
			return pool
		}
	}
	return nil
}

func detectHarnessCA() string {
	exePath, err := os.Executable()
	if err != nil || exePath == "" {
		exePath = os.Args[0]
	}
	exeDir := filepath.Dir(exePath)
	candidates := []string{
		filepath.Clean(filepath.Join(exeDir, "..", "certs", "ca.crt")),
		filepath.Clean(filepath.Join(exeDir, "..", "test-harness", "certs", "ca.crt")),
		filepath.Clean(filepath.Join(exeDir, "..", "..", "clients", "test-harness", "certs", "ca.crt")),
	}
	for _, path := range candidates {
		if _, err := os.Stat(path); err == nil {
			return path
		}
	}
	return ""
}
func (c *conn) Begin() (driver.Tx, error) { return c.beginTx(context.Background(), driver.TxOptions{}) }

func (c *conn) beginTx(ctx context.Context, opts driver.TxOptions) (driver.Tx, error) {
	c.mu.Lock()
	defer c.mu.Unlock()
	if c.activeRows != nil {
		return nil, errors.New("geode: query in progress")
	}
	if c.closed {
		return nil, driver.ErrBadConn
	}
	if err := c.writeJSONLine(map[string]any{"type": "BEGIN"}); err != nil {
		return nil, err
	}
	// Read ACK (schema/bindings ack line); we don't need to interpret
	_, _ = c.readLine(ctx)
	return &tx{c: c}, nil
}

type tx struct{ c *conn }

func (t *tx) Commit() error {
	return t.end("COMMIT")
}
func (t *tx) Rollback() error { return t.end("ROLLBACK") }
func (t *tx) end(kind string) error {
	c := t.c
	c.mu.Lock()
	defer c.mu.Unlock()
	if c.closed {
		return driver.ErrBadConn
	}
	if err := c.writeJSONLine(map[string]any{"type": kind}); err != nil {
		return err
	}
	_, _ = c.readLine(context.Background())
	return nil
}

// QueryerContext
func (c *conn) QueryContext(ctx context.Context, query string, args []driver.NamedValue) (driver.Rows, error) {
	c.mu.Lock()
	defer func() {
		if c.activeRows == nil {
			c.mu.Unlock()
		} // unlocked in rows if rows active
	}()
	if c.closed {
		return nil, driver.ErrBadConn
	}
	if c.activeRows != nil {
		return nil, errors.New("geode: another query is active")
	}
	newQuery, params := rewritePlaceholders(query, args)
	run := map[string]any{"type": "RUN_GQL", "text": newQuery}
	if len(params) > 0 {
		run["params"] = params
	}
	if err := c.writeJSONLine(run); err != nil {
		return nil, err
	}
	line1, err := c.readLine(ctx)
	if err != nil {
		return nil, err
	}
	// check ERROR
	var head frame
	if err := json.Unmarshal(line1, &head); err != nil {
		return nil, fmt.Errorf("schema parse: %w", err)
	}
	if head.Result.Type == "ERROR" {
		return nil, fmt.Errorf("geode error %s: %s (anchor %s)", head.StatusSubclass, head.Result.Code, head.Result.Anchor)
	}
	if head.Result.Type != "SCHEMA" {
		return nil, fmt.Errorf("unexpected first frame: %s", head.Result.Type)
	}
	cols := make([]string, len(head.Result.Columns))
	for i, cdef := range head.Result.Columns {
		cols[i] = cdef.Name
	}
	// Send first PULL
	pull := map[string]any{"type": "PULL", "request_id": 1, "page_size": c.cfg.PageSize}
	if err := c.writeJSONLine(pull); err != nil {
		return nil, err
	}
	line2, err := c.readLine(ctx)
	if err != nil {
		return nil, err
	}
	var b frame
	if err := json.Unmarshal(line2, &b); err != nil {
		return nil, fmt.Errorf("bindings parse: %w", err)
	}
	rows := &rows{c: c, ctx: ctx, cols: cols, pageSize: c.cfg.PageSize}
	switch b.Result.Type {
	case "BINDINGS":
		c.activeRows = rows
		rows.buffer(b.Result.Rows)
		rows.ordered = b.Result.Ordered
		rows.orderKeys = b.Result.OrderKeys
		rows.final = b.Result.Final
	case "PROFILE":
		c.activeRows = rows
		rows.final = true
	case "RESULT", "STATUS":
		c.activeRows = rows
		rows.final = true
	default:
		return nil, fmt.Errorf("unexpected frame after SCHEMA: %s", b.Result.Type)
	}
	// lock held; rows will own lock until Close
	return rows, nil
}

// ExecContext for statements that don't return rows
func (c *conn) ExecContext(ctx context.Context, query string, args []driver.NamedValue) (driver.Result, error) {
	c.mu.Lock()
	defer c.mu.Unlock()
	if c.closed {
		return nil, driver.ErrBadConn
	}
	newQuery, params := rewritePlaceholders(query, args)
	run := map[string]any{"type": "RUN_GQL", "text": newQuery}
	if len(params) > 0 {
		run["params"] = params
	}
	if err := c.writeJSONLine(run); err != nil {
		return nil, err
	}
	line1, err := c.readLine(ctx)
	if err != nil {
		return nil, err
	}
	var head frame
	if err := json.Unmarshal(line1, &head); err != nil {
		return nil, err
	}
	if head.Result.Type == "ERROR" {
		return nil, fmt.Errorf("geode error %s: %s (anchor %s)", head.StatusSubclass, head.Result.Code, head.Result.Anchor)
	}
	// No PULL for simple acks; treat as success
	return driver.RowsAffected(0), nil
}

// Optional interfaces
func (c *conn) BeginTx(ctx context.Context, opts driver.TxOptions) (driver.Tx, error) {
	return c.beginTx(ctx, opts)
}
func (c *conn) Ping(ctx context.Context) error              { return nil }
func (c *conn) CheckNamedValue(nv *driver.NamedValue) error { return nil }

// wire JSON mapping

type frame struct {
	StatusClass    string `json:"status_class"`
	StatusSubclass string `json:"status_subclass"`
	Result         struct {
		Type    string `json:"type"`
		Columns []struct {
			Name string `json:"name"`
			Type string `json:"type"`
		} `json:"columns"`
		Rows      []map[string]any `json:"rows"`
		Ordered   bool             `json:"ordered"`
		OrderKeys []string         `json:"order_keys"`
		Final     bool             `json:"final"`
		Code      string           `json:"code"`
		Message   string           `json:"message"`
		Anchor    string           `json:"anchor"`
		JSON      any              `json:"json"`
	} `json:"result"`
}

type rows struct {
	c         *conn
	ctx       context.Context
	cols      []string
	pageSize  int
	buf       []map[string]any
	i         int
	final     bool
	ordered   bool
	orderKeys []string
	closed    bool
}

func (r *rows) Columns() []string { return r.cols }
func (r *rows) Close() error {
	if r.closed {
		return nil
	}
	r.closed = true
	r.c.activeRows = nil
	r.c.mu.Unlock()
	return nil
}
func (r *rows) Next(dest []driver.Value) error {
	for {
		if r.i < len(r.buf) {
			row := r.buf[r.i]
			r.i++
			for ci, name := range r.cols {
				if v, ok := row[name]; ok {
					dest[ci] = toDriverValue(v)
				} else {
					dest[ci] = nil
				}
			}
			return nil
		}
		if r.final {
			return io.EOF
		}
		// fetch next page
		pull := map[string]any{"type": "PULL", "request_id": 1, "page_size": r.pageSize}
		if err := r.c.writeJSONLine(pull); err != nil {
			return err
		}
		line, err := r.c.readLine(r.ctx)
		if err != nil {
			return err
		}
		var f frame
		if err := json.Unmarshal(line, &f); err != nil {
			return err
		}
		if f.Result.Type == "ERROR" {
			// NoResult after final page -> treat as EOF
			return io.EOF
		}
		if f.Result.Type != "BINDINGS" {
			return fmt.Errorf("expected BINDINGS, got %s", f.Result.Type)
		}
		r.buffer(f.Result.Rows)
		r.final = f.Result.Final
	}
}

func (r *rows) ColumnTypeDatabaseTypeName(index int) string      { return "" }
func (r *rows) ColumnTypeNullable(index int) (nullable, ok bool) { return true, true }

func (r *rows) buffer(rows []map[string]any) {
	r.buf = rows
	r.i = 0
}

func toDriverValue(v any) driver.Value {
	switch x := v.(type) {
	case nil:
		return nil
	case bool:
		return x
	case float64:
		if x == float64(int64(x)) {
			return int64(x)
		}
		return x
	case string:
		return x
	case json.Number:
		if i, err := x.Int64(); err == nil {
			return i
		}
		if f, err := x.Float64(); err == nil {
			return f
		}
		return string(x)
	default:
		return fmt.Sprintf("%v", v)
	}
}

func rewritePlaceholders(query string, args []driver.NamedValue) (string, map[string]any) {
	params := make(map[string]any)
	// Replace '?' with $pN if present
	var b strings.Builder
	b.Grow(len(query) + 8*len(args))
	qi := 0
	argi := 0
	for qi < len(query) {
		ch := query[qi]
		if ch == '?' {
			argi++
			name := fmt.Sprintf("p%d", argi)
			b.WriteByte('$')
			b.WriteString(name)
			// find matching arg by ordinal
			for _, nv := range args {
				if nv.Ordinal == argi {
					params[name] = nv.Value
					break
				}
			}
			qi++
			continue
		}
		b.WriteByte(ch)
		qi++
	}
	// Also include named args explicitly provided
	for _, nv := range args {
		if nv.Name != "" {
			params[nv.Name] = nv.Value
		}
	}
	return b.String(), params
}
