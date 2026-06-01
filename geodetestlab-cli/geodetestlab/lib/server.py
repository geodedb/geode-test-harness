"""Server lifecycle management for geodetestlab.

Handles starting, stopping, and monitoring Geode server processes
for test execution.
"""

from __future__ import annotations

import atexit
import logging
import os
import signal
import socket
import subprocess
import tempfile
import time

from .runner_types import DEFAULT_ADMIN_PASSWORD

logger = logging.getLogger(__name__)

# Global list to track server processes for cleanup on exit
_active_servers: list[subprocess.Popen[str]] = []


class ServerError(Exception):
    """Raised when a server operation fails."""


def cleanup_servers() -> None:
    """Clean up any active server processes on exit."""
    for process in _active_servers[:]:  # Copy list to avoid modification during iteration
        try:
            if process.poll() is None:  # Still running
                # Kill the entire process group first (for servers started with start_new_session)
                try:
                    pgid = os.getpgid(process.pid)
                    os.killpg(pgid, signal.SIGTERM)
                    time.sleep(0.5)
                    os.killpg(pgid, signal.SIGKILL)
                except (OSError, ProcessLookupError):
                    pass
                # Then kill the process directly as fallback
                process.terminate()
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    process.kill()
                    try:
                        process.wait(timeout=1)
                    except subprocess.TimeoutExpired:
                        pass
        except Exception:
            pass
    _active_servers.clear()


def kill_stale_servers() -> None:
    """Kill any stale Geode servers from previous test runs.

    Uses a scoped pattern that only matches servers started with a
    ``geode-test-`` temp directory to avoid killing unrelated processes.
    """
    try:
        subprocess.run(
            ["pkill", "-f", "geode serve.*geode-test-"],
            capture_output=True,
            timeout=5,
        )
        time.sleep(0.5)  # Give processes time to terminate
    except Exception:
        pass


# Register cleanup handler
atexit.register(cleanup_servers)


def _port_is_bound(port: int, sock_type: int) -> bool:
    """Check if a port is bound by attempting to bind to it.

    If the bind fails with EADDRINUSE, the port is in use (server is listening).
    This is a zero-cost alternative to spawning ss/netstat subprocesses.

    NOTE: Do NOT use SO_REUSEADDR here — it allows re-binding to an
    already-bound UDP port on Linux, which defeats the detection.
    """
    try:
        with socket.socket(socket.AF_INET, sock_type) as s:
            s.bind(("127.0.0.1", port))
            return False  # We could bind → port is free, server not ready
    except OSError:
        return True  # Port in use → server is listening


