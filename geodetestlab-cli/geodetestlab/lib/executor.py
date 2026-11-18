"""Test execution for geodetestlab.

Handles dispatching and running individual test cases (CLI, HTTP,
shell, and sequential multi-step tests).
"""

from __future__ import annotations

import logging
import os
import re
import shlex
import signal as _signal
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import httpx

from .checks import check_expectations, check_http_expectations
from .cluster import restart_cluster_node
from .cluster_types import ClusterControlContext
from .runner_types import DEFAULT_ADMIN_PASSWORD, DEFAULT_GRPC_PORT, DEFAULT_QUIC_PORT, TestResult
from .spec import PlaintextCheck, TestCase, TestStep
from .tls_provision import client_tls_args, reconcile_client_tls
from .utils import is_valid_gql, sanitize_args

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants (DEFAULT_QUIC_PORT, DEFAULT_GRPC_PORT from runner_types)
# ---------------------------------------------------------------------------
DEFAULT_HTTP_TIMEOUT_S = 30.0
DEFAULT_SHELL_TIMEOUT_S = 30.0

# Valueless (boolean) geode CLI flags — flags that take NO following value.
# Mirrors the `CliFlagType.bool` entries in the geode CLI (cli_dispatcher.zig /
# main.zig). Used by the query-positional heuristic in `_build_cli_command` so a
# positional query following one of these flags is NOT mistaken for the flag's
# value (which would leave the multi-statement ';' query in the sanitize scan and
# wrongly reject it). Keep this in sync with the geode CLI's boolean flags.
_VALUELESS_CLI_FLAGS = frozenset(
    {
        "--help",
        "--version",
        "--verbose",
        "--json",
        "--audit",
        "--insecure",
        "--insecure-tls-skip-verify",
        "--no-saved-session",
        "--no-cluster",
        "--no-color",
        "--no-header",
    }
)
SSL_VERIFY = os.environ.get("GEODE_VERIFY_SSL", "0").lower() in ("1", "true", "yes")
if not SSL_VERIFY:
    logging.getLogger(__name__).debug(
        "SSL verification disabled (GEODE_VERIFY_SSL=%s). Set GEODE_VERIFY_SSL=1 to enable certificate verification.",
        os.environ.get("GEODE_VERIFY_SSL", "0"),
    )


TIMEOUT_EXCERPT_CHARS = 2000


def timeout_output_excerpt(exc: subprocess.TimeoutExpired) -> str:
    """Return the tail of whatever a timed-out command printed, for the error.

    Without it a timeout reports only its duration, which hides where the
    command stalled (e.g. a ``backup create`` that printed its banner and
    progress lines before hanging).
    """
    parts = []
    for label, data in (("stdout", exc.stdout), ("stderr", exc.stderr)):
        if not data:
            continue
        text = data.decode("utf-8", "replace") if isinstance(data, bytes) else data
        parts.append(f"\n--- {label} before timeout (tail) ---\n{text[-TIMEOUT_EXCERPT_CHARS:]}")
    return "".join(parts)


def _as_list(value: object) -> list[str]:
    """Normalize a scalar-or-list expectation field to a list of strings."""
    if value is None:
        return []
    if isinstance(value, list):
        return [str(v) for v in value]
    return [str(value)]


def _escape_gql_string(s: str) -> str:
    """Escape a string for use inside GQL single quotes.

    Backslashes are escaped first: escaping the quote first and then every
    backslash turned ``'`` into ``\\\\'``, an escaped backslash followed by a
    bare quote that ended the literal early, so a value containing a quote
    could break out of the string.
    """
    return s.replace("\\", "\\\\").replace("'", "\\'")


def _extract_capture(step: TestStep, stdout: str) -> tuple[str | None, str | None]:
    """Extract a sequential gql step's ``capture_regex`` group-1 value from stdout.

    Returns ``(value, error)``. When the step declares no capture at all
    (neither ``capture_regex`` nor ``capture_as``) both are ``None``.
    Never raises: an invalid regex, a regex without exactly one capture
    group, or a regex that doesn't match stdout all surface as a clear
    ``error`` string so the calling step fails cleanly instead of
    crashing the runner.
    """
    if step.capture_regex is None:
        if step.capture_as is not None:
            return None, "capture_as requires capture_regex"
        return None, None

    try:
        pattern = re.compile(step.capture_regex)
    except re.error as exc:
        return None, f"invalid capture_regex {step.capture_regex!r}: {exc}"

    if pattern.groups != 1:
        return None, f"capture_regex must have exactly one capture group: {step.capture_regex!r}"

    # First-match semantics: uses re.search (first match only), not
    # re.findall. The query is expected to return exactly one row, so the
    # first match is the only match — a multi-row result set is not
    # supported and would silently capture only the first row's value.
    match = pattern.search(stdout)
    if not match:
        return None, f"capture_regex {step.capture_regex!r} did not match stdout"

    return match.group(1), None


