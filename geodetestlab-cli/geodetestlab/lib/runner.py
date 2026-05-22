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
from .runner_types import DEFAULT_ADMIN_PASSWORD, RunnerError, RunSummary, TestResult
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
) -> subprocess.Popen[str] | None:
    if dry_run:
        return None
    MAX_PORT_RETRIES = 3
    last_error: Exception | None = None
    for attempt in range(MAX_PORT_RETRIES):
        try:
            return start_server(
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
        if isinstance(setup_item, dict):
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
            if not result.passed and verbose:
                print(f"    Error: {result.error}")


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
        if isinstance(setup_item, dict):
            setup_case = TestCase.from_dict(
                {
                    "name": f"setup-{i}",
                    "description": "Setup query (replay)",
                    **setup_item,
                }
            )
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
    summary = RunSummary()
    start_time = time.time()

    if spec.default_timeout_ms > 0:
        timeout_ms = max(timeout_ms, spec.default_timeout_ms)

    try:
        binary = find_geode_binary(geode_binary)
    except FileNotFoundError as e:
        raise RunnerError(str(e)) from e

    env = os.environ.copy()
    env.update(env_overrides)
    env.update(spec.env)

    data_dir = None
    server_state = ServerState(process=None, port=0, grpc_port=None)
    cluster_state: ClusterState | None = None
    cluster_ctx: ClusterControlContext | None = None

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
                            break
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

        _run_plaintext_checks(spec, data_dir, dry_run, verbose, summary)

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

    summary.duration_ms = (time.time() - start_time) * 1000

    summary_dict = summary.to_dict()
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
    summary_dict["results"] = results_list

    _generate_report(report_json, summary, spec_path, results_list)

    exit_code = 0 if summary.failed == 0 else 1
    return exit_code, summary_dict
