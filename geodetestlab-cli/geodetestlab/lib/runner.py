"""Test runner for geodetestlab.

This module orchestrates test execution: server lifecycle, test dispatch,
result collection, and report generation.  The heavy lifting is delegated
to sub-modules:

* ``server``   – start / stop / track Geode server processes
* ``executor`` – run individual test cases (CLI, HTTP, shell, sequential)
* ``checks``   – verify outputs against expectations
* ``runner_types`` – shared data classes (``TestResult``, ``RunSummary``)
"""

from __future__ import annotations

import json
import logging
import os
import shlex
import signal
import subprocess
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

import httpx

from .executor import (
    DEFAULT_HTTP_TIMEOUT_S,
    SSL_VERIFY,
    run_cli_test,
    run_plaintext_verification,
    run_single_test,
)
from .runner_types import RunnerError, RunSummary, TestResult
from .server import (
    ServerError,
    kill_stale_servers,
    start_server,
    stop_server,
    untrack_server,
)
from .spec import TestCase, TestSpec
from .utils import find_geode_binary, get_free_port

# Re-export public API so existing ``from .runner import …`` keeps working.
__all__ = [
    "RunnerError",
    "RunSummary",
    "TestResult",
    "run_tests",
    # Kept for cli.py which imports this directly:
    "_kill_stale_servers",
]

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants (also available via executor, kept here for backward compat)
# ---------------------------------------------------------------------------
DEFAULT_QUIC_PORT = 3141
DEFAULT_GRPC_PORT = 50051
# DEFAULT_ADMIN_PASSWORD lives in runner_types (centralized)


