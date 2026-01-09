#!/usr/bin/env python3
"""
Performance analysis tool for client library benchmarks.

Analyzes JSON test results and generates performance reports comparing
latency, throughput, and resource usage across all client libraries.
"""

import argparse
import json
import statistics
from pathlib import Path
from typing import Any, Dict, List
import sys


def load_results(json_file: Path) -> Dict[str, Any]:
    """Load test results from JSON file."""
    with open(json_file) as f:
        return json.load(f)


def analyze_latency(results: Dict[str, Any]) -> Dict[str, Any]:
    """Analyze query latency across clients."""
    latency_by_client = {}

    for result in results.get("results", []):
        client = result["client"]
        duration = result.get("duration_ms", 0)

        if client not in latency_by_client:
            latency_by_client[client] = []

        latency_by_client[client].append(duration)

    stats = {}
    for client, latencies in latency_by_client.items():
        if latencies:
            stats[client] = {
                "count": len(latencies),
                "min": min(latencies),
                "max": max(latencies),
                "mean": statistics.mean(latencies),
                "median": statistics.median(latencies),
                "stdev": statistics.stdev(latencies) if len(latencies) > 1 else 0,
                "p95": statistics.quantiles(latencies, n=20)[18] if len(latencies) >= 20 else max(latencies),
                "p99": statistics.quantiles(latencies, n=100)[98] if len(latencies) >= 100 else max(latencies),
            }

    return stats


def compare_clients(stats: Dict[str, Dict[str, float]]) -> None:
    """Print client comparison table."""
    print("\n" + "=" * 100)
    print("PERFORMANCE COMPARISON")
    print("=" * 100)
    print(f"{'Client':<10} {'Count':>6} {'Min':>8} {'Mean':>8} {'Median':>8} {'P95':>8} {'Max':>8} {'StdDev':>8}")
    print("-" * 100)

    for client, client_stats in sorted(stats.items()):
        print(
            f"{client:<10} "
            f"{client_stats['count']:>6} "
            f"{client_stats['min']:>7.1f}ms "
            f"{client_stats['mean']:>7.1f}ms "
            f"{client_stats['median']:>7.1f}ms "
            f"{client_stats['p95']:>7.1f}ms "
            f"{client_stats['max']:>7.1f}ms "
            f"{client_stats['stdev']:>7.1f}ms"
        )

    print("=" * 100)


def analyze_by_test(results: Dict[str, Any]) -> Dict[str, Dict[str, float]]:
    """Analyze performance by test name."""
    by_test = {}

    for result in results.get("results", []):
        test_name = result["test"]
        client = result["client"]
        duration = result.get("duration_ms", 0)

        if test_name not in by_test:
            by_test[test_name] = {}

        by_test[test_name][client] = duration

    return by_test


def print_test_comparison(by_test: Dict[str, Dict[str, float]]) -> None:
    """Print per-test comparison."""
    print("\n" + "=" * 100)
    print("PER-TEST PERFORMANCE")
    print("=" * 100)

    for test_name, client_times in sorted(by_test.items()):
        print(f"\nTest: {test_name}")
        print("-" * 60)

        # Find fastest and slowest
        if client_times:
            fastest_client = min(client_times.items(), key=lambda x: x[1])
            slowest_client = max(client_times.items(), key=lambda x: x[1])

            for client, duration in sorted(client_times.items(), key=lambda x: x[1]):
                speedup = slowest_client[1] / duration if duration > 0 else 0
                is_fastest = client == fastest_client[0]
                is_slowest = client == slowest_client[0]

                marker = ""
                if is_fastest:
                    marker = " ⚡ FASTEST"
                elif is_slowest:
                    marker = " 🐌 SLOWEST"

                print(f"  {client:<10} {duration:>7.1f}ms  ({speedup:>4.2f}x){marker}")


def calculate_throughput(stats: Dict[str, Dict[str, float]]) -> Dict[str, float]:
    """Calculate queries per second for each client."""
    throughput = {}

    for client, client_stats in stats.items():
        if client_stats["mean"] > 0:
            qps = 1000 / client_stats["mean"]  # Convert ms to seconds
            throughput[client] = qps

    return throughput


def print_throughput(throughput: Dict[str, float]) -> None:
    """Print throughput comparison."""
    print("\n" + "=" * 100)
    print("THROUGHPUT (Queries Per Second)")
    print("=" * 100)

    for client, qps in sorted(throughput.items(), key=lambda x: x[1], reverse=True):
        print(f"{client:<10} {qps:>10.1f} qps")

    print("=" * 100)


def analyze_success_rate(results: Dict[str, Any]) -> Dict[str, Dict[str, int]]:
    """Analyze success/failure rates."""
    rates = {}

    for result in results.get("results", []):
        client = result["client"]
        status = result["status"]

        if client not in rates:
            rates[client] = {"passed": 0, "failed": 0, "error": 0, "skipped": 0}

        if status in rates[client]:
            rates[client][status] += 1

    return rates


