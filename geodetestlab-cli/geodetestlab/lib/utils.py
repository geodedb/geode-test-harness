"""Utility functions for geodetestlab.

This module provides helper functions for finding binaries, managing ports,
resolving secrets, and validating inputs.

Common utilities (get_free_port, find_geode_binary, format_duration, sanitize_filename)
are imported from the shared lib module.
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
from pathlib import Path
from typing import Any

# Import shared utilities from the parent geode-test-harness lib
# We need to load the harness lib/utils.py directly to avoid name collision
# with geodetestlab's own lib subpackage
_harness_root = Path(__file__).parent.parent.parent.parent
_harness_utils_path = _harness_root / "lib" / "utils.py"

# Load the module directly by path to avoid import conflicts
_spec = importlib.util.spec_from_file_location("harness_utils", _harness_utils_path)
if _spec is None or _spec.loader is None:
    raise ImportError(f"Cannot load shared utils from {_harness_utils_path}")
_harness_utils = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_harness_utils)

# Import functions from the loaded module
find_geode_binary = _harness_utils.find_geode_binary
format_duration = _harness_utils.format_duration
get_free_port = _harness_utils.get_free_port
sanitize_filename = _harness_utils.sanitize_filename

# Re-export shared utilities
__all__ = [
    "find_geode_binary",
    "format_duration",
    "get_free_port",
    "sanitize_filename",
    "resolve_secrets",
    "SecretResolutionError",
    "GeodeBinaryNotFoundError",
    "sanitize_args",
    "is_valid_gql",
    "extract_json_from_output",
]


class GeodeBinaryNotFoundError(FileNotFoundError):
    """Raised when the Geode binary cannot be found."""

    pass


# Shell metacharacters that indicate likely test misconfiguration.
# Note: subprocess.run is always called with a list (shell=False), so
# no character is actually dangerous.  This check only catches obvious
# mistakes like embedded pipes or command substitutions.
# Characters like (), {}, !, $ are intentionally excluded because they
# appear in GQL queries, passwords, and JSON arguments.
_SHELL_METACHARACTERS = frozenset(";|&`")


def sanitize_args(args: list[str]) -> list[str]:
    """Validate CLI arguments for unsafe characters.

    Parameters
    ----------
    args : list[str]
        List of CLI arguments to validate.

    Returns
    -------
    list[str]
        The same arguments if all are safe.

    Raises
    ------
    ValueError
        If any argument contains unsafe characters.
    """
    for arg in args:
        # Check for non-printable characters
        for ch in arg:
            if ord(ch) < 0x20 and ch not in ("\n", "\r"):
                raise ValueError(f"Non\u2011printable character in argument: {arg!r}")
        # Check for shell metacharacters
        for ch in arg:
            if ch in _SHELL_METACHARACTERS:
                raise ValueError(f"Invalid character '{ch}' in argument: {arg!r}")
    return args


# GQL keywords that indicate a valid query start
_GQL_KEYWORDS = {
    "MATCH",
    "CREATE",
    "DELETE",
    "DETACH",
    "SET",
    "REMOVE",
    "MERGE",
    "RETURN",
    "WITH",
    "UNWIND",
    "CALL",
    "EXPLAIN",
    "PROFILE",
    "INSERT",
    "DROP",
    "ALTER",
    "BEGIN",
    "COMMIT",
    "ROLLBACK",
    "SESSION",
    "OPTIONAL",
    "FOR",
    "LET",
    "FILTER",
    "LIMIT",
    "ORDER",
    "SKIP",
    "WHERE",
    "YIELD",
    "USE",
    "SHOW",
}


def is_valid_gql(query: str) -> bool:
    """Check if a string looks like a valid GQL query.

    This performs basic syntactic validation, not full parsing.

    Parameters
    ----------
    query : str
        The query string to validate.

    Returns
    -------
    bool
        True if the query appears to be valid GQL.
    """
    if not query or not query.strip():
        return False

    stripped = query.strip()

    # Check first word is a GQL keyword
    first_word = stripped.split()[0].upper()
    if first_word not in _GQL_KEYWORDS:
        return False

    # Check bracket balance
    stack: list[str] = []
    matching = {"(": ")", "[": "]", "{": "}"}
    for ch in stripped:
        if ch in matching:
            stack.append(matching[ch])
        elif ch in matching.values():
            if not stack or stack[-1] != ch:
                return False
            stack.pop()

    return len(stack) == 0


def extract_json_from_output(output: str) -> Any:
    """Extract and parse JSON from CLI output that may contain non-JSON text.

    Parameters
    ----------
    output : str
        Raw CLI output potentially containing JSON.

    Returns
    -------
    Any
        Parsed JSON data, or None if no valid JSON found.
    """
    # Try the whole string first
    try:
        return json.loads(output.strip())
    except (json.JSONDecodeError, ValueError):
        pass

    # Try to find JSON object or array in the output
    for line in output.strip().splitlines():
        line = line.strip()
        if line.startswith(("{", "[")):
            try:
                return json.loads(line)
            except (json.JSONDecodeError, ValueError):
                continue

    return None


def _replace_placeholder(text: str, secrets: dict[str, str]) -> str:
    """Replace ${secret:NAME} placeholders with resolved values.

    Parameters
    ----------
    text : str
        Text containing placeholders.
    secrets : dict[str, str]
        Mapping of secret names to values.

    Returns
    -------
    str
        Text with placeholders replaced.

    Raises
    ------
    KeyError
        If a referenced secret is not defined.
    """

    def replacer(match: re.Match[str]) -> str:
        name = match.group(1)
        if name not in secrets:
            raise KeyError(f"Secret '{name}' is not defined")
        return secrets[name]

    return re.sub(r"\$\{secret:(\w+)\}", replacer, text)


from .spec import SecretConfig, TestSpec  # noqa: E402  # circular import


class SecretResolutionError(Exception):
    """Raised when a required secret cannot be resolved."""

    pass


def resolve_secrets(spec: TestSpec) -> tuple[dict[str, str], dict[str, str]]:
    """Resolve all secrets referenced in a test specification.

    Parameters
    ----------
    spec : TestSpec
        The test specification containing secret definitions.

    Returns
    -------
    Tuple[Dict[str, str], Dict[str, str]]
        A tuple of (secrets, env_vars) where secrets maps secret names to
        values and env_vars maps environment variable names to values.

    Raises
    ------
    SecretResolutionError
        If a required secret cannot be resolved.
    """
    secrets: dict[str, str] = {}
    env_vars: dict[str, str] = {}

    for name, config in spec.secrets.items():
        value = _resolve_secret(name, config)
        if value is None:
            if config.required:
                raise SecretResolutionError(f"Required secret '{name}' could not be resolved. Source: {config.source}")
        else:
            secrets[name] = value

    # Also resolve any environment variable references in spec.env
    for env_name, env_value in spec.env.items():
        if env_value.startswith("$"):
            # Reference to an environment variable
            ref_name = env_value[1:]
            resolved = os.environ.get(ref_name)
            if resolved:
                env_vars[env_name] = resolved
            elif env_value.startswith("${") and env_value.endswith("}"):
                # ${VAR:-default} syntax
                inner = env_value[2:-1]
                if ":-" in inner:
                    ref_name, default = inner.split(":-", 1)
                    env_vars[env_name] = os.environ.get(ref_name, default)
                else:
                    resolved = os.environ.get(inner)
                    if resolved:
                        env_vars[env_name] = resolved
        else:
            env_vars[env_name] = env_value

    return secrets, env_vars


def _resolve_secret(name: str, config: SecretConfig) -> str | None:
    """Resolve a single secret.

    Parameters
    ----------
    name : str
        The name of the secret.
    config : SecretConfig
        Configuration for resolving the secret.

    Returns
    -------
    Optional[str]
        The resolved secret value, or None if not found.
    """
    value = None

    if config.source == "env":
        # Environment variable
        env_key = config.key or name
        value = os.environ.get(env_key)

    elif config.source == "keyring":
        # System keyring (requires keyring package)
        try:
            import keyring

            service = config.service or "geodetestlab"
            key = config.key or name
            value = keyring.get_password(service, key)
        except Exception:
            # ImportError: keyring not installed
            # keyring.errors.NoKeyringError: no backend available (CI)
            pass

    elif config.source == "file":
        # Read from file — restrict to safe directories to prevent
        # arbitrary file reads via crafted YAML specs (CWE-22 / SEC-002).
        if config.key:
            path = Path(config.key).expanduser().resolve()
            # Allow files under the user's home, /tmp, or working directory.
            _allowed_roots = [
                Path.home(),
                Path("/tmp"),
                Path.cwd(),
            ]
            if not any(path.is_relative_to(root) for root in _allowed_roots):
                import logging as _log

                _log.getLogger(__name__).warning(
                    "Secret file path rejected (outside allowed directories): %s",
                    path,
                )
            elif path.exists():
                value = path.read_text().strip()

    # Use default if no value found
    if value is None and config.default is not None:
        value = config.default

    return value
