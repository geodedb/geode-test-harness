"""Shared data types for the geodetestlab runner subsystem."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

# Centralized test credential — every Python module should import this
# constant instead of defining its own.  The value is read from the
# environment at import time so it can be overridden externally.
DEFAULT_ADMIN_PASSWORD: str = os.environ.get("GEODE_ADMIN_PASSWORD", "GeodeTestPassword123!")

# Network port defaults — centralised so every module imports from here.
DEFAULT_QUIC_PORT: int = 3141
DEFAULT_GRPC_PORT: int = 50051


class RunnerError(Exception):
    """Raised when the test runner encounters an error."""


@dataclass
class TestResult:
    """Result of a single test case execution."""

    name: str
    passed: bool
    duration_ms: float
    output: str = ""
    error: str = ""
    skip_reason: str | None = None
    plaintext_violations: list[str] = field(default_factory=list)


@dataclass
class RunSummary:
    """Summary of a test run."""

    total: int = 0
    passed: int = 0
    failed: int = 0
    skipped: int = 0
    duration_ms: float = 0.0
    results: list[TestResult] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "total": self.total,
            "passed": self.passed,
            "failed": self.failed,
            "skipped": self.skipped,
            "duration_ms": self.duration_ms,
        }
