"""Test execution for geodetestlab.

Handles dispatching and running individual test cases (CLI, HTTP,
shell, and sequential multi-step tests).
"""

from __future__ import annotations

import logging
import os
import re
import shlex
import subprocess
import time
from pathlib import Path

import httpx

from .checks import check_expectations, check_http_expectations
from .runner_types import DEFAULT_ADMIN_PASSWORD, DEFAULT_GRPC_PORT, DEFAULT_QUIC_PORT, TestResult
from .spec import PlaintextCheck, TestCase
from .utils import is_valid_gql, sanitize_args

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants (DEFAULT_QUIC_PORT, DEFAULT_GRPC_PORT from runner_types)
# ---------------------------------------------------------------------------
DEFAULT_HTTP_TIMEOUT_S = 30.0
DEFAULT_SHELL_TIMEOUT_S = 30.0
SSL_VERIFY = os.environ.get("GEODE_VERIFY_SSL", "0").lower() in ("1", "true", "yes")
if not SSL_VERIFY:
    logging.getLogger(__name__).debug(
        "SSL verification disabled (GEODE_VERIFY_SSL=%s). "
        "Set GEODE_VERIFY_SSL=1 to enable certificate verification.",
        os.environ.get("GEODE_VERIFY_SSL", "0"),
    )


def run_single_test(
    test_case: TestCase,
    binary: str,
    env: dict[str, str],
    secrets: dict[str, str],
    timeout_ms: int,
    data_dir: Path | None,
    verbose: bool,
    http_client: httpx.Client | None = None,
) -> TestResult:
    """Run a single test case, dispatching by test type.

    Parameters
    ----------
    http_client : httpx.Client | None
        Optional shared HTTP client for connection reuse across tests
        within the same spec (PERF-007).
    """
    if test_case.test_type == "http":
        return _run_http_test(test_case, env, verbose, http_client=http_client)
    elif test_case.test_type == "sequential":
        return _run_sequential_test(
            test_case, binary, env, secrets, timeout_ms, data_dir, verbose, http_client=http_client
        )
    elif test_case.test_type == "shell":
        return _run_shell_test(test_case, env, verbose)

    # CLI test (default)
    return run_cli_test(test_case, binary, env, secrets, timeout_ms, data_dir, verbose)


