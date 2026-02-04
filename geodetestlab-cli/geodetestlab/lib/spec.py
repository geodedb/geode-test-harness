"""Test specification loading and validation.

This module handles parsing YAML test specifications and validating them
against the expected schema.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


class SpecValidationError(Exception):
    """Raised when a test specification fails validation."""

    pass


@dataclass
class ExpectedResult:
    """Expected result for a test case."""

    status: str = "success"
    result_contains: str | None = None
    result_not_contains: str | None = None
    result_matches: str | None = None
    error_contains: str | None = None
    exit_code: int | None = None
    stdout_contains: list[str] | None = None
    stderr_contains: list[str] | None = None
    stdout_not_contains: list[str] | None = None
    stderr_not_contains: list[str] | None = None
    stdout_regex: list[str] | None = None
    stderr_regex: list[str] | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ExpectedResult:
        """Create an ExpectedResult from a dictionary.

        Supports both geodetestlab format (status, result_contains, etc.)
        and legacy CLI test format (exit_code, stdout_contains, etc.).
        """
        # Helper function to normalize list fields
        def normalize_list(value: Any) -> list[str] | None:
            if value is None:
                return None
            if isinstance(value, list):
                return value
            return [value]

        return cls(
            status=data.get("status", "success"),
            result_contains=data.get("result_contains"),
            result_not_contains=data.get("result_not_contains"),
            result_matches=data.get("result_matches"),
            error_contains=data.get("error_contains"),
            exit_code=data.get("exit_code"),
            stdout_contains=normalize_list(data.get("stdout_contains")),
            stderr_contains=normalize_list(data.get("stderr_contains")),
            stdout_not_contains=normalize_list(data.get("stdout_not_contains")),
            stderr_not_contains=normalize_list(data.get("stderr_not_contains")),
            stdout_regex=normalize_list(data.get("stdout_regex")),
            stderr_regex=normalize_list(data.get("stderr_regex")),
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
    query: str | None = None
    command: str | None = None
    args: list[str] = field(default_factory=list)
    stdin: str | None = None
    env: dict[str, str] = field(default_factory=dict)
    expected: ExpectedResult = field(default_factory=ExpectedResult)
    skip: bool = False
    skip_reason: str | None = None
    plaintext_check: PlaintextCheck = field(default_factory=PlaintextCheck)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TestCase:
        """Create a TestCase from a dictionary.

        Supports both geodetestlab format and legacy CLI test format.
        """
        # Support both 'expected' and 'expect' keys for expected results
        expected_data = data.get("expected") or data.get("expect") or {}
        plaintext_data = data.get("plaintext_check")

        return cls(
            name=data["name"],
            description=data.get("description", ""),
            query=data.get("query"),
            command=data.get("command"),
            args=data.get("args", []),
            stdin=data.get("stdin"),
            env=data.get("env", {}),
            expected=ExpectedResult.from_dict(expected_data) if isinstance(expected_data, dict) else ExpectedResult(),
            skip=data.get("skip", False),
            skip_reason=data.get("skip_reason"),
            plaintext_check=PlaintextCheck.from_dict(plaintext_data),
        )


@dataclass
class SecretConfig:
    """Configuration for a secret referenced in a test specification."""

    source: str  # "env" or "keyring"
    key: str | None = None
    service: str | None = None
    required: bool = True

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SecretConfig:
        """Create a SecretConfig from a dictionary."""
        return cls(
            source=data.get("source", "env"),
            key=data.get("key"),
            service=data.get("service"),
            required=data.get("required", True),
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
    setup: list[str] | None = None
    teardown: list[str] | None = None
    tde_config: dict[str, Any] | None = None
    plaintext_verification: PlaintextCheck = field(default_factory=PlaintextCheck)

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
        # Otherwise fall back to legacy mode field
        if "server" in cli_config and "enabled" in server_config:
            mode = "server" if server_config.get("enabled", True) else "cli"
        else:
            mode = data.get("mode", "server")

        # Get server args from cli.server.args or legacy server_args
        server_args = server_config.get("args", data.get("server_args", []))

        # Get environment from cli.server.env or legacy env
        env = server_config.get("env", data.get("env", {}))

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
            tde_config=data.get("tde_config"),
            plaintext_verification=PlaintextCheck.from_dict(data.get("plaintext_verification")),
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
            data = yaml.safe_load(f)
    except yaml.YAMLError as e:
        raise SpecValidationError(f"Invalid YAML syntax: {e}") from e

    if not isinstance(data, dict):
        raise SpecValidationError("Specification must be a YAML mapping (dictionary)")

    # Validate required fields
    if "name" not in data:
        raise SpecValidationError("Specification must have a 'name' field")

    if "tests" not in data:
        raise SpecValidationError("Specification must have a 'tests' field")

    if not isinstance(data["tests"], list):
        raise SpecValidationError("'tests' must be a list")

    # Validate each test case
    for i, test in enumerate(data["tests"]):
        if not isinstance(test, dict):
            raise SpecValidationError(f"Test case {i} must be a mapping")

        if "name" not in test:
            raise SpecValidationError(f"Test case {i} must have a 'name' field")

        # Must have either query, command, or args+stdin (legacy format)
        has_query = "query" in test
        has_command = "command" in test
        has_args = "args" in test
        has_stdin = "stdin" in test
        if not (has_query or has_command or has_args or has_stdin):
            raise SpecValidationError(f"Test case '{test['name']}' must have either 'query', 'command', 'args', or 'stdin'")

    # Validate mode
    mode = data.get("mode", "server")
    if mode not in ("server", "cli"):
        raise SpecValidationError(f"Invalid mode '{mode}'. Must be 'server' or 'cli'")

    return TestSpec.from_dict(data)
