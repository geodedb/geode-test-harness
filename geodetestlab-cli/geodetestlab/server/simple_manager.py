"""Simple server lifecycle management for GeodeTestLab.

This module re-exports the shared ServerManager from the geode-test-harness
lib module. The implementation is shared between different test runners.
"""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

# Import shared modules from the parent geode-test-harness lib
# We load them directly by path to avoid name collision with geodetestlab's lib
_harness_root = Path(__file__).parent.parent.parent.parent
_harness_lib_path = _harness_root / "lib"

# Synthetic package name to avoid collisions with geodetestlab.lib
_PKG = "harness_lib"


def _load_module(name: str, path: Path) -> types.ModuleType:
    """Load a Python module by file path and register it in sys.modules."""
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load module from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


# Register a synthetic package so that ``from .utils import get_free_port``
# inside server_manager.py resolves via normal importlib (no exec/compile).
if _PKG not in sys.modules:
    _pkg_mod = types.ModuleType(_PKG)
    _pkg_mod.__path__ = [str(_harness_lib_path)]
    _pkg_mod.__package__ = _PKG
    sys.modules[_PKG] = _pkg_mod

# Load utils first (server_manager depends on it via relative import)
_load_module(f"{_PKG}.utils", _harness_lib_path / "utils.py")

# Load server_manager using standard importlib — no exec() needed
_sm = _load_module(f"{_PKG}.server_manager", _harness_lib_path / "server_manager.py")

# Re-export the ServerManager class
ServerManager = _sm.ServerManager

__all__ = ["ServerManager"]
