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
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from .cluster import start_cluster, stop_cluster
from .cluster_types import ClusterControlContext, ClusterState
from .executor import (
    DEFAULT_HTTP_TIMEOUT_S,
    SSL_VERIFY,
    run_cli_test,
    run_plaintext_verification,
    run_single_test,
)
from .failure_log import append_failure
from .runner_types import DEFAULT_ADMIN_PASSWORD, RunnerError, RunSummary, TestResult
from .server import (
    ServerError,
    kill_stale_servers,
    start_server,
    stop_server,
    untrack_server,
)
from .spec import TestCase, TestSpec
from .tls_provision import args_contain_flag, provision_tls_certs
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

# Exit code for a runner / server lifecycle error (mirrors cli.EXIT_RUNNER_ERROR).
EXIT_RUNNER_ERROR = 3

# Name of the synthetic result recorded when the managed server never starts.
SERVER_STARTUP_RESULT_NAME = "server-startup"

_MAX_TRANSIENT_RETRIES = 2
_RETRY_BASE_DELAY_S = 1.0

_TRANSIENT_PATTERNS = (
    "timed out",
    "connection refused",
    "connection timeout",
    "timeout",
    "broken pipe",
    "failed to get stream",
    "failed to send hello",
    "failed to receive hello",
    "empty handshake response",
    "connection was refused",
    "connection reset",
    "failed to send query",
    "failed to receive response",
    "stream error",
    "quic error",
    "server busy",
    "too many connections",
    "work queue full",
)


def _summarize_expected(test_case: TestCase) -> str:
    """Compact, human/agent-readable summary of a test's expectations.

    Surfaces the assertion the test intended (exit code, required/forbidden
    substrings, regexes) so a failure record shows expected-vs-actual even when
    the check layer records pass/fail without a reason string.
    """
    exp = test_case.expected
    parts: list[str] = []
    if exp.exit_code is not None:
        parts.append(f"exit_code == {exp.exit_code}")
    for label, val in (
        ("stdout_contains", exp.stdout_contains),
        ("stdout_not_contains", exp.stdout_not_contains),
        ("stderr_contains", exp.stderr_contains),
        ("stderr_not_contains", exp.stderr_not_contains),
        ("stdout_regex", exp.stdout_regex),
        ("output_contains", exp.output_contains),
    ):
        if val:
            parts.append(f"{label}: {val}")
    if exp.stdout_exact is not None:
        parts.append(f"stdout_exact: {exp.stdout_exact!r}")
    if exp.result_contains:
        parts.append(f"result_contains: {exp.result_contains}")
    if test_case.query:
        parts.insert(0, f"query: {test_case.query}")
    if test_case.command:
        parts.insert(0, f"command: {test_case.command}")
    elif test_case.args:
        parts.insert(0, f"args: {test_case.args}")
    return "\n".join(parts)


def _is_transient_failure(result: TestResult, test_case: TestCase) -> bool:
    combined = (result.error or "").lower() + (result.output or "").lower()
    if any(p in combined for p in _TRANSIENT_PATTERNS):
        return True
    output_blank = not (result.output or "").strip()
    if output_blank:
        exp = test_case.expected
        expects_content = (
            exp.stdout_contains or exp.result_contains or exp.stdout_exact or exp.stdout_regex or test_case.query
        )
        if expects_content:
            return True
    return False


def _kill_stale_servers() -> None:
    kill_stale_servers()


def _restart_server(
    *,
    binary: str,
    data_dir: Path | None,
    port: int,
    grpc_port: int | None,
    env: dict[str, str],
    server_args: list[str],
    server_timeout_ms: int,
    verbose: bool,
    server_port: int | None,
    max_retries: int,
) -> tuple[subprocess.Popen[str] | None, int, int | None, bool]:
    if data_dir is None:
        raise RuntimeError("data_dir must not be None during server restart")

    for attempt in range(max_retries):
        try:
            process = start_server(
                binary=binary,
                data_dir=data_dir,
                port=port,
                env=env,
                args=server_args,
                timeout_ms=server_timeout_ms,
                verbose=verbose,
                grpc_port=grpc_port,
            )
            return process, port, grpc_port, True
        except ServerError as e:
            if attempt < max_retries - 1 and server_port is None:
                port = get_free_port()
                if grpc_port is not None:
                    grpc_port = get_free_port()
                env["GEODE_SERVER_ADDRESS"] = f"127.0.0.1:{port}"
                env["PORT"] = str(port)
                if verbose:
                    print(f"  Restart failed (attempt {attempt + 1}), retrying on port {port}...")
                continue
            if verbose:
                print(f"  Failed to restart server: {e}")
            return None, port, grpc_port, False
    return None, port, grpc_port, False