def _convert_auth_to_call(args: list[str]) -> str | None:
    """GAP-0270: Convert CLI auth command args to a CALL geode.auth.* GQL query.

    Returns a GQL query string or None if the command can't be converted.
    """
    if len(args) < 2:
        return None

    # Don't convert help requests — let the CLI show its own help text
    if "--help" in args or "-h" in args:
        return None

    subcmd = args[0]  # user, role, apikey, mfa, etc.
    action = args[1]  # create, list, delete, enable, disable, etc.

    # Parse flags from remaining args (start at index 2 by default)
    def _parse_flags_and_positionals(start: int = 2) -> tuple[list[str], dict[str, str]]:
        positionals: list[str] = []
        flags: dict[str, str] = {}
        i = start
        while i < len(args):
            arg = args[i]
            if arg.startswith("--") and i + 1 < len(args) and not args[i + 1].startswith("--"):
                flags[arg] = args[i + 1]
                i += 2
            elif arg.startswith("--"):
                flags[arg] = "true"
                i += 1
            elif arg.startswith("-") and len(arg) == 2 and i + 1 < len(args):
                flags[arg] = args[i + 1]
                i += 2
            else:
                positionals.append(arg)
                i += 1
        return positionals, flags

    positionals, flags = _parse_flags_and_positionals()

    def esc(s: str) -> str:
        return _escape_gql_string(s)

    # --- user commands ---
    if subcmd == "user" and action == "create":
        username = positionals[0] if positionals else flags.get("--username", "")
        email = positionals[1] if len(positionals) > 1 else flags.get("--email", "")
        password = flags.get("--password", "")
        role = flags.get("--role", "user")
        if "--generate-password" in flags:
            password = "auto_generated_password_placeholder"
        return f"CALL geode.auth.user_create('{esc(username)}', '{esc(password)}', '{esc(email)}', '{esc(role)}')"
    elif subcmd == "user" and action == "import":
        # Migration import of a PRE-COMPUTED password hash (no plaintext).
        # user import <username> --hash <h> [--algorithm <a>] [--email <e>] [--role <r>]
        username = positionals[0] if positionals else flags.get("--username", "")
        pw_hash = flags.get("--hash", "")
        algorithm = flags.get("--algorithm", "argon2id")
        email = flags.get("--email", "")
        role = flags.get("--role", "user")
        return (
            f"CALL geode.auth.user_import('{esc(username)}', '{esc(pw_hash)}', "
            f"'{esc(algorithm)}', '{esc(email)}', '{esc(role)}')"
        )
    elif subcmd == "user" and action == "list":
        return "CALL geode.auth.user_list()"
    elif subcmd == "user" and action == "delete":
        username = positionals[0] if positionals else ""
        return f"CALL geode.auth.user_delete('{esc(username)}')"
    elif subcmd == "user" and action in ("show", "info"):
        username = positionals[0] if positionals else ""
        return f"CALL geode.auth.user_show('{esc(username)}')"
    elif subcmd == "user" and action in ("enable", "disable"):
        username = positionals[0] if positionals else ""
        return f"CALL geode.auth.user_{action}('{esc(username)}')"
    elif subcmd == "user" and action == "assign-role":
        username = positionals[0] if positionals else ""
        role = positionals[1] if len(positionals) > 1 else flags.get("--role", "")
        return f"CALL geode.auth.user_assign_role('{esc(username)}', '{esc(role)}')"
    elif subcmd == "user" and action == "permissions":
        username = positionals[0] if positionals else ""
        return f"CALL geode.auth.user_permissions('{esc(username)}')"
    elif subcmd == "user" and action == "change-password":
        username = positionals[0] if positionals else ""
        old_pw = flags.get("--old-password", "")
        new_pw = flags.get("--new-password", "")
        if "--generate-password" in flags:
            new_pw = "auto_generated_password_placeholder"
        return f"CALL geode.auth.user_change_password('{esc(username)}', '{esc(old_pw)}', '{esc(new_pw)}')"
    elif subcmd == "user" and action == "reset-password":
        username = positionals[0] if positionals else ""
        new_pw = flags.get("--new-password", "")
        if "--generate-password" in flags:
            new_pw = "auto_generated_password_placeholder"
        return f"CALL geode.auth.user_reset_password('{esc(username)}', '{esc(new_pw)}')"
    elif subcmd == "user" and action == "mfa":
        # Nested: user mfa enable/disable <username> [--code <code>]
        # Re-parse from index 3 (after "user", "mfa", sub-action)
        if len(args) < 3:
            return None
        mfa_action = args[2]
        mfa_positionals, mfa_flags = _parse_flags_and_positionals(3)
        if mfa_action in ("enable", "disable"):
            username = mfa_positionals[0] if mfa_positionals else mfa_flags.get("-U", mfa_flags.get("--user", ""))
            code = mfa_flags.get("--code", "")
            if code:
                return f"CALL geode.auth.mfa_{mfa_action}('{esc(username)}', '{esc(code)}')"
            return f"CALL geode.auth.mfa_{mfa_action}('{esc(username)}')"
        return None
    elif subcmd == "user" and action == "mfa-setup":
        username = positionals[0] if positionals else ""
        show_uri = "--show-uri" in flags
        show_recovery = "--show-recovery" in flags
        regenerate = "--regenerate" in flags
        opts: list[str] = []
        if show_uri:
            opts.append("show-uri")
        if show_recovery:
            opts.append("show-recovery")
        if regenerate:
            opts.append("regenerate")
        opts_str = ",".join(opts) if opts else ""
        return f"CALL geode.auth.mfa_setup('{esc(username)}', '{esc(opts_str)}')"
    elif subcmd == "user" and action == "mfa-verify":
        username = positionals[0] if positionals else ""
        token = flags.get("--token", "")
        return f"CALL geode.auth.mfa_verify('{esc(username)}', '{esc(token)}')"

    # --- role commands ---
    elif subcmd == "role" and action == "create":
        role_name = positionals[0] if positionals else ""
        desc = positionals[1] if len(positionals) > 1 else ""
        perms = flags.get("--permissions", "")
        return f"CALL geode.auth.role_create('{esc(role_name)}', '{esc(desc)}', '{esc(perms)}')"
    elif subcmd == "role" and action == "list":
        return "CALL geode.auth.role_list()"
    elif subcmd == "role" and action == "delete":
        role_name = positionals[0] if positionals else ""
        return f"CALL geode.auth.role_delete('{esc(role_name)}')"
    elif subcmd == "role" and action == "show":
        role_name = positionals[0] if positionals else ""
        return f"CALL geode.auth.role_show('{esc(role_name)}')"

    # --- mfa commands (top-level) ---
    elif subcmd == "mfa" and action in ("enable", "disable"):
        username = positionals[0] if positionals else flags.get("-U", flags.get("--user", ""))
        return f"CALL geode.auth.mfa_{action}('{esc(username)}')"

    # --- apikey commands ---
    elif subcmd == "apikey" and action == "create":
        username = flags.get("--user", positionals[0] if positionals else "")
        name = flags.get("--name", "")
        scope = flags.get("--scope", "")
        expires_in = flags.get("--expires-in", "")
        return f"CALL geode.auth.apikey_create('{esc(username)}', '{esc(name)}', '{esc(scope)}', '{esc(expires_in)}')"
    elif subcmd == "apikey" and action == "list":
        username = flags.get("--user", "")
        return f"CALL geode.auth.apikey_list('{esc(username)}')"
    elif subcmd == "apikey" and action == "revoke":
        username = flags.get("--user", "")
        name = flags.get("--name", "")
        return f"CALL geode.auth.apikey_revoke('{esc(username)}', '{esc(name)}')"
    elif subcmd == "apikey" and action == "revoke-all":
        username = flags.get("--user", "")
        return f"CALL geode.auth.apikey_revoke_all('{esc(username)}')"
    elif subcmd == "apikey" and action == "validate":
        return None  # Validation is client-side, keep local
    elif subcmd == "apikey" and action == "check-scope":
        username = flags.get("--user", "")
        name = flags.get("--name", "")
        scope = flags.get("--scope", "")
        return f"CALL geode.auth.apikey_check_scope('{esc(username)}', '{esc(name)}', '{esc(scope)}')"

    # --- policy commands ---
    elif subcmd == "policy" and action == "create":
        # geode.auth.policy_create takes (name, table, condition); a
        # description positional is accepted for CLI compatibility but the
        # procedure has no description argument (geode #831). Passing it
        # shifted table into the condition slot.
        name = positionals[0] if positionals else ""
        table = flags.get("--table", "")
        condition = flags.get("--condition", flags.get("--using", ""))
        return f"CALL geode.auth.policy_create('{esc(name)}', '{esc(table)}', '{esc(condition)}')"
    elif subcmd == "policy" and action == "list":
        return "CALL geode.auth.policy_list()"
    elif subcmd == "policy" and action == "delete":
        name = positionals[0] if positionals else ""
        return f"CALL geode.auth.policy_delete('{esc(name)}')"

    # --- grant/revoke commands ---
    # CLI syntax: geode grant <permission> <target> [--resource <resource>]
    # args[0] = "grant"/"revoke", args[1] = permission name, positionals = [target, ...]
    elif subcmd == "grant":
        perm = action  # args[1] is always the permission name
        target = positionals[0] if positionals else ""
        resource = flags.get("--resource", "")
        return f"CALL geode.auth.grant('{esc(perm)}', '{esc(target)}', '{esc(resource)}')"
    elif subcmd == "revoke":
        perm = action  # args[1] is always the permission name
        target = positionals[0] if positionals else ""
        resource = flags.get("--resource", "")
        return f"CALL geode.auth.revoke('{esc(perm)}', '{esc(target)}', '{esc(resource)}')"

    return None  # Unknown command — fall back to local mode


