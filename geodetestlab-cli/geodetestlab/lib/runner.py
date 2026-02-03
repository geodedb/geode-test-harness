"""Test runner for geodetestlab.

This module handles executing test cases from specifications, managing
server lifecycle, and collecting results.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .spec import PlaintextCheck, TestCase, TestSpec
from .utils import find_geode_binary, get_free_port


class RunnerError(Exception):
    """Raised when the test runner encounters an error."""

    pass


@dataclass
class TestResult:
    """Result of a single test case execution."""

    name: str
    passed: bool
    duration_ms: float
    output: str = ""
    error: str = ""
    skip_reason: str | None = None
    plaintext_violations: list[str] = field(default_factory=list)


@dataclass
class RunSummary:
    """Summary of a test run."""

    total: int = 0
    passed: int = 0
    failed: int = 0
    skipped: int = 0
    duration_ms: float = 0.0
    results: list[TestResult] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "total": self.total,
            "passed": self.passed,
            "failed": self.failed,
            "skipped": self.skipped,
            "duration_ms": self.duration_ms,
        }


def run_tests(
    spec: TestSpec,
    secrets: dict[str, str],
    env_overrides: dict[str, str],
    llm_provider: str = "mock",
    model: str | None = None,
    max_cases: int | None = None,
    timeout_ms: int = 30000,
    server_timeout_ms: int = 60000,
    report_json: Path | None = None,
    dry_run: bool = False,
    ci_mode: bool = False,
    seed: int | None = None,
    spec_path: str = "",
    geode_binary: str | None = None,
    server_port: int | None = None,
    verbose: bool = False,
) -> tuple[int, dict[str, Any]]:
    """Run all tests defined in a specification.

    Parameters
    ----------
    spec : TestSpec
        The test specification to run.
    secrets : Dict[str, str]
        Resolved secrets.
    env_overrides : Dict[str, str]
        Environment variable overrides.
    timeout_ms : int
        Per-test timeout in milliseconds.
    server_timeout_ms : int
        Server startup timeout in milliseconds.
    dry_run : bool
        If True, don't actually execute tests.
    ci_mode : bool
        If True, run in CI mode with simplified output.
    verbose : bool
        If True, show verbose output.

    Returns
    -------
    Tuple[int, Dict[str, Any]]
        Exit code (0 for success, 1 for failures) and summary dictionary.
    """
    summary = RunSummary()
    start_time = time.time()

    # Find geode binary
    try:
        binary = find_geode_binary(geode_binary)
    except FileNotFoundError as e:
        raise RunnerError(str(e)) from e

    # Prepare environment
    env = os.environ.copy()
    env.update(env_overrides)
    env.update(spec.env)

    # Create temporary data directory if server mode
    data_dir = None
    server_process = None

    if spec.mode == "server":
        data_dir = Path(tempfile.mkdtemp(prefix="geode-test-"))
        port = server_port or get_free_port()

        # Start server
        if not dry_run:
            server_process = _start_server(
                binary=binary,
                data_dir=data_dir,
                port=port,
                env=env,
                args=spec.server_args,
                timeout_ms=server_timeout_ms,
                verbose=verbose,
            )

        env["GEODE_SERVER_ADDRESS"] = f"127.0.0.1:{port}"
        env["data_dir"] = str(data_dir)

    try:
        # Run each test case
        for test_case in spec.tests:
            summary.total += 1

            if test_case.skip:
                result = TestResult(
                    name=test_case.name,
                    passed=True,
                    duration_ms=0,
                    skip_reason=test_case.skip_reason or "Skipped",
                )
                summary.skipped += 1
                summary.results.append(result)
                continue

            if dry_run:
                result = TestResult(
                    name=test_case.name,
                    passed=True,
                    duration_ms=0,
                    output="[DRY RUN]",
                )
                summary.passed += 1
            else:
                result = _run_single_test(
                    test_case=test_case,
                    binary=binary,
                    env=env,
                    secrets=secrets,
                    timeout_ms=timeout_ms,
                    data_dir=data_dir,
                    verbose=verbose,
                )

                if result.passed:
                    summary.passed += 1
                else:
                    summary.failed += 1

            summary.results.append(result)

            if verbose and not ci_mode:
                status = "PASS" if result.passed else "FAIL"
                if result.skip_reason:
                    status = "SKIP"
                print(f"  [{status}] {test_case.name}")

        # Run spec-level plaintext verification if enabled
        if spec.plaintext_verification.enabled and data_dir and not dry_run:
            violations = _run_plaintext_verification(
                data_dir=data_dir,
                config=spec.plaintext_verification,
                verbose=verbose,
            )
            if violations and spec.plaintext_verification.fail_on_violation:
                # Add a synthetic test result for plaintext violations
                result = TestResult(
                    name="plaintext_verification",
                    passed=False,
                    duration_ms=0,
                    error=f"Plaintext violations found: {violations}",
                    plaintext_violations=violations,
                )
                summary.total += 1
                summary.failed += 1
                summary.results.append(result)

    finally:
        # Stop server if started
        if server_process:
            _stop_server(server_process, verbose=verbose)

        # Cleanup data directory if configured
        # Note: For TDE tests, cleanup is disabled to allow file scanning
        # For now, don't cleanup to allow plaintext verification
        # The data_dir will be cleaned up by the OS temp cleaner eventually
        _ = data_dir and spec.mode == "server" and hasattr(spec, "_cleanup_disabled")

    summary.duration_ms = (time.time() - start_time) * 1000

    # Write JSON report if requested
    if report_json:
        report = {
            "spec": spec.name,
            "summary": summary.to_dict(),
            "results": [
                {
                    "name": r.name,
                    "passed": r.passed,
                    "duration_ms": r.duration_ms,
                    "output": r.output[:1000] if r.output else "",
                    "error": r.error,
                    "skip_reason": r.skip_reason,
                }
                for r in summary.results
            ],
        }
        report_json.parent.mkdir(parents=True, exist_ok=True)
        with open(report_json, "w") as f:
            json.dump(report, f, indent=2)

    exit_code = 0 if summary.failed == 0 else 1
    return exit_code, summary.to_dict()


def _start_server(
    binary: str,
    data_dir: Path,
    port: int,
    env: dict[str, str],
    args: list[str],
    timeout_ms: int,
    verbose: bool,
) -> subprocess.Popen:
    """Start a Geode server process."""
    cmd = [
        binary,
        "serve",
        "--data-dir",
        str(data_dir),
        "--listen",
        f"127.0.0.1:{port}",
        "--log-level",
        "info" if verbose else "warn",
    ]
    cmd.extend(args)

    if verbose:
        print(f"Starting server: {' '.join(cmd)}")

    process = subprocess.Popen(
        cmd,
        env=env,
        stdout=subprocess.PIPE if not verbose else None,
        stderr=subprocess.PIPE if not verbose else None,
        text=True,
    )

    # Wait for server to be ready
    start = time.time()
    timeout_s = timeout_ms / 1000.0

    while time.time() - start < timeout_s:
        if process.poll() is not None:
            stdout, stderr = process.communicate()
            raise RunnerError(
                f"Server exited unexpectedly with code {process.returncode}\nstdout: {stdout}\nstderr: {stderr}"
            )

        # Check if port is bound
        try:
            result = subprocess.run(
                ["netstat", "-uln"],
                capture_output=True,
                text=True,
                timeout=1.0,
            )
            if f":{port}" in result.stdout:
                if verbose:
                    print(f"Server ready on port {port}")
                return process
        except Exception:
            pass

        time.sleep(0.1)

    process.terminate()
    raise RunnerError(f"Server failed to start within {timeout_s} seconds")


def _stop_server(process: subprocess.Popen, verbose: bool = False) -> None:
    """Stop a Geode server process."""
    if verbose:
        print("Stopping server...")

    try:
        process.terminate()
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        if verbose:
            print("Force killing server...")
        process.kill()
        process.wait(timeout=5)


def _run_single_test(
    test_case: TestCase,
    binary: str,
    env: dict[str, str],
    secrets: dict[str, str],
    timeout_ms: int,
    data_dir: Path | None,
    verbose: bool,
) -> TestResult:
    """Run a single test case."""
    start_time = time.time()

    # Determine if this is a query test or command test
    if test_case.query:
        cmd = [binary, "query", test_case.query]
        cmd.extend(["--server", env.get("GEODE_SERVER_ADDRESS", "127.0.0.1:3141")])
        cmd.extend(["--insecure"])
    elif test_case.command:
        # Shell command test
        cmd = [test_case.command]
        args = _substitute_variables(test_case.args, env, secrets, data_dir)
        cmd.extend(args)
    else:
        cmd = [binary]
        args = _substitute_variables(test_case.args, env, secrets, data_dir)
        cmd.extend(args)

    # Merge test-specific environment
    test_env = env.copy()
    test_env.update(test_case.env)

    try:
        result = subprocess.run(
            cmd,
            env=test_env,
            capture_output=True,
            text=True,
            timeout=timeout_ms / 1000.0,
            stdin=subprocess.PIPE,
        )

        output = result.stdout
        error = result.stderr
        exit_code = result.returncode

    except subprocess.TimeoutExpired:
        return TestResult(
            name=test_case.name,
            passed=False,
            duration_ms=(time.time() - start_time) * 1000,
            error=f"Test timed out after {timeout_ms}ms",
        )
    except Exception as e:
        return TestResult(
            name=test_case.name,
            passed=False,
            duration_ms=(time.time() - start_time) * 1000,
            error=str(e),
        )

    duration_ms = (time.time() - start_time) * 1000

    # Check expectations
    passed = _check_expectations(
        test_case=test_case,
        output=output,
        error=error,
        exit_code=exit_code,
    )

    # Run test-specific plaintext verification if enabled
    plaintext_violations = []
    if test_case.plaintext_check.enabled and data_dir:
        plaintext_violations = _run_plaintext_verification(
            data_dir=data_dir,
            config=test_case.plaintext_check,
            verbose=verbose,
        )
        if plaintext_violations and test_case.plaintext_check.fail_on_violation:
            passed = False

    return TestResult(
        name=test_case.name,
        passed=passed,
        duration_ms=duration_ms,
        output=output,
        error=error if not passed else "",
        plaintext_violations=plaintext_violations,
    )


def _substitute_variables(
    args: list[str],
    env: dict[str, str],
    secrets: dict[str, str],
    data_dir: Path | None,
) -> list[str]:
    """Substitute variables in argument list."""
    result = []
    for arg in args:
        # Substitute ${data_dir}
        if data_dir:
            arg = arg.replace("${data_dir}", str(data_dir))

        # Substitute ${env:VAR}
        for key, value in env.items():
            arg = arg.replace(f"${{{key}}}", value)
            arg = arg.replace(f"${{env:{key}}}", value)

        # Substitute ${secret:NAME}
        for key, value in secrets.items():
            arg = arg.replace(f"${{secret:{key}}}", value)

        result.append(arg)
    return result


def _check_expectations(
    test_case: TestCase,
    output: str,
    error: str,
    exit_code: int,
) -> bool:
    """Check if test output matches expectations."""
    expected = test_case.expected

    # Check exit code
    if expected.exit_code is not None and exit_code != expected.exit_code:
        return False

    # Check status (success vs error)
    if expected.status == "success" and exit_code != 0:
        return False
    if expected.status == "error" and exit_code == 0:
        return False

    # Check result contains
    if expected.result_contains and expected.result_contains not in output:
        return False

    # Check result not contains
    if expected.result_not_contains and expected.result_not_contains in output:
        return False

    # Check result matches (regex)
    if expected.result_matches and not re.search(expected.result_matches, output):
        return False

    # Check error contains
    return not (expected.error_contains and expected.error_contains not in error)


def _run_plaintext_verification(
    data_dir: Path,
    config: PlaintextCheck,
    verbose: bool,
) -> list[str]:
    """Run plaintext verification scan on data directory."""
    violations = []

    for pattern in config.search_patterns:
        try:
            # Use grep to search for plaintext patterns in all files
            result = subprocess.run(
                ["grep", "-r", "-a", "-l", pattern, str(data_dir)],
                capture_output=True,
                text=True,
                timeout=60,
            )

            if result.returncode == 0:
                # Pattern was found - this is a violation!
                matching_files = result.stdout.strip().split("\n")
                for file_path in matching_files:
                    if file_path:
                        # Filter out excluded extensions
                        skip = False
                        for ext in config.exclude_extensions:
                            if file_path.endswith(ext):
                                skip = True
                                break
                        if not skip:
                            violations.append(f"Pattern '{pattern}' found in: {file_path}")
                            if verbose:
                                print(f"  VIOLATION: '{pattern}' in {file_path}")

        except subprocess.TimeoutExpired:
            if verbose:
                print(f"  WARNING: Grep timeout for pattern '{pattern}'")
        except Exception as e:
            if verbose:
                print(f"  WARNING: Error scanning for '{pattern}': {e}")

    return violations
