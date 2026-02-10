"""Test execution for geodetestlab.

Handles dispatching and running individual test cases (CLI, HTTP,
shell, and sequential multi-step tests).
"""

from __future__ import annotations

import logging
import os
import shlex
import subprocess
import time
from pathlib import Path

import httpx

from .checks import check_expectations, check_http_expectations
from .spec import PlaintextCheck, TestCase

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
DEFAULT_QUIC_PORT = 3141
DEFAULT_GRPC_PORT = 50051
DEFAULT_ADMIN_PASSWORD = os.environ.get(
    "GEODE_ADMIN_PASSWORD", "GeodeTestPassword123!"
)
DEFAULT_HTTP_TIMEOUT_S = 30.0
DEFAULT_SHELL_TIMEOUT_S = 30.0
SSL_VERIFY = os.environ.get("GEODE_VERIFY_SSL", "0").lower() in ("1", "true", "yes")


# Re-export TestResult so runner.py doesn't need a separate import
from .runner_types import TestResult  # noqa: E402


def run_single_test(
    test_case: TestCase,
    binary: str,
    env: dict[str, str],
    secrets: dict[str, str],
    timeout_ms: int,
    data_dir: Path | None,
    verbose: bool,
) -> TestResult:
    """Run a single test case, dispatching by test type."""
    if test_case.test_type == "http":
        return _run_http_test(test_case, env, verbose)
    elif test_case.test_type == "sequential":
        return _run_sequential_test(test_case, binary, env, secrets, timeout_ms, data_dir, verbose)
    elif test_case.test_type == "shell":
        return _run_shell_test(test_case, env, verbose)

    # CLI test (default)
    return run_cli_test(test_case, binary, env, secrets, timeout_ms, data_dir, verbose)


