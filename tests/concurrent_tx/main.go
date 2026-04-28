// Concurrent BEGIN/EXEC/COMMIT regression test (2026-04-28).
//
// Reproduces the msft-graph parallel-seed failure where 4-9 of 9
// concurrent BEGINs against the same QUIC connection pool failed
// with either "expected BEGIN response" or "sql: connection is
// already closed", and pins the post-fix expectation that EVERY
// concurrent transaction succeeds.
//
// What this test exercises
// ------------------------
//   * Opens N pinned sql.Conns from the geode driver pool.
//   * Spawns N goroutines, each running M iterations of:
//       BeginTx → 3× ExecContext (CREATE node) → Commit
//     on its own pinned conn.
//   * Counts: total iterations, successful commits, BEGIN failures
//     by error category (expected-BEGIN-response vs other), and
//     the final node count after the run.
//   * Asserts:
//       - all iterations commit successfully (failure rate == 0),
//       - the final node count equals N * M * 3.
//
// Why this is the right shape for the regression
// ----------------------------------------------
// The original bug surfaced at the START of the THIRD edge file in
// msft-graph: after two clean files of edges, the third file's first
// chunk's 9 parallel BeginTx calls all failed instantly.  This test
// reproduces the scenario by reusing pinned conns across many tx
// iterations, with concurrency in the same range (8-16 conns) that
// triggered the failure.
//
// Run: from this directory,
//   go run . -dsn "127.0.0.1:3141?insecure=true&user=geode&pass=$GEODE_ADMIN_PASSWORD&graph=concurrent_tx_test"
//   go run . -conns 8 -iter 50 -dsn "..."
//
// Exit codes
// ----------
//   0 — all iterations committed; node count matches expectation.
//   1 — one or more iterations failed, OR final node count mismatched.
//   2 — driver / setup failure (couldn't open the pool, etc).
package main

import (
	"context"
	"database/sql"
	"errors"
	"flag"
	"fmt"
	"os"
	"strings"
	"sync"
	"sync/atomic"
	"time"

	_ "geodedb.com/geode"
)

// failureBucket counts BEGIN-time failures by category.  Pre-fix the
// regression's signature was a non-zero `expectedBeginResponse`
// counter; post-fix this should always be 0 for healthy runs.
type failureBucket struct {
	expectedBeginResponse atomic.Uint64 // "expected BEGIN response"
	connClosed            atomic.Uint64 // "sql: connection is already closed"
	streamDesync          atomic.Uint64 // "stream desync: ..." (post-fix guard fired)
	other                 atomic.Uint64 // any other BEGIN-time failure
	commitErr             atomic.Uint64 // failure inside Commit/Rollback path
	execErr               atomic.Uint64 // failure inside an Exec inside the tx
}

func (b *failureBucket) total() uint64 {
	return b.expectedBeginResponse.Load() +
		b.connClosed.Load() +
		b.streamDesync.Load() +
		b.other.Load() +
		b.commitErr.Load() +
		b.execErr.Load()
}

func (b *failureBucket) report() string {
	return fmt.Sprintf(
		"expected_begin_response=%d conn_closed=%d stream_desync=%d other=%d commit_err=%d exec_err=%d",
		b.expectedBeginResponse.Load(),
		b.connClosed.Load(),
		b.streamDesync.Load(),
		b.other.Load(),
		b.commitErr.Load(),
		b.execErr.Load(),
	)
}

// classifyBeginErr buckets a BeginTx error into one of the failure
// categories so the report can show what KIND of failure dominated.
func classifyBeginErr(b *failureBucket, err error) {
	if err == nil {
		return
	}
	msg := err.Error()
	switch {
	case strings.Contains(msg, "expected BEGIN response"):
		b.expectedBeginResponse.Add(1)
	case strings.Contains(msg, "connection is already closed"):
		b.connClosed.Add(1)
	case strings.Contains(msg, "stream desync"):
		b.streamDesync.Add(1)
	default:
		b.other.Add(1)
	}
}

