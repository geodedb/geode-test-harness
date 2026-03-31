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
        # test_type: bash.  For CLI commands containing shell metacharacters,
        # log a warning and use shlex to avoid CWE-78 injection.
        _shell_metacharacters = {"|", "&&", "||", ";", "$(", "`", ">", "<"}
        has_shell_meta = any(mc in command_str for mc in _shell_metacharacters)
        if has_shell_meta and test_case.test_type == "bash":
            # Explicit bash test - route through bash (trusted spec author)
            args = substitute_variables(test_case.args, env, secrets, data_dir)
            if args:
                command_str += " " + " ".join(args)
            cmd = ["bash", "-c", command_str]
        elif has_shell_meta:
            # CLI test with metacharacters - log and parse safely
            logger.warning(
                "Command contains shell metacharacters but test_type is not 'bash'; "
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
        # Commands that talk to the server via QUIC/gRPC
        _QUERY_COMMANDS = {"query", "shell"}
        # Commands that operate on the local data directory
        _LOCAL_COMMANDS = {
            "user",
            "apikey",
            "authn",
            "session",
            "auth-init",
            "mfa",
            "role",
            "policy",
            "auth",
            "grant",
            "revoke",
        }
        if args and args[0] in _QUERY_COMMANDS and len(args) > 1:
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
        elif args and args[0] in _LOCAL_COMMANDS and len(args) > 1:
            # GAP-0270: Route local auth commands through the running server
            # via CALL geode.auth.* procedures instead of opening local storage
            # (which fails because the server holds file locks).
            call_query = _convert_auth_to_call(args)
            if call_query and server_addr:
                cmd = [binary, "query", call_query, "--server", server_addr]
                if not use_grpc:
                    cmd.extend(["--insecure-tls-skip-verify"])
                cmd.extend(["-U", "geode", "-P", admin_password])
                cmd.extend(["--timeout", str(max(timeout_ms // 1000, 30))])
            elif "--data-dir" not in args and data_dir:
                # Fallback: local commands need --data-dir
                cmd.extend(["--data-dir", data_dir])

    # Validate user-supplied args for shell metacharacters (SEC-003).
    # Bash tests are excluded — they intentionally use shell features.
    # Query text args are excluded — GQL syntax legitimately uses (), {}, $
    # which overlap with shell metacharacters.  Since subprocess.run is
    # called with a list (shell=False), there is no injection risk for
    # any argument, but we still validate non-query args out of caution.
    if test_case.test_type != "bash" and test_case.args:
        args_to_check = list(test_case.args)
        if len(args_to_check) >= 2 and args_to_check[0] == "query":
            # Skip the GQL query text argument — it contains (), {}, $
            # that are valid GQL syntax, not shell metacharacters.
            # The query text is the first positional arg after "query"
            # that doesn't start with "--" (flags may appear before it).
            query_text_idx = None
            for idx in range(1, len(args_to_check)):
                if not args_to_check[idx].startswith("--"):
                    # Skip flag values (e.g., "dot" after "--format")
                    if idx > 1 and args_to_check[idx - 1].startswith("--"):
                        continue
                    query_text_idx = idx
                    break
            if query_text_idx is not None:
                args_to_check = args_to_check[:query_text_idx] + args_to_check[query_text_idx + 1 :]
            else:
                # Fallback: skip args[1] as before
                args_to_check = [args_to_check[0]] + args_to_check[2:]
            # GAP-0271: Skip --role flag values from sanitization — the server
            # validates role strings for injection chars; the test harness must
            # allow intentionally-malicious role values through for security tests.
            filtered = []
            skip_next = False
            for arg in args_to_check:
                if skip_next:
                    skip_next = False
                    continue
                if arg == "--role":
                    skip_next = True
                    continue
                filtered.append(arg)
            args_to_check = filtered
        try:
            sanitize_args(args_to_check)
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