def _sync_server_addresses(env: dict[str, str], port: int, grpc_port: int | None) -> None:
    env["GEODE_SERVER_ADDRESS"] = f"127.0.0.1:{port}"
    env["PORT"] = str(port)
    if grpc_port is not None:
        env["GEODE_GRPC_ADDRESS"] = f"127.0.0.1:{grpc_port}"
    else:
        env.pop("GEODE_GRPC_ADDRESS", None)


@dataclass
class ServerState:
    process: subprocess.Popen[str] | None
    port: int
    grpc_port: int | None


def _run_pre_server_commands(pre_server: list[str] | None, dry_run: bool, verbose: bool) -> None:
    _ALLOWED_PRE_SERVER_CMDS = frozenset({"rm", "mkdir", "cp", "mv", "chmod", "touch", "ln", "sleep"})
    if pre_server and not dry_run:
        if verbose:
            print(f"Running {len(pre_server)} pre-server commands...")
        for i, cmd in enumerate(pre_server):
            if verbose:
                print(f"  pre_server[{i}]: {cmd}")
            parsed = shlex.split(cmd)
            if not parsed:
                continue
            base_cmd = Path(parsed[0]).name
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


def _start_initial_server(
    spec: TestSpec,
    binary: str,
    data_dir: Path,
    port: int,
    grpc_port: int | None,
    env: dict[str, str],
    server_timeout_ms: int,
    verbose: bool,
    server_port: int | None,
    dry_run: bool,
    server_args: list[str] | None = None,
) -> subprocess.Popen[str] | None:
    if dry_run:
        return None
    # server_args defaults to the spec's declared args; callers may pass an
    # augmented list (e.g. with verified-TLS --cert/--key).
    effective_args = spec.server_args if server_args is None else server_args
    MAX_PORT_RETRIES = 3
    last_error: Exception | None = None
    for attempt in range(MAX_PORT_RETRIES):
        try:
            return start_server(
                binary=binary,
                data_dir=data_dir,
                port=port,
                env=env,
                args=effective_args,
                timeout_ms=server_timeout_ms,
                verbose=verbose,
                grpc_port=grpc_port,
            )
        except ServerError as e:
            last_error = e
            if attempt < MAX_PORT_RETRIES - 1 and server_port is None:
                port = get_free_port()
                if grpc_port is not None:
                    grpc_port = get_free_port()
                env["GEODE_SERVER_ADDRESS"] = f"127.0.0.1:{port}"
                env["PORT"] = str(port)
                if verbose:
                    print(f"  Server start failed (attempt {attempt + 1}), retrying on port {port}...")
                continue
            raise RunnerError(str(e)) from e
    if last_error:
        raise RunnerError(str(last_error)) from last_error
    return None


def _setup_item_payload(setup_item: Any, index: int, description: str) -> dict[str, Any] | None:
    """Normalize one ``setup:`` entry into a :class:`TestCase` payload.

    A setup entry may be written either as a mapping (``query``/``command``
    plus optional per-item keys) or as a bare string of GQL — the YAML
    block-scalar form (``- |``) that most specs in this repo use.

    The string form used to be skipped silently, so every spec written that
    way ran its whole test list against an *empty* graph. That is how
    ``geode_c01_c05_regression.yml`` came to assert ``count(DISTINCT n.type)
    == 0`` as a "known regression": the Entity fixture was never created, so
    0 was simply the count of an empty set.

    Returns ``None`` for entries with nothing to execute.
    """
    if isinstance(setup_item, dict):
        return {"name": f"setup-{index}", "description": description, **setup_item}
    if isinstance(setup_item, str):
        text = setup_item.strip()
        if not text:
            return None
        return {"name": f"setup-{index}", "description": description, "query": text}
    return None