def start_server(
    binary: str,
    data_dir: os.PathLike[str],
    port: int,
    env: dict[str, str],
    args: list[str],
    timeout_ms: int,
    verbose: bool,
    grpc_port: int | None = None,
) -> subprocess.Popen[str]:
    """Start a Geode server process.

    Returns the server process handle. Raises ``ServerError`` if the
    server fails to start within the given timeout.
    """
    use_grpc_only = grpc_port is not None and env.get("GEODE_TRANSPORT") == "grpc"
    cmd = [
        binary,
        "serve",
        "--data-dir",
        str(data_dir),
        "--log-level",
        "info" if verbose else "warn",
    ]
    if not use_grpc_only:
        cmd.extend(["--listen", f"127.0.0.1:{port}"])
    if grpc_port:
        cmd.extend(["--listen-grpc", f"127.0.0.1:{grpc_port}"])
    cmd.extend(args)

    # Set environment variables for testing.
    # These flags weaken security and MUST NOT be used in production.
    # Guard: only set if not explicitly overridden by the caller.
    if os.environ.get("GEODE_DISABLE_AUDIT_GUARD") != "0":
        env.setdefault("GEODE_DISABLE_AUDIT", "1")
    else:
        logger.info("GEODE_DISABLE_AUDIT_GUARD=0: audit logging NOT disabled")
    if os.environ.get("GEODE_ALLOW_NO_AUTH_GUARD") != "0":
        env.setdefault("GEODE_ALLOW_NO_AUTH", "1")
    else:
        logger.info("GEODE_ALLOW_NO_AUTH_GUARD=0: auth bypass NOT enabled")
    # Set a known admin password for testing (used by query commands)
    env.setdefault("GEODE_ADMIN_PASSWORD", DEFAULT_ADMIN_PASSWORD)
    if use_grpc_only:
        # The CLI gRPC query path is plaintext HTTP/2 in Debug builds, so
        # the harness opts the server into matching plaintext mode for gRPC runs.
        env.setdefault("GEODE_GRPC_ALLOW_PLAINTEXT_FALLBACK", "1")

    if verbose:
        print(f"Starting server: {' '.join(cmd)}")

    # Start server process - use start_new_session to create a new process group
    # This allows us to kill the entire group if needed.
    #
    # Capture the server's stdout/stderr to a real temp FILE rather than an
    # in-memory subprocess.PIPE. Readiness below uses a socket-bind probe, so
    # the harness never reads these streams during the server's lifetime — and
    # an undrained PIPE deadlocks the server once it writes past the ~64KB OS
    # pipe buffer: the server blocks in writev() on stderr while holding the
    # process-global stderr lock, and any geode thread that logs while holding
    # a data lock (e.g. graph_storage_adapter.createGraphLocked's per-graph
    # "created graph" std.log line) then stalls — observed as
    # gql_catalog_operations_comprehensive.yml hanging 30s per DDL at
    # --log-level info (verbose runs, which inherit the terminal and have no
    # pipe, never reproduce it). A regular file never backpressures, so the
    # server can never block on logging. The file is unlinked immediately
    # (TemporaryFile) and reaped when the server's fd closes.
    # Intentionally not a context manager (ruff SIM115): the file must stay
    # open for the server process's whole lifetime (reaped when its fd closes).
    server_log = tempfile.TemporaryFile(mode="w+") if not verbose else None  # noqa: SIM115
    process = subprocess.Popen(
        cmd,
        env=env,
        stdout=server_log if server_log is not None else None,
        stderr=subprocess.STDOUT if server_log is not None else None,
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
            output = ""
            if server_log is not None:
                try:
                    server_log.seek(0)
                    output = server_log.read()
                except Exception:
                    output = "<server log unavailable>"
            else:
                # verbose path inherits the terminal; nothing captured here
                output = "<see terminal output above>"
            raise ServerError(f"Server exited unexpectedly with code {process.returncode}\n{output}")

        # Check if port is bound using zero-cost socket bind probe
        # (replaces subprocess-based ss/netstat polling — PERF-002)
        quic_ready = use_grpc_only or _port_is_bound(port, socket.SOCK_DGRAM)  # UDP for QUIC
        grpc_ready = grpc_port is None or _port_is_bound(grpc_port, socket.SOCK_STREAM)  # TCP for gRPC

        if quic_ready and grpc_ready:
            if verbose:
                msg = f"Server ready on port {port}"
                if grpc_port:
                    msg += f" (gRPC on {grpc_port})"
                print(msg)
            return process

        time.sleep(0.1)

    process.terminate()
    raise ServerError(f"Server failed to start within {timeout_s} seconds")


def stop_server(process: subprocess.Popen[str], verbose: bool = False) -> None:
    """Stop a Geode server process."""
    if verbose:
        print("Stopping server...")

    # Remove from tracking list
    if process in _active_servers:
        _active_servers.remove(process)

    try:
        # Try to get the process group ID (server was started with start_new_session=True)
        try:
            pgid = os.getpgid(process.pid)
        except (OSError, ProcessLookupError):
            pgid = None

        # Try graceful termination of process group first
        if pgid:
            try:
                os.killpg(pgid, signal.SIGTERM)
            except (OSError, ProcessLookupError):
                pass

        # Also terminate the main process
        process.terminate()
        try:
            # 2026-04-27: bumped from 3s -> 35s.  Geode's shutdown
            # deinit chain (graph_store flush + persistence thread join,
            # per-shard checkpoint flush, ShardedGraphEngine.close which
            # waits up to 5s for its shared thread-pool to drain, then
            # per-shard wal/manifest sync) measured ~29s on a clean run
            # with three medium nodes; FLE-stress with 4-32KB encrypted
            # writes can legitimately take longer.  Earlier we used 12s
            # which still left WAL in a non-checkpointed state on
            # `restart_server: true` (lost data → false test failures
            # `regression_issue_539_wal_recovery_checkpoint.yml`,
            # `fle_large_data_stress_verification.yml`).  35s is
            # generous enough for any legitimate flush; truly hung
            # servers still fall through to the SIGKILL path below.
            process.wait(timeout=35)
        except subprocess.TimeoutExpired:
            if verbose:
                print("Force killing server...")
            # Force kill the entire process group
            if pgid:
                try:
                    os.killpg(pgid, signal.SIGKILL)
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


def untrack_server(process: subprocess.Popen[str]) -> None:
    """Remove a server process from the active tracking list."""
    if process in _active_servers:
        _active_servers.remove(process)
