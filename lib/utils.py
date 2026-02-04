"""Shared utility functions for geode-test-harness.

This module provides helper functions shared between different test runners
including shell_runner and geodetestlab. Functions include binary detection,
port allocation for parallel testing, and output formatting.
"""

from __future__ import annotations

import os
import socket
import subprocess
from pathlib import Path
from typing import Optional


def get_free_port() -> int:
    """Get a free port number for server binding.

    This function finds an available port by binding to port 0 and letting
    the OS assign a free port. Uses UDP since QUIC runs over UDP.
    This enables parallel test execution without port conflicts.

    Returns
    -------
    int
        An available port number.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.bind(("", 0))
        port = s.getsockname()[1]
    return port


def find_geode_binary(custom_path: Optional[str] = None) -> str:
    """Find the Geode binary, checking common locations.

    Parameters
    ----------
    custom_path : Optional[str]
        If provided, use this path directly.

    Returns
    -------
    str
        Path to the Geode binary.

    Raises
    ------
    FileNotFoundError
        If the binary cannot be found.
    """
    if custom_path:
        path = Path(custom_path)
        if path.exists() and path.is_file():
            return str(path.resolve())
        raise FileNotFoundError(f"Specified Geode binary not found: {custom_path}")

    # Search in common locations
    # From geode-test-harness directory structure
    harness_root = Path(__file__).parent.parent
    monorepo_root = harness_root.parent

    search_paths = [
        # Relative to geode-test-harness (monorepo sibling)
        monorepo_root / "geode" / "zig-out" / "bin" / "geode",
        # Relative to working directory
        Path("./zig-out/bin/geode"),
        Path("../zig-out/bin/geode"),
        Path("../../zig-out/bin/geode"),
        Path("../geode/zig-out/bin/geode"),
        # System paths
        Path("/usr/local/bin/geode"),
        Path("/usr/bin/geode"),
    ]

    # Also check PATH
    path_dirs = os.environ.get("PATH", "").split(os.pathsep)
    for path_dir in path_dirs:
        search_paths.append(Path(path_dir) / "geode")

    for path in search_paths:
        if path.exists() and path.is_file():
            # Verify it's executable
            try:
                result = subprocess.run(
                    [str(path), "--version"],
                    capture_output=True,
                    timeout=5,
                )
                if result.returncode == 0 or b"geode" in result.stdout.lower() or b"geode" in result.stderr.lower():
                    return str(path.resolve())
            except (subprocess.TimeoutExpired, PermissionError, OSError):
                continue

    raise FileNotFoundError(
        "Could not find Geode binary. Tried common locations and PATH. "
        "Please specify the path using --geode-binary."
    )


def format_duration(ms: float) -> str:
    """Format a duration in milliseconds to a human-readable string.

    Parameters
    ----------
    ms : float
        Duration in milliseconds.

    Returns
    -------
    str
        Formatted duration string.
    """
    if ms < 1:
        return f"{ms * 1000:.1f}us"
    elif ms < 1000:
        return f"{ms:.1f}ms"
    elif ms < 60000:
        return f"{ms / 1000:.2f}s"
    else:
        minutes = int(ms / 60000)
        seconds = (ms % 60000) / 1000
        return f"{minutes}m{seconds:.1f}s"


def sanitize_filename(name: str) -> str:
    """Convert a string to a safe filename.

    Parameters
    ----------
    name : str
        The string to sanitize.

    Returns
    -------
    str
        A sanitized filename-safe string.
    """
    replacements = {
        "/": "_",
        "\\": "_",
        ":": "_",
        "*": "_",
        "?": "_",
        '"': "_",
        "<": "_",
        ">": "_",
        "|": "_",
        " ": "_",
    }
    result = name
    for old, new in replacements.items():
        result = result.replace(old, new)
    return result