def run_cli_test(
    test_case: TestCase,
    binary: str,
    env: dict[str, str],
    secrets: dict[str, str],
    timeout_ms: int,
    data_dir: Path | None,
    verbose: bool,
) -> TestResult:
    """Run a CLI test case."""
    start_time = time.time()

    # Create setup files if defined (e.g., for --file flag tests)
    if test_case.setup_files:
        for file_spec in test_case.setup_files:
            file_path = file_spec.get("path", "")
            file_content = file_spec.get("content", "")
            if file_path and file_content:
                try:
                    Path(file_path).parent.mkdir(parents=True, exist_ok=True)
                    with open(file_path, "w") as f:
                        f.write(file_content)
                except Exception as e:
                    return TestResult(
                        name=test_case.name,
                        passed=False,
                        duration_ms=(time.time() - start_time) * 1000,
                        error=f"Failed to create setup file {file_path}: {e}",
                    )

    # Get authentication credentials from environment
    admin_password = env.get("GEODE_ADMIN_PASSWORD", DEFAULT_ADMIN_PASSWORD)

    # Transport-aware server address and flags
    use_grpc = env.get("GEODE_TRANSPORT") == "grpc"
    if use_grpc:
        server_addr = env.get("GEODE_GRPC_ADDRESS", env.get("GEODE_SERVER_ADDRESS", f"127.0.0.1:{DEFAULT_GRPC_PORT}"))
    else:
        server_addr = env.get("GEODE_SERVER_ADDRESS", f"127.0.0.1:{DEFAULT_QUIC_PORT}")

    # Determine if this is a query test or command test
    # Helper to detect if a string looks like a GQL query
    def _is_gql_query(text: str) -> bool:
        if not text:
            return False
        text_upper = text.strip().upper()
        gql_keywords = ["CREATE", "MATCH", "RETURN", "MERGE", "DELETE", "SET", "UNWIND", "WITH", "CALL", "OPTIONAL"]
        return any(text_upper.startswith(kw) for kw in gql_keywords)

    if test_case.query:
        cmd = [binary, "query", test_case.query]
        cmd.extend(["--server", server_addr])
        if use_grpc:
            cmd.append("--grpc")
        else:
            cmd.extend(["--insecure"])
        cmd.extend(["-U", "geode", "-P", admin_password])
    elif test_case.command and _is_gql_query(test_case.command):
        # Command field contains GQL - route to query handler
        cmd = [binary, "query", test_case.command]
        cmd.extend(["--server", server_addr])
        if use_grpc:
            cmd.append("--grpc")
        else:
            cmd.extend(["--insecure"])
        cmd.extend(["-U", "geode", "-P", admin_password])
    elif test_case.command:
        # Substitute variables in command string
        command_str = test_case.command
        # Replace relative geode binary paths with the resolved binary path
        # Process longer paths first to avoid partial matches, and only replace once
        for geode_path in ["./zig-out/bin/geode", "zig-out/bin/geode"]:
            if geode_path in command_str:
                command_str = command_str.replace(geode_path, binary, 1)
                break  # Only replace the first matching pattern once
        if data_dir:
            command_str = command_str.replace("${data_dir}", str(data_dir))
        for key, value in env.items():
            command_str = command_str.replace(f"${{{key}}}", value)
            command_str = command_str.replace(f"${{env:{key}}}", value)
        for key, value in secrets.items():
            command_str = command_str.replace(f"${{secret:{key}}}", value)

        # Inject auth credentials if this is a query command without auth flags
        if "query" in command_str and "-U" not in command_str and "-P" not in command_str:
            # Find where to insert auth flags (before the trailing '-' if present, or at end)
            command_str = command_str.strip()
            if command_str.endswith(" -"):
                command_str = command_str[:-2] + f" -U geode -P {admin_password} -"
            else:
                command_str += f" -U geode -P {admin_password}"

        # Inject gRPC transport flag for query commands
        if use_grpc and "query" in command_str and "--grpc" not in command_str:
            command_str += " --grpc"
            # Replace server address with gRPC address if present
            quic_addr = env.get("GEODE_SERVER_ADDRESS", "")
            grpc_addr = env.get("GEODE_GRPC_ADDRESS", "")
            if quic_addr and grpc_addr and quic_addr in command_str:
                command_str = command_str.replace(quic_addr, grpc_addr)
        elif use_grpc and "query" not in command_str:
            logger.warning(
                "gRPC transport requested but command '%s' is not a query — "
                "falling back to QUIC for admin commands",
                command_str.split()[1] if len(command_str.split()) > 1 else command_str,
            )

        # Shell command test - detect shell metacharacters
        shell_metacharacters = ["|", "&&", "||", ";", "$(", "`", ">", "<"]
        if any(mc in command_str for mc in shell_metacharacters):
            # Complex shell command - run through bash
            args = substitute_variables(test_case.args, env, secrets, data_dir)
            if args:
                command_str += " " + " ".join(args)
            cmd = ["bash", "-c", command_str]
        else:
            cmd = shlex.split(command_str)
            args = substitute_variables(test_case.args, env, secrets, data_dir)
            cmd.extend(args)
    else:
        cmd = [binary]
        args = substitute_variables(test_case.args, env, secrets, data_dir)
        cmd.extend(args)
        # If this is a query command via args, add server, insecure, and auth flags
        if args and args[0] == "query" and len(args) > 1:
            if "--server" not in args:
                cmd.extend(["--server", server_addr])
            if use_grpc and "--grpc" not in args:
                cmd.append("--grpc")
            elif not use_grpc and "--insecure" not in args:
                cmd.extend(["--insecure"])
            if "-U" not in args:
                cmd.extend(["-U", "geode", "-P", admin_password])

    # Merge test-specific environment
    test_env = env.copy()
    test_env.update(test_case.env)

    try:
        # Substitute variables in stdin if present
        stdin_input = test_case.stdin
        if stdin_input and data_dir:
            stdin_input = stdin_input.replace("${data_dir}", str(data_dir))
            for key, value in env.items():
                stdin_input = stdin_input.replace(f"${{{key}}}", value)
                stdin_input = stdin_input.replace(f"${{env:{key}}}", value)
            for key, value in secrets.items():
                stdin_input = stdin_input.replace(f"${{secret:{key}}}", value)

        result = subprocess.run(
            cmd,
            env=test_env,
            capture_output=True,
            text=True,
            timeout=timeout_ms / 1000.0,
            input=stdin_input,  # Pass stdin content to the subprocess
        )

        output = result.stdout
        error = result.stderr
        exit_code = result.returncode

    except subprocess.TimeoutExpired:
        return TestResult(
            name=test_case.name,
            passed=False,
            duration_ms=(time.time() - start_time) * 1000,
            error=f"Test timed out after {timeout_ms}ms",
        )
    except Exception as e:
        return TestResult(
            name=test_case.name,
            passed=False,
            duration_ms=(time.time() - start_time) * 1000,
            error=str(e),
        )

    duration_ms = (time.time() - start_time) * 1000

    # Check expectations
    passed = check_expectations(
        test_case=test_case,
        output=output,
        error=error,
        exit_code=exit_code,
    )

    # Debug output for failures
    if not passed and verbose:
        print(f"    Exit code: {exit_code}")
        print(f"    Stdout: {output[:200] if output else '(empty)'}")
        print(f"    Stderr: {error[:200] if error else '(empty)'}")

    # Run test-specific plaintext verification if enabled
    plaintext_violations: list[str] = []
    if test_case.plaintext_check.enabled and data_dir:
        plaintext_violations = run_plaintext_verification(
            data_dir=data_dir,
            config=test_case.plaintext_check,
            verbose=verbose,
        )
        if plaintext_violations and test_case.plaintext_check.fail_on_violation:
            passed = False

    return TestResult(
        name=test_case.name,
        passed=passed,
        duration_ms=duration_ms,
        output=output,
        error=error if not passed else "",
        plaintext_violations=plaintext_violations,
    )


