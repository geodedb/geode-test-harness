"""Utility functions for geodetestlab.

This module provides helper functions for finding binaries, managing ports,
and resolving secrets.

Common utilities (get_free_port, find_geode_binary, format_duration, sanitize_filename)
are imported from the shared lib module.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Import shared utilities from the parent geode-test-harness lib
# utils.py -> lib -> geodetestlab -> geodetestlab-cli -> geode-test-harness
_harness_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(_harness_root))

from lib.utils import (  # noqa: E402
    find_geode_binary,
    format_duration,
    get_free_port,
    sanitize_filename,
)

# Re-export shared utilities
__all__ = [
    "find_geode_binary",
    "format_duration",
    "get_free_port",
    "sanitize_filename",
    "resolve_secrets",
    "SecretResolutionError",
]

from .spec import SecretConfig, TestSpec


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
    if config.source == "env":
        # Environment variable
        env_key = config.key or name
        return os.environ.get(env_key)

    elif config.source == "keyring":
        # System keyring (requires keyring package)
        try:
            import keyring

            service = config.service or "geodetestlab"
            key = config.key or name
            return keyring.get_password(service, key)
        except ImportError:
            return None

    elif config.source == "file":
        # Read from file
        if config.key:
            path = Path(config.key).expanduser()
            if path.exists():
                return path.read_text().strip()
        return None

    return None