def _kill_stale_servers() -> None:
    """Thin wrapper so ``cli.py`` can keep importing from ``runner``."""
    kill_stale_servers()


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


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
    transport: str = "quic",
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
    # NOTE: _kill_stale_servers() is intentionally NOT called here.
    # It must only be called once before parallel workers start, not
    # inside each worker. See cli.py run() for the single invocation.

    summary = RunSummary()
    start_time = time.time()

    # Apply spec-level default timeout if set (overrides runner default)
    if spec.default_timeout_ms > 0:
        timeout_ms = max(timeout_ms, spec.default_timeout_ms)

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

        # Run pre_server commands (e.g., cleanup of shared state files)
        # Only allow known-safe commands to mitigate CWE-78.
        _ALLOWED_PRE_SERVER_CMDS = frozenset({"rm", "mkdir", "cp", "mv", "chmod", "touch", "ln", "sleep"})
        if spec.pre_server and not dry_run:
            if verbose:
                print(f"Running {len(spec.pre_server)} pre-server commands...")
            for i, cmd in enumerate(spec.pre_server):
                if verbose:
                    print(f"  pre_server[{i}]: {cmd}")
                parsed = shlex.split(cmd)
                if not parsed:
                    continue
                base_cmd = Path(parsed[0]).name  # handle /usr/bin/rm → rm
                if base_cmd not in _ALLOWED_PRE_SERVER_CMDS:
                    logger.warning(
                        "pre_server[%d] blocked: '%s' not in allowlist %s",
                        i,
                        base_cmd,
                        sorted(_ALLOWED_PRE_SERVER_CMDS),
                    )
                    continue
                try:
                    subprocess.run(parsed, shell=False, check=False)
                except Exception as e:
                    if verbose:
                        print(f"  pre_server[{i}] warning: {e}")

        # Allocate gRPC port if needed
        grpc_port = None
        if transport == "grpc":
            grpc_port = get_free_port()

        # Start server
        if not dry_run:
            try:
                server_process = start_server(
                    binary=binary,
                    data_dir=data_dir,
                    port=port,
                    env=env,
                    args=spec.server_args,
                    timeout_ms=server_timeout_ms,
                    verbose=verbose,
                    grpc_port=grpc_port,
                )
            except ServerError as e:
                raise RunnerError(str(e)) from e

        env["GEODE_SERVER_ADDRESS"] = f"127.0.0.1:{port}"
        env["PORT"] = str(port)
        env["data_dir"] = str(data_dir)
        # Isolate CLI state (users, API keys) per test run so state from a
        # previous run (or a parallel retry) cannot bleed into this run.
        if "GEODE_STATE_DIR" not in env:
            env["GEODE_STATE_DIR"] = str(data_dir)
        env["GEODE_TRANSPORT"] = transport
        if grpc_port:
            env["GEODE_GRPC_ADDRESS"] = f"127.0.0.1:{grpc_port}"

    # Set up signal handler for graceful shutdown in worker processes
    interrupted = False

    def _worker_signal_handler(signum: int, frame: Any) -> None:
        nonlocal interrupted
        interrupted = True
        if server_process:
            stop_server(server_process, verbose=verbose)

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
                    setup_case = TestCase.from_dict(
                        {
                            "name": f"setup-{i}",
                            "description": "Setup query",
                            **setup_item,
                        }
                    )
                    if verbose:
                        print(f"  Executing setup-{i}...")
                    result = run_cli_test(
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

        # Create a shared httpx client for connection reuse across tests (PERF-007)
        _shared_http = httpx.Client(timeout=DEFAULT_HTTP_TIMEOUT_S, verify=SSL_VERIFY)

        # Lock protects summary mutation and server health checks in parallel mode
        _lock = threading.Lock()

        def _execute_one_test(test_case: TestCase) -> TestResult:
            """Execute a single test case and handle server crash recovery.

            Returns the TestResult. Server restart is serialized via _lock.
            """
            nonlocal server_process

            if test_case.skip:
                return TestResult(
                    name=test_case.name,
                    passed=True,
                    duration_ms=0,
                    skip_reason=test_case.skip_reason or "Skipped",
                )

            if dry_run:
                return TestResult(
                    name=test_case.name,
                    passed=True,
                    duration_ms=0,
                    output="[DRY RUN]",
                )

            # Check if server is still alive before running the test
            # (server may have crashed due to QUIC memory bugs)
            with _lock:
                if server_process and server_process.poll() is not None:
                    if verbose:
                        print(f"  Server crashed (exit code {server_process.returncode}), restarting...")
                    untrack_server(server_process)
                    try:
                        assert data_dir is not None
                        server_process = start_server(
                            binary=binary,
                            data_dir=data_dir,
                            port=port,
                            env=env,
                            args=spec.server_args,
                            timeout_ms=server_timeout_ms,
                            verbose=verbose,
                            grpc_port=grpc_port,
                        )
                    except ServerError as e:
                        if verbose:
                            print(f"  Failed to restart server: {e}")
                        return TestResult(
                            name=test_case.name,
                            passed=False,
                            duration_ms=0,
                            error=f"Server crashed and failed to restart: {e}",
                        )

            result = run_single_test(
                test_case=test_case,
                binary=binary,
                env=env,
                secrets=secrets,
                timeout_ms=timeout_ms,
                data_dir=data_dir,
                verbose=verbose,
                http_client=_shared_http,
            )

            # Retry once on transient failures (timeouts, connection errors)
            # that are likely caused by parallel resource contention rather
            # than real bugs.  The retry uses the same server instance.
            if not result.passed and server_process:
                err = (result.error or "").lower() + (result.output or "").lower()
                _TRANSIENT = ("timed out", "connection refused", "connection timeout", "timeout", "broken pipe")
                if any(t in err for t in _TRANSIENT):
                    # Only retry if the server is still alive
                    with _lock:
                        alive = server_process.poll() is None
                    if alive:
                        if verbose:
                            print(f"  Retrying {test_case.name} after transient failure...")
                        time.sleep(2)
                        result = run_single_test(
                            test_case=test_case,
                            binary=binary,
                            env=env,
                            secrets=secrets,
                            timeout_ms=timeout_ms,
                            data_dir=data_dir,
                            verbose=verbose,
                            http_client=_shared_http,
                        )

            # If test failed with a timeout-like error, the server may be hung
            # (still alive but unresponsive). Force-kill and restart.
            if not result.passed and server_process:
                error_text = (result.error or "").lower() + (result.output or "").lower()
                is_timeout = "timed out" in error_text or "connection timeout" in error_text or "timeout" in error_text
                with _lock:
                    if server_process.poll() is not None:
                        # Server crashed - restart
                        if verbose:
                            print("  Server died during test, restarting for next test...")
                        untrack_server(server_process)
                        try:
                            assert data_dir is not None
                            server_process = start_server(
                                binary=binary,
                                data_dir=data_dir,
                                port=port,
                                env=env,
                                args=spec.server_args,
                                timeout_ms=server_timeout_ms,
                                verbose=verbose,
                                grpc_port=grpc_port,
                            )
                        except ServerError:
                            pass  # Will be caught at the top of the next test
                    elif is_timeout:
                        # Server may be hung - health check with a simple query
                        try:
                            health_result = subprocess.run(
                                [
                                    binary,
                                    "query",
                                    "--server",
                                    f"127.0.0.1:{port}",
                                    "--insecure-tls-skip-verify",
                                    "-U",
                                    "geode",
                                    "-P",
                                    env.get("GEODE_ADMIN_PASSWORD", ""),
                                    "RETURN 1 AS _health",
                                ],
                                capture_output=True,
                                text=True,
                                timeout=5,
                                env=env,
                            )
                            if health_result.returncode != 0:
                                raise subprocess.TimeoutExpired(cmd="health", timeout=5)
                        except (subprocess.TimeoutExpired, Exception):
                            # Server is hung - force kill and restart
                            if verbose:
                                print("  Server hung (unresponsive), force-killing and restarting...")
                            try:
                                pgid = os.getpgid(server_process.pid)
                                os.killpg(pgid, signal.SIGKILL)
                            except (OSError, ProcessLookupError):
                                pass
                            server_process.kill()
                            try:
                                server_process.wait(timeout=2)
                            except subprocess.TimeoutExpired:
                                pass
                            untrack_server(server_process)
                            try:
                                assert data_dir is not None
                                server_process = start_server(
                                    binary=binary,
                                    data_dir=data_dir,
                                    port=port,
                                    env=env,
                                    args=spec.server_args,
                                    timeout_ms=server_timeout_ms,
                                    verbose=verbose,
                                    grpc_port=grpc_port,
                                )
                            except ServerError:
                                pass  # Will be caught at the top of the next test

            return result

        def _record_result(test_case: TestCase, result: TestResult) -> None:
            """Record a test result into the summary and print status."""
            if result.skip_reason:
                summary.skipped += 1
            elif dry_run or result.passed:
                summary.passed += 1
            else:
                summary.failed += 1
            summary.results.append(result)

            if verbose and not ci_mode:
                status = "PASS" if result.passed else "FAIL"
                if result.skip_reason:
                    status = "SKIP"
                print(f"  [{status}] {test_case.name}")

        # Run each test case — parallel or sequential (PERF-004)
        if spec.parallel_tests and not dry_run:
            pool_size = min(os.cpu_count() or 4, len(spec.tests), 8)
            with ThreadPoolExecutor(max_workers=pool_size) as pool:
                futures = {}
                for tc in spec.tests:
                    summary.total += 1
                    futures[pool.submit(_execute_one_test, tc)] = tc

                for future in as_completed(futures):
                    tc = futures[future]
                    result = future.result()
                    _record_result(tc, result)
        else:
            for test_case in spec.tests:
                if interrupted:
                    break
                summary.total += 1
                result = _execute_one_test(test_case)
                _record_result(test_case, result)

        # Run spec-level plaintext verification if enabled
        if spec.plaintext_verification.enabled and data_dir and not dry_run:
            violations = run_plaintext_verification(
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
        # Close shared HTTP client (PERF-007)
        try:
            _shared_http.close()
        except Exception:
            pass

        # Restore original signal handlers
        signal.signal(signal.SIGINT, original_sigint)
        signal.signal(signal.SIGTERM, original_sigterm)

        # Stop server if started
        if server_process:
            stop_server(server_process, verbose=verbose)

        # Cleanup data directory — skip for plaintext verification specs
        if data_dir and spec.mode == "server":
            has_plaintext_checks = any(getattr(t, "plaintext_checks", None) for t in spec.tests)
            if not has_plaintext_checks:
                import shutil

                try:
                    shutil.rmtree(data_dir, ignore_errors=True)
                except Exception:
                    pass

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