def _run_http_test(
    test_case: TestCase,
    env: dict[str, str],
    verbose: bool,
) -> TestResult:
    """Run an HTTP test case."""
    start_time = time.time()
    outputs: list[str] = []
    errors: list[str] = []

    try:
        # Create an HTTP client with connection reuse
        with httpx.Client(timeout=DEFAULT_HTTP_TIMEOUT_S, verify=SSL_VERIFY) as client:
            for i, req in enumerate(test_case.http_requests):
                # Substitute environment variables in URL
                url = req.url
                for key, value in env.items():
                    url = url.replace(f"${{{key}}}", value)
                    url = url.replace(f"${{env:{key}}}", value)

                if verbose:
                    print(f"  HTTP {req.method} {url}")

                try:
                    response = client.request(
                        method=req.method,
                        url=url,
                        headers=req.headers,
                        content=req.body,
                        timeout=req.timeout_ms / 1000.0,
                    )

                    # Check expectations for this request
                    passed = check_http_expectations(response, req.expected, verbose)

                    if not passed:
                        errors.append(
                            f"Request {i+1} failed: {req.method} {url}\n"
                            f"Status: {response.status_code}\n"
                            f"Body: {response.text[:500]}"
                        )
                        return TestResult(
                            name=test_case.name,
                            passed=False,
                            duration_ms=(time.time() - start_time) * 1000,
                            output="\n".join(outputs),
                            error="\n".join(errors),
                        )

                    outputs.append(f"Request {i+1}: {response.status_code} OK")

                except httpx.RequestError as e:
                    errors.append(f"Request {i+1} error: {e}")
                    return TestResult(
                        name=test_case.name,
                        passed=False,
                        duration_ms=(time.time() - start_time) * 1000,
                        output="\n".join(outputs),
                        error="\n".join(errors),
                    )

    except Exception as e:
        return TestResult(
            name=test_case.name,
            passed=False,
            duration_ms=(time.time() - start_time) * 1000,
            error=str(e),
        )

    return TestResult(
        name=test_case.name,
        passed=True,
        duration_ms=(time.time() - start_time) * 1000,
        output="\n".join(outputs),
    )


