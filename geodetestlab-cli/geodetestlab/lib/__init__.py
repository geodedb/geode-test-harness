"""Core module for geodetestlab.

This module provides the core functionality for loading specs, running tests,
resolving secrets, and utility functions.
"""

from .plaintext_scanner import PlaintextScanner, PlaintextViolation
from .runner import RunnerError, run_tests
from .spec import SecretConfig, SpecValidationError, TestCase, TestSpec, load_spec
from .utils import (
    SecretResolutionError,
    find_geode_binary,
    get_free_port,
    resolve_secrets,
)

__all__ = [
    "load_spec",
    "SpecValidationError",
    "TestSpec",
    "TestCase",
    "SecretConfig",
    "run_tests",
    "RunnerError",
    "resolve_secrets",
    "SecretResolutionError",
    "find_geode_binary",
    "get_free_port",
    "PlaintextScanner",
    "PlaintextViolation",
]
