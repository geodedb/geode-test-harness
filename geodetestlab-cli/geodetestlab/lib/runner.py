"""Test runner for geodetestlab.

This module handles executing test cases from specifications, managing
server lifecycle, and collecting results.
"""

from __future__ import annotations

import atexit
import json
import os
import re
import signal
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

from .spec import HttpExpected, HttpRequest, PlaintextCheck, TestCase, TestSpec, TestStep
from .utils import find_geode_binary, get_free_port

# Global list to track server processes for cleanup on exit
_active_servers: list[subprocess.Popen] = []


def _cleanup_servers() -> None:
    """Clean up any active server processes on exit."""
    for process in _active_servers[:]:  # Copy list to avoid modification during iteration
        try:
            if process.poll() is None:  # Still running
                process.terminate()
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=1)
        except Exception:
            pass
    _active_servers.clear()


# Register cleanup handler
atexit.register(_cleanup_servers)


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

    # Set up signal handler for graceful shutdown in worker processes
    interrupted = False

    def _worker_signal_handler(signum: int, frame: Any) -> None:
        nonlocal interrupted
        interrupted = True
        if server_process:
            _stop_server(server_process, verbose=verbose)

    original_sigint = signal.getsignal(signal.SIGINT)
    original_sigterm = signal.getsignal(signal.SIGTERM)
    signal.signal(signal.SIGINT, _worker_signal_handler)
    signal.signal(signal.SIGTERM, _worker_signal_handler)

    try:
        # Run setup queries if defined
        if spec.setup and not dry_run:
            if verbose:
                print(f"Running {len(spec.setup)} setup queries...")
            for i, setup_item in enumerate(spec.setup):
                if isinstance(setup_item, dict):
                    # Create a minimal TestCase for the setup query
                    setup_case = TestCase.from_dict({
                        "name": f"setup-{i}",
                        "description": "Setup query",
                        **setup_item,
                    })
                    if verbose:
                        print(f"  Executing setup-{i}...")
                    result = _run_cli_test(
                        test_case=setup_case,
                        binary=binary,
                        env=env,
                        secrets=secrets,
                        timeout_ms=timeout_ms,
                        data_dir=data_dir,
                        verbose=verbose,
                    )
                    if verbose:
                        status = "OK" if result.passed else "FAILED"
                        print(f"  Setup-{i}: {status}")
                    if not result.passed:
                        if verbose:
                            print(f"    Error: {result.error}")
                        # Continue anyway - some setup failures might be expected

        # Run each test case
        for test_case in spec.tests:
            # Check if we were interrupted
            if interrupted:
                break

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
        # Restore original signal handlers
        signal.signal(signal.SIGINT, original_sigint)
        signal.signal(signal.SIGTERM, original_sigterm)

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

    # Set environment variables for testing
    # Disable audit logging (avoids signing key requirements)
    env["GEODE_DISABLE_AUDIT"] = "1"
    # Allow auth to be disabled in release builds for testing
    env["GEODE_ALLOW_NO_AUTH"] = "1"
    # Set a known admin password for testing (used by query commands)
    env["GEODE_ADMIN_PASSWORD"] = "GeodeTestPassword123!"

    if verbose:
        print(f"Starting server: {' '.join(cmd)}")

    # Start server process - use start_new_session to create a new process group
    # This allows us to kill the entire group if needed
    process = subprocess.Popen(
        cmd,
        env=env,
        stdout=subprocess.PIPE if not verbose else None,
        stderr=subprocess.PIPE if not verbose else None,
        text=True,
        start_new_session=True,  # Create new session so we can kill the group
    )

    # Track this server for cleanup
    _active_servers.append(process)

    # Wait for server to be ready
    start = time.time()
    timeout_s = timeout_ms / 1000.0

    while time.time() - start < timeout_s:
        if process.poll() is not None:
            stdout, stderr = process.communicate()
            raise RunnerError(
                f"Server exited unexpectedly with code {process.returncode}\nstdout: {stdout}\nstderr: {stderr}"
            )

        # Check if port is bound (try ss first, then netstat as fallback)
        try:
            # Try ss first (more commonly available on modern systems)
            result = subprocess.run(
                ["ss", "-uln"],
                capture_output=True,
                text=True,
                timeout=1.0,
            )
            if result.returncode == 0 and f":{port}" in result.stdout:
                if verbose:
                    print(f"Server ready on port {port}")
                return process
        except FileNotFoundError:
            # ss not available, try netstat
            try:
                result = subprocess.run(
                    ["netstat", "-uln"],
                    capture_output=True,
                    text=True,
                    timeout=1.0,
                )
                if result.returncode == 0 and f":{port}" in result.stdout:
                    if verbose:
                        print(f"Server ready on port {port}")
                    return process
            except Exception:
                pass
        except Exception:
            pass

        time.sleep(0.1)

    process.terminate()
    raise RunnerError(f"Server failed to start within {timeout_s} seconds")


