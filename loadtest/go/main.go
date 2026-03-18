// Geode Load Test — Concurrent Connection Stress Test
//
// Tests concurrent QUIC connections via the Go database/sql driver.
// Ramps through increasing concurrency levels, measuring latency,
// throughput, and error rates at each level.
//
// Usage:
//
//	go run . -dsn "localhost:3141?insecure=true&user=geode&pass=YourPass"
//	go run . -dsn "localhost:3141?insecure=true" -levels "1,2,4,8,16,32"
//	go run . -dsn "localhost:3141?insecure=true" -duration 10s -output report.json
package main

import (
	"context"
	"database/sql"
	"encoding/json"
	"flag"
	"fmt"
	"math"
	"os"
	"sort"
	"strconv"
	"strings"
	"sync"
	"sync/atomic"
	"time"

	_ "geodedb.com/geode"
)

type LevelResult struct {
	Concurrency   int       `json:"concurrency"`
	TotalQueries  int64     `json:"total_queries"`
	Errors        int64     `json:"errors"`
	ErrorRate     float64   `json:"error_rate"`
	Duration      string    `json:"duration"`
	QPS           float64   `json:"qps"`
	LatencyP50    string    `json:"latency_p50"`
	LatencyP95    string    `json:"latency_p95"`
	LatencyP99    string    `json:"latency_p99"`
	LatencyMean   string    `json:"latency_mean"`
	LatencyMax    string    `json:"latency_max"`
	ErrorSamples  []string  `json:"error_samples,omitempty"`
}

type Report struct {
	Timestamp   string        `json:"timestamp"`
	DSN         string        `json:"dsn"`
	QueryType   string        `json:"query_type"`
	Levels      []LevelResult `json:"levels"`
	Summary     string        `json:"summary"`
}

func main() {
	dsn := flag.String("dsn", "localhost:3141?insecure=true", "Geode DSN")
	levelsStr := flag.String("levels", "1,2,4,8,16,32,64", "Comma-separated concurrency levels")
	duration := flag.Duration("duration", 5*time.Second, "Duration per concurrency level")
	output := flag.String("output", "", "JSON output file (stdout if empty)")
	queryType := flag.String("query", "read", "Query type: read, write, mixed")
	flag.Parse()

	levels := parseLevels(*levelsStr)

	fmt.Fprintf(os.Stderr, "Geode Load Test\n")
	fmt.Fprintf(os.Stderr, "  DSN:      %s\n", *dsn)
	fmt.Fprintf(os.Stderr, "  Levels:   %v\n", levels)
	fmt.Fprintf(os.Stderr, "  Duration: %s per level\n", *duration)
	fmt.Fprintf(os.Stderr, "  Query:    %s\n\n", *queryType)

	report := Report{
		Timestamp: time.Now().UTC().Format(time.RFC3339),
		DSN:       sanitizeDSN(*dsn),
		QueryType: *queryType,
	}

	for _, concurrency := range levels {
		result := runLevel(*dsn, concurrency, *duration, *queryType)
		report.Levels = append(report.Levels, result)

		fmt.Fprintf(os.Stderr, "  c=%-3d  qps=%-8.1f  p50=%-10s  p99=%-10s  errors=%d/%d\n",
			result.Concurrency, result.QPS, result.LatencyP50, result.LatencyP99,
			result.Errors, result.TotalQueries)

		if result.ErrorRate > 0.5 {
			fmt.Fprintf(os.Stderr, "  ⚠ >50%% error rate at c=%d, stopping ramp\n", concurrency)
			break
		}
	}

	// Summary
	if len(report.Levels) > 0 {
		last := report.Levels[len(report.Levels)-1]
		best := report.Levels[0]
		for _, l := range report.Levels {
			if l.QPS > best.QPS && l.ErrorRate < 0.1 {
				best = l
			}
		}
		report.Summary = fmt.Sprintf("Peak QPS: %.1f at c=%d. Max tested: c=%d (%.1f QPS, %.1f%% errors)",
			best.QPS, best.Concurrency, last.Concurrency, last.QPS, last.ErrorRate*100)
	}

	data, _ := json.MarshalIndent(report, "", "  ")

	if *output != "" {
		os.WriteFile(*output, data, 0644)
		fmt.Fprintf(os.Stderr, "\nReport: %s\n", *output)
	} else {
		fmt.Println(string(data))
	}
}