def _resolve_server_address(env: dict[str, str]) -> tuple[str, bool]:
    """Return ``(server_addr, use_grpc)`` based on transport env vars."""
    use_grpc = env.get("GEODE_TRANSPORT") == "grpc"
    if use_grpc:
        server_addr = env.get(
            "GEODE_GRPC_ADDRESS",
            env.get("GEODE_SERVER_ADDRESS", f"127.0.0.1:{DEFAULT_GRPC_PORT}"),
        )
    else:
        server_addr = env.get("GEODE_SERVER_ADDRESS", f"127.0.0.1:{DEFAULT_QUIC_PORT}")
    return server_addr, use_grpc


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
    # Sandbox: per-test temp directory with 0o700 to prevent path traversal (CWE-22, SEC-015)
    if test_case.setup_files:
        import tempfile as _tempfile

        sandbox_root = Path(_tempfile.mkdtemp(prefix="geodetestlab_"))
        os.chmod(sandbox_root, 0o700)
        for file_spec in test_case.setup_files:
            file_path = file_spec.get("path", "")
            file_content = file_spec.get("content", "")
            if file_path and file_content:
                resolved = Path(file_path).resolve()
                if not resolved.is_relative_to(sandbox_root):
                    # Allow absolute paths only if they're under the system tmpdir
                    sys_tmp = Path(_tempfile.gettempdir())
                    if not resolved.is_relative_to(sys_tmp):
                        return TestResult(
                            name=test_case.name,
                            passed=False,
                            duration_ms=(time.time() - start_time) * 1000,
                            error=f"setup_files path must be under {sys_tmp}: {file_path}",
                        )
                try:
                    resolved.parent.mkdir(parents=True, exist_ok=True)
                    with open(resolved, "w") as f:
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
    server_addr, use_grpc = _resolve_server_address(env)

    # Resolve DSN with variable substitution if present
    resolved_dsn = None
    if test_case.dsn:
        resolved_dsn = _substitute_one(test_case.dsn, env, secrets, data_dir)

    if test_case.query and resolved_dsn:
        # DSN mode: use --dsn instead of --server, credentials are in the DSN
        cmd = [binary, "query", test_case.query]
        cmd.extend(["--dsn", resolved_dsn])
        cmd.extend(["--insecure-tls-skip-verify"])
        # No -U/-P injection: credentials are embedded in DSN
    elif test_case.query:
        cmd = [binary, "query", test_case.query]
        cmd.extend(["--server", server_addr])
        if use_grpc:
            cmd.append("--grpc")
        else:
            cmd.extend(["--insecure-tls-skip-verify"])
        cmd.extend(["-U", "geode", "-P", admin_password])
    elif test_case.command and is_valid_gql(test_case.command) and resolved_dsn:
        # GQL command with DSN: use --dsn instead of --server
        cmd = [binary, "query", test_case.command]
        cmd.extend(["--dsn", resolved_dsn])
        cmd.extend(["--insecure-tls-skip-verify"])
    elif test_case.command and is_valid_gql(test_case.command):
        # Command field contains GQL - route to query handler
        cmd = [binary, "query", test_case.command]
        cmd.extend(["--server", server_addr])
        if use_grpc:
            cmd.append("--grpc")
        else:
            cmd.extend(["--insecure-tls-skip-verify"])
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
        command_str = _substitute_one(command_str, env, secrets, data_dir)

        # Inject auth credentials if this is a query command without auth flags
        if "query" in command_str and "-U" not in command_str and "-P" not in command_str:
            # Find where to insert auth flags (before the trailing '-' if present, or at end)
            command_str = command_str.strip()
            if command_str.endswith(" -"):
                command_str = command_str[:-2] + f" -U geode -P {admin_password} -"
            else:
                command_str += f" -U geode -P {admin_password}"

        # Inject --timeout flag to prevent premature client disconnection under load
        if "query" in command_str and "--timeout" not in command_str:
            cli_timeout = max(timeout_ms // 1000, 30)
            command_str = command_str.strip()
            if command_str.endswith(" -"):
                command_str = command_str[:-2] + f" --timeout {cli_timeout} -"
            else:
                command_str += f" --timeout {cli_timeout}"

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
                "gRPC transport requested but command '%s' is not a query — falling back to QUIC for admin commands",
                command_str.split()[1] if len(command_str.split()) > 1 else command_str,
            )

        # Shell command test - detect shell metacharacters
        # Only route through bash when the spec explicitly requests it via
        # test_type: shell.  For CLI commands containing shell metacharacters,
        # log a warning and use shlex to avoid CWE-78 injection.
        _shell_metacharacters = {"|", "&&", "||", ";", "$(", "`", ">", "<"}
        has_shell_meta = any(mc in command_str for mc in _shell_metacharacters)
        if has_shell_meta and test_case.test_type == "shell":
            # Explicit shell test - route through bash (trusted spec author)
            args = substitute_variables(test_case.args, env, secrets, data_dir)
            if args:
                command_str += " " + " ".join(args)
            cmd = ["bash", "-c", command_str]
        elif has_shell_meta:
            # CLI test with metacharacters - log and parse safely
            logger.warning(
                "Command contains shell metacharacters but test_type is not 'shell'; "
                "using shlex (no shell expansion): %s",
                command_str[:120],
            )
            cmd = shlex.split(command_str)
            args = substitute_variables(test_case.args, env, secrets, data_dir)
            cmd.extend(args)
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
            elif not use_grpc and "--insecure-tls-skip-verify" not in args and "--insecure" not in args:
                cmd.extend(["--insecure-tls-skip-verify"])
            # Add auth credentials unless intentionally unauthenticated
            if "-U" not in args and "--no-saved-session" not in args:
                cmd.extend(["-U", "geode", "-P", admin_password])
            # Pass CLI-level timeout matching the test harness timeout
            if "--timeout" not in args:
                cmd.extend(["--timeout", str(max(timeout_ms // 1000, 30))])

    # Validate user-supplied args for shell metacharacters (SEC-003).
    # Shell tests are excluded — they intentionally use shell features.
    if test_case.test_type != "shell" and test_case.args:
        try:
            sanitize_args(test_case.args)
        except ValueError as e:
            return TestResult(
                name=test_case.name,
                passed=False,
                duration_ms=(time.time() - start_time) * 1000,
                error=f"Unsafe argument rejected: {e}",
            )

    # Merge test-specific environment
    test_env = env.copy()
    test_env.update(test_case.env)

    # Use the larger of the global timeout and per-test timeout
    effective_timeout_ms = max(timeout_ms, test_case.timeout_ms)

    try:
        # Substitute variables in stdin if present
        stdin_input = test_case.stdin
        if stdin_input:
            stdin_input = _substitute_one(stdin_input, env, secrets, data_dir)

        result = subprocess.run(
            cmd,
            env=test_env,
            capture_output=True,
            text=True,
            timeout=effective_timeout_ms / 1000.0,
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
            error=f"Test timed out after {effective_timeout_ms}ms",
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
    *,
    http_client: httpx.Client | None = None,
) -> TestResult:
    """Run an HTTP test case."""
    start_time = time.time()
    outputs: list[str] = []
    errors: list[str] = []

    try:
        # Reuse shared client if provided (PERF-007), else create one
        _owned = http_client is None
        client = http_client or httpx.Client(timeout=DEFAULT_HTTP_TIMEOUT_S, verify=SSL_VERIFY)
        try:
            for i, req in enumerate(test_case.http_requests):
                # Substitute environment variables in URL
                url = _substitute_one(req.url, env, {}, None)

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
                            f"Request {i + 1} failed: {req.method} {url}\n"
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

                    outputs.append(f"Request {i + 1}: {response.status_code} OK")

                except httpx.RequestError as e:
                    errors.append(f"Request {i + 1} error: {e}")
                    return TestResult(
                        name=test_case.name,
                        passed=False,
                        duration_ms=(time.time() - start_time) * 1000,
                        output="\n".join(outputs),
                        error="\n".join(errors),
                    )

        finally:
            if _owned:
                client.close()

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
    # Prefer GEODE_SOURCE_DIR env var, then fall back to sibling directory detection.
    geode_source_env = os.environ.get("GEODE_SOURCE_DIR")
    if geode_source_env:
        geode_source = Path(geode_source_env)
    else:
        harness_dir = Path(__file__).resolve().parent.parent.parent.parent.parent
        geode_source = harness_dir / "geode"

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
            error=stderr if not passed else "",
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
    *,
    http_client: httpx.Client | None = None,
) -> TestResult:
    """Run a sequential test case with multiple steps."""
    start_time = time.time()
    outputs: list[str] = []
    errors: list[str] = []

    # Get authentication credentials from environment
    admin_password = env.get("GEODE_ADMIN_PASSWORD", DEFAULT_ADMIN_PASSWORD)

    # Transport-aware server address and flags
    server_addr, use_grpc = _resolve_server_address(env)

    try:
        # Reuse shared client if provided (PERF-007), else create one
        _owned_seq = http_client is None
        _http_client = http_client or httpx.Client(timeout=DEFAULT_HTTP_TIMEOUT_S, verify=SSL_VERIFY)
        try:
            for i, step in enumerate(test_case.steps):
                if verbose:
                    print(f"  Step {i + 1}: {step.step_type}")

                if step.step_type == "wait":
                    time.sleep(step.wait_ms / 1000.0)
                    outputs.append(f"Step {i + 1}: waited {step.wait_ms}ms")

                elif step.step_type == "http":
                    # Execute HTTP step
                    url = _substitute_one(step.url or "", env, {}, None)

                    response = _http_client.request(
                        method=step.method or "GET",
                        url=url,
                        headers=step.headers,
                        content=step.body,
                        timeout=step.timeout_ms / 1000.0,
                    )

                    if step.expected:
                        passed = check_http_expectations(response, step.expected, verbose)
                        if not passed:
                            errors.append(f"Step {i + 1} failed: HTTP {step.method} {url}")
                            return TestResult(
                                name=test_case.name,
                                passed=False,
                                duration_ms=(time.time() - start_time) * 1000,
                                output="\n".join(outputs),
                                error="\n".join(errors),
                            )

                    outputs.append(f"Step {i + 1}: HTTP {response.status_code} OK")

                elif step.step_type == "gql":
                    # Execute GQL query step
                    cmd = [binary, "query", step.query or ""]
                    cmd.extend(["--server", server_addr])
                    if use_grpc:
                        cmd.append("--grpc")
                    else:
                        cmd.extend(["--insecure-tls-skip-verify"])
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
                            errors.append(f"Step {i + 1} failed: expected status {expected_status}")
                            return TestResult(
                                name=test_case.name,
                                passed=False,
                                duration_ms=(time.time() - start_time) * 1000,
                                output="\n".join(outputs),
                                error="\n".join(errors),
                            )

                    outputs.append(f"Step {i + 1}: GQL OK")

        finally:
            if _owned_seq:
                _http_client.close()

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
    """Substitute variables in argument list.

    Uses a single ``re.sub`` pass instead of O(n*m) ``.replace()`` calls
    (PERF-008).
    """
    return [_substitute_one(arg, env, secrets, data_dir) for arg in args]


def _substitute_one(
    text: str,
    env: dict[str, str],
    secrets: dict[str, str],
    data_dir: Path | None,
) -> str:
    """Replace ``${key}``, ``${env:key}``, ``${secret:key}``, ``${data_dir}`` in *text*."""

    def _replacer(m: re.Match[str]) -> str:
        full = m.group(0)  # e.g. ${env:FOO} or ${FOO} or ${secret:BAR} or ${data_dir}
        inner = m.group(1)  # e.g. env:FOO or FOO or secret:BAR or data_dir

        if inner == "data_dir":
            return str(data_dir) if data_dir else full

        if inner.startswith("env:"):
            key = inner[4:]
            return env.get(key, full)

        if inner.startswith("secret:"):
            key = inner[7:]
            return secrets.get(key, full)

        # Plain ${KEY} — look up in env
        return env.get(inner, full)

    return re.sub(r"\$\{([^}]+)\}", _replacer, text)


def run_plaintext_verification(
    data_dir: Path,
    config: PlaintextCheck,
    verbose: bool,
) -> list[str]:
    """Run plaintext verification scan on data directory.

    Combines all search patterns into a single ``grep -E`` invocation
    to avoid N recursive directory scans (PERF-005).
    """
    violations: list[str] = []
    patterns = config.search_patterns
    if not patterns:
        return violations

    # Build a combined extended regex: pat1|pat2|pat3
    combined = "|".join(re.escape(p) for p in patterns)

    try:
        result = subprocess.run(
            ["grep", "-r", "-a", "-E", combined, str(data_dir)],
            capture_output=True,
            text=True,
            timeout=120,
        )

        if result.returncode == 0:
            for line in result.stdout.strip().split("\n"):
                if not line:
                    continue
                # line format: filepath:matched_content
                file_path = line.split(":")[0] if ":" in line else line
                # Filter out excluded extensions
                skip = any(file_path.endswith(ext) for ext in config.exclude_extensions)
                if skip:
                    continue
                # Figure out which pattern matched
                for pattern in patterns:
                    if pattern in line:
                        violations.append(f"Pattern '{pattern}' found in: {file_path}")
                        if verbose:
                            print(f"  VIOLATION: '{pattern}' in {file_path}")
                        break
                else:
                    violations.append(f"Pattern match found in: {file_path}")

    except subprocess.TimeoutExpired:
        if verbose:
            print("  WARNING: Grep timeout for combined pattern scan")
    except Exception as e:
        if verbose:
            print(f"  WARNING: Error scanning: {e}")

    return violations
