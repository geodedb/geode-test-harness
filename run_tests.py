#!/usr/bin/env python3
"""
Unified test runner for all Geode client libraries.

Runs identical test specifications across Zig, Go, Rust, and Python clients
to ensure feature parity and correctness.
"""

import argparse
import asyncio
import atexit
import json
import os
import random
import signal
import socket
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

import yaml


class IndentedDumper(yaml.Dumper):
    """Custom YAML dumper that properly indents list items."""
    def increase_indent(self, flow=False, indentless=False):
        return super(IndentedDumper, self).increase_indent(flow, False)

    def represent_str(self, data):
        """Represent strings using appropriate YAML scalar style.

        - Multi-line strings: literal block scalar (|)
        - Other strings: default (usually plain or single-quoted)
        """
        if '\n' in data:
            # Use literal block scalar for multi-line strings
            return self.represent_scalar('tag:yaml.org,2002:str', data, style='|')
        return self.represent_scalar('tag:yaml.org,2002:str', data)

# Register the custom string representer
IndentedDumper.add_representer(str, IndentedDumper.represent_str)


def derive_status_from_summary(result: Dict[str, Any]) -> str:
    """Determine overall status from runner JSON summary."""
    summary = result.get("summary", {})
    errors = summary.get("errors", 0)
    failed = summary.get("failed", 0)
    if errors and errors > 0:
        return "error"
    if failed and failed > 0:
        return "failed"
    return "passed"


@dataclass
class TestResult:
    """Result of a single test execution."""

    test_name: str
    client: str
    status: str  # "passed", "failed", "skipped", "error"
    duration_ms: float
    error_message: Optional[str] = None
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass
class TestSummary:
    """Summary of test run for a client."""

    client: str
    total: int = 0
    passed: int = 0
    failed: int = 0
    skipped: int = 0
    errors: int = 0
    duration_ms: float = 0.0