func runLevel(dsn string, concurrency int, duration time.Duration, queryType string) LevelResult {
	db, err := sql.Open("geode", dsn)
	if err != nil {
		return LevelResult{Concurrency: concurrency, ErrorSamples: []string{err.Error()}}
	}
	defer db.Close()

	db.SetMaxOpenConns(concurrency)
	db.SetMaxIdleConns(concurrency)
	db.SetConnMaxLifetime(time.Minute)

	// Warm up: establish connections
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	if err := db.PingContext(ctx); err != nil {
		return LevelResult{Concurrency: concurrency, ErrorSamples: []string{"ping: " + err.Error()}}
	}

	var (
		totalQueries atomic.Int64
		totalErrors  atomic.Int64
		latencies    = make([][]time.Duration, concurrency)
		errSamples   []string
		errMu        sync.Mutex
		wg           sync.WaitGroup
	)

	for i := range concurrency {
		latencies[i] = make([]time.Duration, 0, 1000)
	}

	deadline := time.Now().Add(duration)
	wg.Add(concurrency)

	for i := range concurrency {
		go func(workerID int) {
			defer wg.Done()
			for time.Now().Before(deadline) {
				start := time.Now()
				var qerr error

				switch queryType {
				case "write":
					qerr = execWrite(db, workerID)
				case "mixed":
					if workerID%2 == 0 {
						qerr = execRead(db)
					} else {
						qerr = execWrite(db, workerID)
					}
				default:
					qerr = execRead(db)
				}

				elapsed := time.Since(start)
				totalQueries.Add(1)

				if qerr != nil {
					totalErrors.Add(1)
					errMu.Lock()
					if len(errSamples) < 5 {
						errSamples = append(errSamples, qerr.Error())
					}
					errMu.Unlock()
				} else {
					latencies[workerID] = append(latencies[workerID], elapsed)
				}
			}
		}(i)
	}

	wg.Wait()

	// Merge and compute latencies
	var all []time.Duration
	for _, l := range latencies {
		all = append(all, l...)
	}

	total := totalQueries.Load()
	errors := totalErrors.Load()
	errorRate := float64(0)
	if total > 0 {
		errorRate = float64(errors) / float64(total)
	}

	result := LevelResult{
		Concurrency:  concurrency,
		TotalQueries: total,
		Errors:       errors,
		ErrorRate:    errorRate,
		Duration:     duration.String(),
		ErrorSamples: errSamples,
	}

	if len(all) > 0 {
		sort.Slice(all, func(i, j int) bool { return all[i] < all[j] })
		result.QPS = float64(len(all)) / duration.Seconds()
		result.LatencyP50 = percentile(all, 0.50).String()
		result.LatencyP95 = percentile(all, 0.95).String()
		result.LatencyP99 = percentile(all, 0.99).String()
		result.LatencyMax = all[len(all)-1].String()

		var sum time.Duration
		for _, d := range all {
			sum += d
		}
		result.LatencyMean = (sum / time.Duration(len(all))).String()
	}

	// Cleanup write data
	if queryType == "write" || queryType == "mixed" {
		db.ExecContext(context.Background(), "MATCH (n:LoadTestNode) DELETE n")
	}

	return result
}

func execRead(db *sql.DB) error {
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	rows, err := db.QueryContext(ctx, "RETURN 1 AS x")
	if err != nil {
		return err
	}
	defer rows.Close()
	for rows.Next() {
		var x int
		if err := rows.Scan(&x); err != nil {
			return err
		}
	}
	return rows.Err()
}

func execWrite(db *sql.DB, workerID int) error {
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	_, err := db.ExecContext(ctx,
		fmt.Sprintf("CREATE (:LoadTestNode {worker: %d, ts: %d})", workerID, time.Now().UnixNano()))
	return err
}

func percentile(sorted []time.Duration, p float64) time.Duration {
	if len(sorted) == 0 {
		return 0
	}
	idx := int(math.Ceil(p*float64(len(sorted)))) - 1
	if idx < 0 {
		idx = 0
	}
	if idx >= len(sorted) {
		idx = len(sorted) - 1
	}
	return sorted[idx]
}

func parseLevels(s string) []int {
	parts := strings.Split(s, ",")
	var levels []int
	for _, p := range parts {
		n, err := strconv.Atoi(strings.TrimSpace(p))
		if err == nil && n > 0 {
			levels = append(levels, n)
		}
	}
	return levels
}

func sanitizeDSN(dsn string) string {
	// Remove password from DSN for report
	if idx := strings.Index(dsn, "pass="); idx != -1 {
		end := strings.IndexByte(dsn[idx:], '&')
		if end == -1 {
			return dsn[:idx] + "pass=***"
		}
		return dsn[:idx] + "pass=***" + dsn[idx+end:]
	}
	return dsn
}