def _run_setup_queries(
    setup: list[Any] | None,
    dry_run: bool,
    verbose: bool,
    binary: str,
    env: dict[str, str],
    secrets: dict[str, str],
    timeout_ms: int,
    data_dir: Path | None,
) -> None:
    if not setup or dry_run:
        return
    if verbose:
        print(f"Running {len(setup)} setup queries...")
    for i, setup_item in enumerate(setup):
        payload = _setup_item_payload(setup_item, i, "Setup query")
        if payload is None:
            continue
        setup_case = TestCase.from_dict(payload)
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
        # A failed fixture makes every downstream assertion meaningless, so
        # report it even when not running verbosely.
        if not result.passed:
            print(f"  WARNING: setup-{i} failed: {result.error}", file=sys.stderr)


def _replay_setup(
    setup: list[Any] | None,
    dry_run: bool,
    verbose: bool,
    binary: str,
    env: dict[str, str],
    secrets: dict[str, str],
    timeout_ms: int,
    data_dir: Path | None,
) -> None:
    if not setup or dry_run:
        return
    if verbose:
        print(f"  Re-running {len(setup)} setup queries after restart...")
    for i, setup_item in enumerate(setup):
        payload = _setup_item_payload(setup_item, i, "Setup query (replay)")
        if payload is None:
            continue
        setup_case = TestCase.from_dict(payload)
        run_cli_test(
            test_case=setup_case,
            binary=binary,
            env=env,
            secrets=secrets,
            timeout_ms=timeout_ms,
            data_dir=data_dir,
            verbose=verbose,
        )


def _check_and_restart_crashed_server(
    lock: threading.Lock,
    server_state: ServerState,
    binary: str,
    data_dir: Path | None,
    env: dict[str, str],
    spec: TestSpec,
    server_timeout_ms: int,
    verbose: bool,
    server_port: int | None,
    secrets: dict[str, str],
    timeout_ms: int,
    dry_run: bool,
) -> bool:
    with lock:
        if server_state.process and server_state.process.poll() is not None:
            if verbose:
                print(f"  Server crashed (exit code {server_state.process.returncode}), restarting...")
            untrack_server(server_state.process)
            new_proc, port, grpc_port, restarted = _restart_server(
                binary=binary,
                data_dir=data_dir,
                port=server_state.port,
                grpc_port=server_state.grpc_port,
                env=env,
                server_args=spec.server_args,
                server_timeout_ms=server_timeout_ms,
                verbose=verbose,
                server_port=server_port,
                max_retries=3,
            )
            if restarted:
                server_state.process = new_proc
                server_state.port = port
                server_state.grpc_port = grpc_port
                _replay_setup(spec.setup, dry_run, verbose, binary, env, secrets, timeout_ms, data_dir)
                return True
            return False
    return True


def _retry_transient_failures(
    test_case: TestCase,
    result: TestResult,
    lock: threading.Lock,
    server_state: ServerState,
    binary: str,
    env: dict[str, str],
    secrets: dict[str, str],
    timeout_ms: int,
    data_dir: Path | None,
    verbose: bool,
    shared_http: httpx.Client | None,
) -> TestResult:
    if not result.passed and _is_transient_failure(result, test_case):
        for attempt in range(1, _MAX_TRANSIENT_RETRIES + 1):
            if server_state.process:
                with lock:
                    alive = server_state.process.poll() is None
                if not alive:
                    break
            delay = _RETRY_BASE_DELAY_S * attempt
            if verbose:
                print(
                    f"  Retrying {test_case.name} "
                    f"(attempt {attempt + 1}/{_MAX_TRANSIENT_RETRIES + 1}, "
                    f"backoff {delay:.0f}s)..."
                )
            time.sleep(delay)
            result = run_single_test(
                test_case=test_case,
                binary=binary,
                env=env,
                secrets=secrets,
                timeout_ms=timeout_ms,
                data_dir=data_dir,
                verbose=verbose,
                http_client=shared_http,
            )
            if result.passed:
                break
            if not _is_transient_failure(result, test_case):
                break
    return result


