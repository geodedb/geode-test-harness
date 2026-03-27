"""Shared server lifecycle management for geode-test-harness.

This module provides functionality to start, manage, and stop Geode server
instances for testing purposes. It is shared between different test runners
(shell_runner, geodetestlab) to enable consistent server management.
"""

from __future__ import annotations

import os
import signal
import socket
import subprocess
import tempfile
import time
from typing import Dict, Optional

from .utils import get_free_port

# Default admin password for testing
DEFAULT_ADMIN_PASSWORD = "GeodeTestPassword123!"


class ServerManager:
    """Manages a Geode server instance for testing.

    This class provides server lifecycle management with automatic port
    allocation and data directory isolation for parallel test execution.

    Usage:
        # As context manager (recommended)
        with ServerManager(binary_path="/path/to/geode") as server:
            address = f"127.0.0.1:{server.port}"
            # run tests...

        # Manual management
        server = ServerManager(binary_path="/path/to/geode")
        address = server.start()
        # run tests...
        server.stop()
    """

    def __init__(
        self,
        binary_path: str,
        port: Optional[int] = None,
        grpc_port: Optional[int] = None,
        data_dir: Optional[str] = None,
        startup_timeout_ms: int = 60000,
        cleanup: bool = True,
        args: Optional[list] = None,
        env: Optional[Dict[str, str]] = None,
        verbose: bool = False,
        admin_password: Optional[str] = None,
    ):
        """Initialize the server manager.

        Parameters
        ----------
        binary_path : str
            Path to the geode binary
        port : Optional[int]
            QUIC port to bind the server to (auto-allocated if None)
        grpc_port : Optional[int]
            gRPC port to bind the server to (disabled if None)
        data_dir : Optional[str]
            Data directory for the server (temporary if None)
        startup_timeout_ms : int
            Maximum time to wait for server startup
        cleanup : bool
            Whether to cleanup data directory on shutdown
        args : Optional[list]
            Additional arguments to pass to the server
        env : Optional[Dict[str, str]]
            Environment variables to set for the server process
        verbose : bool
            Whether to print server logs
        admin_password : Optional[str]
            Admin password for authentication (uses default if None)
        """
        self.binary_path = binary_path
        self.port = port or get_free_port()
        self.grpc_port = grpc_port
        self.data_dir = data_dir
        self.startup_timeout_ms = startup_timeout_ms
        self.cleanup = cleanup
        self.args = args or []
        self.env = env or {}
        self.verbose = verbose
        self.admin_password = admin_password or DEFAULT_ADMIN_PASSWORD
        self.process: Optional[subprocess.Popen] = None
        self._temp_dir: Optional[tempfile.TemporaryDirectory] = None

    @property
    def address(self) -> str:
        """Return the QUIC server address (host:port)."""
        return f"127.0.0.1:{self.port}"

    @property
    def grpc_address(self) -> Optional[str]:
        """Return the gRPC server address (host:port), or None if gRPC is disabled."""
        return f"127.0.0.1:{self.grpc_port}" if self.grpc_port else None

    def start(self) -> str:
        """Start the Geode server.

        Returns
        -------
        str
            The QUIC server address (host:port)

        Raises
        ------
        RuntimeError
            If the server fails to start
        """
        # Setup data directory
        if self.data_dir is None:
            self._temp_dir = tempfile.TemporaryDirectory(prefix="geode_test_")
            self.data_dir = self._temp_dir.name

        # Prepare server command
        cmd = [
            self.binary_path,
            "serve",
            "--listen",
            f"127.0.0.1:{self.port}",
            "--data-dir",
            self.data_dir,
        ]

        # Add gRPC port if specified
        if self.grpc_port:
            cmd.extend(["--listen-grpc", f"127.0.0.1:{self.grpc_port}"])

        cmd.extend(self.args)

        # Prepare environment
        server_env = os.environ.copy()
        server_env.update(self.env)

        # Disable audit logging for testing (avoids signing key requirements)
        server_env["GEODE_DISABLE_AUDIT"] = "1"

        # Set admin password for testing authentication
        server_env["GEODE_ADMIN_PASSWORD"] = self.admin_password

        # Start the server process
        try:
            stdout = None if self.verbose else subprocess.DEVNULL
            stderr = None if self.verbose else subprocess.DEVNULL

            self.process = subprocess.Popen(
                cmd,
                stdout=stdout,
                stderr=stderr,
                env=server_env,
                preexec_fn=os.setsid if os.name != "nt" else None,
            )
        except FileNotFoundError:
            raise RuntimeError(f"Geode binary not found: {self.binary_path}")
        except Exception as e:
            raise RuntimeError(f"Failed to start server: {e}")

        # Wait for server to become ready
        server_address = self.address
        timeout_seconds = self.startup_timeout_ms / 1000
        start_time = time.time()

        while time.time() - start_time < timeout_seconds:
            # Check if process is still running
            if self.process.poll() is not None:
                raise RuntimeError(
                    f"Server process exited with code {self.process.returncode}"
                )

            # Try to connect to the server port
            # QUIC servers listen on UDP, so we check if the port is bound
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                    s.settimeout(1)
                    # Try to bind to the same port - if it fails, the server has it
                    try:
                        s.bind(("127.0.0.1", self.port))
                        # If we could bind, server hasn't started listening yet
                        s.close()
                    except OSError:
                        # Port is in use - server is listening
                        # Brief pause for server to complete initialization
                        time.sleep(0.1)
                        # Verify process is still running after the delay
                        if self.process.poll() is not None:
                            raise RuntimeError(
                                f"Server process exited with code {self.process.returncode}"
                            )
                        return server_address
            except (socket.timeout, OSError):
                pass

            time.sleep(0.1)

        # Timeout reached
        self.stop()
        raise RuntimeError(f"Server failed to start within {timeout_seconds}s")

    def stop(self):
        """Stop the Geode server and cleanup resources."""
        if self.process:
            try:
                # Try graceful shutdown first
                if os.name != "nt":
                    os.killpg(os.getpgid(self.process.pid), signal.SIGTERM)
                else:
                    self.process.terminate()

                # Wait for process to exit
                try:
                    self.process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    # Force kill if graceful shutdown fails
                    if os.name != "nt":
                        os.killpg(os.getpgid(self.process.pid), signal.SIGKILL)
                    else:
                        self.process.kill()
                    self.process.wait()
            except Exception:
                pass

            self.process = None

        # Cleanup temporary directory
        if self.cleanup and self._temp_dir:
            try:
                self._temp_dir.cleanup()
            except Exception:
                pass
            self._temp_dir = None

    def is_running(self) -> bool:
        """Check if the server is currently running."""
        return self.process is not None and self.process.poll() is None

    def __enter__(self):
        """Context manager entry."""
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.stop()
