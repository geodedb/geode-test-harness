#!/usr/bin/env python3
"""
Coverage Analysis Tool for Client Library Tests

Analyzes test coverage across all client libraries and generates reports showing:
- Feature parity across clients
- Test distribution by category
- Coverage gaps and recommendations
- Historical coverage trends
"""

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Set


def load_test_results(json_file: Path) -> Dict[str, Any]:
    """Load test results from JSON file."""
    with open(json_file) as f:
        return json.load(f)


def analyze_feature_coverage(results: Dict[str, Any]) -> Dict[str, Any]:
    """Analyze which features are covered by which clients."""
    coverage = defaultdict(lambda: {"total": 0, "clients": {}})

    for result in results.get("results", []):
        test = result["test"]
        client = result["client"]
        status = result["status"]

        coverage[test]["total"] += 1
        coverage[test]["clients"][client] = status

    return dict(coverage)


def calculate_parity_score(coverage: Dict[str, Any], clients: List[str]) -> float:
    """Calculate overall feature parity score (0-100)."""
    total_tests = len(coverage)
    if total_tests == 0:
        return 0.0

    full_coverage_tests = 0
    for test_data in coverage.values():
        if all(client in test_data["clients"] for client in clients):
            # All clients have this test
            if all(
                test_data["clients"][client] == "passed" for client in clients
            ):
                full_coverage_tests += 1

    return (full_coverage_tests / total_tests) * 100


def identify_gaps(coverage: Dict[str, Any], clients: List[str]) -> List[Dict[str, Any]]:
    """Identify coverage gaps and failures."""
    gaps = []

    for test, data in coverage.items():
        missing_clients = [c for c in clients if c not in data["clients"]]
        failed_clients = [
            c
            for c in clients
            if c in data["clients"] and data["clients"][c] in ("failed", "error")
        ]

        if missing_clients or failed_clients:
            gaps.append(
                {
                    "test": test,
                    "missing": missing_clients,
                    "failed": failed_clients,
                    "severity": "high" if len(missing_clients) > 2 else "medium",
                }
            )

    return sorted(gaps, key=lambda x: len(x["missing"]), reverse=True)


def categorize_tests(coverage: Dict[str, Any]) -> Dict[str, List[str]]:
    """Categorize tests by feature area."""
    categories = {
        "basic": [],
        "transactions": [],
        "connections": [],
        "authentication": [],
        "performance": [],
        "other": [],
    }

    for test in coverage.keys():
        test_lower = test.lower()
        if any(
            keyword in test_lower
            for keyword in ["simple", "param", "return", "arithmetic", "null"]
        ):
            categories["basic"].append(test)
        elif any(
            keyword in test_lower
            for keyword in ["begin", "commit", "rollback", "transaction"]
        ):
            categories["transactions"].append(test)
        elif any(
            keyword in test_lower
            for keyword in ["connect", "disconnect", "pool", "reuse"]
        ):
            categories["connections"].append(test)
        elif any(
            keyword in test_lower
            for keyword in ["user", "login", "role", "permission", "auth", "rls"]
        ):
            categories["authentication"].append(test)
        elif any(
            keyword in test_lower
            for keyword in ["latency", "throughput", "concurrent", "benchmark"]
        ):
            categories["performance"].append(test)
        else:
            categories["other"].append(test)

    return {k: v for k, v in categories.items() if v}