def _recover_hung_server(
    test_case: TestCase,
    result: TestResult,
    lock: threading.Lock,
    server_state: ServerState,
    binary: str,
    data_dir: Path | None,
    env: dict[str, str],
    spec: TestSpec,
    server_timeout_ms: int,
    verbose: bool,
    server_port: int | None,
    secrets: dict[str, str],
    timeout_ms: int,
    dry_run: bool,
) -> None:
    if not result.passed and server_state.process:
        error_text = (result.error or "").lower() + (result.output or "").lower()
        is_timeout = "timed out" in error_text or "connection timeout" in error_text or "timeout" in error_text
        with lock:
            if server_state.process.poll() is not None:
                if verbose:
                    print("  Server died during test, restarting for next test...")
                untrack_server(server_state.process)
                new_proc, port, grpc_port, restarted = _restart_server(
                    binary=binary,
                    data_dir=data_dir,
                    port=server_state.port,
                    grpc_port=server_state.grpc_port,
                    env=env,
                    server_args=spec.server_args,
                    server_timeout_ms=server_timeout_ms,
                    verbose=verbose,
                    server_port=server_port,
                    max_retries=3,
                )
                if restarted:
                    server_state.process = new_proc
                    server_state.port = port
                    server_state.grpc_port = grpc_port
                    _replay_setup(spec.setup, dry_run, verbose, binary, env, secrets, timeout_ms, data_dir)
            elif is_timeout:
                try:
                    health_result = subprocess.run(
                        [
                            binary,
                            "query",
                            "--server",
                            f"127.0.0.1:{server_state.port}",
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
                    if verbose:
                        print("  Server hung (unresponsive), force-killing and restarting...")
                    try:
                        pgid = os.getpgid(server_state.process.pid)
                        os.killpg(pgid, signal.SIGKILL)
                    except (OSError, ProcessLookupError):
                        pass
                    server_state.process.kill()
                    try:
                        server_state.process.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        pass
                    untrack_server(server_state.process)
                    new_proc, port, grpc_port, restarted = _restart_server(
                        binary=binary,
                        data_dir=data_dir,
                        port=server_state.port,
                        grpc_port=server_state.grpc_port,
                        env=env,
                        server_args=spec.server_args,
                        server_timeout_ms=server_timeout_ms,
                        verbose=verbose,
                        server_port=server_port,
                        max_retries=3,
                    )
                    if restarted:
                        server_state.process = new_proc
                        server_state.port = port
                        server_state.grpc_port = grpc_port
                        _replay_setup(spec.setup, dry_run, verbose, binary, env, secrets, timeout_ms, data_dir)


def _execute_one_test(
    test_case: TestCase,
    dry_run: bool,
    lock: threading.Lock,
    server_state: ServerState,
    binary: str,
    data_dir: Path | None,
    env: dict[str, str],
    spec: TestSpec,
    server_timeout_ms: int,
    verbose: bool,
    server_port: int | None,
    secrets: dict[str, str],
    timeout_ms: int,
    shared_http: httpx.Client | None,
    cluster_ctx: ClusterControlContext | None = None,
) -> TestResult:
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

    if not _check_and_restart_crashed_server(
        lock,
        server_state,
        binary,
        data_dir,
        env,
        spec,
        server_timeout_ms,
        verbose,
        server_port,
        secrets,
        timeout_ms,
        dry_run,
    ):
        return TestResult(
            name=test_case.name,
            passed=False,
            duration_ms=0,
            error="Server crashed and failed to restart after retries",
        )

    result = run_single_test(
        test_case=test_case,
        binary=binary,
        env=env,
        secrets=secrets,
        timeout_ms=timeout_ms,
        data_dir=data_dir,
        verbose=verbose,
        http_client=shared_http,
        cluster_ctx=cluster_ctx,
    )

    result = _retry_transient_failures(
        test_case, result, lock, server_state, binary, env, secrets, timeout_ms, data_dir, verbose, shared_http
    )

    _recover_hung_server(
        test_case,
        result,
        lock,
        server_state,
        binary,
        data_dir,
        env,
        spec,
        server_timeout_ms,
        verbose,
        server_port,
        secrets,
        timeout_ms,
        dry_run,
    )

    if result.passed and test_case.restart_server and server_state.process:
        with lock:
            if verbose:
                print("  Restarting server as requested by test...")
            stop_server(server_state.process, verbose=verbose)
            untrack_server(server_state.process)
            new_proc, port, grpc_port, restarted = _restart_server(
                binary=binary,
                data_dir=data_dir,
                port=server_state.port,
                grpc_port=server_state.grpc_port,
                env=env,
                server_args=spec.server_args,
                server_timeout_ms=server_timeout_ms,
                verbose=verbose,
                server_port=server_port,
                max_retries=3,
            )
            if not restarted or new_proc is None:
                result.passed = False
                result.error = "Requested server restart failed after test"
                return result
            server_state.process = new_proc
            server_state.port = port
            server_state.grpc_port = grpc_port
            _sync_server_addresses(env, port, grpc_port)

    return result


def _run_plaintext_checks(
    spec: TestSpec,
    data_dir: Path | None,
    dry_run: bool,
    verbose: bool,
    summary: RunSummary,
    failure_file: str | None = None,
    spec_path: str = "",
) -> None:
    if spec.plaintext_verification.enabled and data_dir and not dry_run:
        violations = run_plaintext_verification(
            data_dir=data_dir,
            config=spec.plaintext_verification,
            verbose=verbose,
        )
        if violations and spec.plaintext_verification.fail_on_violation:
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
            append_failure(
                failure_file,
                spec=spec_path,
                test_name="plaintext_verification",
                error=result.error,
                plaintext_violations=violations,
            )


def _generate_report(
    report_json: Path | None,
    summary: RunSummary,
    spec_path: str,
    results_list: list[dict[str, Any]],
) -> None:
    if report_json:
        report = {
            "summary": summary.to_dict(),
            "specs": [
                {
                    "spec": spec_path,
                    "summary": summary.to_dict(),
                    "results": results_list,
                }
            ],
        }
        report_json.parent.mkdir(parents=True, exist_ok=True)
        with open(report_json, "w") as f:
            json.dump(report, f, indent=2)


def _finalize_summary(
    summary: RunSummary,
    start_time: float,
    report_json: Path | None,
    spec_path: str,
) -> dict[str, Any]:
    """Stamp the duration, flatten the results and write the JSON report."""
    summary.duration_ms = (time.time() - start_time) * 1000

    results_list = [
        {
            "name": r.name,
            "passed": r.passed,
            "duration_ms": r.duration_ms,
            "output": r.output[:1000] if r.output else "",
            "error": r.error,
            "skip_reason": r.skip_reason,
        }
        for r in summary.results
    ]

    summary_dict = summary.to_dict()
    summary_dict["results"] = results_list

    _generate_report(report_json, summary, spec_path, results_list)
    return summary_dict


def _record_server_startup_failure(
    summary: RunSummary,
    error: str,
    start_time: float,
    report_json: Path | None,
    spec_path: str,
    failure_file: str | None,
) -> tuple[int, dict[str, Any]]:
    """Report a managed server that never came up as a failed run.

    A spec whose server fails to start executes zero tests. Returning the
    untouched (all-zero) summary made every consumer — the single-line JSON
    summary, the aggregate report, the rich "✓ All tests passed!" banner —
    report success for a spec that never ran a single case. Synthesizing one
    failing result instead makes the infrastructure failure visible everywhere
    a test failure is, while the ``EXIT_RUNNER_ERROR`` exit code still marks it
    as a lifecycle problem rather than an assertion failure.
    """
    message = f"Managed server failed to start: {error}"
    print(f"  ERROR: {message}", file=sys.stderr)
    summary.total += 1
    summary.failed += 1
    summary.results.append(
        TestResult(
            name=SERVER_STARTUP_RESULT_NAME,
            passed=False,
            duration_ms=0.0,
            error=message,
        )
    )
    append_failure(
        failure_file,
        spec=spec_path,
        test_name=SERVER_STARTUP_RESULT_NAME,
        error=message,
        kind="spec",
    )
    return EXIT_RUNNER_ERROR, _finalize_summary(summary, start_time, report_json, spec_path)


def _apply_force_cluster_size(spec: TestSpec, size: int) -> None:
    """Promote a spec without a ``cluster:`` block to an N-node cluster.

    Used by the harness's ``--force-cluster-size N`` flag (Task B3 of the
    2026-05-25 distributed cluster testing plan). The harness needs a way
    to run the full single-node spec suite against 1-, 3-, 5-, 10-node
    deployments without modifying every spec.

    Semantics:
      - size <= 1: no-op (cluster mode not requested)
      - spec.cluster_config already set: no-op (spec wins over CLI flag)
      - spec has ``single_node_only`` set truthy: opt-out, no-op
      - otherwise: synthesize ClusterConfig.from_size(size) and switch
        spec.mode to ``"cluster"`` so run_tests takes the cluster path.

    Idempotent. Mutates ``spec`` in place.
    """
    if size <= 1:
        return
    if spec.cluster_config is not None:
        return
    if getattr(spec, "single_node_only", False):
        return
    from .cluster_types import ClusterConfig

    spec.cluster_config = ClusterConfig.from_size(size)
    spec.mode = "cluster"


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
    force_cluster_size: int = 1,
    failure_file: str | None = None,
) -> tuple[int, dict[str, Any]]:
    summary = RunSummary()
    start_time = time.time()

    # Apply --force-cluster-size CLI override before the rest of the runner
    # branches on spec.mode. The helper is idempotent and a no-op for size<=1.
    _apply_force_cluster_size(spec, force_cluster_size)

    if spec.default_timeout_ms > 0:
        timeout_ms = max(timeout_ms, spec.default_timeout_ms)

    try:
        binary = find_geode_binary(geode_binary)
    except FileNotFoundError as e:
        # Dry runs never execute the binary; a placeholder path keeps
        # `--dry-run` usable (and its CLI tests green) on machines/CI
        # without a geode build. Real runs still fail loudly.
        if dry_run:
            binary = "geode"
        else:
            raise RunnerError(str(e)) from e

    env = os.environ.copy()
    env.update(env_overrides)
    env.update(spec.env)

    data_dir = None
    server_state = ServerState(process=None, port=0, grpc_port=None)
    cluster_state: ClusterState | None = None
    cluster_ctx: ClusterControlContext | None = None
    # Temp dir holding the verified-TLS CA+leaf provisioned for a single-server
    # spec (cluster mode tracks its own on ClusterState.cert_dir). Cleaned up in
    # the finally block.
    single_server_cert_dir: str | None = None

    if spec.mode == "server":
        data_dir = Path(tempfile.mkdtemp(prefix="geode-test-"))
        server_state.port = server_port or get_free_port()

        _run_pre_server_commands(spec.pre_server, dry_run, verbose)

        if transport == "grpc":
            server_state.grpc_port = get_free_port()

        if "GEODE_STATE_DIR" not in env:
            env["GEODE_STATE_DIR"] = str(data_dir)
        if "GEODE_ADMIN_PASSWORD" not in env:
            env["GEODE_ADMIN_PASSWORD"] = DEFAULT_ADMIN_PASSWORD
        env["GEODE_TRANSPORT"] = transport

        # Provision verified TLS so the server presents a CA-signed cert and the
        # client verifies it with --ca-cert — required on a ReleaseSafe binary,
        # which refuses --insecure-tls-skip-verify (insecure_tls_gate.zig). Skip
        # when the spec already supplies its own --cert (respect its intent) or
        # when openssl is unavailable (fall back to the debug-only insecure path).
        server_args = list(spec.server_args)
        if not args_contain_flag(server_args, "--cert"):
            provisioned = provision_tls_certs()
            if provisioned is not None:
                single_server_cert_dir, ca_crt, leaf_crt, leaf_key = provisioned
                server_args.extend(["--cert", leaf_crt, "--key", leaf_key])
                env["GEODE_TEST_CA_CERT"] = ca_crt

        try:
            server_state.process = _start_initial_server(
                spec,
                binary,
                data_dir,
                server_state.port,
                server_state.grpc_port,
                env,
                server_timeout_ms,
                verbose,
                server_port,
                dry_run,
                server_args=server_args,
            )
        except RunnerError as exc:
            # No server means no test can run. Record the infrastructure
            # failure and return a summary that says so, rather than
            # abandoning the run with an empty summary (false green).
            import shutil

            shutil.rmtree(data_dir, ignore_errors=True)
            if single_server_cert_dir is not None:
                shutil.rmtree(single_server_cert_dir, ignore_errors=True)
            return _record_server_startup_failure(
                summary,
                str(exc),
                start_time,
                report_json,
                spec_path,
                failure_file,
            )

        env["GEODE_SERVER_ADDRESS"] = f"127.0.0.1:{server_state.port}"
        env["PORT"] = str(server_state.port)
        env["data_dir"] = str(data_dir)
        _sync_server_addresses(env, server_state.port, server_state.grpc_port)

    elif spec.mode == "cluster" and spec.cluster_config is not None:
        cluster_config = spec.cluster_config

        _run_pre_server_commands(spec.pre_server, dry_run, verbose)

        if not dry_run:
            cluster_state = start_cluster(
                cluster_config,
                binary=binary,
                base_env=env,
                spec_server_args=spec.server_args,
                verbose=verbose,
                transport=transport,
            )

            # Point tests at the target node
            target = cluster_state.get_target_node(cluster_config.target_node)
            env["GEODE_SERVER_ADDRESS"] = target.address
            env["PORT"] = str(target.port)
            env["GEODE_TRANSPORT"] = transport
            if target.grpc_port:
                env["GEODE_GRPC_ADDRESS"] = target.grpc_address or ""

            # Expose the cluster's verified-TLS CA so client queries verify the
            # node certs with --ca-cert instead of --insecure-tls-skip-verify
            # (refused on ReleaseSafe binaries). start_cluster provisions the CA
            # under cert_dir as ca.crt by convention.
            if cluster_state.cert_dir is not None:
                ca_crt = str(Path(cluster_state.cert_dir) / "ca.crt")
                if Path(ca_crt).exists():
                    env["GEODE_TEST_CA_CERT"] = ca_crt

            # Inject cluster metadata
            env["GEODE_CLUSTER_SIZE"] = str(cluster_config.node_count)
            env["GEODE_CLUSTER_PORTS"] = ",".join(str(n.port) for n in cluster_state.nodes)

            data_dir = Path(target.data_dir)

            # Create ServerState for compatibility with _execute_one_test
            server_state = ServerState(
                process=target.process,
                port=target.port,
                grpc_port=target.grpc_port,
            )

            # Cluster-control context — lets `signal` / `restart_node` steps
            # reach individual node processes from inside a sequential test.
            cluster_ctx = ClusterControlContext(
                cluster_state=cluster_state,
                cluster_config=cluster_config,
                binary=binary,
                base_env=env,
                spec_server_args=spec.server_args,
                verbose=verbose,
                transport=transport,
            )

    interrupted = False

    def _worker_signal_handler(signum: int, frame: Any) -> None:
        nonlocal interrupted
        interrupted = True
        if server_state.process:
            stop_server(server_state.process, verbose=verbose)

    original_sigint = signal.getsignal(signal.SIGINT)
    original_sigterm = signal.getsignal(signal.SIGTERM)
    signal.signal(signal.SIGINT, _worker_signal_handler)
    signal.signal(signal.SIGTERM, _worker_signal_handler)

    _shared_http: httpx.Client | None = None
    try:
        _run_setup_queries(spec.setup, dry_run, verbose, binary, env, secrets, timeout_ms, data_dir)

        _shared_http = httpx.Client(timeout=DEFAULT_HTTP_TIMEOUT_S, verify=SSL_VERIFY)
        _lock = threading.Lock()

        def _record_result(test_case: TestCase, result: TestResult) -> None:
            if result.skip_reason:
                summary.skipped += 1
            elif dry_run or result.passed:
                summary.passed += 1
            else:
                summary.failed += 1
                # Stream the failure to the tailable failure file the instant it
                # is recorded (flock-guarded; safe across processes/threads).
                append_failure(
                    failure_file,
                    spec=spec_path,
                    test_name=test_case.name,
                    error=result.error,
                    output=result.output,
                    expected=_summarize_expected(test_case),
                    duration_ms=result.duration_ms,
                    cluster_node=result.cluster_node,
                    plaintext_violations=result.plaintext_violations,
                )
            summary.results.append(result)

            if verbose and not ci_mode:
                status = "PASS" if result.passed else "FAIL"
                if result.skip_reason:
                    status = "SKIP"
                print(f"  [{status}] {test_case.name}")

        if spec.parallel_tests and not dry_run:
            pool_size = min(os.cpu_count() or 4, len(spec.tests), 8)
            with ThreadPoolExecutor(max_workers=pool_size) as pool:
                futures = {}
                for tc in spec.tests:
                    summary.total += 1
                    futures[
                        pool.submit(
                            _execute_one_test,
                            tc,
                            dry_run,
                            _lock,
                            server_state,
                            binary,
                            data_dir,
                            env,
                            spec,
                            server_timeout_ms,
                            verbose,
                            server_port,
                            secrets,
                            timeout_ms,
                            _shared_http,
                            cluster_ctx,
                        )
                    ] = tc

                for future in as_completed(futures):
                    tc = futures[future]
                    result = future.result()
                    _record_result(tc, result)
        else:
            for test_case in spec.tests:
                if interrupted:
                    break

                # "all" mode: run each test against every cluster node
                if cluster_state is not None and spec.cluster_config and spec.cluster_config.target_node == "all":
                    for node in cluster_state.nodes:
                        if interrupted:
                            # mypy narrows `interrupted` to False after the
                            # outer check and cannot see the signal-handler
                            # mutation, so it flags this break unreachable.
                            break  # type: ignore[unreachable]
                        summary.total += 1
                        env["GEODE_SERVER_ADDRESS"] = node.address
                        env["PORT"] = str(node.port)
                        if node.grpc_port:
                            env["GEODE_GRPC_ADDRESS"] = node.grpc_address or ""
                        server_state = ServerState(process=node.process, port=node.port, grpc_port=node.grpc_port)
                        result = _execute_one_test(
                            test_case,
                            dry_run,
                            _lock,
                            server_state,
                            binary,
                            data_dir,
                            env,
                            spec,
                            server_timeout_ms,
                            verbose,
                            server_port,
                            secrets,
                            timeout_ms,
                            _shared_http,
                            cluster_ctx,
                        )
                        result.cluster_node = node.node_id
                        _record_result(test_case, result)
                else:
                    summary.total += 1

                    # Round-robin: update target for each test
                    if (
                        cluster_state is not None
                        and spec.cluster_config
                        and spec.cluster_config.target_node == "round-robin"
                    ):
                        next_node = cluster_state.next_round_robin_node()
                        env["GEODE_SERVER_ADDRESS"] = next_node.address
                        env["PORT"] = str(next_node.port)
                        if next_node.grpc_port:
                            env["GEODE_GRPC_ADDRESS"] = next_node.grpc_address or ""

                    result = _execute_one_test(
                        test_case,
                        dry_run,
                        _lock,
                        server_state,
                        binary,
                        data_dir,
                        env,
                        spec,
                        server_timeout_ms,
                        verbose,
                        server_port,
                        secrets,
                        timeout_ms,
                        _shared_http,
                        cluster_ctx,
                    )
                    _record_result(test_case, result)

        _run_plaintext_checks(spec, data_dir, dry_run, verbose, summary, failure_file, spec_path)

    finally:
        if _shared_http is not None:
            try:
                _shared_http.close()
            except Exception:
                pass

        signal.signal(signal.SIGINT, original_sigint)
        signal.signal(signal.SIGTERM, original_sigterm)

        if cluster_state is not None:
            stop_cluster(cluster_state, verbose=verbose, cleanup_data=True)

        if server_state.process:
            stop_server(server_state.process, verbose=verbose)

        if data_dir and spec.mode == "server":
            has_plaintext_checks = any(getattr(t, "plaintext_checks", None) for t in spec.tests)
            if not has_plaintext_checks:
                import shutil

                try:
                    shutil.rmtree(data_dir, ignore_errors=True)
                except Exception:
                    pass

        if single_server_cert_dir is not None:
            import shutil

            shutil.rmtree(single_server_cert_dir, ignore_errors=True)

    summary_dict = _finalize_summary(summary, start_time, report_json, spec_path)

    exit_code = 0 if summary.failed == 0 else 1
    return exit_code, summary_dict
