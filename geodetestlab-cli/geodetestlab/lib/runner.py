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
import time
from pathlib import Path
from typing import Any

from .executor import run_cli_test, run_plaintext_verification, run_single_test
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
DEFAULT_ADMIN_PASSWORD = os.environ.get("GEODE_ADMIN_PASSWORD", "GeodeTestPassword123!")


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
        if spec.pre_server and not dry_run:
            if verbose:
                print(f"Running {len(spec.pre_server)} pre-server commands...")
            for i, cmd in enumerate(spec.pre_server):
                if verbose:
                    print(f"  pre_server[{i}]: {cmd}")
                try:
                    subprocess.run(shlex.split(cmd), shell=False, check=False)
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
                # Check if server is still alive before running the test
                # (server may have crashed due to QUIC memory bugs)
                if server_process and server_process.poll() is not None:
                    if verbose:
                        print(f"  Server crashed (exit code {server_process.returncode}), restarting...")
                    # Clean up old server
                    untrack_server(server_process)
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
                        if verbose:
                            print(f"  Failed to restart server: {e}")
                        # Mark remaining tests as failed
                        result = TestResult(
                            name=test_case.name,
                            passed=False,
                            duration_ms=0,
                            error=f"Server crashed and failed to restart: {e}",
                        )
                        summary.failed += 1
                        summary.results.append(result)
                        continue

                result = run_single_test(
                    test_case=test_case,
                    binary=binary,
                    env=env,
                    secrets=secrets,
                    timeout_ms=timeout_ms,
                    data_dir=data_dir,
                    verbose=verbose,
                )

                # If test failed with connection timeout and server is dead, restart server
                if not result.passed and "connection timeout" in (result.error or "") and server_process:
                    if server_process.poll() is not None:
                        if verbose:
                            print("  Server died during test, restarting for next test...")
                        untrack_server(server_process)
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
                        except ServerError:
                            pass  # Will be caught at the top of the next iteration

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