def generate_coverage_report(
    results: Dict[str, Any], coverage: Dict[str, Any], output_file: Path
) -> None:
    """Generate detailed coverage report in markdown."""
    all_clients = set()
    for test_data in coverage.values():
        all_clients.update(test_data["clients"].keys())
    all_clients = sorted(all_clients)

    parity_score = calculate_parity_score(coverage, all_clients)
    gaps = identify_gaps(coverage, all_clients)
    categories = categorize_tests(coverage)

    with open(output_file, "w") as f:
        f.write("# Client Library Test Coverage Report\n\n")
        f.write(f"**Generated**: {results.get('timestamp', 'N/A')}\\n\n")
        f.write(f"**Server**: {results.get('server', 'N/A')}\\n\n")
        f.write(f"**Total Tests**: {len(coverage)}\\n\n")
        f.write(f"**Clients Analyzed**: {', '.join(all_clients)}\\n\n")
        f.write(f"**Feature Parity Score**: {parity_score:.1f}%\\n\n")

        # Summary statistics
        f.write("## Summary Statistics\n\n")
        f.write("| Metric | Value |\n")
        f.write("|--------|-------|\n")
        f.write(f"| Total Tests | {len(coverage)} |\n")
        f.write(f"| Clients | {len(all_clients)} |\n")
        f.write(f"| Coverage Gaps | {len(gaps)} |\n")

        total_passed = sum(
            1
            for test_data in coverage.values()
            for status in test_data["clients"].values()
            if status == "passed"
        )
        total_possible = len(coverage) * len(all_clients)
        pass_rate = (total_passed / total_possible * 100) if total_possible > 0 else 0
        f.write(f"| Overall Pass Rate | {pass_rate:.1f}% |\n")
        f.write(f"| Feature Parity | {parity_score:.1f}% |\n\n")

        # Coverage by category
        f.write("## Coverage by Category\n\n")
        f.write("| Category | Tests | Coverage |\n")
        f.write("|----------|-------|----------|\n")

        for category, tests in categories.items():
            category_passed = sum(
                1
                for test in tests
                for status in coverage[test]["clients"].values()
                if status == "passed"
            )
            category_possible = len(tests) * len(all_clients)
            category_rate = (
                (category_passed / category_possible * 100)
                if category_possible > 0
                else 0
            )
            f.write(
                f"| {category.title()} | {len(tests)} | {category_rate:.1f}% |\n"
            )

        f.write("\n")

        # Full coverage matrix
        f.write("## Full Coverage Matrix\n\n")
        f.write("| Test | " + " | ".join(all_clients) + " |\n")
        f.write("|------" + "|------" * len(all_clients) + "|\n")

        for test, data in sorted(coverage.items()):
            row = [test]
            for client in all_clients:
                if client in data["clients"]:
                    status = data["clients"][client]
                    if status == "passed":
                        row.append("✅")
                    elif status == "failed":
                        row.append("❌")
                    elif status == "error":
                        row.append("⚠️")
                    else:
                        row.append("⊘")
                else:
                    row.append("-")
            f.write("| " + " | ".join(row) + " |\n")

        f.write("\n")

        # Coverage gaps
        if gaps:
            f.write("## Coverage Gaps\n\n")
            f.write(
                "Tests with missing or failing client implementations:\n\n"
            )

            for gap in gaps[:10]:  # Top 10 gaps
                f.write(f"### {gap['test']}\n\n")
                if gap["missing"]:
                    f.write(
                        f"**Missing**: {', '.join(gap['missing'])}\\n\n"
                    )
                if gap["failed"]:
                    f.write(
                        f"**Failed**: {', '.join(gap['failed'])}\\n\n"
                    )
                f.write(f"**Severity**: {gap['severity']}\\n\n")

        # Client-specific metrics
        f.write("## Client-Specific Metrics\n\n")

        for client in all_clients:
            client_passed = sum(
                1
                for test_data in coverage.values()
                if test_data["clients"].get(client) == "passed"
            )
            client_total = sum(
                1 for test_data in coverage.values() if client in test_data["clients"]
            )
            client_rate = (
                (client_passed / client_total * 100) if client_total > 0 else 0
            )

            f.write(f"### {client}\n\n")
            f.write(f"- **Tests Run**: {client_total}/{len(coverage)}\n")
            f.write(f"- **Passed**: {client_passed}\n")
            f.write(f"- **Pass Rate**: {client_rate:.1f}%\n")
            f.write(
                f"- **Coverage**: {(client_total/len(coverage)*100):.1f}%\n\n"
            )

        # Recommendations
        f.write("## Recommendations\n\n")

        if parity_score < 80:
            f.write(
                "1. **Improve Feature Parity**: Current parity score is below 80%. "
                "Focus on implementing missing tests across all clients.\\n\n"
            )

        if gaps:
            f.write(
                f"2. **Address Coverage Gaps**: {len(gaps)} tests have missing or "
                "failing implementations. Prioritize high-severity gaps.\\n\n"
            )

        missing_categories = [
            cat for cat, tests in categories.items() if len(tests) < 5
        ]
        if missing_categories:
            f.write(
                f"3. **Expand Test Categories**: Categories with limited coverage: "
                f"{', '.join(missing_categories)}.\\n\n"
            )

        f.write(
            "4. **Continuous Monitoring**: Regularly run coverage analysis to track "
            "improvements and catch regressions.\\n\n"
        )

    print(f"Coverage report generated: {output_file}")


def print_coverage_summary(
    coverage: Dict[str, Any], clients: List[str], verbose: bool = False
) -> None:
    """Print coverage summary to console."""
    parity_score = calculate_parity_score(coverage, clients)
    gaps = identify_gaps(coverage, clients)
    categories = categorize_tests(coverage)

    print("\n" + "=" * 80)
    print("COVERAGE ANALYSIS SUMMARY")
    print("=" * 80)

    print(f"Total Tests: {len(coverage)}")
    print(f"Clients: {', '.join(clients)}")
    print(f"Feature Parity Score: {parity_score:.1f}%")
    print(f"Coverage Gaps: {len(gaps)}")

    print("\nCoverage by Category:")
    print("-" * 80)
    for category, tests in categories.items():
        category_passed = sum(
            1
            for test in tests
            for status in coverage[test]["clients"].values()
            if status == "passed"
        )
        category_possible = len(tests) * len(clients)
        category_rate = (
            (category_passed / category_possible * 100) if category_possible > 0 else 0
        )
        print(f"  {category.title():<15} {len(tests):>3} tests  {category_rate:>5.1f}%")

    if verbose and gaps:
        print("\nTop Coverage Gaps:")
        print("-" * 80)
        for gap in gaps[:5]:
            print(f"  {gap['test']}")
            if gap["missing"]:
                print(f"    Missing: {', '.join(gap['missing'])}")
            if gap["failed"]:
                print(f"    Failed: {', '.join(gap['failed'])}")

    print("=" * 80)


def main():
    parser = argparse.ArgumentParser(
        description="Analyze test coverage across client libraries"
    )
    parser.add_argument("results_json", type=Path, help="Test results JSON file")
    parser.add_argument(
        "--markdown",
        type=Path,
        help="Output detailed markdown report to file",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Show detailed coverage information",
    )

    args = parser.parse_args()

    if not args.results_json.exists():
        print(
            f"ERROR: Results file not found: {args.results_json}", file=sys.stderr
        )
        sys.exit(1)

    # Load and analyze
    results = load_test_results(args.results_json)
    coverage = analyze_feature_coverage(results)

    # Get all clients
    all_clients = set()
    for test_data in coverage.values():
        all_clients.update(test_data["clients"].keys())
    all_clients = sorted(all_clients)

    # Print summary
    print_coverage_summary(coverage, all_clients, args.verbose)

    # Generate markdown report
    if args.markdown:
        generate_coverage_report(results, coverage, args.markdown)


if __name__ == "__main__":
    main()
