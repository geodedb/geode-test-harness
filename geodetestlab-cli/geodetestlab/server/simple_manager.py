"""Simple server lifecycle management for GeodeTestLab.

This module re-exports the shared ServerManager from the geode-test-harness
lib module. The implementation is shared between different test runners.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Import shared ServerManager from the parent geode-test-harness lib
# simple_manager.py -> server -> geodetestlab -> geodetestlab-cli -> geode-test-harness
_harness_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(_harness_root))

from lib.server_manager import ServerManager  # noqa: E402

__all__ = ["ServerManager"]
