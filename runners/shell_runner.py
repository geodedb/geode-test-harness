#!/usr/bin/env python3
"""
Interactive shell test runner for Geode.

Executes test specifications using the geode shell command via pexpect
for interactive TTY simulation. Supports testing /source command and
data persistence.
"""

import argparse
import json
import os
import re
import sys
import tempfile
from pathlib import Path
from typing import Any

import yaml

from runners.shell_test_methods import (
    run_persistence_test,
    run_query_test,
    run_source_test,
    run_steps_test,
)

# Import shared utilities
sys.path.insert(0, str(Path(__file__).parent.parent))
from lib.server_manager import ServerManager
from lib.utils import find_geode_binary

# Try to import pexpect for interactive shell testing
try:
    import pexpect

    PEXPECT_AVAILABLE = True
except ImportError:
    PEXPECT_AVAILABLE = False
    pexpect = None

# Errors pexpect raises (timeouts, EOF, spawn failures); empty when pexpect is absent.
_PEXPECT_ERRORS: tuple[type[BaseException], ...] = (
    (pexpect.ExceptionPexpect,) if pexpect is not None else ()
)

# ANSI escape code pattern for stripping terminal control sequences
# Includes cursor movement, colors, and carriage returns
ANSI_ESCAPE_PATTERN = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]|\x1b\[\?[0-9;]*[a-zA-Z]|\r")


class ShellTestRunner:
    """Test runner for interactive Geode shell.

    When manage_server=True is used via run_spec(), this runner automatically
    allocates a free port and creates an isolated data directory to enable
    parallel test execution without conflicts.
    """

    def __init__(
        self,
        server: str | None = None,
        geode_binary: str = "./zig-out/bin/geode",
        data_dir: str | None = None,
        verbose: bool = False,
        auto_allocate_port: bool = False,
    ):
        """Initialize the shell test runner.

        Parameters
        ----------
        server : Optional[str]
            Server address (host:port). If None and auto_allocate_port=True,
            a free port will be allocated automatically.
        geode_binary : str
            Path to the geode binary.
        data_dir : Optional[str]
            Data directory for the server. If None, a unique temp directory
            is created for isolation.
        verbose : bool
            Enable verbose logging.
        auto_allocate_port : bool
            If True and server is None, automatically allocate a free port.
        """
        self.geode_binary = geode_binary
        self.verbose = verbose
        self.shell_process: pexpect.spawn | None = None
        self.server_manager: ServerManager | None = None
        self.prompt_pattern = r"geode(?:\([^)]+\))?>\s*"
        self.default_timeout = 30

        # Handle server address and port allocation
        if auto_allocate_port and server is None:
            # Will be set when server starts
            self._auto_allocate = True
            self.server = None
            self.data_dir = data_dir  # Let ServerManager create temp dir if None
        else:
            self._auto_allocate = False
            self.server = server or "127.0.0.1:3141"
            self.data_dir = data_dir or tempfile.mkdtemp(prefix="geode_shell_test_")

    def log(self, message: str):
        """Log message if verbose mode is enabled."""
        if self.verbose:
            print(f"[SHELL_RUNNER] {message}", file=sys.stderr)

    def strip_ansi(self, text: str) -> str:
        """Strip ANSI escape codes from text."""
        return ANSI_ESCAPE_PATTERN.sub("", text)

    def start_server(self) -> bool:
        """Start the Geode server for testing using the shared ServerManager."""
        self.log(f"Starting server with geode_binary={self.geode_binary}")

        try:
            # Create server manager with auto-allocated port if needed
            self.server_manager = ServerManager(
                binary_path=self.geode_binary,
                port=None
                if self._auto_allocate
                else int(self.server.split(":")[-1])
                if self.server
                else None,
                data_dir=self.data_dir,
                verbose=self.verbose,
            )

            # Start the server
            address = self.server_manager.start()
            self.server = address
            self.data_dir = self.server_manager.data_dir

            self.log(f"Server started on {self.server}, data_dir={self.data_dir}")
            return True

        except RuntimeError as e:
            self.log(f"Failed to start server: {e}")
            return False

    def stop_server(self):
        """Stop the Geode server."""
        if self.server_manager:
            self.log("Stopping server")
            self.server_manager.stop()
            self.server_manager = None

    def start_shell(self) -> bool:
        """Start an interactive shell session."""
        if not PEXPECT_AVAILABLE:
            self.log("pexpect not available - cannot run interactive shell tests")
            return False

        # Use json format for reliable parsing.
        cmd = f"{self.geode_binary} shell --server {self.server} --insecure-tls-skip-verify --format json --no-history -U geode -P 'Geode Test Admin Passphrase'"
        self.log(f"Starting shell: {cmd}")

        # Environment to disable colors and spinners
        env = os.environ.copy()
        env["TERM"] = "dumb"
        env["NO_COLOR"] = "1"
        env["GEODE_NO_SPINNER"] = "1"

        try:
            self.shell_process = pexpect.spawn(
                cmd,
                encoding="utf-8",
                timeout=self.default_timeout,
                env=env,
                dimensions=(24, 120),  # rows, cols - wide terminal
            )

            # Wait for initial prompt
            self.shell_process.expect(self.prompt_pattern, timeout=30)
            self.log("Shell started and ready")
            return True
        except pexpect.TIMEOUT:
            self.log("Timeout waiting for shell prompt")
            if self.shell_process:
                self.log(f"Buffer contents: {self.shell_process.before}")
            return False
        except pexpect.EOF:
            self.log("Shell process ended unexpectedly")
            if self.shell_process:
                self.log(f"Buffer contents: {self.shell_process.before}")
            return False
        except (OSError, *_PEXPECT_ERRORS) as e:
            self.log(f"Failed to start shell: {e}")
            return False

    def stop_shell(self):
        """Stop the shell session."""
        if self.shell_process:
            self.log("Stopping shell")
            try:
                self.shell_process.sendline("/quit")
                self.shell_process.expect(pexpect.EOF, timeout=5)
            except (OSError, *_PEXPECT_ERRORS) as e:
                self.log(f"Shell did not quit cleanly: {e}")
            finally:
                if self.shell_process.isalive():
                    self.shell_process.terminate(force=True)
                self.shell_process = None

    def send_command(
        self, command: str, timeout: int | None = None
    ) -> tuple[bool, str]:
        """
        Send a command to the shell and wait for the response.

        Returns:
            Tuple of (success, output)
        """
        if not self.shell_process:
            return False, "Shell not started"

        timeout = timeout or self.default_timeout
        self.log(f"Sending command: {command}")

        try:
            # Wait for prompt to be ready instead of a fixed 0.3s sleep (PERF-009).
            # A short expect with the prompt pattern confirms the shell is idle.
            try:
                self.shell_process.expect(self.prompt_pattern, timeout=0.5)
            except pexpect.TIMEOUT:
                pass  # If no prompt yet, proceed anyway

            # Send the command
            self.shell_process.sendline(command)

            # Wait for prompt - need to wait for BOTH the echo and the output
            # The pattern: [command echo]\n[output]\n[prompt]
            self.shell_process.expect(self.prompt_pattern, timeout=timeout)

            # Collect ALL output including any buffered data
            raw_output = self.shell_process.before

            # Sometimes there's more output after the initial match - try to get it
            try:
                self.shell_process.expect(self.prompt_pattern, timeout=0.5)
                raw_output += self.shell_process.before
            except pexpect.TIMEOUT:
                pass  # No more prompts, that's fine

            # Strip ANSI escape codes
            output = self.strip_ansi(raw_output).strip()

            # Since we switched to JSON output parsing, we no longer need to fragilely
            # match the echoed command line by line. The JSON parser will naturally
            # ignore the echoed command which precedes the JSON block.

            self.log(
                f"Output: {output[:200]}..."
                if len(output) > 200
                else f"Output: {output}"
            )
            return True, output
        except pexpect.TIMEOUT:
            self.log("Timeout waiting for response")
            if self.shell_process:
                self.log(f"Buffer: {self.shell_process.before}")
            return False, "Timeout waiting for response"
        except pexpect.EOF:
            self.log("Shell process ended")
            return False, "Shell process ended unexpectedly"

    def execute_query(self, query: str, timeout: int | None = None) -> dict[str, Any]:
        """Execute a GQL query and return the result."""
        success, output = self.send_command(query, timeout)

        if not success:
            return {"status": "error", "error": output}

        # Parse output to extract result
        result = {
            "status": "success",
            "output": output,
            "rows": 0,
            "data": [],
        }

        # Try to parse JSON output. We look for the JSON object in the output.
        # Since we use --format json, the valid response should be a JSON object
        # containing "status_class" or "result".
        try:
            # Find the JSON block by looking for the first '{' and last '}'
            # This avoids issues with echoed commands or minor warnings before the JSON
            start_idx = output.find("{")
            end_idx = output.rfind("}")

            if start_idx != -1 and end_idx != -1 and end_idx >= start_idx:
                json_str = output[start_idx : end_idx + 1]
                data = json.loads(json_str)

                # Check for error status class (anything not starting with 00)
                status_class = data.get("status_class", "")
                if status_class and not status_class.startswith("00"):
                    # Extract error message
                    error_msg = "Unknown error"
                    if (
                        isinstance(data.get("result"), dict)
                        and "message" in data["result"]
                    ):
                        error_msg = data["result"]["message"]
                    elif "message" in data:
                        error_msg = data["message"]
                    elif "error" in data:
                        error_msg = data["error"]

                    return {
                        "status": "error",
                        "output": output,
                        "error": f"Query error ({status_class}): {error_msg}",
                        "rows": 0,
                        "data": [],
                    }

                # Success path
                if (
                    "result" in data
                    and isinstance(data["result"], dict)
                    and "rows" in data["result"]
                ):
                    result["data"] = data["result"]["rows"]
                    result["rows"] = len(data["result"]["rows"])
                elif isinstance(data.get("result"), list):
                    result["data"] = data["result"]
                    result["rows"] = len(data["result"])

                return result

        except (json.JSONDecodeError, AttributeError):
            pass

        # If it wasn't valid JSON, check for explicit shell errors.
        # Avoid falsely matching "error" in normal query output by checking for shell error prefixes
        if "Error (" in output or "\nError: " in output or output.startswith("Error:"):
            error_match = re.search(r"Error\s*\(([^)]+)\):\s*(.*)", output)
            if error_match:
                error_code = error_match.group(1)
                error_msg = error_match.group(2)
            else:
                error_code = "unknown"
                error_msg = "Unknown error"

            return {
                "status": "error",
                "output": output,
                "error": f"Query error ({error_code}): {error_msg}",
                "rows": 0,
                "data": [],
            }

        # Sometimes a simple array is returned
        try:
            start_idx = output.find("[")
            end_idx = output.rfind("]")
            if start_idx != -1 and end_idx != -1 and end_idx >= start_idx:
                json_str = output[start_idx : end_idx + 1]
                data = json.loads(json_str)
                result["data"] = data
                result["rows"] = len(data)
                return result
        except (json.JSONDecodeError, AttributeError):
            pass

        return result

    def source_file(self, file_path: str, timeout: int | None = None) -> dict[str, Any]:
        """Execute /source command with a file."""
        timeout = timeout or 300  # 5 minutes for large files
        success, output = self.send_command(f"/source {file_path}", timeout)

        if not success:
            return {"status": "error", "error": output}

        # Parse output to extract execution summary
        result = {
            "status": "success",
            "output": output,
        }

        # Look for execution summary in output
        # Expected format: "Executed N statement(s) successfully"
        match = re.search(r"Executed (\d+) statement\(s\)", output)
        if match:
            result["statements_executed"] = int(match.group(1))

        # Check for errors
        if "error" in output.lower() or "Error" in output:
            result["has_errors"] = True
        else:
            result["has_errors"] = False

        return result

    def check_file_exists(self, file_path: str) -> bool:
        """Check if a file exists on the filesystem."""
        return os.path.exists(file_path)

    def get_file_size(self, file_path: str) -> int:
        """Get the size of a file in bytes."""
        try:
            return os.path.getsize(file_path)
        except OSError:
            return -1

    def run_test(self, test: dict[str, Any]) -> dict[str, Any]:
        """Run a single shell test."""
        test_name = test.get("name", "unnamed")
        test_type = test.get("type", "query")

        self.log(f"Running test: {test_name} (type={test_type})")

        result = {
            "test_name": test_name,
            "status": "passed",
            "error": None,
            "details": {},
        }

        try:
            if test_type in ("shell_source", "source"):
                # Test /source command with a file
                result = run_source_test(self, test)
            elif test_type in ("shell_persistence", "persistence"):
                # Test that data persists across server restarts
                result = run_persistence_test(self, test)
            elif test_type in ("shell_query", "query"):
                # Run a query through the shell
                result = run_query_test(self, test)
            elif test_type in ("shell_steps", "steps"):
                # Run a sequence of shell commands
                result = run_steps_test(self, test)
            else:
                result["status"] = "error"
                result["error"] = f"Unknown test type: {test_type}"
        except (
            OSError,
            RuntimeError,
            LookupError,
            ValueError,
            TypeError,
            AttributeError,
            *_PEXPECT_ERRORS,
        ) as e:
            result["status"] = "error"
            result["error"] = str(e)

        return result


def run_spec(
    spec_path: str,
    geode_binary: str = "./zig-out/bin/geode",
    server: str | None = None,
    data_dir: str | None = None,
    verbose: bool = False,
) -> list[dict[str, Any]]:
    """Run all tests in a spec file with proper isolation.

    When the spec has manage_server=True, this function automatically:
    - Allocates a free port for the server (unless server is specified)
    - Creates a unique temp directory for data isolation
    - Starts/stops the server for the test run

    This enables parallel execution of multiple spec files without conflicts.

    Parameters
    ----------
    spec_path : str
        Path to the test specification YAML file.
    geode_binary : str
        Path to the geode binary.
    server : Optional[str]
        Server address. If None and manage_server=True, a free port is allocated.
    data_dir : Optional[str]
        Data directory. If None, a unique temp directory is created.
    verbose : bool
        Enable verbose logging.

    Returns
    -------
    List[Dict[str, Any]]
        List of test results.
    """
    with open(spec_path) as f:
        spec = yaml.safe_load(f)

    results = []
    tests = spec.get("tests", [])

    # Check if this spec requires server management
    manage_server = spec.get("manage_server", spec.get("mode", "server") == "server")

    # Create runner with automatic port allocation if managing server
    runner = ShellTestRunner(
        server=server,
        geode_binary=geode_binary,
        data_dir=data_dir,
        verbose=verbose,
        auto_allocate_port=manage_server and server is None,
    )

    if verbose:
        runner.log(f"Running spec: {spec_path}")
        runner.log(f"Server: {runner.server}, Data dir: {runner.data_dir}")
        runner.log(f"Manage server: {manage_server}")

    if manage_server and not runner.start_server():
        return [
            {
                "status": "error",
                "error": f"Failed to start server on {runner.server}",
            }
        ]

    if not runner.start_shell():
        if manage_server:
            runner.stop_server()
        return [
            {
                "status": "error",
                "error": f"Failed to start shell connecting to {runner.server}",
            }
        ]

    try:
        for test in tests:
            result = runner.run_test(test)
            results.append(result)
    finally:
        runner.stop_shell()
        if manage_server:
            runner.stop_server()

    return results


def main():
    parser = argparse.ArgumentParser(description="Geode shell test runner")
    parser.add_argument(
        "--spec", required=True, help="Path to test specification YAML file"
    )
    parser.add_argument(
        "--server",
        default=None,
        help="Server address (auto-allocated if not specified and manage_server=true)",
    )
    parser.add_argument(
        "--geode-binary",
        default=None,
        help="Path to geode binary (auto-detected if not specified)",
    )
    parser.add_argument(
        "--data-dir", help="Data directory for server (auto-created if not specified)"
    )
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")
    parser.add_argument("--json", action="store_true", help="Output results as JSON")

    args = parser.parse_args()

    if not PEXPECT_AVAILABLE:
        print(json.dumps({"status": "error", "error": "pexpect not installed"}))
        sys.exit(1)

    # Find geode binary
    try:
        geode_binary = find_geode_binary(args.geode_binary)
    except FileNotFoundError as e:
        print(json.dumps({"status": "error", "error": str(e)}))
        sys.exit(1)

    results = run_spec(
        spec_path=args.spec,
        geode_binary=geode_binary,
        server=args.server,
        data_dir=args.data_dir,
        verbose=args.verbose,
    )

    if args.json:
        print(json.dumps(results, indent=2))
    else:
        for result in results:
            status = result.get("status", "unknown")
            name = result.get("test_name", "unnamed")
            error = result.get("error", "")

            if status == "passed":
                print(f"✓ {name}")
            else:
                print(f"✗ {name}: {error}")

    # Exit with non-zero if any test failed
    if any(r.get("status") != "passed" for r in results):
        sys.exit(1)


if __name__ == "__main__":
    main()