func main() {
	var (
		dsn            = flag.String("dsn", "", "geode DSN (required); typically 127.0.0.1:3141?insecure=true&user=geode&pass=$GEODE_ADMIN_PASSWORD&graph=concurrent_tx_test")
		conns          = flag.Int("conns", 8, "number of pinned sql.Conn workers running concurrently")
		iter           = flag.Int("iter", 25, "tx iterations per worker")
		nodesPerTx     = flag.Int("nodes-per-tx", 3, "CREATE statements inside each tx")
		setupGraph     = flag.String("graph", "concurrent_tx_test", "graph name to seed (auto-created)")
		timeout        = flag.Duration("timeout", 5*time.Minute, "overall test timeout")
		failOnAnyError = flag.Bool("strict", true, "treat ANY tx failure as a regression (default true)")
	)
	flag.Parse()

	if *dsn == "" {
		fmt.Fprintln(os.Stderr, "concurrent-tx-test: -dsn is required")
		os.Exit(2)
	}

	ctx, cancel := context.WithTimeout(context.Background(), *timeout)
	defer cancel()

	db, err := sql.Open("geode", *dsn)
	if err != nil {
		fmt.Fprintf(os.Stderr, "open: %v\n", err)
		os.Exit(2)
	}
	defer db.Close()

	// Generous open conns so the worker count maps 1:1 to underlying QUIC
	// streams.  The pool inside the driver caps QUIC connections at the
	// pool_size DSN parameter; here we rely on its default (16).
	db.SetMaxOpenConns(*conns + 4)
	db.SetMaxIdleConns(*conns + 4)

	// Sanity ping — also verifies the server is up and the user/graph
	// path works before fanning out N parallel workers.
	pingCtx, pingCancel := context.WithTimeout(ctx, 30*time.Second)
	if err := db.PingContext(pingCtx); err != nil {
		pingCancel()
		fmt.Fprintf(os.Stderr, "ping: %v\n", err)
		os.Exit(2)
	}
	pingCancel()

	// Reset the test graph deterministically so the final node count is
	// well-defined.  Use a single non-pinned conn for setup.
	if _, err := db.ExecContext(ctx, fmt.Sprintf("CREATE GRAPH IF NOT EXISTS %s", *setupGraph)); err != nil {
		fmt.Fprintf(os.Stderr, "create graph: %v\n", err)
		os.Exit(2)
	}
	if _, err := db.ExecContext(ctx, fmt.Sprintf("USE GRAPH %s", *setupGraph)); err != nil {
		// Some DSN setups bind the graph at HELLO time and reject USE GRAPH.
		// That's fine — the inserts will run on the bound graph regardless.
		_ = err
	}
	if _, err := db.ExecContext(ctx, "MATCH (n:CTXNode) DETACH DELETE n"); err != nil {
		// Empty-graph delete is ok; surface the error only if it's not the
		// "no nodes" idempotent case.
		fmt.Fprintf(os.Stderr, "warn: pre-test cleanup: %v\n", err)
	}

	// Pin N conns up front so each worker uses the same conn for the
	// whole run.  This is exactly the msft-graph "pinned conns across
	// chunks" pattern that surfaced the regression.
	pinned := make([]*sql.Conn, 0, *conns)
	for i := 0; i < *conns; i++ {
		c, err := db.Conn(ctx)
		if err != nil {
			fmt.Fprintf(os.Stderr, "acquire conn %d: %v\n", i, err)
			os.Exit(2)
		}
		pinned = append(pinned, c)
	}
	defer func() {
		for _, c := range pinned {
			_ = c.Close()
		}
	}()

	bucket := &failureBucket{}
	var totalCommits atomic.Uint64
	var totalAttempts atomic.Uint64

	// Barrier so all workers START their first BeginTx within a tight
	// window — pre-fix this was when the failures concentrated.
	startGate := make(chan struct{})

	var wg sync.WaitGroup
	wg.Add(*conns)
	for i := 0; i < *conns; i++ {
		i := i
		c := pinned[i]
		go func() {
			defer wg.Done()
			<-startGate
			for it := 0; it < *iter; it++ {
				totalAttempts.Add(1)
				if err := runOneTx(ctx, c, *nodesPerTx, i, it); err != nil {
					// classify based on which step failed.  The message
					// prefixes are emitted by runOneTx below.
					switch {
					case strings.HasPrefix(err.Error(), "begin:"):
						classifyBeginErr(bucket, errors.Unwrap(err))
					case strings.HasPrefix(err.Error(), "exec:"):
						bucket.execErr.Add(1)
					case strings.HasPrefix(err.Error(), "commit:"):
						bucket.commitErr.Add(1)
					default:
						bucket.other.Add(1)
					}
					fmt.Fprintf(os.Stderr, "worker %d iter %d: %v\n", i, it, err)
				} else {
					totalCommits.Add(1)
				}
			}
		}()
	}
	close(startGate)

	doneCh := make(chan struct{})
	go func() { wg.Wait(); close(doneCh) }()
	select {
	case <-doneCh:
	case <-ctx.Done():
		fmt.Fprintf(os.Stderr, "deadline exceeded after %s; %d/%d attempts completed\n",
			*timeout, totalCommits.Load(), totalAttempts.Load())
		os.Exit(1)
	}

	// Verify the final node count.  Each successful tx commits N
	// CREATE statements, so the count should equal commits × nodesPerTx.
	expectedNodes := totalCommits.Load() * uint64(*nodesPerTx)
	var actualNodes uint64
	row := db.QueryRowContext(ctx, "MATCH (n:CTXNode) RETURN count(n)")
	if err := row.Scan(&actualNodes); err != nil {
		fmt.Fprintf(os.Stderr, "count rows: %v\n", err)
		os.Exit(2)
	}

	failures := bucket.total()
	fmt.Printf("concurrent-tx-test: workers=%d iter=%d nodes_per_tx=%d attempts=%d commits=%d failures=%d (%s) nodes_actual=%d nodes_expected=%d\n",
		*conns, *iter, *nodesPerTx,
		totalAttempts.Load(), totalCommits.Load(), failures,
		bucket.report(), actualNodes, expectedNodes)

	if actualNodes != expectedNodes {
		fmt.Fprintf(os.Stderr, "FAIL: node count mismatch — committed %d txs but only %d nodes present\n",
			totalCommits.Load(), actualNodes)
		os.Exit(1)
	}
	if *failOnAnyError && failures > 0 {
		fmt.Fprintf(os.Stderr, "FAIL: %d tx failures observed (strict mode); see breakdown above\n", failures)
		os.Exit(1)
	}
	fmt.Println("PASS")
}

// runOneTx wraps a single BEGIN/EXEC×N/COMMIT sequence and returns any
// failure prefixed with the failing step name so the caller can bucket
// it.  The CREATE statements use the (worker, iter, n) triple so a
// post-mortem scan of the surviving nodes can identify which workers
// landed which iterations.
func runOneTx(ctx context.Context, c *sql.Conn, nodesPerTx, worker, iter int) error {
	tx, err := c.BeginTx(ctx, nil)
	if err != nil {
		return fmt.Errorf("begin: %w", err)
	}
	for n := 0; n < nodesPerTx; n++ {
		_, err := tx.ExecContext(ctx, "CREATE (n:CTXNode {worker: $worker, iter: $iter, n: $n})",
			sql.Named("worker", worker),
			sql.Named("iter", iter),
			sql.Named("n", n))
		if err != nil {
			_ = tx.Rollback()
			return fmt.Errorf("exec: %w", err)
		}
	}
	if err := tx.Commit(); err != nil {
		return fmt.Errorf("commit: %w", err)
	}
	return nil
}
