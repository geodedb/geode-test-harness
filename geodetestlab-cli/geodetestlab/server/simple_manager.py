"""Simple server lifecycle management for GeodeTestLab.

This module re-exports the shared ServerManager from the geode-test-harness
lib module. The implementation is shared between different test runners.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

# Import shared modules from the parent geode-test-harness lib
# We load them directly by path to avoid name collision with geodetestlab's lib
_harness_root = Path(__file__).parent.parent.parent.parent
_harness_lib_path = _harness_root / "lib"


def _load_module_from_path(name: str, path: Path) -> ModuleType:
    """Load a Python module from a file path."""
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load module from {path}")
    module = importlib.util.module_from_spec(spec)
    return module, spec


# Load utils first (server_manager depends on it)
_utils_module, _utils_spec = _load_module_from_path(
    "harness_lib_utils", _harness_lib_path / "utils.py"
)
_utils_spec.loader.exec_module(_utils_module)

# Load server_manager, but we need to handle its relative import
# by pre-injecting the function it needs
_sm_path = _harness_lib_path / "server_manager.py"
_sm_source = _sm_path.read_text()
# Replace the relative import with an absolute one using our loaded module
_sm_source = _sm_source.replace(
    "from .utils import get_free_port",
    "pass  # get_free_port injected externally"
)
_sm_code = compile(_sm_source, str(_sm_path), "exec")

# Create a module namespace with the required imports pre-loaded
_sm_namespace = {
    "__name__": "harness_lib_server_manager",
    "__file__": str(_sm_path),
    "__builtins__": __builtins__,
    "get_free_port": _utils_module.get_free_port,
}
exec(_sm_code, _sm_namespace)

# Extract the ServerManager class
ServerManager = _sm_namespace["ServerManager"]

__all__ = ["ServerManager"]