def _run_shell_test(
    test_case: TestCase,
    env: dict[str, str],
    verbose: bool,
) -> TestResult:
    """Run a shell test case.

    Shell tests execute bash commands/scripts, typically used for source code
    verification tests that grep for patterns in the codebase.
    """
    start_time = time.time()

    # Get the command to execute
    command = test_case.command
    if not command:
        return TestResult(
            name=test_case.name,
            passed=False,
            duration_ms=(time.time() - start_time) * 1000,
            error="Shell test missing 'command' field",
        )

    # Determine the working directory - shell tests typically need to run from Geode source
    # The test harness is in geode-test-harness, and geode source is in ../geode
    harness_dir = Path(__file__).parent.parent.parent.parent.parent
    geode_source = harness_dir / "geode"

    # If geode source doesn't exist, try the parent directory structure
    if not geode_source.exists():
        # Try /home/benji/src/gl/devnw/codepros/geode/geode
        geode_source = Path("/home/benji/src/gl/devnw/codepros/geode/geode")

    if not geode_source.exists():
        return TestResult(
            name=test_case.name,
            passed=False,
            duration_ms=(time.time() - start_time) * 1000,
            error=f"Geode source directory not found: {geode_source}",
        )

    # Merge test-specific environment
    test_env = env.copy()
    test_env.update(test_case.env)

    try:
        result = subprocess.run(
            ["bash", "-c", command],
            env=test_env,
            capture_output=True,
            text=True,
            timeout=DEFAULT_SHELL_TIMEOUT_S,
            cwd=str(geode_source),  # Run from Geode source directory
        )

        stdout = result.stdout
        stderr = result.stderr
        exit_code = result.returncode

        # Use full expectation checking (same as CLI tests)
        passed = check_expectations(
            test_case=test_case,
            output=stdout,
            error=stderr,
            exit_code=exit_code,
        )

        if verbose:
            status = "PASS" if passed else "FAIL"
            print(f"    Shell: exit_code={exit_code} [{status}]")
            if stdout.strip():
                print(f"    stdout: {stdout.strip()[:200]}")
            if stderr.strip() and not passed:
                print(f"    stderr: {stderr.strip()[:200]}")

        return TestResult(
            name=test_case.name,
            passed=passed,
            duration_ms=(time.time() - start_time) * 1000,
            output=stdout,
            error=stderr if not passed else None,
        )

    except subprocess.TimeoutExpired:
        return TestResult(
            name=test_case.name,
            passed=False,
            duration_ms=(time.time() - start_time) * 1000,
            error="Shell test timed out after 30 seconds",
        )
    except Exception as e:
        return TestResult(
            name=test_case.name,
            passed=False,
            duration_ms=(time.time() - start_time) * 1000,
            error=str(e),
        )