class GeodeServerManager:
    """Manages Geode server instances with dynamic port allocation."""

    # Class-level tracking of used ports to prevent collisions
    _used_ports: Set[int] = set()
    _all_servers: List['GeodeServerManager'] = []

    def __init__(self, geode_binary: Optional[Path] = None, verbose: bool = False):
        self.geode_binary = geode_binary or self._find_geode_binary()
        self.verbose = verbose
        self.port: Optional[int] = None
        self.process: Optional[asyncio.subprocess.Process] = None
        self.log_file: Optional[Path] = None
        self.data_dir: Optional[Path] = None
        self._cleanup_registered = False

        # Register this instance for cleanup
        GeodeServerManager._all_servers.append(self)

    def _find_geode_binary(self) -> Path:
        """Find the geode binary."""
        # Try relative to test harness
        candidates = [
            Path(__file__).parent.parent.parent / "zig-out" / "bin" / "geode",
            Path.cwd() / "zig-out" / "bin" / "geode",
            Path.cwd().parent.parent / "zig-out" / "bin" / "geode",
        ]

        for candidate in candidates:
            if candidate.exists():
                return candidate

        raise FileNotFoundError("Could not find geode binary")

    def _find_free_port(self) -> int:
        """Find an available port in the ephemeral range."""
        max_attempts = 100
        for _ in range(max_attempts):
            # Use ephemeral port range (49152-65535)
            port = random.randint(49152, 65535)

            # Check if port is already used by this test run
            if port in GeodeServerManager._used_ports:
                continue

            # Try to bind to the port to verify it's available
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                    s.bind(('localhost', port))
                    # Port is available
                    GeodeServerManager._used_ports.add(port)
                    return port
            except OSError:
                # Port is in use, try another
                continue

        raise RuntimeError(f"Could not find free port after {max_attempts} attempts")

    async def start(self) -> str:
        """Start the Geode server and return the server address."""
        if self.process is not None:
            raise RuntimeError("Server is already running")

        # Allocate a unique port
        self.port = self._find_free_port()

        # Create log file in temp directory
        self.log_file = Path(tempfile.mktemp(prefix=f"geode_server_{self.port}_", suffix=".log"))

        # Create temporary data directory for test isolation
        self.data_dir = Path(tempfile.mkdtemp(prefix=f"geode_data_{self.port}_"))

        listen_addr = f"localhost:{self.port}"

        # Certificate paths for TLS
        cert_dir = Path(__file__).parent / "certs"
        cert_path = cert_dir / "server.crt"
        key_path = cert_dir / "server.key"

        if self.verbose:
            print(f"Starting Geode server on {listen_addr}")
            print(f"Server log: {self.log_file}")
            print(f"Server data: {self.data_dir}")
            print(f"Server cert: {cert_path}")
            print(f"Server key: {key_path}")

        # Start server process with isolated data directory
        log_fd = open(self.log_file, 'w')
        self.process = await asyncio.create_subprocess_exec(
            str(self.geode_binary),
            "serve",
            "--listen",
            listen_addr,
            "--data-dir",
            str(self.data_dir),
            "--cert",
            str(cert_path),
            "--key",
            str(key_path),
            stdout=log_fd,
            stderr=asyncio.subprocess.STDOUT,
        )

        # Register cleanup on exit
        if not self._cleanup_registered:
            atexit.register(self._emergency_cleanup)
            self._cleanup_registered = True

        # Wait for server to be ready
        await self._wait_for_server_ready()

        return listen_addr

    async def _wait_for_server_ready(self, timeout: float = 5.0):
        """Wait for server to be ready to accept connections."""
        start_time = time.time()

        # QUIC servers don't accept raw TCP connections, so we need to check the log
        # for the "Server ready" message instead
        while time.time() - start_time < timeout:
            # Check if server process is still alive
            if self.process.returncode is not None:
                # Server crashed
                log_content = ""
                if self.log_file and self.log_file.exists():
                    log_content = self.log_file.read_text()
                raise RuntimeError(
                    f"Server process exited with code {self.process.returncode}.\n"
                    f"Last 20 lines of log:\n{chr(10).join(log_content.splitlines()[-20:])}"
                )

            # Check log file for ready message
            if self.log_file and self.log_file.exists():
                try:
                    log_content = self.log_file.read_text()
                    if "Server ready" in log_content or "accepting QUIC connections" in log_content:
                        if self.verbose:
                            print(f"Server ready on port {self.port}")
                        return
                except Exception:
                    # Log file might be being written to
                    pass

            await asyncio.sleep(0.1)

        raise TimeoutError(f"Server did not become ready within {timeout} seconds")

    async def stop(self):
        """Stop the Geode server."""
        if self.process is None:
            return

        if self.verbose:
            print(f"Stopping Geode server on port {self.port}")

        # Try graceful shutdown first
        try:
            self.process.terminate()
            await asyncio.wait_for(self.process.wait(), timeout=5.0)
        except asyncio.TimeoutError:
            # Force kill if graceful shutdown times out
            if self.verbose:
                print(f"Server did not stop gracefully, force killing...")
            self.process.kill()
            await self.process.wait()

        # Release the port
        if self.port is not None:
            GeodeServerManager._used_ports.discard(self.port)
            self.port = None

        self.process = None

        # Clean up log file if verbose is off
        if not self.verbose and self.log_file and self.log_file.exists():
            try:
                self.log_file.unlink()
            except Exception:
                pass

        # Clean up data directory
        if self.data_dir and self.data_dir.exists():
            try:
                import shutil
                shutil.rmtree(self.data_dir)
            except Exception:
                pass

    def _emergency_cleanup(self):
        """Emergency cleanup called on exit."""
        if self.process and self.process.returncode is None:
            try:
                self.process.kill()
            except Exception:
                pass

    @classmethod
    async def cleanup_all(cls):
        """Clean up all server instances."""
        for server in cls._all_servers:
            try:
                await server.stop()
            except Exception as e:
                print(f"Error stopping server: {e}", file=sys.stderr)
        cls._all_servers.clear()
        cls._used_ports.clear()

    async def __aenter__(self):
        """Context manager support."""
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Context manager support."""
        await self.stop()


class ClientRunner:
    """Base class for language-specific test runners."""

    def __init__(self, client_name: str, server: str):
        self.client_name = client_name
        self.server = server

    async def run_test(self, spec: Dict[str, Any], test: Dict[str, Any]) -> TestResult:
        """Run a single test."""
        raise NotImplementedError

    async def setup(self) -> bool:
        """Setup runner (verify binary exists, etc.)."""
        return True

    async def teardown(self):
        """Cleanup after tests."""
        pass


class PythonRunner(ClientRunner):
    """Python client test runner."""

    def __init__(self, server: str):
        super().__init__("python", server)
        self.runner_path = Path(__file__).parent / "runners" / "python_runner.py"
        # Use venv Python if available
        venv_python = Path(__file__).parent.parent / "python" / "venv" / "bin" / "python3"
        self.python_exe = str(venv_python) if venv_python.exists() else sys.executable

    async def run_test(self, spec: Dict[str, Any], test: Dict[str, Any]) -> TestResult:
        start_time = time.time()

        try:
            # Create temporary test file
            test_spec = {
                "setup": spec.get("setup", []),
                "tests": [test],
                "cleanup": spec.get("cleanup", []),
            }
            test_file = Path("/tmp") / f"test_{test['name']}.yaml"
            test_file.write_text(yaml.dump(test_spec, Dumper=IndentedDumper, default_flow_style=False, sort_keys=False))

            # Run Python runner using venv Python
            proc = await asyncio.create_subprocess_exec(
                self.python_exe,
                str(self.runner_path),
                "--spec",
                str(test_file),
                "--server",
                self.server,
                "--json",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=test.get("timeout_ms", 30000) / 1000
            )

            duration_ms = (time.time() - start_time) * 1000

            # Parse result
            if stdout:
                try:
                    result = json.loads(stdout.decode())
                    status = derive_status_from_summary(result)
                    return TestResult(
                        test_name=test["name"],
                        client="python",
                        status=status,
                        duration_ms=duration_ms,
                        details=result,
                        error_message=stderr.decode() if status != "passed" and stderr else None,
                    )
                except json.JSONDecodeError:
                    pass

            if proc.returncode != 0:
                return TestResult(
                    test_name=test["name"],
                    client="python",
                    status="failed",
                    duration_ms=duration_ms,
                    error_message=stderr.decode(),
                )

            return TestResult(
                test_name=test["name"],
                client="python",
                status="error",
                duration_ms=duration_ms,
                error_message="Runner produced no output",
            )

        except asyncio.TimeoutError:
            return TestResult(
                test_name=test["name"],
                client="python",
                status="error",
                duration_ms=(time.time() - start_time) * 1000,
                error_message="Test timed out",
            )
        except Exception as e:
            return TestResult(
                test_name=test["name"],
                client="python",
                status="error",
                duration_ms=(time.time() - start_time) * 1000,
                error_message=str(e),
            )

    async def setup(self) -> bool:
        """Verify Python runner exists."""
        return self.runner_path.exists()


class GoRunner(ClientRunner):
    """Go client test runner."""

    def __init__(self, server: str):
        super().__init__("go", server)
        self.runner_path = Path(__file__).parent / "runners" / "go_runner"

    async def run_test(self, spec: Dict[str, Any], test: Dict[str, Any]) -> TestResult:
        start_time = time.time()

        try:
            # Create temporary test file
            test_spec = {
                "setup": spec.get("setup", []),
                "tests": [test],
                "cleanup": spec.get("cleanup", []),
            }
            test_file = Path("/tmp") / f"test_{test['name']}.yaml"
            test_file.write_text(yaml.dump(test_spec, Dumper=IndentedDumper, default_flow_style=False, sort_keys=False))

            # Run Go runner
            proc = await asyncio.create_subprocess_exec(
                str(self.runner_path),
                "-spec",
                str(test_file),
                "-server",
                self.server,
                "-json",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=test.get("timeout_ms", 30000) / 1000
            )

            duration_ms = (time.time() - start_time) * 1000

            if stdout:
                try:
                    result = json.loads(stdout.decode())
                    status = derive_status_from_summary(result)
                    return TestResult(
                        test_name=test["name"],
                        client="go",
                        status=status,
                        duration_ms=duration_ms,
                        details=result,
                        error_message=stderr.decode() if status != "passed" and stderr else None,
                    )
                except json.JSONDecodeError:
                    pass

            if proc.returncode != 0:
                return TestResult(
                    test_name=test["name"],
                    client="go",
                    status="failed",
                    duration_ms=duration_ms,
                    error_message=stderr.decode(),
                )

            return TestResult(
                test_name=test["name"],
                client="go",
                status="error",
                duration_ms=duration_ms,
                error_message="Runner produced no output",
            )

        except asyncio.TimeoutError:
            return TestResult(
                test_name=test["name"],
                client="go",
                status="error",
                duration_ms=(time.time() - start_time) * 1000,
                error_message="Test timed out",
            )
        except Exception as e:
            return TestResult(
                test_name=test["name"],
                client="go",
                status="error",
                duration_ms=(time.time() - start_time) * 1000,
                error_message=str(e),
            )

    async def setup(self) -> bool:
        """Build Go runner if needed."""
        runners_dir = Path(__file__).parent / "runners"
        go_file = runners_dir / "go_runner.go"

        # Check if go is available
        go_check = await asyncio.create_subprocess_exec(
            "which", "go",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await go_check.wait()

        if go_check.returncode != 0:
            print(f"Go not found - Go runner unavailable (install Go to enable)")
            return False

        if not self.runner_path.exists() and go_file.exists():
            print(f"Building Go runner...")
            # Initialize go.mod if needed
            go_mod = runners_dir / "go.mod"
            if not go_mod.exists():
                proc = await asyncio.create_subprocess_exec(
                    "go", "mod", "init",
                    "gitlab.com/devnw/geode/geode/clients/test-harness/runners",
                    cwd=str(runners_dir),
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                await proc.wait()

            # Get dependencies
            proc = await asyncio.create_subprocess_exec(
                "go", "mod", "tidy",
                cwd=str(runners_dir),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await proc.wait()

            # Build
            proc = await asyncio.create_subprocess_exec(
                "go", "build", "-o", str(self.runner_path), str(go_file),
                cwd=str(runners_dir),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await proc.wait()
            if proc.returncode != 0:
                stderr = await proc.stderr.read() if proc.stderr else b''
                print(f"Go build failed: {stderr.decode() if stderr else 'unknown error'}")

        return self.runner_path.exists()


class RustRunner(ClientRunner):
    """Rust client test runner."""

    def __init__(self, server: str):
        super().__init__("rust", server)
        self.runner_path = (
            Path(__file__).parent / "runners" / "rust_runner" / "target" / "release" / "rust_runner"
        )

    async def run_test(self, spec: Dict[str, Any], test: Dict[str, Any]) -> TestResult:
        start_time = time.time()

        try:
            # Create temporary test file
            test_spec = {
                "setup": spec.get("setup", []),
                "tests": [test],
                "cleanup": spec.get("cleanup", []),
            }
            test_file = Path("/tmp") / f"test_{test['name']}.yaml"
            test_file.write_text(yaml.dump(test_spec, Dumper=IndentedDumper, default_flow_style=False, sort_keys=False))

            # Run Rust runner
            proc = await asyncio.create_subprocess_exec(
                str(self.runner_path),
                "--spec",
                str(test_file),
                "--server",
                self.server,
                "--json",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=test.get("timeout_ms", 30000) / 1000
            )

            duration_ms = (time.time() - start_time) * 1000

            if stdout:
                try:
                    result = json.loads(stdout.decode())
                    status = derive_status_from_summary(result)
                    return TestResult(
                        test_name=test["name"],
                        client="rust",
                        status=status,
                        duration_ms=duration_ms,
                        details=result,
                        error_message=stderr.decode() if status != "passed" and stderr else None,
                    )
                except json.JSONDecodeError:
                    pass

            if proc.returncode != 0:
                return TestResult(
                    test_name=test["name"],
                    client="rust",
                    status="failed",
                    duration_ms=duration_ms,
                    error_message=stderr.decode(),
                )

            return TestResult(
                test_name=test["name"],
                client="rust",
                status="error",
                duration_ms=duration_ms,
                error_message="Runner produced no output",
            )

        except asyncio.TimeoutError:
            return TestResult(
                test_name=test["name"],
                client="rust",
                status="error",
                duration_ms=(time.time() - start_time) * 1000,
                error_message="Test timed out",
            )
        except Exception as e:
            return TestResult(
                test_name=test["name"],
                client="rust",
                status="error",
                duration_ms=(time.time() - start_time) * 1000,
                error_message=str(e),
            )

    async def setup(self) -> bool:
        """Build Rust runner if needed."""
        cargo_dir = Path(__file__).parent / "runners" / "rust_runner"

        # Check if cargo is available (try PATH first, then common install location)
        cargo_cmd = "cargo"
        cargo_check = await asyncio.create_subprocess_exec(
            "which", "cargo",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await cargo_check.wait()

        if cargo_check.returncode != 0:
            # Try common Rust installation location
            home_cargo = Path.home() / ".cargo" / "bin" / "cargo"
            if home_cargo.exists():
                cargo_cmd = str(home_cargo)
            else:
                print(f"Cargo not found - Rust runner unavailable (install Rust to enable)")
                return False

        if not self.runner_path.exists() and (cargo_dir / "Cargo.toml").exists():
            print(f"Building Rust runner (this may take a minute)...")
            proc = await asyncio.create_subprocess_exec(
                cargo_cmd, "build", "--release",
                cwd=str(cargo_dir),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await proc.wait()
            if proc.returncode != 0:
                stderr = await proc.stderr.read() if proc.stderr else b''
                print(f"Rust build failed: {stderr.decode() if stderr else 'unknown error'}")
        return self.runner_path.exists()


class ZigRunner(ClientRunner):
    """Zig client test runner."""

    def __init__(self, server: str):
        super().__init__("zig", server)
        self.runner_path = Path(__file__).parent / "runners" / "zig-out" / "bin" / "zig_runner"

    async def run_test(self, spec: Dict[str, Any], test: Dict[str, Any]) -> TestResult:
        start_time = time.time()

        try:
            # Create temporary test file
            test_spec = {
                "setup": spec.get("setup", []),
                "tests": [test],
                "cleanup": spec.get("cleanup", []),
            }
            test_file = Path("/tmp") / f"test_{test['name']}.yaml"
            test_file.write_text(yaml.dump(test_spec, Dumper=IndentedDumper, default_flow_style=False, sort_keys=False))

            # Run Zig runner
            proc = await asyncio.create_subprocess_exec(
                str(self.runner_path),
                "--spec",
                str(test_file),
                "--server",
                self.server,
                "--json",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=test.get("timeout_ms", 30000) / 1000
            )

            duration_ms = (time.time() - start_time) * 1000

            if proc.returncode == 0:
                result = json.loads(stdout.decode())
                return TestResult(
                    test_name=test["name"],
                    client="zig",
                    status="passed",
                    duration_ms=duration_ms,
                    details=result,
                )
            else:
                return TestResult(
                    test_name=test["name"],
                    client="zig",
                    status="failed",
                    duration_ms=duration_ms,
                    error_message=stderr.decode(),
                )

        except asyncio.TimeoutError:
            return TestResult(
                test_name=test["name"],
                client="zig",
                status="error",
                duration_ms=(time.time() - start_time) * 1000,
                error_message="Test timed out",
            )
        except Exception as e:
            return TestResult(
                test_name=test["name"],
                client="zig",
                status="error",
                duration_ms=(time.time() - start_time) * 1000,
                error_message=str(e),
            )

    async def setup(self) -> bool:
        """Build Zig runner if needed."""
        build_zig = Path(__file__).parent / "runners" / "build.zig"

        # Check if zig is available
        zig_check = await asyncio.create_subprocess_exec(
            "which", "zig",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await zig_check.wait()

        if zig_check.returncode != 0:
            print(f"Zig not found - Zig runner unavailable (install Zig to enable)")
            return False

        if not self.runner_path.exists() and build_zig.exists():
            print(f"Building Zig runner...")
            proc = await asyncio.create_subprocess_exec(
                "zig", "build",
                cwd=str(build_zig.parent),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await proc.wait()
            if proc.returncode != 0:
                stderr = await proc.stderr.read() if proc.stderr else b''
                print(f"Zig build failed: {stderr.decode() if stderr else 'unknown error'}")
        return self.runner_path.exists()


class TestHarness:
    """Main test harness coordinator."""

    def __init__(
        self,
        server: Optional[str] = None,
        clients: List[str] = None,
        parallel: bool = False,
        verbose: bool = False,
        fail_fast: bool = False,
        manage_server: bool = True,
        restart_server_between_tests: bool = True,
        restart_server_between_clients: bool = True,
    ):
        self.server = server
        self.verbose = verbose
        self.fail_fast = fail_fast
        self.parallel = parallel
        self.manage_server = manage_server
        self.restart_server_between_tests = restart_server_between_tests
        self.restart_server_between_clients = restart_server_between_clients
        self.server_manager: Optional[GeodeServerManager] = None

        # Initialize runners (will be configured with actual server address in setup())
        self.runners: Dict[str, ClientRunner] = {}
        self.requested_clients = clients or ["python", "go", "rust", "zig"]

    async def setup(self) -> bool:
        """Setup all runners."""
        # Start server if managed
        if self.manage_server:
            if self.verbose:
                print("Starting managed Geode server...")
            try:
                self.server_manager = GeodeServerManager(verbose=self.verbose)
                self.server = await self.server_manager.start()
                if self.verbose:
                    print(f"Server started at {self.server}")
            except Exception as e:
                print(f"ERROR: Failed to start server: {e}", file=sys.stderr)
                return False
        elif not self.server:
            print("ERROR: No server address provided and server management disabled", file=sys.stderr)
            return False

        # Initialize runners with server address
        temp_runners = {}
        if "python" in self.requested_clients:
            temp_runners["python"] = PythonRunner(self.server)
        if "go" in self.requested_clients:
            temp_runners["go"] = GoRunner(self.server)
        if "rust" in self.requested_clients:
            temp_runners["rust"] = RustRunner(self.server)
        if "zig" in self.requested_clients:
            temp_runners["zig"] = ZigRunner(self.server)

        # Setup each runner
        available_runners = {}
        for name, runner in temp_runners.items():
            if self.verbose:
                print(f"Setting up {name} runner...")
            if await runner.setup():
                available_runners[name] = runner
            else:
                if self.verbose:
                    print(f"Skipping {name} runner (not available)")

        if not available_runners:
            print(f"ERROR: No runners available - at least one language toolchain must be installed", file=sys.stderr)
            # Clean up server if we started it
            if self.server_manager:
                await self.server_manager.stop()
            return False

        # Replace runners dict with only available ones
        self.runners = available_runners
        return True

    async def teardown(self):
        """Clean up resources."""
        # Teardown all runners
        for runner in self.runners.values():
            try:
                await runner.teardown()
            except Exception as e:
                if self.verbose:
                    print(f"Error in runner teardown: {e}", file=sys.stderr)

        # Stop server if managed
        if self.server_manager:
            try:
                await self.server_manager.stop()
            except Exception as e:
                if self.verbose:
                    print(f"Error stopping server: {e}", file=sys.stderr)

    async def restart_server(self):
        """Restart the managed server to ensure clean state between tests."""
        if not self.server_manager:
            return

        if self.verbose:
            print("    Restarting server for clean test isolation...")

        # Stop current server
        await self.server_manager.stop()

        # Small delay to ensure port is released
        await asyncio.sleep(0.5)

        # Start new server (reuses same port allocation)
        self.server = await self.server_manager.start()

        # Update all runners with new server address
        for runner in self.runners.values():
            runner.server = self.server

        if self.verbose:
            print(f"    Server restarted at {self.server}")

    async def run_spec(self, spec_path: Path) -> List[TestResult]:
        """Run a test specification file."""
        # Load spec
        with open(spec_path) as f:
            spec = yaml.safe_load(f)

        if self.verbose:
            print(f"\nRunning spec: {spec.get('name', spec_path.name)}")
            print(f"Description: {spec.get('description', 'N/A')}")
            print(f"Tests: {len(spec.get('tests', []))}")

        results = []

        # Run tests
        for test in spec.get("tests", []):
            if test.get("skip", False):
                if self.verbose:
                    print(f"  SKIP: {test['name']}")
                for client in self.runners.keys():
                    results.append(
                        TestResult(
                            test_name=test["name"],
                            client=client,
                            status="skipped",
                            duration_ms=0.0,
                        )
                    )
                continue

            # Restart server between tests if enabled
            if self.restart_server_between_tests and self.manage_server:
                await self.restart_server()

            if self.verbose:
                print(f"\n  Test: {test['name']}")
                print(f"    {test.get('description', '')}")

            # Run test on all clients
            if self.parallel:
                # Run clients in parallel
                tasks = [
                    runner.run_test(spec, test) for runner in self.runners.values()
                ]
                test_results = await asyncio.gather(*tasks)
                results.extend(test_results)
            else:
                # Run clients sequentially
                for name, runner in self.runners.items():
                    if self.manage_server and self.restart_server_between_clients:
                        # Tear down any existing client state and restart the server for isolation
                        try:
                            await runner.teardown()
                        except Exception:
                            # Ignore teardown errors during isolation
                            pass

                        await self.restart_server()

                        # Clear cached connections on runners that maintain them
                        if hasattr(runner, "connection"):
                            try:
                                runner.connection = None
                            except Exception:
                                pass

                    if self.verbose:
                        print(f"    Running {name}...", end=" ", flush=True)

                    result = await runner.run_test(spec, test)
                    results.append(result)

                    if self.verbose:
                        status_symbol = {
                            "passed": "✓",
                            "failed": "✗",
                            "error": "⚠",
                            "skipped": "-",
                        }.get(result.status, "?")
                        print(
                            f"{status_symbol} {result.status.upper()} ({result.duration_ms:.1f}ms)"
                        )
                        if result.error_message and self.verbose:
                            print(f"      Error: {result.error_message}")

                    if self.fail_fast and result.status in ("failed", "error"):
                        print(
                            f"\nFail-fast mode: Stopping after first failure in {name}",
                            file=sys.stderr,
                        )
                        return results

        return results

    def generate_summary(self, results: List[TestResult]) -> Dict[str, TestSummary]:
        """Generate summary statistics."""
        summaries = {}

        for client in self.runners.keys():
            summary = TestSummary(client=client)
            client_results = [r for r in results if r.client == client]

            summary.total = len(client_results)
            summary.passed = len([r for r in client_results if r.status == "passed"])
            summary.failed = len([r for r in client_results if r.status == "failed"])
            summary.skipped = len([r for r in client_results if r.status == "skipped"])
            summary.errors = len([r for r in client_results if r.status == "error"])
            summary.duration_ms = sum(r.duration_ms for r in client_results)

            summaries[client] = summary

        return summaries

    def print_summary(self, summaries: Dict[str, TestSummary]):
        """Print test summary."""
        print("\n" + "=" * 80)
        print("TEST SUMMARY")
        print("=" * 80)

        for client, summary in summaries.items():
            pass_rate = (
                (summary.passed / summary.total * 100) if summary.total > 0 else 0
            )
            print(f"\n{client.upper()}:")
            print(
                f"  Total: {summary.total} | Passed: {summary.passed} | Failed: {summary.failed}"
            )
            print(f"  Skipped: {summary.skipped} | Errors: {summary.errors}")
            print(f"  Pass Rate: {pass_rate:.1f}%")
            print(f"  Duration: {summary.duration_ms:.1f}ms")

        # Overall
        total = sum(s.total for s in summaries.values())
        passed = sum(s.passed for s in summaries.values())
        failed = sum(s.failed for s in summaries.values())
        errors = sum(s.errors for s in summaries.values())

        print(f"\nOVERALL:")
        print(f"  Total Tests: {total}")
        print(f"  Passed: {passed}")
        print(f"  Failed: {failed}")
        print(f"  Errors: {errors}")
        print(f"  Pass Rate: {(passed/total*100) if total > 0 else 0:.1f}%")
        print("=" * 80)

    def _prepare_report_data(self, results: List[TestResult], summaries: Dict[str, TestSummary]) -> Dict[str, Any]:
        """Prepare report data structure for JSON/HTML output."""
        return {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "server": self.server,
            "total_tests": len(results),
            "summary": {
                client: {
                    "total": summary.total,
                    "passed": summary.passed,
                    "failed": summary.failed,
                    "skipped": summary.skipped,
                    "errors": summary.errors,
                    "duration_ms": summary.duration_ms,
                }
                for client, summary in summaries.items()
            },
            "results": [
                {
                    "test": r.test_name,
                    "client": r.client,
                    "status": r.status,
                    "duration_ms": r.duration_ms,
                    "error": r.error_message,
                    "details": r.details,
                }
                for r in results
            ],
        }

    def save_json_report(self, results: List[TestResult], summaries: Dict[str, TestSummary], output_path: Path):
        """Save JSON report."""
        report = self._prepare_report_data(results, summaries)

        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w") as f:
            json.dump(report, f, indent=2)

        if self.verbose:
            print(f"\nJSON report saved to: {output_path}")


async def main():
    parser = argparse.ArgumentParser(
        description="Run client library tests for Geode"
    )
    parser.add_argument(
        "--server",
        default=None,
        help="Geode server address (default: auto-start server on random port)",
    )
    parser.add_argument(
        "--no-manage-server",
        action="store_true",
        help="Don't start/stop server automatically (requires --server)",
    )
    parser.add_argument(
        "--spec", type=Path, help="Test specification file (runs all if not specified)"
    )
    parser.add_argument(
        "--clients",
        default="python,go,rust,zig",
        help="Comma-separated list of clients to test (default: python,go,rust,zig)",
    )
    parser.add_argument(
        "--parallel",
        action="store_true",
        help="Run clients in parallel (default: sequential)",
    )
    parser.add_argument(
        "--fail-fast", action="store_true", help="Stop on first failure"
    )
    parser.add_argument("--verbose", action="store_true", help="Verbose output")
    parser.add_argument(
        "--report-json", type=Path, help="Save JSON report to file"
    )
    parser.add_argument(
        "--report-html", type=Path, help="Generate HTML report to file"
    )

    args = parser.parse_args()

    # Parse clients
    clients = [c.strip() for c in args.clients.split(",")]

    # Determine server management strategy
    manage_server = not args.no_manage_server

    # Initialize harness
    harness = TestHarness(
        server=args.server,
        clients=clients,
        parallel=args.parallel,
        verbose=args.verbose,
        fail_fast=args.fail_fast,
        manage_server=manage_server,
        restart_server_between_tests=False,  # Disabled: Server restart has issues
        restart_server_between_clients=False,
    )

    try:
        # Setup
        if not await harness.setup():
            sys.exit(3)

        # Find specs
        if args.spec:
            specs = [args.spec]
        else:
            spec_dir = Path(__file__).parent / "specs"
            specs = sorted(spec_dir.glob("*.yaml"))

        if not specs:
            print("ERROR: No test specifications found", file=sys.stderr)
            sys.exit(2)

        # Run tests
        all_results = []
        for spec in specs:
            results = await harness.run_spec(spec)
            all_results.extend(results)

        # Generate summary
        summaries = harness.generate_summary(all_results)
        harness.print_summary(summaries)

        # Save reports
        if args.report_json:
            harness.save_json_report(all_results, summaries, args.report_json)

        if args.report_html:
            # Import HTML report generator
            from generate_html_report import generate_html_report

            # Prepare report data
            report_data = harness._prepare_report_data(all_results, summaries)

            # Generate HTML
            generate_html_report(report_data, args.report_html)

        # Exit code
        failed = sum(s.failed + s.errors for s in summaries.values())
        exit_code = 1 if failed > 0 else 0

    except KeyboardInterrupt:
        print("\nInterrupted by user", file=sys.stderr)
        exit_code = 130
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        if args.verbose:
            import traceback
            traceback.print_exc()
        exit_code = 1
    finally:
        # Ensure cleanup happens
        await harness.teardown()
        await GeodeServerManager.cleanup_all()

    sys.exit(exit_code)


if __name__ == "__main__":
    asyncio.run(main())