def _stop_server(process: subprocess.Popen, verbose: bool = False) -> None:
    """Stop a Geode server process."""
    if verbose:
        print("Stopping server...")

    # Remove from tracking list
    if process in _active_servers:
        _active_servers.remove(process)

    try:
        # Try graceful termination first
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            if verbose:
                print("Force killing server...")
            # Kill the entire process group if we created a new session
            try:
                os.killpg(os.getpgid(process.pid), signal.SIGKILL)
            except (OSError, ProcessLookupError):
                pass
            process.kill()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                pass
    except Exception:
        # Process may have already exited
        pass


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
    # Dispatch based on test type
    if test_case.test_type == "http":
        return _run_http_test(test_case, env, verbose)
    elif test_case.test_type == "sequential":
        return _run_sequential_test(test_case, binary, env, secrets, timeout_ms, data_dir, verbose)

    # CLI test (default)
    return _run_cli_test(test_case, binary, env, secrets, timeout_ms, data_dir, verbose)


def _run_cli_test(
    test_case: TestCase,
    binary: str,
    env: dict[str, str],
    secrets: dict[str, str],
    timeout_ms: int,
    data_dir: Path | None,
    verbose: bool,
) -> TestResult:
    """Run a CLI test case."""
    start_time = time.time()

    # Get authentication credentials from environment
    admin_password = env.get("GEODE_ADMIN_PASSWORD", "GeodeTestPassword123!")

    # Determine if this is a query test or command test
    if test_case.query:
        cmd = [binary, "query", test_case.query]
        cmd.extend(["--server", env.get("GEODE_SERVER_ADDRESS", "127.0.0.1:3141")])
        cmd.extend(["--insecure"])
        cmd.extend(["-U", "geode", "-P", admin_password])
    elif test_case.command:
        # Shell command test
        cmd = [test_case.command]
        args = _substitute_variables(test_case.args, env, secrets, data_dir)
        cmd.extend(args)
    else:
        cmd = [binary]
        args = _substitute_variables(test_case.args, env, secrets, data_dir)
        cmd.extend(args)
        # If this is a query command via args, add server, insecure, and auth flags
        if args and args[0] == "query" and len(args) > 1:
            cmd.extend(["--server", env.get("GEODE_SERVER_ADDRESS", "127.0.0.1:3141")])
            cmd.extend(["--insecure"])
            cmd.extend(["-U", "geode", "-P", admin_password])

    # Merge test-specific environment
    test_env = env.copy()
    test_env.update(test_case.env)

    try:
        # Substitute variables in stdin if present
        stdin_input = test_case.stdin
        if stdin_input and data_dir:
            stdin_input = stdin_input.replace("${data_dir}", str(data_dir))
            for key, value in env.items():
                stdin_input = stdin_input.replace(f"${{{key}}}", value)
                stdin_input = stdin_input.replace(f"${{env:{key}}}", value)
            for key, value in secrets.items():
                stdin_input = stdin_input.replace(f"${{secret:{key}}}", value)

        result = subprocess.run(
            cmd,
            env=test_env,
            capture_output=True,
            text=True,
            timeout=timeout_ms / 1000.0,
            input=stdin_input,  # Pass stdin content to the subprocess
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

    # Debug output for failures
    if not passed and verbose:
        print(f"    Exit code: {exit_code}")
        print(f"    Stdout: {output[:200] if output else '(empty)'}")
        print(f"    Stderr: {error[:200] if error else '(empty)'}")

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


def _run_http_test(
    test_case: TestCase,
    env: dict[str, str],
    verbose: bool,
) -> TestResult:
    """Run an HTTP test case."""
    start_time = time.time()
    outputs = []
    errors = []

    try:
        # Create an HTTP client with connection reuse
        with httpx.Client(timeout=30.0, verify=False) as client:
            for i, req in enumerate(test_case.http_requests):
                # Substitute environment variables in URL
                url = req.url
                for key, value in env.items():
                    url = url.replace(f"${{{key}}}", value)
                    url = url.replace(f"${{env:{key}}}", value)

                if verbose:
                    print(f"  HTTP {req.method} {url}")

                try:
                    response = client.request(
                        method=req.method,
                        url=url,
                        headers=req.headers,
                        content=req.body,
                        timeout=req.timeout_ms / 1000.0,
                    )

                    # Check expectations for this request
                    passed = _check_http_expectations(response, req.expected, verbose)

                    if not passed:
                        errors.append(
                            f"Request {i+1} failed: {req.method} {url}\n"
                            f"Status: {response.status_code}\n"
                            f"Body: {response.text[:500]}"
                        )
                        return TestResult(
                            name=test_case.name,
                            passed=False,
                            duration_ms=(time.time() - start_time) * 1000,
                            output="\n".join(outputs),
                            error="\n".join(errors),
                        )

                    outputs.append(f"Request {i+1}: {response.status_code} OK")

                except httpx.RequestError as e:
                    errors.append(f"Request {i+1} error: {e}")
                    return TestResult(
                        name=test_case.name,
                        passed=False,
                        duration_ms=(time.time() - start_time) * 1000,
                        output="\n".join(outputs),
                        error="\n".join(errors),
                    )

    except Exception as e:
        return TestResult(
            name=test_case.name,
            passed=False,
            duration_ms=(time.time() - start_time) * 1000,
            error=str(e),
        )

    return TestResult(
        name=test_case.name,
        passed=True,
        duration_ms=(time.time() - start_time) * 1000,
        output="\n".join(outputs),
    )


def _check_http_expectations(
    response: httpx.Response,
    expected: HttpExpected,
    verbose: bool,
) -> bool:
    """Check if HTTP response matches expectations."""
    # Check status code
    if expected.status_code is not None and response.status_code != expected.status_code:
        if verbose:
            print(f"    Expected status {expected.status_code}, got {response.status_code}")
        return False

    # Check content type
    if expected.content_type is not None:
        content_type = response.headers.get("content-type", "")
        if expected.content_type not in content_type:
            if verbose:
                print(f"    Expected content-type containing '{expected.content_type}', got '{content_type}'")
            return False

    # Check body contains
    body = response.text
    if expected.body_contains:
        for substring in expected.body_contains:
            if substring not in body:
                if verbose:
                    print(f"    Body missing expected substring: '{substring}'")
                return False

    # Check body not contains
    if expected.body_not_contains:
        for substring in expected.body_not_contains:
            if substring in body:
                if verbose:
                    print(f"    Body contains unexpected substring: '{substring}'")
                return False

    # Check body regex
    if expected.body_regex:
        for pattern in expected.body_regex:
            if not re.search(pattern, body):
                if verbose:
                    print(f"    Body doesn't match regex: '{pattern}'")
                return False

    # Check headers
    if expected.headers:
        for header_name, header_value in expected.headers.items():
            actual = response.headers.get(header_name)
            if actual is None or header_value not in actual:
                if verbose:
                    print(f"    Header '{header_name}' expected '{header_value}', got '{actual}'")
                return False

    return True


def _run_sequential_test(
    test_case: TestCase,
    binary: str,
    env: dict[str, str],
    secrets: dict[str, str],
    timeout_ms: int,
    data_dir: Path | None,
    verbose: bool,
) -> TestResult:
    """Run a sequential test case with multiple steps."""
    start_time = time.time()
    outputs = []
    errors = []

    # Get authentication credentials from environment
    admin_password = env.get("GEODE_ADMIN_PASSWORD", "GeodeTestPassword123!")

    try:
        # Create an HTTP client for HTTP steps
        with httpx.Client(timeout=30.0, verify=False) as http_client:
            for i, step in enumerate(test_case.steps):
                if verbose:
                    print(f"  Step {i+1}: {step.step_type}")

                if step.step_type == "wait":
                    time.sleep(step.wait_ms / 1000.0)
                    outputs.append(f"Step {i+1}: waited {step.wait_ms}ms")

                elif step.step_type == "http":
                    # Execute HTTP step
                    url = step.url or ""
                    for key, value in env.items():
                        url = url.replace(f"${{{key}}}", value)
                        url = url.replace(f"${{env:{key}}}", value)

                    response = http_client.request(
                        method=step.method or "GET",
                        url=url,
                        headers=step.headers,
                        content=step.body,
                        timeout=step.timeout_ms / 1000.0,
                    )

                    if step.expected:
                        passed = _check_http_expectations(response, step.expected, verbose)
                        if not passed:
                            errors.append(f"Step {i+1} failed: HTTP {step.method} {url}")
                            return TestResult(
                                name=test_case.name,
                                passed=False,
                                duration_ms=(time.time() - start_time) * 1000,
                                output="\n".join(outputs),
                                error="\n".join(errors),
                            )

                    outputs.append(f"Step {i+1}: HTTP {response.status_code} OK")

                elif step.step_type == "gql":
                    # Execute GQL query step
                    cmd = [binary, "query", step.query or ""]
                    cmd.extend(["--server", env.get("GEODE_SERVER_ADDRESS", "127.0.0.1:3141")])
                    cmd.extend(["--insecure"])
                    cmd.extend(["-U", "geode", "-P", admin_password])

                    result = subprocess.run(
                        cmd,
                        env=env,
                        capture_output=True,
                        text=True,
                        timeout=step.timeout_ms / 1000.0,
                    )

                    if step.gql_expected:
                        # Check GQL expectations
                        expected_status = step.gql_expected.get("status_class")
                        if expected_status and expected_status not in result.stdout:
                            errors.append(f"Step {i+1} failed: expected status {expected_status}")
                            return TestResult(
                                name=test_case.name,
                                passed=False,
                                duration_ms=(time.time() - start_time) * 1000,
                                output="\n".join(outputs),
                                error="\n".join(errors),
                            )

                    outputs.append(f"Step {i+1}: GQL OK")

    except Exception as e:
        return TestResult(
            name=test_case.name,
            passed=False,
            duration_ms=(time.time() - start_time) * 1000,
            error=str(e),
        )

    return TestResult(
        name=test_case.name,
        passed=True,
        duration_ms=(time.time() - start_time) * 1000,
        output="\n".join(outputs),
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

    # Check status (success vs error) - only if exit_code not explicitly specified
    # This allows tests to specify exit_code without also needing to set status
    if expected.exit_code is None:
        if expected.status == "success" and exit_code != 0:
            return False
        if expected.status == "error" and exit_code == 0:
            return False

    # Check result contains (legacy format - single string or list)
    if expected.result_contains:
        if isinstance(expected.result_contains, list):
            for item in expected.result_contains:
                if item not in output:
                    return False
        elif expected.result_contains not in output:
            return False

    # Check result not contains (legacy format - single string or list)
    if expected.result_not_contains:
        if isinstance(expected.result_not_contains, list):
            for item in expected.result_not_contains:
                if item in output:
                    return False
        elif expected.result_not_contains in output:
            return False

    # Check result matches (legacy format - single regex or list)
    if expected.result_matches:
        if isinstance(expected.result_matches, list):
            for pattern in expected.result_matches:
                if not re.search(pattern, output):
                    return False
        elif not re.search(expected.result_matches, output):
            return False

    # Check error contains (legacy format - single string or list)
    if expected.error_contains:
        if isinstance(expected.error_contains, list):
            for item in expected.error_contains:
                if item not in error:
                    return False
        elif expected.error_contains not in error:
            return False

    # Check stdout_contains (list of substrings that must ALL be present)
    if expected.stdout_contains:
        for substring in expected.stdout_contains:
            if substring not in output:
                return False

    # Check stderr_contains (list of substrings that must ALL be present)
    if expected.stderr_contains:
        for substring in expected.stderr_contains:
            if substring not in error:
                return False

    # Check stdout_not_contains (list of substrings that must NOT be present)
    if expected.stdout_not_contains:
        for substring in expected.stdout_not_contains:
            if substring in output:
                return False

    # Check stderr_not_contains (list of substrings that must NOT be present)
    if expected.stderr_not_contains:
        for substring in expected.stderr_not_contains:
            if substring in error:
                return False

    # Check stdout_regex (list of regex patterns that must ALL match)
    if expected.stdout_regex:
        for pattern in expected.stdout_regex:
            if not re.search(pattern, output):
                return False

    # Check stderr_regex (list of regex patterns that must ALL match)
    if expected.stderr_regex:
        for pattern in expected.stderr_regex:
            if not re.search(pattern, error):
                return False

    return True


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
