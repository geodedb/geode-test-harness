"""Geode server lifecycle management.

This module provides the ServerManager class for starting, monitoring, and
stopping Geode server instances during testing. It handles server readiness
detection, port allocation, data directory management, and cleanup.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import psutil

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.utils import find_geode_binary, get_free_port


class ServerManagerDisabled:
    """Manages a Geode server instance for testing."""

    @staticmethod
    def generate_test_certificates(cert_dir: Path) -> tuple[Path, Path, Path]:
        """Generate test certificates for TLS.

        Returns
        -------
        tuple[Path, Path, Path]
            CA certificate, server certificate, and server key paths.
        """
        cert_dir = Path(cert_dir)
        cert_dir.mkdir(parents=True, exist_ok=True)

        ca_key = cert_dir / "ca-key.pem"
        ca_cert = cert_dir / "ca-cert.pem"
        server_key = cert_dir / "server-key.pem"
        server_cert = cert_dir / "server-cert.pem"
        server_csr = cert_dir / "server.csr"
        server_conf = cert_dir / "server.conf"

        # Generate CA private key
        subprocess.run(["openssl", "genrsa", "-out", str(ca_key), "2048"], check=True, capture_output=True)

        # Generate CA certificate
        subprocess.run(
            [
                "openssl",
                "req",
                "-new",
                "-x509",
                "-days",
                "365",
                "-key",
                str(ca_key),
                "-out",
                str(ca_cert),
                "-subj",
                "/C=US/ST=Test/L=Test/O=Geode Test/CN=Geode Test CA",
            ],
            check=True,
            capture_output=True,
        )

        # Generate server private key
        subprocess.run(["openssl", "genrsa", "-out", str(server_key), "2048"], check=True, capture_output=True)

        # Create server config file
        server_conf.write_text("""[req]
distinguished_name = req_distinguished_name
req_extensions = v3_req
prompt = no

[req_distinguished_name]
C = US
ST = Test
L = Test
O = Geode Test
CN = 127.0.0.1

[v3_req]
keyUsage = keyEncipherment, dataEncipherment
extendedKeyUsage = serverAuth
subjectAltName = @alt_names

