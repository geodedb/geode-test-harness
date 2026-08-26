"""Test specification loading and validation.

This module handles parsing YAML test specifications and validating them
against the expected schema.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .cluster_types import ClusterConfig


# ---------------------------------------------------------------------------
# Custom YAML loader: disable YAML 1.1 sexagesimal number parsing.
#
# PyYAML (YAML 1.1) treats values like 14:30 as sexagesimal integers
# (14*60 + 30 = 870) and 14:30:00 as 52200.  YAML 1.2 dropped this
# implicit tag, and our spec files are written by humans who mean "14:30"
# as a literal string.  We subclass SafeLoader and replace the int/float
# resolver regexes with versions that omit the sexagesimal alternative.
# ---------------------------------------------------------------------------
class _SafeLoaderNoSexagesimal(yaml.SafeLoader):
    pass


# Replacement patterns: same as PyYAML defaults but without sexagesimal.
_INT_NO_SEXA = re.compile(
    r"^(?:[-+]?0b[0-1_]+" r"|[-+]?0[0-7_]+" r"|[-+]?(?:0|[1-9][0-9_]*)" r"|[-+]?0x[0-9a-fA-F_]+)$",
    re.VERBOSE,
)
_FLOAT_NO_SEXA = re.compile(
    r"^(?:[-+]?(?:[0-9][0-9_]*)\.  [0-9_]*(?:[eE][-+][0-9]+)?"
    r"|\.[0-9][0-9_]*(?:[eE][-+][0-9]+)?"
    r"|[-+]?\.(?:inf|Inf|INF)"
    r"|\.(?:nan|NaN|NAN))$",
    re.VERBOSE,
)
_INT_TAG = "tag:yaml.org,2002:int"
_FLOAT_TAG = "tag:yaml.org,2002:float"

for _key in list(_SafeLoaderNoSexagesimal.yaml_implicit_resolvers):
    _SafeLoaderNoSexagesimal.yaml_implicit_resolvers[_key] = [
        (_INT_TAG, _INT_NO_SEXA)
        if tag == _INT_TAG
        else (_FLOAT_TAG, _FLOAT_NO_SEXA)
        if tag == _FLOAT_TAG
        else (tag, regexp)
        for tag, regexp in _SafeLoaderNoSexagesimal.yaml_implicit_resolvers[_key]
    ]


class SpecValidationError(Exception):
    """Raised when a test specification fails validation."""

    pass


@dataclass
class HttpExpected:
    """Expected result for an HTTP request."""

    status_code: int | None = None
    content_type: str | None = None
    body_contains: list[str] | None = None
    body_not_contains: list[str] | None = None
    body_regex: list[str] | None = None
    headers: dict[str, str] | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> HttpExpected:
        """Create an HttpExpected from a dictionary."""
        if data is None:
            return cls()

        def normalize_list(value: Any) -> list[Any] | None:
            if value is None:
                return None
            if isinstance(value, list):
                return value
            return [value]

        return cls(
            status_code=data.get("status_code"),
            content_type=data.get("content_type"),
            body_contains=normalize_list(data.get("body_contains")),
            body_not_contains=normalize_list(data.get("body_not_contains")),
            body_regex=normalize_list(data.get("body_regex")),
            headers=data.get("headers"),
        )


@dataclass
class HttpRequest:
    """Definition of an HTTP request for testing."""

    method: str = "GET"
    url: str = ""
    headers: dict[str, str] = field(default_factory=dict)
    body: str | None = None
    timeout_ms: int = 5000
    expected: HttpExpected = field(default_factory=HttpExpected)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> HttpRequest:
        """Create an HttpRequest from a dictionary."""
        return cls(
            method=data.get("method", "GET"),
            url=data.get("url", ""),
            headers=data.get("headers", {}),
            body=data.get("body"),
            timeout_ms=data.get("timeout_ms", 5000),
            expected=HttpExpected.from_dict(data.get("expect")),
        )


@dataclass
class TestStep:
    """A single step in a sequential test.

    Step types
    ----------
    gql       — run a GQL query against the current server.
    http      — issue an HTTP request.
    wait      — sleep ``wait_ms`` milliseconds.
    bash      — run a shell command.
    signal    — send a Unix signal to a named cluster node process
                (cluster-mode specs only). Requires ``target`` ("node:N")
                and ``sig`` (SIGSTOP | SIGCONT | SIGKILL | SIGTERM).
    restart_node — stop (if running) then restart a single cluster node
                on its original port + data directory. Requires ``target``.
    """

    step_type: str  # "gql", "http", "wait", "bash", "signal", "restart_node"
    query: str | None = None
    method: str | None = None
    url: str | None = None
    headers: dict[str, str] = field(default_factory=dict)
    body: str | None = None
    command: str | None = None
    timeout_ms: int = 5000
    wait_ms: int = 0
    expected: HttpExpected | None = None
    gql_expected: dict[str, Any] | None = None
    # Cluster-control fields (signal / restart_node steps)
    target: str | None = None  # e.g. "node:0"
    sig: str | None = None  # e.g. "SIGSTOP", "SIGCONT", "SIGKILL"
    # When set, a gql step asserting the surviving server is reachable may
    # tolerate a non-zero exit (used after SIGSTOP/SIGKILL on a peer node).
    allow_failure: bool = False

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TestStep:
        """Create a TestStep from a dictionary."""
        step_type = data.get("type", "gql")
        return cls(
            step_type=step_type,
            query=data.get("query"),
            method=data.get("method"),
            url=data.get("url"),
            headers=data.get("headers", {}),
            body=data.get("body"),
            command=data.get("command"),
            timeout_ms=data.get("timeout_ms", 5000),
            wait_ms=data.get("wait_ms", 0),
            expected=HttpExpected.from_dict(data.get("expect")) if step_type == "http" else None,
            gql_expected=data.get("expect") if step_type == "gql" else None,
            target=data.get("target"),
            sig=data.get("sig"),
            allow_failure=bool(data.get("allow_failure", False)),
        )


@dataclass
class ExpectedResult:
    """Expected result for a test case."""

    status: str = "success"
    result_contains: str | list[Any] | dict[str, Any] | None = None
    result_not_contains: str | list[Any] | dict[str, Any] | None = None
    result_matches: str | list[str] | None = None
    error_contains: str | list[str] | None = None
    exit_code: int | list[int] | None = None
    stdout_contains: list[str | dict[str, Any]] | None = None
    output_contains: list[str | dict[str, Any]] | None = None  # combined stdout+stderr
    stderr_contains: list[str] | None = None
    stdout_not_contains: list[str | dict[str, Any]] | None = None
    stderr_not_contains: list[str] | None = None
    stdout_regex: list[str] | None = None
    stderr_regex: list[str] | None = None
    stdout_exact: str | None = None  # Exact stdout match (stripped)
    stderr_exact: str | None = None  # Exact stderr match (stripped)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ExpectedResult:
        """Create an ExpectedResult from a dictionary.

        Supports both geodetestlab format (status, result_contains, etc.)
        and legacy CLI test format (exit_code, stdout_contains, etc.).
        """

        # Helper function to normalize list fields
        def normalize_list(value: Any) -> list[Any] | None:
            if value is None:
                return None
            if isinstance(value, list):
                return value
            return [value]

        # Support "contains" as shorthand for "stdout_contains"
        stdout_contains = normalize_list(data.get("stdout_contains")) or normalize_list(data.get("contains"))
        # Support "not_contains" as shorthand for "stdout_not_contains"
        stdout_not_contains = normalize_list(data.get("stdout_not_contains")) or normalize_list(
            data.get("not_contains")
        )
        # Support "regex" / "matches" as shorthand for "stdout_regex"
        stdout_regex = (
            normalize_list(data.get("stdout_regex"))
            or normalize_list(data.get("regex"))
            or normalize_list(data.get("matches"))
        )

        return cls(
            status=data.get("status", "success"),
            result_contains=data.get("result_contains"),
            result_not_contains=data.get("result_not_contains"),
            result_matches=data.get("result_matches"),
            error_contains=data.get("error_contains"),
            exit_code=data.get("exit_code"),
            stdout_contains=stdout_contains,
            output_contains=normalize_list(data.get("output_contains")),
            stderr_contains=normalize_list(data.get("stderr_contains")),
            stdout_not_contains=stdout_not_contains,
            stderr_not_contains=normalize_list(data.get("stderr_not_contains")),
            stdout_regex=stdout_regex,
            stderr_regex=normalize_list(data.get("stderr_regex")),
            stdout_exact=data.get("stdout_exact"),
            stderr_exact=data.get("stderr_exact"),
        )


@dataclass
class PlaintextCheck:
    """Configuration for plaintext verification after test execution."""

    enabled: bool = False
    search_patterns: list[str] = field(default_factory=list)
    scan_paths: list[str] = field(default_factory=list)
    exclude_extensions: list[str] = field(default_factory=lambda: [".log", ".txt", ".md", ".yml", ".yaml", ".json"])
    fail_on_violation: bool = True

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> PlaintextCheck:
        """Create a PlaintextCheck from a dictionary."""
        if data is None:
            return cls()
        return cls(
            enabled=data.get("enabled", False),
            search_patterns=data.get("search_patterns", []),
            scan_paths=data.get("scan_paths", []),
            exclude_extensions=data.get("exclude_extensions", [".log", ".txt", ".md", ".yml", ".yaml", ".json"]),
            fail_on_violation=data.get("fail_on_violation", True),
        )


@dataclass
class TestCase:
    """A single test case within a test specification."""

    name: str
    description: str
    test_type: str = "cli"  # "cli", "http", or "sequential"
    query: str | None = None
    command: str | None = None
    args: list[str] = field(default_factory=list)
    stdin: str | None = None
    env: dict[str, str] = field(default_factory=dict)
    expected: ExpectedResult = field(default_factory=ExpectedResult)
    skip: bool = False
    skip_reason: str | None = None
    plaintext_check: PlaintextCheck = field(default_factory=PlaintextCheck)
    # Setup files to create before running the test
    setup_files: list[dict[str, str]] = field(default_factory=list)
    # Per-test setup queries to run before the test command
    setup_queries: list[dict[str, Any]] = field(default_factory=list)
    # Per-test timeout override (if larger than global timeout, this takes precedence)
    timeout_ms: int = 0
    # Request a managed server restart after this test succeeds
    restart_server: bool = False
    # HTTP test fields
    http_requests: list[HttpRequest] = field(default_factory=list)
    # Sequential test fields
    steps: list[TestStep] = field(default_factory=list)
    # DSN connection string — when set, uses --dsn instead of --server and skips -U/-P injection
    dsn: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TestCase:
        """Create a TestCase from a dictionary.

        Supports geodetestlab format, legacy CLI test format, HTTP tests, and sequential tests.
        """
        # Support both 'expected' and 'expect' keys for expected results
        expected_data = data.get("expected") or data.get("expect") or {}
        plaintext_data = data.get("plaintext_check")

        # For shell tests, expected_exit_code is at top level
        if data.get("type") == "shell" and "expected_exit_code" in data:
            if not isinstance(expected_data, dict):
                expected_data = {}
            expected_data = dict(expected_data)  # Make a copy to avoid mutation
            expected_data["exit_code"] = data["expected_exit_code"]

        # Support expected_stdout at top level (exact match converted to stdout_contains)
        if "expected_stdout" in data:
            if not isinstance(expected_data, dict):
                expected_data = {}
            expected_data = dict(expected_data)  # Make a copy to avoid mutation
            # Treat as exact match - strip and compare
            expected_data["stdout_exact"] = data["expected_stdout"]

        # Support expected_stderr at top level
        if "expected_stderr" in data:
            if not isinstance(expected_data, dict):
                expected_data = {}
            expected_data = dict(expected_data)  # Make a copy to avoid mutation
            expected_data["stderr_exact"] = data["expected_stderr"]

        # Support expected_output: {contains: [...]} legacy format
        if "expected_output" in data:
            if not isinstance(expected_data, dict):
                expected_data = {}
            expected_data = dict(expected_data)
            eo = data["expected_output"]
            if isinstance(eo, dict):
                if "contains" in eo:
                    existing = expected_data.get("stdout_contains") or []
                    contains_val = eo["contains"]
                    if isinstance(contains_val, list):
                        existing.extend(contains_val)
                    else:
                        existing.append(contains_val)
                    expected_data["stdout_contains"] = existing

        # Support expected_output_contains at top level
        if "expected_output_contains" in data:
            if not isinstance(expected_data, dict):
                expected_data = {}
            expected_data = dict(expected_data)
            eoc = data["expected_output_contains"]
            existing = expected_data.get("stdout_contains") or []
            if isinstance(eoc, list):
                existing.extend(eoc)
            else:
                existing.append(eoc)
            expected_data["stdout_contains"] = existing

        # Support expected_output_pattern at top level
        if "expected_output_pattern" in data:
            if not isinstance(expected_data, dict):
                expected_data = {}
            expected_data = dict(expected_data)
            eop = data["expected_output_pattern"]
            existing = expected_data.get("stdout_regex") or []
            if isinstance(eop, list):
                existing.extend(eop)
            else:
                existing.append(eop)
            expected_data["stdout_regex"] = existing

        # Determine test type
        test_type = data.get("type", "cli")

        # Parse HTTP requests
        http_requests = []
        if "requests" in data:
            for req in data["requests"]:
                http_requests.append(HttpRequest.from_dict(req))

        # Parse sequential steps
        steps = []
        if "steps" in data:
            for step in data["steps"]:
                steps.append(TestStep.from_dict(step))

        # Parse setup files (files to create before running the test)
        setup_files = []
        setup_queries: list[dict[str, Any]] = []
        setup_data = data.get("setup")
        if isinstance(setup_data, dict) and "files" in setup_data:
            setup_files = setup_data["files"]
        elif isinstance(setup_data, list):
            # Per-test setup queries: list of dicts with args/expect keys
            setup_queries = [item for item in setup_data if isinstance(item, dict)]

        return cls(
            name=data["name"],
            description=data.get("description", ""),
            test_type=test_type,
            query=data.get("query"),
            command=data.get("command"),
            args=data.get("args", []),
            stdin=data.get("stdin"),
            env=data.get("env", {}),
            expected=ExpectedResult.from_dict(expected_data) if isinstance(expected_data, dict) else ExpectedResult(),
            skip=data.get("skip", False),
            skip_reason=data.get("skip_reason"),
            plaintext_check=PlaintextCheck.from_dict(plaintext_data),
            setup_files=setup_files,
            setup_queries=setup_queries,
            timeout_ms=data.get("timeout_ms", 0),
            restart_server=data.get("restart_server", False),
            http_requests=http_requests,
            steps=steps,
            dsn=data.get("dsn"),
        )


@dataclass
class SecretConfig:
    """Configuration for a secret referenced in a test specification."""

    source: str  # "env" or "keyring"
    key: str | None = None
    service: str | None = None
    required: bool = True
    default: str | None = None  # Default value if not found

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SecretConfig:
        """Create a SecretConfig from a dictionary."""
        return cls(
            source=data.get("source", "env"),
            key=data.get("key"),
            service=data.get("service"),
            required=data.get("required", True),
            default=data.get("default"),
        )


@dataclass
class TestSpec:
    """Complete test specification loaded from a YAML file."""

    name: str
    description: str
    mode: str = "server"  # "server" or "cli"
    server_args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    secrets: dict[str, SecretConfig] = field(default_factory=dict)
    tests: list[TestCase] = field(default_factory=list)
    setup: list[str | dict[str, Any]] | None = None
    teardown: list[str] | None = None
    pre_server: list[str] | None = None  # Shell commands to run before server starts
    tde_config: dict[str, Any] | None = None
    plaintext_verification: PlaintextCheck = field(default_factory=PlaintextCheck)
    parallel_tests: bool = False
    default_timeout_ms: int = 0  # Spec-level default timeout for all tests (0 = use runner default)
    skip: str | None = (
        None  # Top-level skip directive (free-text reason). When set, the spec is pending and contributes 0 cases to the run.
    )
    cluster_config: ClusterConfig | None = None
    # When true, the spec opts out of `--force-cluster-size N` promotion
    # (the harness will not synthesize a ClusterConfig). Useful for specs
    # that exercise filesystem-local state or single-process invariants
    # that don't translate to multi-node deployments.
    single_node_only: bool = False

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TestSpec:
        """Create a TestSpec from a dictionary.

        Supports both the new cli: block format and legacy flat format.
        """
        secrets = {}
        for name, config in data.get("secrets", {}).items():
            secrets[name] = SecretConfig.from_dict(config) if isinstance(config, dict) else SecretConfig(source="env")

        tests = []
        for test_data in data.get("tests", []):
            tests.append(TestCase.from_dict(test_data))

        # Extract configuration from cli: block if present (new format)
        cli_config = data.get("cli", {})
        server_config = cli_config.get("server", {})

        # Determine mode: if cli.server.enabled is explicitly set, use it
        # Otherwise fall back to legacy mode field or skip_server flag
        if "server" in cli_config and "enabled" in server_config:
            mode = "server" if server_config.get("enabled", True) else "cli"
        elif data.get("skip_server", False):
            mode = "cli"
        else:
            mode = data.get("mode", "server")

        # Get server args from cli.server.args or legacy server_args
        server_args = server_config.get("args", data.get("server_args", []))

        # Merge environment: start with top-level env, then overlay cli.server.env
        # This ensures both legacy env vars and server-specific env vars are available
        env = data.get("env", {}).copy()
        env.update(server_config.get("env", {}))

        # Parse cluster configuration
        cluster_config = None
        cluster_data = data.get("cluster")
        if cluster_data is not None:
            cluster_config = ClusterConfig.from_dict(cluster_data)
            mode = "cluster"  # Override mode when cluster block is present

        return cls(
            name=data.get("name", "unnamed"),
            description=data.get("description", ""),
            mode=mode,
            server_args=server_args,
            env=env,
            secrets=secrets,
            tests=tests,
            setup=data.get("setup"),
            teardown=data.get("teardown"),
            pre_server=data.get("pre_server"),
            tde_config=data.get("tde_config"),
            plaintext_verification=PlaintextCheck.from_dict(data.get("plaintext_verification")),
            parallel_tests=bool(data.get("parallel_tests", False)),
            default_timeout_ms=data.get("default_timeout_ms", 0),
            skip=(str(data["skip"]) if data.get("skip") else None),
            cluster_config=cluster_config,
            single_node_only=bool(data.get("single_node_only", False)),
        )


def load_spec(path: str | Path) -> TestSpec:
    """Load and validate a test specification from a YAML file.

    Parameters
    ----------
    path : Union[str, Path]
        Path to the YAML specification file.

    Returns
    -------
    TestSpec
        The loaded and validated test specification.

    Raises
    ------
    SpecValidationError
        If the specification fails validation.
    FileNotFoundError
        If the specification file doesn't exist.
    """
    path = Path(path)

    if not path.exists():
        raise FileNotFoundError(f"Specification file not found: {path}")

    if not path.is_file():
        raise SpecValidationError(f"Path is not a file: {path}")

    try:
        with open(path, encoding="utf-8") as f:
            data = yaml.load(f, Loader=_SafeLoaderNoSexagesimal)  # noqa: S506  # nosec B506 - SafeLoader subclass
    except yaml.YAMLError as e:
        raise SpecValidationError(f"Invalid YAML syntax: {e}") from e

    if not isinstance(data, dict):
        raise SpecValidationError("Specification must be a YAML mapping (dictionary)")

    # Validate required fields
    if "name" not in data:
        raise SpecValidationError("Specification must have a 'name' field")

    # A spec-level `skip:` directive (string reason or truthy value) means
    # the spec documents a future / pending capability and need not yet
    # define `tests:`. The runner contributes 0 cases to the run.
    spec_skipped = bool(data.get("skip"))

    if "tests" not in data:
        if spec_skipped:
            data["tests"] = []
        else:
            raise SpecValidationError("Specification must have a 'tests' field")

    if not isinstance(data["tests"], list):
        raise SpecValidationError("'tests' must be a list")

    # Validate each test case
    for i, test in enumerate(data["tests"]):
        if not isinstance(test, dict):
            raise SpecValidationError(f"Test case {i} must be a mapping")

        if "name" not in test:
            raise SpecValidationError(f"Test case {i} must have a 'name' field")

        # Determine test type
        test_type = test.get("type", "cli")

        # Validate based on test type
        if test_type == "http":
            # HTTP tests must have requests
            if "requests" not in test:
                raise SpecValidationError(f"HTTP test case '{test['name']}' must have a 'requests' field")
        elif test_type == "sequential":
            # Sequential tests must have steps
            if "steps" not in test:
                raise SpecValidationError(f"Sequential test case '{test['name']}' must have a 'steps' field")
        else:
            # CLI tests must have either query, command, or args+stdin (legacy format)
            has_query = "query" in test
            has_command = "command" in test
            has_args = "args" in test
            has_stdin = "stdin" in test
            if not (has_query or has_command or has_args or has_stdin):
                raise SpecValidationError(
                    f"Test case '{test['name']}' must have either 'query', 'command', 'args', or 'stdin'"
                )

    # Validate mode
    mode = data.get("mode", "server")
    if mode not in ("server", "cli", "cluster"):
        raise SpecValidationError(f"Invalid mode '{mode}'. Must be 'server' or 'cli'")

    return TestSpec.from_dict(data)