def print_success_rates(rates: Dict[str, Dict[str, int]]) -> None:
    """Print success rate comparison."""
    print("\n" + "=" * 100)
    print("SUCCESS RATES")
    print("=" * 100)
    print(f"{'Client':<10} {'Passed':>8} {'Failed':>8} {'Errors':>8} {'Skipped':>8} {'Pass Rate':>10}")
    print("-" * 100)

    for client, client_rates in sorted(rates.items()):
        total = sum(client_rates.values())
        pass_rate = (client_rates["passed"] / total * 100) if total > 0 else 0

        print(
            f"{client:<10} "
            f"{client_rates['passed']:>8} "
            f"{client_rates['failed']:>8} "
            f"{client_rates['error']:>8} "
            f"{client_rates['skipped']:>8} "
            f"{pass_rate:>9.1f}%"
        )

    print("=" * 100)


def generate_markdown_report(
    results: Dict[str, Any],
    latency_stats: Dict[str, Dict[str, float]],
    by_test: Dict[str, Dict[str, float]],
    throughput: Dict[str, float],
    rates: Dict[str, Dict[str, int]],
    output_file: Path,
) -> None:
    """Generate markdown performance report."""
    with open(output_file, "w") as f:
        f.write("# Client Library Performance Report\n\n")
        f.write(f"**Generated**: {results.get('timestamp', 'N/A')}\n\n")
        f.write(f"**Server**: {results.get('server', 'N/A')}\n\n")
        f.write(f"**Total Tests**: {results.get('total_tests', 0)}\n\n")

        # Latency comparison
        f.write("## Latency Comparison\n\n")
        f.write("| Client | Count | Min | Mean | Median | P95 | Max | StdDev |\n")
        f.write("|--------|-------|-----|------|--------|-----|-----|--------|\n")

        for client, stats in sorted(latency_stats.items()):
            f.write(
                f"| {client} | {stats['count']} | "
                f"{stats['min']:.1f}ms | {stats['mean']:.1f}ms | "
                f"{stats['median']:.1f}ms | {stats['p95']:.1f}ms | "
                f"{stats['max']:.1f}ms | {stats['stdev']:.1f}ms |\n"
            )

        # Throughput
        f.write("\n## Throughput\n\n")
        f.write("| Client | Queries/Second |\n")
        f.write("|--------|----------------|\n")

        for client, qps in sorted(throughput.items(), key=lambda x: x[1], reverse=True):
            f.write(f"| {client} | {qps:.1f} |\n")

        # Success rates
        f.write("\n## Success Rates\n\n")
        f.write("| Client | Passed | Failed | Errors | Pass Rate |\n")
        f.write("|--------|--------|--------|--------|----------|\n")

        for client, client_rates in sorted(rates.items()):
            total = sum(client_rates.values())
            pass_rate = (client_rates["passed"] / total * 100) if total > 0 else 0
            f.write(
                f"| {client} | {client_rates['passed']} | "
                f"{client_rates['failed']} | {client_rates['error']} | "
                f"{pass_rate:.1f}% |\n"
            )

        # Per-test breakdown
        f.write("\n## Per-Test Performance\n\n")

        for test_name, client_times in sorted(by_test.items()):
            f.write(f"### {test_name}\n\n")
            f.write("| Client | Duration |\n")
            f.write("|--------|----------|\n")

            for client, duration in sorted(client_times.items(), key=lambda x: x[1]):
                f.write(f"| {client} | {duration:.1f}ms |\n")

            f.write("\n")

    print(f"\nMarkdown report saved to: {output_file}")


def main():
    parser = argparse.ArgumentParser(description="Analyze client library performance")
    parser.add_argument("results_json", type=Path, help="Test results JSON file")
    parser.add_argument(
        "--markdown",
        type=Path,
        help="Output markdown report to file",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Show detailed per-test breakdown",
    )

    args = parser.parse_args()

    if not args.results_json.exists():
        print(f"ERROR: Results file not found: {args.results_json}", file=sys.stderr)
        sys.exit(1)

    # Load results
    results = load_results(args.results_json)

    # Analyze
    latency_stats = analyze_latency(results)
    by_test = analyze_by_test(results)
    throughput = calculate_throughput(latency_stats)
    rates = analyze_success_rate(results)

    # Print reports
    compare_clients(latency_stats)
    print_throughput(throughput)
    print_success_rates(rates)

    if args.verbose:
        print_test_comparison(by_test)

    # Generate markdown
    if args.markdown:
        generate_markdown_report(
            results, latency_stats, by_test, throughput, rates, args.markdown
        )


if __name__ == "__main__":
    main()
