"""Server lifecycle management for geodetestlab.

Handles starting, stopping, and monitoring Geode server processes
for test execution.
"""

from __future__ import annotations

import atexit
import logging
import os
import signal
import subprocess
import time

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
DEFAULT_ADMIN_PASSWORD = os.environ.get("GEODE_ADMIN_PASSWORD", "GeodeTestPassword123!")

# Global list to track server processes for cleanup on exit
_active_servers: list[subprocess.Popen] = []


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
    """Kill any stale Geode servers from previous runs."""
    try:
        subprocess.run(["pkill", "-f", "geode serve"], capture_output=True, timeout=5)
        time.sleep(0.5)  # Give processes time to terminate
    except Exception:
        pass


# Register cleanup handler
atexit.register(cleanup_servers)


def start_server(
    binary: str,
    data_dir: os.PathLike[str],
    port: int,
    env: dict[str, str],
    args: list[str],
    timeout_ms: int,
    verbose: bool,
    grpc_port: int | None = None,
) -> subprocess.Popen:
    """Start a Geode server process.

    Returns the server process handle. Raises ``ServerError`` if the
    server fails to start within the given timeout.
    """
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
    if grpc_port:
        cmd.extend(["--listen-grpc", f"127.0.0.1:{grpc_port}"])
    cmd.extend(args)

    # Set environment variables for testing
    # Disable audit logging (avoids signing key requirements)
    env["GEODE_DISABLE_AUDIT"] = "1"
    # Allow auth to be disabled in release builds for testing
    env["GEODE_ALLOW_NO_AUTH"] = "1"
    # Set a known admin password for testing (used by query commands)
    env["GEODE_ADMIN_PASSWORD"] = DEFAULT_ADMIN_PASSWORD

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
            raise ServerError(
                f"Server exited unexpectedly with code {process.returncode}\nstdout: {stdout}\nstderr: {stderr}"
            )

        # Check if port is bound (try ss first, then netstat as fallback)
        quic_ready = False
        grpc_ready = grpc_port is None  # If no gRPC, consider it ready
        try:
            # Check QUIC (UDP) port
            result = subprocess.run(
                ["ss", "-uln"],
                capture_output=True,
                text=True,
                timeout=1.0,
            )
            if result.returncode == 0 and f":{port}" in result.stdout:
                quic_ready = True

            # Check gRPC (TCP) port if needed
            if grpc_port and not grpc_ready:
                result = subprocess.run(
                    ["ss", "-tln"],
                    capture_output=True,
                    text=True,
                    timeout=1.0,
                )
                if result.returncode == 0 and f":{grpc_port}" in result.stdout:
                    grpc_ready = True

            if quic_ready and grpc_ready:
                if verbose:
                    msg = f"Server ready on port {port}"
                    if grpc_port:
                        msg += f" (gRPC on {grpc_port})"
                    print(msg)
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
    raise ServerError(f"Server failed to start within {timeout_s} seconds")


def stop_server(process: subprocess.Popen, verbose: bool = False) -> None:
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
            process.wait(timeout=3)
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


def untrack_server(process: subprocess.Popen) -> None:
    """Remove a server process from the active tracking list."""
    if process in _active_servers:
        _active_servers.remove(process)