[alt_names]
DNS.1 = localhost
IP.1 = 127.0.0.1
""")

        # Generate server certificate signing request
        subprocess.run(
            [
                "openssl",
                "req",
                "-new",
                "-key",
                str(server_key),
                "-out",
                str(server_csr),
                "-subj",
                "/C=US/ST=Test/L=Test/O=Geode Test/CN=127.0.0.1",
            ],
            check=True,
            capture_output=True,
        )

        # Generate server certificate signed by CA
        subprocess.run(
            [
                "openssl",
                "x509",
                "-req",
                "-in",
                str(server_csr),
                "-CA",
                str(ca_cert),
                "-CAkey",
                str(ca_key),
                "-CAcreateserial",
                "-out",
                str(server_cert),
                "-days",
                "365",
                "-extensions",
                "v3_req",
                "-extfile",
                str(server_conf),
            ],
            check=True,
            capture_output=True,
        )

        return ca_cert, server_cert, server_key

    def __init__(
        self,
        *,
        geode_binary: Optional[str] = None,
        port: Optional[int] = None,
        data_dir: Optional[Path] = None,
        timeout_ms: int = 60000,
        verbose: bool = False,
        extra_args: Optional[List[str]] = None,
        env_overrides: Optional[Dict[str, str]] = None,
    ):
        """Initialize the server manager.

        Parameters
        ----------
        geode_binary:
            Path to the Geode binary. Auto-detected if None.
        port:
            Port to bind the server to. Auto-allocated if None.
        data_dir:
            Data directory for the server. Temporary if None.
        timeout_ms:
            Startup timeout in milliseconds.
        verbose:
            Whether to show server output.
        extra_args:
            Additional arguments to pass to the server.
        env_overrides:
            Environment variables to set for the server process.
        """
        self.binary = find_geode_binary(geode_binary)
        self.port = port or get_free_port()
        self.timeout_ms = timeout_ms
        self.verbose = verbose
        self.extra_args = extra_args or []
        self.env_overrides = env_overrides or {}

        # Data directory management
        self._temp_data_dir = data_dir is None
        if data_dir is None:
            self.data_dir = Path(tempfile.mkdtemp(prefix="geode-test-"))
        else:
            self.data_dir = Path(data_dir)
            self.data_dir.mkdir(parents=True, exist_ok=True)

        # Generate test certificates
        self.ca_cert, self.server_cert, self.server_key = self.generate_test_certificates(self.data_dir / "certs")

        # Process management
        self.process: Optional[subprocess.Popen] = None
        self._ready = False

    def start(self) -> None:
        """Start the Geode server and wait for it to be ready.

        Raises
        ------
        RuntimeError
            If the server fails to start or become ready within timeout.
        """
        if self.process is not None:
            raise RuntimeError("Server is already running")

        # Build command line
        cmd = [
            self.binary,
            "serve",
            "--data-dir",
            str(self.data_dir),
            "--listen",
            f"127.0.0.1:{self.port}",
            "--cert",
            str(self.server_cert),
            "--key",
            str(self.server_key),
            "--log-level",
            "info",
        ]

        # Add extra arguments
        cmd.extend(self.extra_args)

        if self.verbose:
            print(f"Starting Geode server: {' '.join(cmd)}")

        # Prepare environment
        env = os.environ.copy()
        env.update(self.env_overrides)

        # Start the process
        try:
            self.process = subprocess.Popen(
                cmd,
                cwd=self.data_dir.parent,
                env=env,
                stdout=subprocess.PIPE if not self.verbose else None,
                stderr=subprocess.PIPE if not self.verbose else None,
                text=True,
            )
            self._start_time = time.time()
        except Exception as exc:
            raise RuntimeError(f"Failed to start server process: {exc}")

        # Wait for server to become ready
        self._wait_for_ready()

    def stop(self) -> None:
        """Stop the server gracefully."""
        if self.process is None:
            return

        if self.verbose:
            print(f"Stopping Geode server (PID: {self.process.pid})")

        # Try graceful shutdown first
        try:
            self.process.terminate()
            self.process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            # Force kill if graceful shutdown times out
            if self.verbose:
                print("Graceful shutdown timed out, force killing")
            self.process.kill()
            self.process.wait(timeout=5)
        except Exception as exc:
            if self.verbose:
                print(f"Error during shutdown: {exc}")

        self.process = None
        self._ready = False

        # Cleanup temporary data directory
        if self._temp_data_dir and self.data_dir.exists():
            try:
                shutil.rmtree(self.data_dir)
            except Exception as exc:
                if self.verbose:
                    print(f"Warning: Failed to cleanup data directory: {exc}")

    def wait(self) -> int:
        """Wait for the server process to exit.

        Returns
        -------
        int
            The exit code of the server process.
        """
        if self.process is None:
            raise RuntimeError("No server process is running")

        return self.process.wait()

    def is_ready(self) -> bool:
        """Check if the server is ready to accept connections."""
        return self._ready and self.is_running()

    def is_running(self) -> bool:
        """Check if the server process is still running."""
        if self.process is None:
            return False
        return self.process.poll() is None

    def get_connection_string(self) -> str:
        """Get the connection string for this server."""
        return f"127.0.0.1:{self.port}"

    def _wait_for_ready(self) -> None:
        """Wait for the server to become ready to accept connections."""
        start_time = time.time()
        timeout_seconds = self.timeout_ms / 1000.0

        while time.time() - start_time < timeout_seconds:
            # Check if process is still running
            if not self.is_running():
                # Capture any error output
                stdout, stderr = "", ""
                if self.process and not self.verbose:
                    try:
                        stdout, stderr = self.process.communicate(timeout=1)
                    except subprocess.TimeoutExpired:
                        pass

                raise RuntimeError(
                    f"Server process exited unexpectedly (exit code: {self.process.returncode})\n"
                    f"stdout: {stdout}\nstderr: {stderr}"
                )

            # Check if port is accepting connections
            if self._check_port_ready():
                self._ready = True
                if self.verbose:
                    print(f"Server ready on port {self.port}")
                return

            time.sleep(0.1)

        # Timeout reached
        if self.process:
            self.process.terminate()
        raise RuntimeError(f"Server failed to become ready within {timeout_seconds} seconds")

    def _check_port_ready(self) -> bool:
        """Check if the server is ready by checking process stability and port binding."""
        try:
            # Check if process has been running for a reasonable time and port is bound
            if hasattr(self, "_start_time") and time.time() - self._start_time > 2.0:
                # Check if UDP port is bound (QUIC uses UDP)
                result = subprocess.run(["netstat", "-uln"], capture_output=True, text=True, timeout=1.0)
                if result.returncode == 0:
                    port_bound = f":{self.port}" in result.stdout
                    if port_bound and self.is_running():
                        return True
            return False
        except Exception:
            # Final fallback: just check if process is running for enough time
            if hasattr(self, "_start_time"):
                return time.time() - self._start_time > 4.0 and self.is_running()
            return False

    @staticmethod
    def stop_by_port(port: int, force: bool = False) -> bool:
        """Stop a Geode server running on the specified port.

        Parameters
        ----------
        port:
            Port number of the server to stop.
        force:
            Whether to force kill the process.

        Returns
        -------
        bool
            True if a server was found and stopped, False otherwise.
        """
        servers = ServerManager.list_servers(port)
        if not servers:
            return False

        for server in servers:
            pid = server["pid"]
            try:
                process = psutil.Process(pid)
                if force:
                    process.kill()
                else:
                    process.terminate()
                    # Wait a bit for graceful shutdown
                    try:
                        process.wait(timeout=10)
                    except psutil.TimeoutExpired:
                        process.kill()
                return True
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

        return False

    @staticmethod
    def list_servers(port: Optional[int] = None) -> List[Dict[str, Any]]:
        """List running Geode server processes.

        Parameters
        ----------
        port:
            If specified, only return servers on this port.

        Returns
        -------
        List[Dict[str, Any]]
            List of server information dictionaries.
        """
        servers = []

        for proc in psutil.process_iter(["pid", "name", "cmdline"]):
            try:
                # Look for processes that might be Geode servers
                cmdline = proc.info["cmdline"] or []
                if len(cmdline) < 2:
                    continue

                # Check if this looks like a Geode server process
                if not (("geode" in cmdline[0].lower() or "geoded" in cmdline[0].lower()) and "serve" in cmdline):
                    continue

                # Extract port from command line
                server_port = None
                for i, arg in enumerate(cmdline):
                    if arg == "--listen" and i + 1 < len(cmdline):
                        listen_addr = cmdline[i + 1]
                        if ":" in listen_addr:
                            try:
                                server_port = int(listen_addr.split(":")[-1])
                            except ValueError:
                                continue
                        break

                # Filter by port if specified
                if port is not None and server_port != port:
                    continue

                # Extract data directory
                data_dir = None
                for i, arg in enumerate(cmdline):
                    if arg == "--data-dir" and i + 1 < len(cmdline):
                        data_dir = cmdline[i + 1]
                        break

                servers.append(
                    {
                        "pid": proc.info["pid"],
                        "port": server_port,
                        "status": "running",
                        "data_dir": data_dir,
                        "cmdline": cmdline,
                    }
                )

            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue

        return servers

    def __enter__(self):
        """Context manager entry."""
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.stop()
