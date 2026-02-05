#!/usr/bin/env python3
"""
Unified test runner for all Geode client libraries.

Runs identical test specifications across Zig, Go, Rust, Python, and Node.js clients
to ensure feature parity and correctness.

Server management uses Docker containers for isolation and consistency.
"""

import argparse
import asyncio
import atexit
import json
import os
import shutil
import subprocess
import sys
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
    skip_reason: Optional[str] = None


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
    """Manages Geode server using Docker containers."""

    # Docker settings
    DEFAULT_IMAGE = "registry.gitlab.com/devnw/geode/geode:latest"
    DEFAULT_CONTAINER_NAME = "geode-test-harness"
    DEFAULT_PORT = 3141
    DEFAULT_GRPC_PORT = 50051
    DEFAULT_ADMIN_PASSWORD = "GeodeTestPassword123!"

    # Class-level tracking
    _all_servers: List['GeodeServerManager'] = []

    def __init__(
        self,
        image: Optional[str] = None,
        container_name: Optional[str] = None,
        port: Optional[int] = None,
        grpc_port: Optional[int] = None,
        verbose: bool = False,
        enable_grpc: bool = True,
    ):
        self.image = image or os.environ.get("GEODE_IMAGE", self.DEFAULT_IMAGE)
        self.container_name = container_name or os.environ.get("GEODE_CONTAINER", self.DEFAULT_CONTAINER_NAME)
        self.port = port or int(os.environ.get("GEODE_PORT", self.DEFAULT_PORT))
        self.grpc_port = grpc_port or int(os.environ.get("GEODE_GRPC_PORT", self.DEFAULT_GRPC_PORT)) if enable_grpc else None
        self.admin_password = os.environ.get("GEODE_ADMIN_PASSWORD", self.DEFAULT_ADMIN_PASSWORD)
        self.verbose = verbose
        self.host = os.environ.get("GEODE_HOST", "127.0.0.1")
        self._cleanup_registered = False

        # Register this instance for cleanup
        GeodeServerManager._all_servers.append(self)

    @property
    def grpc_address(self) -> Optional[str]:
        """Return the gRPC server address (host:port), or None if gRPC is disabled."""
        return f"{self.host}:{self.grpc_port}" if self.grpc_port else None

    @staticmethod
    def check_docker_available() -> bool:
        """Check if Docker is installed and the daemon is running."""
        if not shutil.which("docker"):
            return False
        try:
            result = subprocess.run(
                ["docker", "info"],
                check=True,
                capture_output=True,
                text=True
            )
            return result.returncode == 0
        except (subprocess.CalledProcessError, FileNotFoundError):
            return False

    def _run_docker(self, *args, check: bool = True, capture: bool = True) -> subprocess.CompletedProcess:
        """Run a docker command."""
        cmd = ["docker"] + list(args)
        if self.verbose:
            print(f"Running: {' '.join(cmd)}")
        return subprocess.run(
            cmd,
            check=check,
            capture_output=capture,
            text=True
        )

    async def start(self) -> str:
        """Start the Geode server container and return the server address."""
        # Check Docker availability before attempting to use it
        if not self.check_docker_available():
            raise RuntimeError(
                "Docker is not available. Please ensure:\n"
                "  1. Docker is installed (https://docs.docker.com/get-docker/)\n"
                "  2. Docker daemon is running (try 'docker info')\n"
                "  3. Your user has permission to run Docker\n"
                "Alternatively, use --no-manage-server with an external Geode server."
            )

        if self.verbose:
            print(f"Starting Geode server container: {self.container_name}")
            print(f"  Image: {self.image}")
            print(f"  QUIC Port: {self.port}")
            if self.grpc_port:
                print(f"  gRPC Port: {self.grpc_port}")

        # Remove any existing container with the same name
        try:
            self._run_docker("rm", "-f", self.container_name, check=False)
        except Exception:
            pass

        # Build Docker run command
        # QUIC uses UDP, gRPC uses TCP
        docker_args = [
            "run", "-d",
            "--name", self.container_name,
            "-p", f"{self.port}:3141/udp",
            "-e", f"GEODE_ADMIN_PASSWORD={self.admin_password}",
            "-e", "GEODE_DISABLE_AUDIT=1",
        ]

        # Add gRPC port if enabled
        if self.grpc_port:
            docker_args.extend(["-p", f"{self.grpc_port}:50051/tcp"])

        # Add image and serve command
        docker_args.append(self.image)
        docker_args.extend(["serve", "--listen", "0.0.0.0:3141", "--log-level", "info"])

        # Add gRPC listen if enabled
        if self.grpc_port:
            docker_args.extend(["--listen-grpc", "0.0.0.0:50051"])

        # Start the container
        try:
            self._run_docker(*docker_args)
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"Failed to start Docker container: {e.stderr}")

        # Register cleanup on exit
        if not self._cleanup_registered:
            atexit.register(self._emergency_cleanup)
            self._cleanup_registered = True

        # Wait for server to be ready
        await self._wait_for_server_ready()

        return f"{self.host}:{self.port}"

    async def _wait_for_server_ready(self, timeout: float = 30.0):
        """Wait for server to be ready by checking container logs."""
        start_time = time.time()

        while time.time() - start_time < timeout:
            # Check if container is still running
            result = self._run_docker(
                "inspect", "-f", "{{.State.Running}}",
                self.container_name,
                check=False
            )
            if result.returncode != 0 or result.stdout.strip() != "true":
                # Get container logs for debugging
                logs = self._run_docker("logs", self.container_name, check=False)
                raise RuntimeError(
                    f"Container is not running.\n"
                    f"Last logs:\n{logs.stdout if logs.stdout else logs.stderr}"
                )

            # Check logs for ready message
            logs = self._run_docker("logs", self.container_name, check=False)
            log_content = logs.stdout + logs.stderr
            if "Server ready" in log_content or "accepting QUIC connections" in log_content:
                if self.verbose:
                    print(f"Server ready on {self.host}:{self.port}")
                return

            await asyncio.sleep(0.5)

        raise TimeoutError(f"Server did not become ready within {timeout} seconds")

    async def stop(self):
        """Stop the Geode server container."""
        if self.verbose:
            print(f"Stopping Geode server container: {self.container_name}")

        try:
            self._run_docker("stop", self.container_name, check=False)
            self._run_docker("rm", self.container_name, check=False)
        except Exception as e:
            if self.verbose:
                print(f"Error stopping container: {e}")

    async def run_migrations(self, migrations_dir: Path, geode_cli: Optional[Path] = None) -> bool:
        """Run database migrations using Geode CLI.

        Args:
            migrations_dir: Path to migrations directory
            geode_cli: Path to geode CLI binary (auto-detected if not provided)

        Returns:
            True if migrations succeeded, False otherwise
        """
        if not migrations_dir.exists():
            if self.verbose:
                print(f"Migrations directory not found: {migrations_dir}")
            return True  # No migrations to run

        # Find geode CLI
        if geode_cli is None:
            # Try common locations
            possible_paths = [
                Path(__file__).parent.parent / "geode" / "zig-out" / "bin" / "geode",
                Path.home() / ".local" / "bin" / "geode",
                Path("/usr/local/bin/geode"),
            ]
            for path in possible_paths:
                if path.exists():
                    geode_cli = path
                    break

            # Try which
            if geode_cli is None:
                result = subprocess.run(["which", "geode"], capture_output=True, text=True)
                if result.returncode == 0:
                    geode_cli = Path(result.stdout.strip())

        if geode_cli is None or not geode_cli.exists():
            if self.verbose:
                print("Geode CLI not found - skipping migrations")
            return True  # Can't run migrations without CLI

        if self.verbose:
            print(f"Running migrations from: {migrations_dir}")
            print(f"Using Geode CLI: {geode_cli}")

        # Run migrations
        server_addr = f"{self.host}:{self.port}"
        cmd = [
            str(geode_cli),
            "migrate", "run",
            "--dir", str(migrations_dir),
            "--server", server_addr,
            "--insecure"  # Skip TLS verification for test containers
        ]

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=60  # 60 second timeout for migrations
            )

            if result.returncode != 0:
                print(f"Migration failed: {result.stderr}")
                if self.verbose:
                    print(f"Migration stdout: {result.stdout}")
                return False

            if self.verbose:
                print("Migrations applied successfully")
                if result.stdout:
                    print(result.stdout)

            return True

        except subprocess.TimeoutExpired:
            print("Migration timed out after 60 seconds")
            return False
        except Exception as e:
            print(f"Migration error: {e}")
            return False

    def _emergency_cleanup(self):
        """Emergency cleanup called on exit."""
        try:
            subprocess.run(
                ["docker", "rm", "-f", self.container_name],
                check=False,
                capture_output=True
            )
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

    def __init__(self, server: str, transport: str = "quic"):
        super().__init__("python", server)
        self.runner_path = Path(__file__).parent / "runners" / "python_runner.py"
        self.transport = transport
        # Use venv Python if available
        venv_python = Path(__file__).parent / ".venv" / "bin" / "python3"
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
                "--transport",
                self.transport,
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

    def __init__(self, server: str, transport: str = "quic"):
        super().__init__("go", server)
        self.runner_path = Path(__file__).parent / "runners" / "go_runner"
        self.transport = transport

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
                "-transport",
                self.transport,
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

    def __init__(self, server: str, transport: str = "quic"):
        super().__init__("rust", server)
        self.runner_path = (
            Path(__file__).parent / "runners" / "rust_runner" / "target" / "release" / "rust_runner"
        )
        self.transport = transport

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
                "--transport",
                self.transport,
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

    def __init__(self, server: str, transport: str = "quic"):
        super().__init__("zig", server)
        self.runner_path = Path(__file__).parent / "runners" / "zig-out" / "bin" / "zig_runner"
        self.transport = transport

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
                "--transport",
                self.transport,
                "--json",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=test.get("timeout_ms", 30000) / 1000
            )

            duration_ms = (time.time() - start_time) * 1000

            # Parse result from stdout
            if stdout:
                try:
                    result = json.loads(stdout.decode())
                    status = derive_status_from_summary(result)
                    return TestResult(
                        test_name=test["name"],
                        client="zig",
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
                    client="zig",
                    status="failed",
                    duration_ms=duration_ms,
                    error_message=stderr.decode(),
                )

            return TestResult(
                test_name=test["name"],
                client="zig",
                status="error",
                duration_ms=duration_ms,
                error_message="Runner produced no output",
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


class NodeJSRunner(ClientRunner):
    """Node.js client test runner."""

    def __init__(self, server: str, transport: str = "quic"):
        super().__init__("nodejs", server)
        self.runner_path = Path(__file__).parent / "runners" / "nodejs_runner.js"
        self.node_modules = Path(__file__).parent / "runners" / "node_modules"
        self.transport = transport

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

            # Run Node.js runner
            proc = await asyncio.create_subprocess_exec(
                "node",
                str(self.runner_path),
                "--spec",
                str(test_file),
                "--server",
                self.server,
                "--transport",
                self.transport,
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
                        client="nodejs",
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
                    client="nodejs",
                    status="failed",
                    duration_ms=duration_ms,
                    error_message=stderr.decode(),
                )

            return TestResult(
                test_name=test["name"],
                client="nodejs",
                status="error",
                duration_ms=duration_ms,
                error_message="Runner produced no output",
            )

        except asyncio.TimeoutError:
            return TestResult(
                test_name=test["name"],
                client="nodejs",
                status="error",
                duration_ms=(time.time() - start_time) * 1000,
                error_message="Test timed out",
            )
        except Exception as e:
            return TestResult(
                test_name=test["name"],
                client="nodejs",
                status="error",
                duration_ms=(time.time() - start_time) * 1000,
                error_message=str(e),
            )

    async def setup(self) -> bool:
        """Check if Node.js runner is available."""
        # Check if node is available
        node_check = await asyncio.create_subprocess_exec(
            "which", "node",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await node_check.wait()

        if node_check.returncode != 0:
            print(f"Node.js not found - Node.js runner unavailable (install Node.js to enable)")
            return False

        if not self.runner_path.exists():
            print(f"Node.js runner not found at {self.runner_path}")
            return False

        # Check if node_modules exists (dependencies installed)
        if not self.node_modules.exists():
            print(f"Installing Node.js dependencies...")
            runners_dir = Path(__file__).parent / "runners"
            proc = await asyncio.create_subprocess_exec(
                "npm", "install",
                cwd=str(runners_dir),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await proc.wait()
            if proc.returncode != 0:
                stderr = await proc.stderr.read() if proc.stderr else b''
                print(f"npm install failed: {stderr.decode() if stderr else 'unknown error'}")
                return False

        return True


class ShellRunner(ClientRunner):
    """Interactive shell test runner using pexpect."""

    def __init__(self, server: str, geode_binary: str = None):
        super().__init__("shell", server)
        self.runner_path = Path(__file__).parent / "runners" / "shell_runner.py"
        # Use venv Python if available
        venv_python = Path(__file__).parent / ".venv" / "bin" / "python3"
        self.python_exe = str(venv_python) if venv_python.exists() else sys.executable
        # Find geode binary
        if geode_binary:
            self.geode_binary = geode_binary
        else:
            # Try to find geode binary in common locations
            for path in [
                Path(__file__).parent.parent / "geode" / "zig-out" / "bin" / "geode",
                Path(__file__).parent.parent / "zig-out" / "bin" / "geode",
                Path("/usr/local/bin/geode"),
            ]:
                if path.exists():
                    self.geode_binary = str(path)
                    break
            else:
                self.geode_binary = "geode"  # Hope it's in PATH

    async def run_test(self, spec: Dict[str, Any], test: Dict[str, Any]) -> TestResult:
        start_time = time.time()

        try:
            # Create temporary test file
            test_spec = {
                "manage_server": spec.get("manage_server", False),
                "server_options": spec.get("server_options", {}),
                "tests": [test],
            }
            test_file = Path("/tmp") / f"shell_test_{test['name']}.yaml"
            test_file.write_text(yaml.dump(test_spec, Dumper=IndentedDumper, default_flow_style=False, sort_keys=False))

            # Run shell runner
            cmd = [
                self.python_exe,
                str(self.runner_path),
                "--spec", str(test_file),
                "--server", self.server,
                "--geode-binary", self.geode_binary,
                "--json",
            ]

            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=test.get("timeout_ms", 300000) / 1000
            )

            duration_ms = (time.time() - start_time) * 1000

            if stdout:
                try:
                    results = json.loads(stdout.decode())
                    # Shell runner returns a list of results
                    if isinstance(results, list) and len(results) > 0:
                        result = results[0]
                        status = result.get("status", "error")
                        return TestResult(
                            test_name=test["name"],
                            client="shell",
                            status=status,
                            duration_ms=duration_ms,
                            details=result.get("details", {}),
                            error_message=result.get("error") if status != "passed" else None,
                        )
                except json.JSONDecodeError:
                    pass

            if proc.returncode != 0:
                return TestResult(
                    test_name=test["name"],
                    client="shell",
                    status="failed",
                    duration_ms=duration_ms,
                    error_message=stderr.decode() if stderr else "Unknown error",
                )

            return TestResult(
                test_name=test["name"],
                client="shell",
                status="error",
                duration_ms=duration_ms,
                error_message="Runner produced no output",
            )

        except asyncio.TimeoutError:
            return TestResult(
                test_name=test["name"],
                client="shell",
                status="error",
                duration_ms=(time.time() - start_time) * 1000,
                error_message="Test timed out",
            )
        except Exception as e:
            return TestResult(
                test_name=test["name"],
                client="shell",
                status="error",
                duration_ms=(time.time() - start_time) * 1000,
                error_message=str(e),
            )

    async def setup(self) -> bool:
        """Verify shell runner exists and pexpect is available."""
        if not self.runner_path.exists():
            print(f"Shell runner not found: {self.runner_path}")
            return False

        # Check if pexpect is available
        try:
            proc = await asyncio.create_subprocess_exec(
                self.python_exe, "-c", "import pexpect",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await proc.wait()
            if proc.returncode != 0:
                print("pexpect not installed - shell tests will be skipped")
                return False
        except Exception:
            return False

        return True


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
        restart_server_between_tests: bool = False,
        restart_server_between_clients: bool = False,
        migrations_dir: Optional[Path] = None,
        skip_migrations: bool = False,
        transport: str = "quic",
    ):
        self.server = server
        self.verbose = verbose
        self.fail_fast = fail_fast
        self.parallel = parallel
        self.manage_server = manage_server
        self.restart_server_between_tests = restart_server_between_tests
        self.restart_server_between_clients = restart_server_between_clients
        self.migrations_dir = migrations_dir or Path(__file__).parent / "migrations"
        self.skip_migrations = skip_migrations
        self.migrations_succeeded = False  # Track if migrations ran successfully
        self.server_manager: Optional[GeodeServerManager] = None
        self.transport = transport

        # Initialize runners (will be configured with actual server address in setup())
        self.runners: Dict[str, ClientRunner] = {}
        self.requested_clients = clients or ["python", "go", "rust", "zig", "nodejs", "shell"]

    async def setup(self) -> bool:
        """Setup all runners."""
        # Start server if managed
        if self.manage_server:
            if self.verbose:
                print("Starting managed Geode server (Docker)...")
            try:
                self.server_manager = GeodeServerManager(verbose=self.verbose)
                self.server = await self.server_manager.start()
                if self.verbose:
                    print(f"Server started at {self.server}")

                # Run migrations if not skipped
                if not self.skip_migrations and self.migrations_dir.exists():
                    if self.verbose:
                        print(f"Running migrations from {self.migrations_dir}...")
                    if await self.server_manager.run_migrations(self.migrations_dir):
                        self.migrations_succeeded = True
                    else:
                        print("WARNING: Some migrations failed, specs requiring migrations will be skipped", file=sys.stderr)
                elif self.verbose and self.skip_migrations:
                    print("Skipping migrations (--skip-migrations)")

            except Exception as e:
                print(f"ERROR: Failed to start server: {e}", file=sys.stderr)
                return False
        elif not self.server:
            print("ERROR: No server address provided and server management disabled", file=sys.stderr)
            return False

        # Initialize runners with server address and transport
        temp_runners = {}
        if "python" in self.requested_clients:
            temp_runners["python"] = PythonRunner(self.server, transport=self.transport)
        if "go" in self.requested_clients:
            temp_runners["go"] = GoRunner(self.server, transport=self.transport)
        if "rust" in self.requested_clients:
            temp_runners["rust"] = RustRunner(self.server, transport=self.transport)
        if "zig" in self.requested_clients:
            temp_runners["zig"] = ZigRunner(self.server, transport=self.transport)
        if "nodejs" in self.requested_clients:
            temp_runners["nodejs"] = NodeJSRunner(self.server, transport=self.transport)
        if "shell" in self.requested_clients:
            temp_runners["shell"] = ShellRunner(self.server)

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

        # Start new server
        self.server = await self.server_manager.start()

        # Update all runners with new server address
        for runner in self.runners.values():
            runner.server = self.server

        if self.verbose:
            print(f"    Server restarted at {self.server}")

    def _validate_spec(self, spec: Dict[str, Any], spec_path: Path) -> List[str]:
        """Validate a test specification and return list of errors."""
        errors = []

        # Check required top-level fields
        if not isinstance(spec, dict):
            errors.append(f"{spec_path}: Spec must be a YAML mapping/dictionary")
            return errors

        if "tests" not in spec:
            errors.append(f"{spec_path}: Missing required field 'tests'")

        tests = spec.get("tests", [])
        if not isinstance(tests, list):
            errors.append(f"{spec_path}: 'tests' must be a list")
            return errors

        # Validate each test
        for i, test in enumerate(tests):
            if not isinstance(test, dict):
                errors.append(f"{spec_path}: test[{i}] must be a mapping")
                continue

            if "name" not in test:
                errors.append(f"{spec_path}: test[{i}] missing required field 'name'")

            # Test must have either 'query', 'steps', or be skipped
            has_query = "query" in test
            has_steps = "steps" in test
            is_skipped = test.get("skip", False)

            if not has_query and not has_steps and not is_skipped:
                test_name = test.get("name", f"test[{i}]")
                errors.append(f"{spec_path}: {test_name} must have 'query' or 'steps' field")

        return errors

    async def run_spec(self, spec_path: Path) -> List[TestResult]:
        """Run a test specification file."""
        # Load spec
        with open(spec_path) as f:
            spec = yaml.safe_load(f)

        # Validate spec before running
        validation_errors = self._validate_spec(spec, spec_path)
        if validation_errors:
            error_msg = "Spec validation failed:\n  " + "\n  ".join(validation_errors)
            if self.verbose:
                print(f"ERROR: {error_msg}")
            # Return error results for all tests
            return [
                TestResult(
                    test_name="spec-validation",
                    client="harness",
                    status="error",
                    error_message=error_msg,
                    duration_ms=0.0,
                )
            ]

        if self.verbose:
            print(f"\nRunning spec: {spec.get('name', spec_path.name)}")
            print(f"Description: {spec.get('description', 'N/A')}")
            print(f"Tests: {len(spec.get('tests', []))}")

        results = []

        # Check if spec requires migrations and skip if migrations failed
        if spec.get("requires_migrations", False) and not self.migrations_succeeded:
            if self.verbose:
                print(f"  SKIPPING: Spec requires migrations but migrations failed/skipped")
            for test in spec.get("tests", []):
                for client in self.runners.keys():
                    results.append(
                        TestResult(
                            test_name=test["name"],
                            client=client,
                            status="skipped",
                            duration_ms=0.0,
                            skip_reason="Requires migrations but migrations failed/skipped",
                        )
                    )
            return results

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

            # Get test timeout (default 60 seconds if not specified)
            timeout_ms = test.get("timeout_ms", 60000)
            timeout_seconds = timeout_ms / 1000.0

            # Run test on all clients
            if self.parallel:
                # Run clients in parallel with timeout
                async def run_with_timeout(runner, name):
                    try:
                        return await asyncio.wait_for(
                            runner.run_test(spec, test),
                            timeout=timeout_seconds
                        )
                    except asyncio.TimeoutError:
                        return TestResult(
                            test_name=test["name"],
                            client=name,
                            status="error",
                            error_message=f"Test timed out after {timeout_ms}ms",
                            duration_ms=timeout_ms,
                        )

                tasks = [
                    run_with_timeout(runner, name)
                    for name, runner in self.runners.items()
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

                    # Run test with timeout enforcement
                    try:
                        result = await asyncio.wait_for(
                            runner.run_test(spec, test),
                            timeout=timeout_seconds
                        )
                    except asyncio.TimeoutError:
                        result = TestResult(
                            test_name=test["name"],
                            client=name,
                            status="error",
                            error_message=f"Test timed out after {timeout_ms}ms",
                            duration_ms=timeout_ms,
                        )
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
        help="Geode server address (default: auto-start Docker container)",
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
        default="python,go,rust,zig,nodejs",
        help="Comma-separated list of clients to test (default: python,go,rust,zig,nodejs)",
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
    parser.add_argument(
        "--migrations-dir", type=Path, default=None,
        help="Directory containing migration files (default: ./migrations)"
    )
    parser.add_argument(
        "--skip-migrations", action="store_true",
        help="Skip running migrations before tests"
    )
    parser.add_argument(
        "--transport",
        default="quic",
        choices=["quic", "grpc"],
        help="Transport protocol to use (default: quic)"
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
        restart_server_between_tests=False,
        restart_server_between_clients=False,
        migrations_dir=args.migrations_dir,
        skip_migrations=args.skip_migrations,
        transport=args.transport,
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