def run_single_test(
    test_case: TestCase,
    binary: str,
    env: dict[str, str],
    secrets: dict[str, str],
    timeout_ms: int,
    data_dir: Path | None,
    verbose: bool,
    http_client: httpx.Client | None = None,
    cluster_ctx: ClusterControlContext | None = None,
) -> TestResult:
    """Run a single test case, dispatching by test type.

    Parameters
    ----------
    http_client : httpx.Client | None
        Optional shared HTTP client for connection reuse across tests
        within the same spec (PERF-007).
    cluster_ctx : ClusterControlContext | None
        Present for cluster-mode specs.  Required for ``signal`` and
        ``restart_node`` steps inside a sequential test.
    """
    if test_case.test_type == "http":
        return _run_http_test(test_case, env, verbose, http_client=http_client)
    elif test_case.test_type == "sequential":
        return _run_sequential_test(
            test_case,
            binary,
            env,
            secrets,
            timeout_ms,
            data_dir,
            verbose,
            http_client=http_client,
            cluster_ctx=cluster_ctx,
        )
    elif test_case.test_type == "bash":
        return _run_shell_test(test_case, env, verbose, data_dir, binary)

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


def _is_remote_admin_command(args: list[str]) -> bool:
    """Return True for CLI commands that execute against the live server."""
    if not args:
        return False

    if args[0] == "backup" and len(args) > 1 and args[1] == "create":
        return True

    return args[0] in {"restore", "migrate"}


