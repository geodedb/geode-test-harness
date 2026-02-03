#!/usr/bin/env python3
"""Verify all geodetestlab comprehensive tests would pass."""

import os
import subprocess
from pathlib import Path

import yaml


def find_geode_binary():
    """Find the geode binary."""
    script_dir = Path(__file__).parent
    # Try relative to this script (geodetestlab-cli -> geode-test-harness -> monorepo -> geode)
    candidates = [
        script_dir.parent.parent / "geode" / "zig-out" / "bin" / "geode",
        script_dir.parent / ".." / "geode" / "zig-out" / "bin" / "geode",
        Path("./zig-out/bin/geode"),
        Path("../geode/zig-out/bin/geode"),
    ]
    for path in candidates:
        if path.exists():
            return str(path.resolve())
    return "geode"  # Fall back to PATH


def run_test(test_case, geode_binary):
    """Run a single test case."""
    args = test_case.get("args", [])
    expect = test_case.get("expect", {})

    result = subprocess.run(
        [geode_binary] + args, capture_output=True, text=True
    )

    # Check exit code
    if "exit_code" in expect and result.returncode != expect["exit_code"]:
        return False, f"Expected exit code {expect['exit_code']}, got {result.returncode}"

    # Check stdout_contains (geodetestlab checks both stdout and stderr)
    if "stdout_contains" in expect:
        combined = result.stdout + result.stderr
        for pattern in expect["stdout_contains"]:
            if pattern.lower() not in combined.lower():
                return False, f"Pattern '{pattern}' not found in output"

    # Check stderr_contains
    if "stderr_contains" in expect:
        for pattern in expect["stderr_contains"]:
            if pattern.lower() not in result.stderr.lower():
                return False, f"Pattern '{pattern}' not found in stderr"

    return True, "PASSED"


def main():
    geode_binary = find_geode_binary()
    print(f"Using geode binary: {geode_binary}")

    # Find the spec file relative to this script
    script_dir = Path(__file__).parent
    spec_path = script_dir / "specs" / "geode_comprehensive.yml"

    if not spec_path.exists():
        print(f"Spec file not found: {spec_path}")
        return 1

    with open(spec_path) as f:
        spec = yaml.safe_load(f)

    passed = 0
    failed = 0
    failures = []

    print("Running geodetestlab comprehensive tests...")
    print("=" * 60)

    for test in spec["tests"]:
        name = test["name"]
        success, message = run_test(test, geode_binary)

        if success:
            print(f"✓ {name}")
            passed += 1
        else:
            print(f"✗ {name}: {message}")
            failed += 1
            failures.append(name)

    print("\n" + "=" * 60)
    print(f"Results: {passed}/{passed + failed} tests passed")

    if failed > 0:
        print("\nFailed tests:")
        for name in failures:
            print(f"  - {name}")
        return 1
    else:
        print("\nAll tests passed!")
        return 0


if __name__ == "__main__":
    exit(main())
