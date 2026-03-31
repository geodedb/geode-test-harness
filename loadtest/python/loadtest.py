#!/usr/bin/env python3
"""Geode Load Test — Concurrent Connection Stress Test (Python Client)

Tests concurrent connections via the geode-client-python library.
Ramps through increasing concurrency levels using ThreadPoolExecutor.

Usage:
    python loadtest.py --host localhost --port 3141 --user geode --password YourPass
    python loadtest.py --levels 1,2,4,8,16,32 --duration 5
    python loadtest.py --output report.json
"""

import argparse
import json
import os
import statistics
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timezone
from threading import Lock


@dataclass
class LevelResult:
    concurrency: int
    total_queries: int = 0
    errors: int = 0
    latencies: list = field(default_factory=list)
    error_samples: list = field(default_factory=list)

    @property
    def error_rate(self) -> float:
        return self.errors / self.total_queries if self.total_queries > 0 else 0.0

    @property
    def qps(self) -> float:
        return len(self.latencies) / self._duration if self._duration > 0 else 0.0

    _duration: float = 0.0

    def to_dict(self) -> dict:
        lat = sorted(self.latencies)
        result = {
            "concurrency": self.concurrency,
            "total_queries": self.total_queries,
            "errors": self.errors,
            "error_rate": round(self.error_rate, 4),
            "qps": round(self.qps, 1),
        }
        if lat:
            result["latency_p50"] = f"{percentile(lat, 0.50) * 1000:.1f}ms"
            result["latency_p95"] = f"{percentile(lat, 0.95) * 1000:.1f}ms"
            result["latency_p99"] = f"{percentile(lat, 0.99) * 1000:.1f}ms"
            result["latency_mean"] = f"{statistics.mean(lat) * 1000:.1f}ms"
            result["latency_max"] = f"{max(lat) * 1000:.1f}ms"
        if self.error_samples:
            result["error_samples"] = self.error_samples[:5]
        return result


def percentile(sorted_data: list, p: float) -> float:
    if not sorted_data:
        return 0.0
    idx = max(0, min(int(p * len(sorted_data)), len(sorted_data) - 1))
    return sorted_data[idx]


def run_query_cli(host: str, port: int, user: str, password: str, query: str) -> tuple:
    """Execute a query via the geode CLI binary and return (latency, error)."""
    start = time.monotonic()
    try:
        geode_bin = os.environ.get("GEODE_BINARY", "geode")
        result = subprocess.run(
            [
                geode_bin,
                "query",
                query,
                "--server",
                f"{host}:{port}",
                "--insecure-tls-skip-verify",
                "-U",
                user,
                "-P",
                password,
                "--format",
                "json",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        elapsed = time.monotonic() - start
        if result.returncode != 0:
            return elapsed, result.stderr.strip() or f"exit code {result.returncode}"
        # Check for error in JSON response
        try:
            resp = json.loads(result.stdout)
            if resp.get("status_class", "00000")[:1] in ("4", "5"):
                return elapsed, resp.get("error", "unknown error")
        except json.JSONDecodeError:
            pass
        return elapsed, None
    except subprocess.TimeoutExpired:
        return time.monotonic() - start, "timeout"
    except Exception as e:
        return time.monotonic() - start, str(e)


def run_level(
    host: str,
    port: int,
    user: str,
    password: str,
    concurrency: int,
    duration: float,
    query_type: str,
) -> LevelResult:
    result = LevelResult(concurrency=concurrency)
    result._duration = duration
    err_lock = Lock()
    deadline = time.monotonic() + duration

    queries = {
        "read": "RETURN 1 AS x",
        "write": "CREATE (:PythonLoadTest {ts: timestamp()})",
        "mixed": None,  # alternates
    }

    def worker(worker_id: int):
        count = 0
        while time.monotonic() < deadline:
            if query_type == "mixed":
                q = queries["read"] if count % 2 == 0 else queries["write"]
            else:
                q = queries[query_type]

            latency, err = run_query_cli(host, port, user, password, q)
            result.total_queries += 1
            count += 1

            if err:
                result.errors += 1
                with err_lock:
                    if len(result.error_samples) < 5:
                        result.error_samples.append(str(err)[:200])
            else:
                result.latencies.append(latency)

    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        futures = [executor.submit(worker, i) for i in range(concurrency)]
        for f in as_completed(futures):
            f.result()  # propagate exceptions

    # Cleanup write data
    if query_type in ("write", "mixed"):
        run_query_cli(host, port, user, password, "MATCH (n:PythonLoadTest) DELETE n")

    return result


def main():
    parser = argparse.ArgumentParser(description="Geode Load Test (Python CLI)")
    parser.add_argument("--host", default="localhost")
    parser.add_argument("--port", type=int, default=3141)
    parser.add_argument("--user", "-U", default="geode")
    parser.add_argument(
        "--password", "-P", default=os.environ.get("GEODE_ADMIN_PASSWORD", "")
    )
    parser.add_argument("--levels", default="1,2,4,8", help="Concurrency levels")
    parser.add_argument("--duration", type=float, default=5.0, help="Seconds per level")
    parser.add_argument("--query", default="read", choices=["read", "write", "mixed"])
    parser.add_argument("--output", default="", help="JSON output file")
    args = parser.parse_args()

    if not args.password:
        print("Error: --password or GEODE_ADMIN_PASSWORD required", file=sys.stderr)
        sys.exit(1)

    levels = [int(x.strip()) for x in args.levels.split(",") if x.strip().isdigit()]

    print("Geode Load Test (Python CLI)", file=sys.stderr)
    print(f"  Host:     {args.host}:{args.port}", file=sys.stderr)
    print(f"  Levels:   {levels}", file=sys.stderr)
    print(f"  Duration: {args.duration}s per level", file=sys.stderr)
    print(f"  Query:    {args.query}\n", file=sys.stderr)

    report = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "host": f"{args.host}:{args.port}",
        "query_type": args.query,
        "client": "python-cli",
        "levels": [],
    }

    for concurrency in levels:
        result = run_level(
            args.host,
            args.port,
            args.user,
            args.password,
            concurrency,
            args.duration,
            args.query,
        )
        level_dict = result.to_dict()
        report["levels"].append(level_dict)

        p50 = level_dict.get("latency_p50", "N/A")
        p99 = level_dict.get("latency_p99", "N/A")
        print(
            f"  c={concurrency:<3d}  qps={result.qps:<8.1f}  "
            f"p50={p50:<10s}  p99={p99:<10s}  "
            f"errors={result.errors}/{result.total_queries}",
            file=sys.stderr,
        )

        if result.error_rate > 0.5:
            print(f"  ⚠ >50% error rate at c={concurrency}, stopping", file=sys.stderr)
            break

    data = json.dumps(report, indent=2)
    if args.output:
        with open(args.output, "w") as f:
            f.write(data)
        print(f"\nReport: {args.output}", file=sys.stderr)
    else:
        print(data)


if __name__ == "__main__":
    main()