def _run_sequential_test(
    test_case: TestCase,
    binary: str,
    env: dict[str, str],
    secrets: dict[str, str],
    timeout_ms: int,
    data_dir: Path | None,
    verbose: bool,
) -> TestResult:
    """Run a sequential test case with multiple steps."""
    start_time = time.time()
    outputs: list[str] = []
    errors: list[str] = []

    # Get authentication credentials from environment
    admin_password = env.get("GEODE_ADMIN_PASSWORD", DEFAULT_ADMIN_PASSWORD)

    # Transport-aware server address and flags
    use_grpc = env.get("GEODE_TRANSPORT") == "grpc"
    if use_grpc:
        server_addr = env.get("GEODE_GRPC_ADDRESS", env.get("GEODE_SERVER_ADDRESS", f"127.0.0.1:{DEFAULT_GRPC_PORT}"))
    else:
        server_addr = env.get("GEODE_SERVER_ADDRESS", f"127.0.0.1:{DEFAULT_QUIC_PORT}")

    try:
        # Create an HTTP client for HTTP steps
        with httpx.Client(timeout=DEFAULT_HTTP_TIMEOUT_S, verify=SSL_VERIFY) as http_client:
            for i, step in enumerate(test_case.steps):
                if verbose:
                    print(f"  Step {i+1}: {step.step_type}")

                if step.step_type == "wait":
                    time.sleep(step.wait_ms / 1000.0)
                    outputs.append(f"Step {i+1}: waited {step.wait_ms}ms")

                elif step.step_type == "http":
                    # Execute HTTP step
                    url = step.url or ""
                    for key, value in env.items():
                        url = url.replace(f"${{{key}}}", value)
                        url = url.replace(f"${{env:{key}}}", value)

                    response = http_client.request(
                        method=step.method or "GET",
                        url=url,
                        headers=step.headers,
                        content=step.body,
                        timeout=step.timeout_ms / 1000.0,
                    )

                    if step.expected:
                        passed = check_http_expectations(response, step.expected, verbose)
                        if not passed:
                            errors.append(f"Step {i+1} failed: HTTP {step.method} {url}")
                            return TestResult(
                                name=test_case.name,
                                passed=False,
                                duration_ms=(time.time() - start_time) * 1000,
                                output="\n".join(outputs),
                                error="\n".join(errors),
                            )

                    outputs.append(f"Step {i+1}: HTTP {response.status_code} OK")

                elif step.step_type == "gql":
                    # Execute GQL query step
                    cmd = [binary, "query", step.query or ""]
                    cmd.extend(["--server", server_addr])
                    if use_grpc:
                        cmd.append("--grpc")
                    else:
                        cmd.extend(["--insecure"])
                    cmd.extend(["-U", "geode", "-P", admin_password])

                    result = subprocess.run(
                        cmd,
                        env=env,
                        capture_output=True,
                        text=True,
                        timeout=step.timeout_ms / 1000.0,
                    )

                    if step.gql_expected:
                        # Check GQL expectations
                        expected_status = step.gql_expected.get("status_class")
                        if expected_status and expected_status not in result.stdout:
                            errors.append(f"Step {i+1} failed: expected status {expected_status}")
                            return TestResult(
                                name=test_case.name,
                                passed=False,
                                duration_ms=(time.time() - start_time) * 1000,
                                output="\n".join(outputs),
                                error="\n".join(errors),
                            )

                    outputs.append(f"Step {i+1}: GQL OK")

    except Exception as e:
        return TestResult(
            name=test_case.name,
            passed=False,
            duration_ms=(time.time() - start_time) * 1000,
            error=str(e),
        )

    return TestResult(
        name=test_case.name,
        passed=True,
        duration_ms=(time.time() - start_time) * 1000,
        output="\n".join(outputs),
    )


def substitute_variables(
    args: list[str],
    env: dict[str, str],
    secrets: dict[str, str],
    data_dir: Path | None,
) -> list[str]:
    """Substitute variables in argument list."""
    result = []
    for arg in args:
        # Substitute ${data_dir}
        if data_dir:
            arg = arg.replace("${data_dir}", str(data_dir))

        # Substitute ${env:VAR}
        for key, value in env.items():
            arg = arg.replace(f"${{{key}}}", value)
            arg = arg.replace(f"${{env:{key}}}", value)

        # Substitute ${secret:NAME}
        for key, value in secrets.items():
            arg = arg.replace(f"${{secret:{key}}}", value)

        result.append(arg)
    return result


def run_plaintext_verification(
    data_dir: Path,
    config: PlaintextCheck,
    verbose: bool,
) -> list[str]:
    """Run plaintext verification scan on data directory."""
    violations = []

    for pattern in config.search_patterns:
        try:
            # Use grep to search for plaintext patterns in all files
            result = subprocess.run(
                ["grep", "-r", "-a", "-l", pattern, str(data_dir)],
                capture_output=True,
                text=True,
                timeout=60,
            )

            if result.returncode == 0:
                # Pattern was found - this is a violation!
                matching_files = result.stdout.strip().split("\n")
                for file_path in matching_files:
                    if file_path:
                        # Filter out excluded extensions
                        skip = False
                        for ext in config.exclude_extensions:
                            if file_path.endswith(ext):
                                skip = True
                                break
                        if not skip:
                            violations.append(f"Pattern '{pattern}' found in: {file_path}")
                            if verbose:
                                print(f"  VIOLATION: '{pattern}' in {file_path}")

        except subprocess.TimeoutExpired:
            if verbose:
                print(f"  WARNING: Grep timeout for pattern '{pattern}'")
        except Exception as e:
            if verbose:
                print(f"  WARNING: Error scanning for '{pattern}': {e}")

    return violations
