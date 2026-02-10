"""Core module for geodetestlab.

This module provides the core functionality for loading specs, running tests,
resolving secrets, assertion evaluation, and utility functions.
"""

from .assertions import (
    GeodeQueryAssert,
    StdoutJsonAssert,
    TestExpectations,
    evaluate_assertions,
)
from .plaintext_scanner import PlaintextScanner, PlaintextViolation
from .runner import RunnerError, run_tests
from .spec import SecretConfig, SpecValidationError, TestCase, TestSpec, load_spec
from .utils import (
    GeodeBinaryNotFoundError,
    SecretResolutionError,
    extract_json_from_output,
    find_geode_binary,
    format_duration,
    get_free_port,
    is_valid_gql,
    resolve_secrets,
    sanitize_args,
    sanitize_filename,
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
    "GeodeBinaryNotFoundError",
    "find_geode_binary",
    "format_duration",
    "get_free_port",
    "sanitize_filename",
    "sanitize_args",
    "is_valid_gql",
    "extract_json_from_output",
    "evaluate_assertions",
    "TestExpectations",
    "GeodeQueryAssert",
    "StdoutJsonAssert",
    "PlaintextScanner",
    "PlaintextViolation",
]