def _convert_grpc_auth_login_probe(binary: str, args: list[str], server_addr: str, timeout_ms: int) -> list[str] | None:
    """Translate auth login to a gRPC-authenticated probe query for harness use.

    The CLI login path is QUIC-only today. In gRPC harness runs, use a real
    authenticated gRPC query instead and return the same success phrases that
    the login specs assert on.
    """
    if "--help" in args or "-h" in args:
        return None

    is_auth_login = len(args) >= 2 and args[0] == "auth" and args[1] == "login"
    is_login_alias = len(args) >= 1 and args[0] == "login"
    if not is_auth_login and not is_login_alias:
        return None

    username: str | None = None
    password: str | None = None
    start_idx = 2 if is_auth_login else 1
    i = start_idx
    while i < len(args):
        arg = args[i]
        if arg in {"-U", "--user", "--username"} and i + 1 < len(args):
            username = args[i + 1]
            i += 2
        elif arg in {"-P", "--password", "--pass"} and i + 1 < len(args):
            password = args[i + 1]
            i += 2
        else:
            i += 1

    if not username or not password:
        return None

    status = _escape_gql_string(f"Successfully authenticated as '{username}' on server '{server_addr}'")
    token = _escape_gql_string("Session token: grpc-session-probe")
    query = f"RETURN '{status}' AS status, '{token}' AS token"
    return [
        binary,
        "query",
        query,
        "--server",
        server_addr,
        "--grpc",
        "-U",
        username,
        "-P",
        password,
        "--timeout",
        str(max(timeout_ms // 1000, 30)),
    ]


def _rewrite_dsn_for_transport(dsn: str, env: dict[str, str], use_grpc: bool) -> str:
    """Rewrite DSN scheme/authority to match the active harness transport."""
    parsed = urlsplit(dsn)
    if not parsed.scheme or not parsed.netloc:
        return dsn

    if use_grpc:
        grpc_addr = env.get("GEODE_GRPC_ADDRESS")
        if not grpc_addr:
            return dsn
        userinfo = ""
        if "@" in parsed.netloc:
            userinfo = parsed.netloc.rsplit("@", 1)[0] + "@"
        return urlunsplit(
            (
                "grpc",
                f"{userinfo}{grpc_addr}",
                parsed.path,
                parsed.query,
                parsed.fragment,
            )
        )

    server_addr = env.get("GEODE_SERVER_ADDRESS")
    if not server_addr:
        return dsn
    userinfo = ""
    if "@" in parsed.netloc:
        userinfo = parsed.netloc.rsplit("@", 1)[0] + "@"
    return urlunsplit(
        (
            "quic",
            f"{userinfo}{server_addr}",
            parsed.path,
            parsed.query,
            parsed.fragment,
        )
    )


def _build_cli_command(
    test_case: TestCase,
    binary: str,
    env: dict[str, str],
    secrets: dict[str, str],
    timeout_ms: int,
    data_dir: Path | None,
    start_time: float,
) -> tuple[list[str], TestResult | None]:
    """Build the CLI command and validate arguments."""
    admin_password = env.get("GEODE_ADMIN_PASSWORD", DEFAULT_ADMIN_PASSWORD)
    server_addr, use_grpc = _resolve_server_address(env)
    quic_server_addr = env.get("GEODE_SERVER_ADDRESS", f"127.0.0.1:{DEFAULT_QUIC_PORT}")

    resolved_dsn = None
    if test_case.dsn:
        resolved_dsn = _substitute_one(test_case.dsn, env, secrets, data_dir)
        resolved_dsn = _rewrite_dsn_for_transport(resolved_dsn, env, use_grpc)

    if test_case.query and resolved_dsn:
        cmd = [binary, "query", test_case.query]
        cmd.extend(["--dsn", resolved_dsn])
        cmd.extend(client_tls_args(env))
    elif test_case.query:
        cmd = [binary, "query", test_case.query]
        cmd.extend(["--server", server_addr])
        if use_grpc:
            cmd.append("--grpc")
        else:
            cmd.extend(client_tls_args(env))
        cmd.extend(["-U", "geode", "-P", admin_password])
    elif test_case.command and is_valid_gql(test_case.command) and resolved_dsn:
        cmd = [binary, "query", test_case.command]
        cmd.extend(["--dsn", resolved_dsn])
        cmd.extend(client_tls_args(env))
    elif test_case.command and is_valid_gql(test_case.command):
        cmd = [binary, "query", test_case.command]
        cmd.extend(["--server", server_addr])
        if use_grpc:
            cmd.append("--grpc")
        else:
            cmd.extend(client_tls_args(env))
        cmd.extend(["-U", "geode", "-P", admin_password])
    elif test_case.command:
        command_str = test_case.command
        for geode_path in ["./zig-out/bin/geode", "zig-out/bin/geode"]:
            if geode_path in command_str:
                command_str = command_str.replace(geode_path, binary, 1)
                break
        command_str = _substitute_one(command_str, env, secrets, data_dir)

        if "query" in command_str and "-U" not in command_str and "-P" not in command_str:
            command_str = command_str.strip()
            if command_str.endswith(" -"):
                command_str = command_str[:-2] + f" -U geode -P {admin_password} -"
            else:
                command_str += f" -U geode -P {admin_password}"

        if "query" in command_str and "--timeout" not in command_str:
            cli_timeout = max(timeout_ms // 1000, 30)
            command_str = command_str.strip()
            if command_str.endswith(" -"):
                command_str = command_str[:-2] + f" --timeout {cli_timeout} -"
            else:
                command_str += f" --timeout {cli_timeout}"

        if use_grpc and "query" in command_str and "--grpc" not in command_str:
            command_str += " --grpc"
            quic_addr = env.get("GEODE_SERVER_ADDRESS", "")
            grpc_addr = env.get("GEODE_GRPC_ADDRESS", "")
            if quic_addr and grpc_addr and quic_addr in command_str:
                command_str = command_str.replace(quic_addr, grpc_addr)
        elif use_grpc and "query" not in command_str:
            logger.warning(
                "gRPC transport requested but command '%s' is not a query — falling back to QUIC for admin commands",
                command_str.split()[1] if len(command_str.split()) > 1 else command_str,
            )

        _shell_metacharacters = {"|", "&&", "||", ";", "$(", "`", ">", "<"}
        has_shell_meta = any(mc in command_str for mc in _shell_metacharacters)
        if has_shell_meta and test_case.test_type == "bash":
            args = substitute_variables(test_case.args, env, secrets, data_dir)
            if args:
                command_str += " " + " ".join(args)
            cmd = ["bash", "-c", command_str]
        elif has_shell_meta:
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

        # For shlex (non-bash) commands carrying a spec-supplied insecure flag,
        # reconcile to verified --ca-cert on a release binary (which refuses
        # --insecure). Bash commands carry the flag inside the -c string and
        # instead reference $GEODE_CLIENT_TLS, so skip them here.
        if cmd and cmd[0] != "bash" and not use_grpc and ("--insecure" in cmd or "--insecure-tls-skip-verify" in cmd):
            cmd = reconcile_client_tls(cmd, [], env)
    else:
        cmd = [binary]
        args = substitute_variables(test_case.args, env, secrets, data_dir)
        cmd.extend(args)
        _QUERY_COMMANDS = {"query", "shell"}
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
            if not use_grpc:
                # Reconcile TLS posture for the target binary: on a release
                # binary a spec-supplied --insecure/--insecure-tls-skip-verify is
                # REFUSED, so swap it for verified --ca-cert when a CA was
                # provisioned (else keep the legacy debug-only insecure path).
                cmd = reconcile_client_tls(cmd, args, env)
            if "-U" not in args and "--no-saved-session" not in args:
                cmd.extend(["-U", "geode", "-P", admin_password])
            if "--timeout" not in args:
                cmd.extend(["--timeout", str(max(timeout_ms // 1000, 30))])
        elif args and args[0] in _LOCAL_COMMANDS and len(args) > 1:
            call_query = _convert_auth_to_call(args)
            login_probe = _convert_grpc_auth_login_probe(binary, args, server_addr, timeout_ms) if use_grpc else None
            if login_probe:
                cmd = login_probe
            elif call_query and server_addr:
                cmd = [binary, "query", call_query, "--server", server_addr]
                if use_grpc:
                    cmd.append("--grpc")
                else:
                    cmd.extend(client_tls_args(env))
                cmd.extend(["-U", "geode", "-P", admin_password])
                cmd.extend(["--timeout", str(max(timeout_ms // 1000, 30))])
            elif args[0] == "auth" and len(args) > 1 and args[1] == "login" and not use_grpc:
                # Native QUIC auth-login: point it at the managed test server.
                # Like backup/restore, its verified-TLS (--ca-cert) handshake
                # STALLS on a release binary (the tracked geode bug —
                # docs/bugs/2026-06-13-verified-tls-backup-and-cluster-handshake.md),
                # so drive it through geode's DOCUMENTED insecure escape hatch
                # (GEODE_ALLOW_INSECURE_TLS=1 + --insecure-tls-skip-verify). The
                # auth handshake is still real. geode auth login now also accepts
                # --ca-cert for when the verified path is fixed.
                if "--server" not in args:
                    cmd.extend(["--server", quic_server_addr])
                if "--insecure-tls-skip-verify" not in cmd and "--insecure" not in cmd and "--ca-cert" not in cmd:
                    env["GEODE_ALLOW_INSECURE_TLS"] = "1"
                    cmd.append("--insecure-tls-skip-verify")
            elif "--data-dir" not in args and data_dir:
                cmd.extend(["--data-dir", str(data_dir)])
        elif args and _is_remote_admin_command(args):
            if use_grpc:
                logger.warning(
                    "gRPC transport requested but command '%s' is QUIC-only; using the managed QUIC address instead",
                    args[0],
                )
            if "--server" not in args:
                cmd.extend(["--server", quic_server_addr])
            # KNOWN GEODE BUG: `backup create` / `restore` stream over QUIC and
            # their verified-TLS (--ca-cert) handshake STALLS on a release binary
            # — the handshake's Initial/Handshake packets are processed but the
            # connection never reaches "active" (a single-shot `query --ca-cert`
            # works fine; same class as the GAP-0838 client-side TLS-1.3
            # CertificateVerify path). Until that geode bug is fixed, drive the
            # streaming backup/restore commands through geode's DOCUMENTED insecure
            # escape hatch (GEODE_ALLOW_INSECURE_TLS=1 + --insecure-tls-skip-verify)
            # so the REAL data transfer still happens. `migrate` is not a streaming
            # command and verifies fine, so it keeps verified TLS via client_tls_args.
            is_stream_admin = args[0] == "backup" or args[0] == "restore"
            if "--insecure-tls-skip-verify" not in args and "--insecure" not in args:
                if is_stream_admin and not use_grpc:
                    env["GEODE_ALLOW_INSECURE_TLS"] = "1"
                    cmd.append("--insecure-tls-skip-verify")
                else:
                    cmd.extend(client_tls_args(env))
            if "-U" not in args and "--user" not in args:
                cmd.extend(["--user", "geode"])
            if "-P" not in args and "--password" not in args:
                cmd.extend(["--password", admin_password])

    if test_case.test_type != "bash" and test_case.args:
        args_to_check = list(test_case.args)
        if len(args_to_check) >= 2 and args_to_check[0] == "query":
            query_text_idx = None
            for idx in range(1, len(args_to_check)):
                if not args_to_check[idx].startswith("--"):
                    # A positional is the value of the preceding flag ONLY when
                    # that flag actually takes a value. A valueless/boolean flag
                    # (e.g. --insecure) takes no value, so the positional after it
                    # is the query itself and must be excluded from the ';' scan.
                    prev = args_to_check[idx - 1]
                    if idx > 1 and prev.startswith("--") and prev not in _VALUELESS_CLI_FLAGS:
                        continue
                    query_text_idx = idx
                    break
            if query_text_idx is not None:
                args_to_check = args_to_check[:query_text_idx] + args_to_check[query_text_idx + 1 :]
            else:
                args_to_check = [args_to_check[0]] + args_to_check[2:]
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
            return cmd, TestResult(
                name=test_case.name,
                passed=False,
                duration_ms=(time.time() - start_time) * 1000,
                error=f"Unsafe argument rejected: {e}",
            )

    # Catch-all: any non-bash geode subcommand (query/shell/migrate/backup/...)
    # carrying a spec-supplied insecure flag is reconciled to verified --ca-cert
    # on a release binary, which refuses --insecure. Idempotent if an earlier
    # branch already reconciled (the insecure token is gone → no-op).
    if cmd and cmd[0] != "bash" and not use_grpc and ("--insecure" in cmd or "--insecure-tls-skip-verify" in cmd):
        cmd = reconcile_client_tls(cmd, [], env)

    return cmd, None


def _execute_and_check(
    test_case: TestCase,
    cmd: list[str],
    env: dict[str, str],
    secrets: dict[str, str],
    timeout_ms: int,
    data_dir: Path | None,
    verbose: bool,
    start_time: float,
) -> TestResult:
    """Execute the command and check expectations."""
    test_env = env.copy()
    test_env.update(test_case.env)
    # Expose the reconciled client-TLS posture to bash/command steps so specs can
    # connect to the provisioned server without hardcoding --insecure (which a
    # release binary refuses). Resolves to "--ca-cert <ca>" when a CA was
    # provisioned, else the legacy "--insecure-tls-skip-verify". A spec's own
    # test_case.env still wins (setdefault).
    test_env.setdefault("GEODE_CLIENT_TLS", " ".join(client_tls_args(test_env)))

    effective_timeout_ms = max(timeout_ms, test_case.timeout_ms)

    try:
        stdin_input = test_case.stdin
        if stdin_input:
            stdin_input = _substitute_one(stdin_input, env, secrets, data_dir)

        result = subprocess.run(
            cmd,
            env=test_env,
            capture_output=True,
            text=True,
            timeout=effective_timeout_ms / 1000.0,
            input=stdin_input,
        )

        output = result.stdout
        error = result.stderr
        exit_code = result.returncode

    except subprocess.TimeoutExpired as exc:
        return TestResult(
            name=test_case.name,
            passed=False,
            duration_ms=(time.time() - start_time) * 1000,
            error=f"Test timed out after {effective_timeout_ms}ms" + timeout_output_excerpt(exc),
        )
    except Exception as e:
        return TestResult(
            name=test_case.name,
            passed=False,
            duration_ms=(time.time() - start_time) * 1000,
            error=str(e),
        )

    duration_ms = (time.time() - start_time) * 1000

    passed = check_expectations(
        test_case=test_case,
        output=output,
        error=error,
        exit_code=exit_code,
    )

    if not passed and verbose:
        print(f"    Exit code: {exit_code}")
        print(f"    Stdout: {output[:200] if output else '(empty)'}")
        print(f"    Stderr: {error[:200] if error else '(empty)'}")

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

    # Run per-test setup queries before the main test command
    if test_case.setup_queries:
        for i, setup_item in enumerate(test_case.setup_queries):
            setup_tc = TestCase.from_dict(
                {
                    "name": f"{test_case.name}-setup-{i}",
                    "description": f"Setup query {i} for {test_case.name}",
                    **setup_item,
                }
            )
            if verbose:
                print(f"    Executing setup-{i}...")
            setup_cmd, setup_err = _build_cli_command(setup_tc, binary, env, secrets, timeout_ms, data_dir, start_time)
            if setup_err:
                return TestResult(
                    name=test_case.name,
                    passed=False,
                    duration_ms=(time.time() - start_time) * 1000,
                    error=f"Setup query {i} failed to build: {setup_err.error}",
                )
            setup_result = _execute_and_check(
                setup_tc, setup_cmd, env, secrets, timeout_ms, data_dir, verbose, start_time
            )
            if not setup_result.passed:
                if verbose:
                    print(f"    Setup-{i}: FAILED - {setup_result.error}")
                return TestResult(
                    name=test_case.name,
                    passed=False,
                    duration_ms=(time.time() - start_time) * 1000,
                    error=f"Setup query {i} failed: {setup_result.error}",
                )
            if verbose:
                print(f"    Setup-{i}: OK")

    cmd, error_result = _build_cli_command(test_case, binary, env, secrets, timeout_ms, data_dir, start_time)
    if error_result:
        return error_result

    main_result = _execute_and_check(test_case, cmd, env, secrets, timeout_ms, data_dir, verbose, start_time)

    # Run per-test verify queries (post-conditions) only if the main step passed,
    # mirroring the setup_queries semantics. A failing verify fails the whole test.
    if main_result.passed and test_case.verify_queries:
        for i, verify_item in enumerate(test_case.verify_queries):
            verify_tc = TestCase.from_dict(
                {
                    "name": f"{test_case.name}-verify-{i}",
                    "description": f"Verify query {i} for {test_case.name}",
                    **verify_item,
                }
            )
            if verbose:
                print(f"    Executing verify-{i}...")
            verify_cmd, verify_err = _build_cli_command(
                verify_tc, binary, env, secrets, timeout_ms, data_dir, start_time
            )
            if verify_err:
                return TestResult(
                    name=test_case.name,
                    passed=False,
                    duration_ms=(time.time() - start_time) * 1000,
                    output=main_result.output,
                    error=f"Verify query {i} failed to build: {verify_err.error}",
                )
            verify_result = _execute_and_check(
                verify_tc, verify_cmd, env, secrets, timeout_ms, data_dir, verbose, start_time
            )
            if not verify_result.passed:
                if verbose:
                    print(f"    Verify-{i}: FAILED - {verify_result.error}")
                return TestResult(
                    name=test_case.name,
                    passed=False,
                    duration_ms=(time.time() - start_time) * 1000,
                    output=main_result.output,
                    error=f"Verify query {i} failed: {verify_result.error}",
                )
            if verbose:
                print(f"    Verify-{i}: OK")

    return main_result


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
    data_dir: Path | None = None,
    binary: str | None = None,
) -> TestResult:
    """Run a shell test case.

    Shell tests execute bash commands/scripts, typically used for source code
    verification tests that grep for patterns in the codebase.

    The active server's data directory is exported as ``GEODE_DATA_DIR`` so
    bash steps can locate the on-disk store files (e.g. the TDE bit-flip
    corruption specs that flip a byte in a data file before a restart).
    Without this, those steps cannot find the dynamic per-run data dir and
    silently skip, which then breaks downstream assertions.
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
    # Expose the active server's data directory to bash steps so they can
    # operate on the on-disk store files (TDE corruption/flip specs rely on
    # this). CLI steps get ${data_dir} substitution; bash steps need the env
    # var. test_case.env (below) still wins if the spec sets it explicitly.
    if data_dir is not None:
        test_env["GEODE_DATA_DIR"] = str(data_dir)
    # Expose the binary under test so bash steps invoke it instead of whatever
    # `geode` resolves to on PATH (which may be a stale system install). Specs
    # should call "${GEODE_BINARY}" rather than a bare `geode`. Also prepend its
    # directory to PATH so existing bare-`geode` steps pick up the right binary.
    if binary:
        test_env["GEODE_BINARY"] = str(binary)
        bin_dir = os.path.dirname(os.path.abspath(str(binary)))
        if bin_dir:
            test_env["PATH"] = bin_dir + os.pathsep + test_env.get("PATH", os.environ.get("PATH", ""))
    # Reconciled client-TLS posture for shell/bash steps — "--ca-cert <ca>" when
    # a CA was provisioned (release-safe), else "--insecure-tls-skip-verify".
    # Specs reference $GEODE_CLIENT_TLS instead of hardcoding the insecure flag.
    test_env.setdefault("GEODE_CLIENT_TLS", " ".join(client_tls_args(test_env)))
    # The interpreter running the harness (its venv carries grpcio/protobuf), so
    # bash steps that speak a wire protocol directly (raw gRPC probes) need not
    # guess which python3 has the libraries. Specs fall back to python3.
    test_env.setdefault("GEODETESTLAB_PYTHON", sys.executable)
    test_env.update(test_case.env)

    # Honor per-test timeout_ms if it exceeds the default shell timeout. Long-
    # running stress/perf shell tests (e.g. GAP-0343-LOOP-001) specify their own
    # timeout in milliseconds and the harness must respect it -- otherwise every
    # bash-driven sustained-load spec would be killed at 30s regardless of the
    # spec's declared budget.
    if test_case.timeout_ms and test_case.timeout_ms > 0:
        timeout_s = max(DEFAULT_SHELL_TIMEOUT_S, test_case.timeout_ms / 1000.0)
    else:
        timeout_s = DEFAULT_SHELL_TIMEOUT_S

    try:
        result = subprocess.run(
            ["bash", "-c", command],
            env=test_env,
            capture_output=True,
            text=True,
            timeout=timeout_s,
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

    except subprocess.TimeoutExpired as exc:
        return TestResult(
            name=test_case.name,
            passed=False,
            duration_ms=(time.time() - start_time) * 1000,
            error=f"Shell test timed out after {timeout_s:.0f} seconds" + timeout_output_excerpt(exc),
        )
    except Exception as e:
        return TestResult(
            name=test_case.name,
            passed=False,
            duration_ms=(time.time() - start_time) * 1000,
            error=str(e),
        )


# ---------------------------------------------------------------------------
# Cluster-control step handlers (signal / restart_node)
# ---------------------------------------------------------------------------

# Signals a `signal` step is permitted to deliver to a cluster node.
_ALLOWED_SIGNALS = {
    "SIGSTOP": _signal.SIGSTOP,
    "SIGCONT": _signal.SIGCONT,
    "SIGKILL": _signal.SIGKILL,
    "SIGTERM": _signal.SIGTERM,
}


def _run_signal_step(step: TestStep, cluster_ctx: ClusterControlContext | None) -> tuple[bool, str]:
    """Send a Unix signal to a named cluster node process.

    Each cluster node is started with ``start_new_session=True`` (its own
    process group), so the signal is delivered to the whole group via
    ``os.killpg`` — this reliably reaches the server even if it spawned
    children.  Returns ``(ok, message)``.
    """
    if cluster_ctx is None:
        return False, "signal step requires cluster mode (no cluster context available)"
    if not step.target:
        return False, "signal step missing 'target' (expected 'node:N')"
    if not step.sig:
        return False, "signal step missing 'sig' (expected SIGSTOP/SIGCONT/SIGKILL/SIGTERM)"

    sig_name = step.sig.strip().upper()
    sig = _ALLOWED_SIGNALS.get(sig_name)
    if sig is None:
        return False, f"signal step: unsupported signal {step.sig!r} (allowed: {sorted(_ALLOWED_SIGNALS)})"

    try:
        node = cluster_ctx.cluster_state.node_by_target(step.target)
    except ValueError as exc:
        return False, str(exc)

    if node.process is None:
        return False, f"signal step: node {step.target} has no process (already stopped?)"

    pid = node.process.pid
    try:
        pgid = os.getpgid(pid)
        from .server import _safe_killpg

        _safe_killpg(pgid, sig)
    except ProcessLookupError:
        # The process is already gone. SIGKILL/SIGTERM on a dead node is a
        # benign no-op; treat it as success. SIGSTOP/SIGCONT cannot apply.
        if sig_name in ("SIGKILL", "SIGTERM"):
            return True, f"node {step.target} (pid {pid}) already exited; {sig_name} no-op"
        return False, f"signal step: node {step.target} (pid {pid}) is not running, cannot {sig_name}"
    except PermissionError as exc:  # pragma: no cover - environment dependent
        return False, f"signal step: not permitted to {sig_name} node {step.target}: {exc}"

    return True, f"sent {sig_name} to node {step.target} (pid {pid})"


def _run_restart_node_step(step: TestStep, cluster_ctx: ClusterControlContext | None) -> tuple[bool, str]:
    """Restart a single cluster node on its original port + data directory."""
    if cluster_ctx is None:
        return False, "restart_node step requires cluster mode (no cluster context available)"
    if not step.target:
        return False, "restart_node step missing 'target' (expected 'node:N')"

    try:
        node = cluster_ctx.cluster_state.node_by_target(step.target)
    except ValueError as exc:
        return False, str(exc)

    try:
        restart_cluster_node(
            cluster_ctx.cluster_state,
            cluster_ctx.cluster_config,
            node.node_id,
            binary=cluster_ctx.binary,
            base_env=cluster_ctx.base_env,
            spec_server_args=cluster_ctx.spec_server_args,
            verbose=cluster_ctx.verbose,
            transport=cluster_ctx.transport,
        )
    except (ValueError, RuntimeError) as exc:
        return False, f"restart_node step failed for {step.target}: {exc}"

    return True, f"restarted node {step.target} on port {node.port} (data_dir {node.data_dir})"


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
    cluster_ctx: ClusterControlContext | None = None,
) -> TestResult:
    """Run a sequential test case with multiple steps."""
    start_time = time.time()
    outputs: list[str] = []
    errors: list[str] = []
    # Named capture values stashed by earlier gql steps' capture_as, for
    # later steps' gql_expected.equals_capture comparisons.
    captures: dict[str, str] = {}

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

                elif step.step_type == "signal":
                    ok, message = _run_signal_step(step, cluster_ctx)
                    if not ok:
                        errors.append(f"Step {i + 1} failed: {message}")
                        return TestResult(
                            name=test_case.name,
                            passed=False,
                            duration_ms=(time.time() - start_time) * 1000,
                            output="\n".join(outputs),
                            error="\n".join(errors),
                        )
                    outputs.append(f"Step {i + 1}: signal — {message}")

                elif step.step_type == "restart_node":
                    ok, message = _run_restart_node_step(step, cluster_ctx)
                    if not ok:
                        errors.append(f"Step {i + 1} failed: {message}")
                        return TestResult(
                            name=test_case.name,
                            passed=False,
                            duration_ms=(time.time() - start_time) * 1000,
                            output="\n".join(outputs),
                            error="\n".join(errors),
                        )
                    outputs.append(f"Step {i + 1}: restart_node — {message}")

                elif step.step_type == "bash":
                    # Run a shell command against the live (cluster) servers.
                    # Same environment as a shell test: GEODE_BINARY, the
                    # reconciled client-TLS flags and, in cluster mode,
                    # GEODE_CLUSTER_PORTS / GEODE_CLUSTER_SIZE. The step fails
                    # on a non-zero exit or an unmet stdout_contains.
                    if not step.command:
                        errors.append(f"Step {i + 1} failed: bash step missing 'command'")
                        return TestResult(
                            name=test_case.name,
                            passed=False,
                            duration_ms=(time.time() - start_time) * 1000,
                            output="\n".join(outputs),
                            error="\n".join(errors),
                        )
                    bash_env = env.copy()
                    bash_env["GEODE_BINARY"] = str(binary)
                    bin_dir = os.path.dirname(os.path.abspath(str(binary)))
                    if bin_dir:
                        bash_env["PATH"] = bin_dir + os.pathsep + bash_env.get("PATH", os.environ.get("PATH", ""))
                    bash_env.setdefault("GEODE_CLIENT_TLS", " ".join(client_tls_args(bash_env)))
                    try:
                        bash_result = subprocess.run(
                            ["bash", "-c", step.command],
                            env=bash_env,
                            capture_output=True,
                            text=True,
                            timeout=max(step.timeout_ms, 1) / 1000.0,
                        )
                    except subprocess.TimeoutExpired as exc:
                        errors.append(
                            f"Step {i + 1} failed: bash step timed out after {step.timeout_ms}ms"
                            + timeout_output_excerpt(exc)
                        )
                        return TestResult(
                            name=test_case.name,
                            passed=False,
                            duration_ms=(time.time() - start_time) * 1000,
                            output="\n".join(outputs),
                            error="\n".join(errors),
                        )
                    bash_failure = ""
                    if bash_result.returncode != 0:
                        bash_failure = f"exit code {bash_result.returncode}"
                    if step.gql_expected and not bash_failure:
                        for needle in _as_list(step.gql_expected.get("stdout_contains")):
                            if needle not in bash_result.stdout:
                                bash_failure = f"stdout missing {needle!r}"
                    if bash_failure and not step.allow_failure:
                        errors.append(f"Step {i + 1} failed: bash {bash_failure}")
                        return TestResult(
                            name=test_case.name,
                            passed=False,
                            duration_ms=(time.time() - start_time) * 1000,
                            output="\n".join(outputs) + "\n" + bash_result.stdout + bash_result.stderr[-2000:],
                            error="\n".join(errors),
                        )
                    outputs.append(f"Step {i + 1}: bash OK :: {bash_result.stdout.strip()[-300:]}")

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
                    # Execute GQL query step.  ``target`` may redirect the
                    # query at a specific cluster node ("node:N"); otherwise
                    # the spec-level target node is used.
                    step_server_addr = server_addr
                    if step.target and cluster_ctx is not None:
                        try:
                            tnode = cluster_ctx.cluster_state.node_by_target(step.target)
                            step_server_addr = tnode.address
                        except ValueError as exc:
                            errors.append(f"Step {i + 1} failed: {exc}")
                            return TestResult(
                                name=test_case.name,
                                passed=False,
                                duration_ms=(time.time() - start_time) * 1000,
                                output="\n".join(outputs),
                                error="\n".join(errors),
                            )

                    cmd = [binary, "query", step.query or ""]
                    cmd.extend(["--server", step_server_addr])
                    if use_grpc:
                        cmd.append("--grpc")
                    else:
                        cmd.extend(client_tls_args(env))
                    cmd.extend(["-U", "geode", "-P", admin_password])

                    try:
                        result = subprocess.run(
                            cmd,
                            env=env,
                            capture_output=True,
                            text=True,
                            timeout=step.timeout_ms / 1000.0,
                        )
                    except subprocess.TimeoutExpired:
                        if step.allow_failure:
                            outputs.append(f"Step {i + 1}: GQL timed out (allow_failure)")
                            continue
                        errors.append(f"Step {i + 1} failed: GQL query timed out")
                        return TestResult(
                            name=test_case.name,
                            passed=False,
                            duration_ms=(time.time() - start_time) * 1000,
                            output="\n".join(outputs),
                            error="\n".join(errors),
                        )

                    step_failed = result.returncode != 0
                    failure_detail = ""

                    # capture_regex / capture_as: extract this step's current
                    # capture value (if declared). Storage under capture_as is
                    # deferred until after the gql_expected checks below finalize
                    # step_failed — a step that fails its own checks (even one
                    # with allow_failure: true) must not commit a garbage value
                    # that later equals_capture comparisons would silently trust.
                    capture_value, capture_error = _extract_capture(step, result.stdout)
                    if capture_error:
                        step_failed = True
                        failure_detail = capture_error

                    if step.gql_expected:
                        expected_status = step.gql_expected.get("status_class")
                        if expected_status and expected_status not in result.stdout:
                            step_failed = True
                            failure_detail = f"expected status {expected_status}"

                        for needle in _as_list(step.gql_expected.get("stdout_contains")):
                            if needle not in result.stdout:
                                step_failed = True
                                failure_detail = f"stdout missing {needle!r}"

                        for needle in _as_list(step.gql_expected.get("stdout_not_contains")):
                            if needle in result.stdout:
                                step_failed = True
                                failure_detail = f"stdout unexpectedly contains {needle!r}"

                        equals_capture_name = step.gql_expected.get("equals_capture")
                        if equals_capture_name is not None and not capture_error:
                            if capture_value is None:
                                step_failed = True
                                failure_detail = "equals_capture requires capture_regex on the same step"
                            elif equals_capture_name not in captures:
                                step_failed = True
                                failure_detail = f"unknown capture name: {equals_capture_name!r}"
                            elif captures[equals_capture_name] != capture_value:
                                step_failed = True
                                failure_detail = (
                                    f"equals_capture mismatch: {equals_capture_name}="
                                    f"{captures[equals_capture_name]!r} != {capture_value!r}"
                                )

                    # Commit the capture only now that the step's failure state
                    # is finalized — a step that failed (status/expectation
                    # checks or allow_failure) never poisons a later step's
                    # equals_capture comparison.
                    if step.capture_as and not step_failed and not capture_error:
                        captures[step.capture_as] = capture_value  # type: ignore[assignment]

                    if step_failed and not step.allow_failure:
                        detail = failure_detail or (result.stderr.strip() or "non-zero exit")
                        errors.append(f"Step {i + 1} failed: GQL {detail}")
                        return TestResult(
                            name=test_case.name,
                            passed=False,
                            duration_ms=(time.time() - start_time) * 1000,
                            output="\n".join(outputs) + "\n" + result.stdout,
                            error="\n".join(errors),
                        )

                    suffix = " (allow_failure)" if step_failed else ""
                    outputs.append(f"Step {i + 1}: GQL OK{suffix} :: {result.stdout.strip()[:160]}")

                else:
                    errors.append(f"Step {i + 1} failed: unknown step type {step.step_type!r}")
                    return TestResult(
                        name=test_case.name,
                        passed=False,
                        duration_ms=(time.time() - start_time) * 1000,
                        output="\n".join(outputs),
                        error="\n".join(errors),
                    )

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
