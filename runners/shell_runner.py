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
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml

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
        server: Optional[str] = None,
        geode_binary: str = "./zig-out/bin/geode",
        data_dir: Optional[str] = None,
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
        self.shell_process: Optional[pexpect.spawn] = None
        self.server_manager: Optional[ServerManager] = None
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

        # Use --plain mode for automated testing - disables terminal control sequences
        # that interfere with output capture. Also use table format for easier parsing.
        cmd = f"{self.geode_binary} shell --server {self.server} --insecure --format table --no-history --plain"
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
        except Exception as e:
            self.log(f"Failed to start shell: {e}")
            return False

    def stop_shell(self):
        """Stop the shell session."""
        if self.shell_process:
            self.log("Stopping shell")
            try:
                self.shell_process.sendline("/quit")
                self.shell_process.expect(pexpect.EOF, timeout=5)
            except Exception:
                pass
            finally:
                if self.shell_process.isalive():
                    self.shell_process.terminate(force=True)
                self.shell_process = None

    def send_command(
        self, command: str, timeout: Optional[int] = None
    ) -> Tuple[bool, str]:
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
            output = self.strip_ansi(raw_output)

            # The output contains: echoed command + newline + actual output
            # Find and remove the echoed command
            lines = output.split("\n")

            # Find where the echoed command ends
            cmd_prefix = command.strip()[:20] if len(command) > 20 else command.strip()
            output_start = 0
            for i, line in enumerate(lines):
                if cmd_prefix in line:
                    output_start = i + 1
                    break

            # Get the actual output (everything after the echoed command)
            output_lines = lines[output_start:]

            # Clean up: remove empty lines at start/end
            while output_lines and not output_lines[0].strip():
                output_lines.pop(0)
            while output_lines and not output_lines[-1].strip():
                output_lines.pop()

            output = "\n".join(output_lines)
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

    def execute_query(
        self, query: str, timeout: Optional[int] = None
    ) -> Dict[str, Any]:
        """Execute a GQL query and return the result."""
        success, output = self.send_command(query, timeout)

        if not success:
            return {"status": "error", "error": output}

        # Check for error in output
        if "Error" in output or "error" in output.lower():
            # Extract error code if present
            error_match = re.search(r"Error\s*\(([^)]+)\)", output)
            error_code = error_match.group(1) if error_match else "unknown"
            return {
                "status": "error",
                "output": output,
                "error": f"Query error: {error_code}",
                "rows": 0,
                "data": [],
            }

        # Parse output to extract result
        result = {
            "status": "success",
            "output": output,
            "rows": 0,
            "data": [],
        }

        # Try to parse JSON output (when shell is started with --format json)
        # Shell outputs: {"status_class":"00000","result":{"type":"BINDINGS",...,"rows":[...]}}
        try:
            # Find JSON object in output (shell format)
            json_match = re.search(
                r'\{[^{}]*"status_class"[^{}]*\{.*\}\}', output, re.DOTALL
            )
            if json_match:
                data = json.loads(json_match.group())
                if "result" in data and "rows" in data["result"]:
                    result["data"] = data["result"]["rows"]
                    result["rows"] = len(data["result"]["rows"])
                    return result
        except (json.JSONDecodeError, AttributeError):
            pass

        # Try simple JSON array format
        try:
            json_match = re.search(r"\[.*\]", output, re.DOTALL)
            if json_match:
                data = json.loads(json_match.group())
                result["data"] = data
                result["rows"] = len(data)
                return result
        except (json.JSONDecodeError, AttributeError):
            pass

        # Fallback: Try to parse table output
        # Tables look like:
        # +-------+-------+
        # | col1  | col2  |
        # +-------+-------+
        # | val1  | val2  |
        # +-------+-------+
        lines = output.strip().split("\n")

        # Filter to data lines (those starting with |)
        data_lines = [
            line
            for line in lines
            if line.strip().startswith("|") and not line.strip().startswith("|--")
        ]

        # Subtract 1 for header row if we have any data lines
        if len(data_lines) > 1:
            result["rows"] = len(data_lines) - 1
        elif len(data_lines) == 1:
            # Just header, no data
            result["rows"] = 0
        else:
            # Try alternative: count non-border, non-empty lines
            non_border_lines = [
                line
                for line in lines
                if line.strip()
                and not line.startswith("+")
                and not line.startswith("---")
            ]
            if non_border_lines:
                result["rows"] = max(0, len(non_border_lines) - 1)

        return result

    def source_file(
        self, file_path: str, timeout: Optional[int] = None
    ) -> Dict[str, Any]:
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

    def run_test(self, test: Dict[str, Any]) -> Dict[str, Any]:
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
            if test_type == "shell_source":
                # Test /source command with a file
                result = self._run_source_test(test)
            elif test_type == "shell_persistence":
                # Test that data persists across server restarts
                result = self._run_persistence_test(test)
            elif test_type == "shell_query":
                # Run a query through the shell
                result = self._run_query_test(test)
            elif test_type == "shell_steps":
                # Run a sequence of shell commands
                result = self._run_steps_test(test)
            else:
                result["status"] = "error"
                result["error"] = f"Unknown test type: {test_type}"
        except Exception as e:
            result["status"] = "error"
            result["error"] = str(e)

        return result

    def _run_source_test(self, test: Dict[str, Any]) -> Dict[str, Any]:
        """Run a /source file test."""
        result = {
            "test_name": test.get("name", "unnamed"),
            "status": "passed",
            "error": None,
            "details": {},
        }

        # Create the source file if content is provided
        source_content = test.get("source_content")
        source_file = test.get("source_file")

        if source_content:
            # Write content to a temporary file
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".gql", delete=False
            ) as f:
                f.write(source_content)
                source_file = f.name
            result["details"]["temp_file"] = source_file

        if not source_file:
            result["status"] = "error"
            result["error"] = "No source_file or source_content provided"
            return result

        # Execute /source
        source_result = self.source_file(
            source_file, test.get("timeout_ms", 300000) // 1000
        )
        result["details"]["source_result"] = source_result

        # Check expectations
        expect = test.get("expect", {})

        if expect.get("success", True) and source_result.get("has_errors"):
            result["status"] = "failed"
            result["error"] = (
                f"Expected success but got errors: {source_result.get('output', '')[:500]}"
            )

        if "statements" in expect:
            actual = source_result.get("statements_executed", 0)
            expected = expect["statements"]
            if actual != expected:
                result["status"] = "failed"
                result["error"] = f"Expected {expected} statements, got {actual}"

        # Clean up temp file if created
        if source_content and source_file:
            try:
                os.unlink(source_file)
            except OSError:
                pass

        return result

    def _run_persistence_test(self, test: Dict[str, Any]) -> Dict[str, Any]:
        """Run a persistence test - verifies data survives server restart."""
        result = {
            "test_name": test.get("name", "unnamed"),
            "status": "passed",
            "error": None,
            "details": {},
        }

        steps = test.get("steps", [])

        for i, step in enumerate(steps):
            step_type = step.get("type")

            if step_type == "create_data":
                # Create data via shell
                source_content = step.get("content")
                if source_content:
                    with tempfile.NamedTemporaryFile(
                        mode="w", suffix=".gql", delete=False
                    ) as f:
                        f.write(source_content)
                        temp_file = f.name

                    source_result = self.source_file(temp_file)
                    result["details"][f"step_{i}_source"] = source_result

                    os.unlink(temp_file)

                    if source_result.get("has_errors"):
                        result["status"] = "failed"
                        result["error"] = (
                            f"Step {i} failed: {source_result.get('output', '')[:500]}"
                        )
                        return result

            elif step_type == "check_persistence_file":
                # Check that the persistence file exists and has data
                persistence_file = os.path.join(self.data_dir, "graph_store.dat")

                if not self.check_file_exists(persistence_file):
                    result["status"] = "failed"
                    result["error"] = f"Persistence file not found: {persistence_file}"
                    return result

                file_size = self.get_file_size(persistence_file)
                result["details"]["persistence_file_size"] = file_size

                min_size = step.get("min_size", 0)
                if file_size < min_size:
                    result["status"] = "failed"
                    result["error"] = (
                        f"Persistence file too small: {file_size} < {min_size}"
                    )
                    return result

            elif step_type == "restart_server":
                # Restart the server to test persistence
                self.stop_shell()
                self.stop_server()

                time.sleep(1)

                if not self.start_server():
                    result["status"] = "failed"
                    result["error"] = "Failed to restart server"
                    return result

                if not self.start_shell():
                    result["status"] = "failed"
                    result["error"] = "Failed to reconnect shell after restart"
                    return result

            elif step_type == "verify_data":
                # Verify data exists after restart
                query = step.get("query")
                if query:
                    query_result = self.execute_query(query)
                    result["details"][f"step_{i}_verify"] = query_result

                    expect = step.get("expect", {})
                    if "min_rows" in expect:
                        if query_result.get("rows", 0) < expect["min_rows"]:
                            result["status"] = "failed"
                            result["error"] = (
                                f"Expected at least {expect['min_rows']} rows, got {query_result.get('rows', 0)}"
                            )
                            return result

        return result

    def _run_query_test(self, test: Dict[str, Any]) -> Dict[str, Any]:
        """Run a simple query test through the shell."""
        result = {
            "test_name": test.get("name", "unnamed"),
            "status": "passed",
            "error": None,
            "details": {},
        }

        query = test.get("query")
        if not query:
            result["status"] = "error"
            result["error"] = "No query provided"
            return result

        query_result = self.execute_query(query)
        result["details"]["query_result"] = query_result

        expect = test.get("expect", {})

        if query_result.get("status") == "error":
            if not expect.get("error"):
                result["status"] = "failed"
                result["error"] = f"Query failed: {query_result.get('error')}"

        if "rows" in expect:
            actual = query_result.get("rows", 0)
            expected = expect["rows"]
            if actual != expected:
                result["status"] = "failed"
                result["error"] = f"Expected {expected} rows, got {actual}"

        return result

    def _run_steps_test(self, test: Dict[str, Any]) -> Dict[str, Any]:
        """Run a multi-step shell test."""
        result = {
            "test_name": test.get("name", "unnamed"),
            "status": "passed",
            "error": None,
            "details": {},
        }

        steps = test.get("steps", [])

        for i, step in enumerate(steps):
            step_type = step.get("type")

            if step_type == "command":
                cmd = step.get("text")
                success, output = self.send_command(
                    cmd, step.get("timeout_ms", 30000) // 1000
                )
                result["details"][f"step_{i}"] = {
                    "command": cmd,
                    "success": success,
                    "output": output[:500],
                }

                if not success:
                    result["status"] = "failed"
                    result["error"] = f"Step {i} failed: {output}"
                    return result

                # Check expectations
                expect = step.get("expect", {})
                if "contains" in expect:
                    for expected_text in expect["contains"]:
                        if expected_text not in output:
                            result["status"] = "failed"
                            result["error"] = (
                                f"Step {i}: Expected output to contain '{expected_text}'"
                            )
                            return result

            elif step_type == "query":
                query = step.get("text")
                query_result = self.execute_query(query)
                result["details"][f"step_{i}"] = query_result

                if query_result.get("status") == "error":
                    result["status"] = "failed"
                    result["error"] = (
                        f"Step {i} query failed: {query_result.get('error')}"
                    )
                    return result

        return result


def run_spec(
    spec_path: str,
    geode_binary: str = "./zig-out/bin/geode",
    server: Optional[str] = None,
    data_dir: Optional[str] = None,
    verbose: bool = False,
) -> List[Dict[str, Any]]:
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
    manage_server = spec.get("manage_server", False)

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

    if manage_server:
        if not runner.start_server():
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
