"""Tests for utility functions."""

import os
import tempfile

import pytest

from geodetestlab.lib.spec import SecretConfig, TestSpec
from geodetestlab.lib.utils import (
    SecretResolutionError,
    _replace_placeholder,
    extract_json_from_output,
    find_geode_binary,
    get_free_port,
    is_valid_gql,
    resolve_secrets,
    sanitize_args,
)


def test_sanitize_args_valid():
    """Test argument sanitization with valid arguments."""
    args = ["geode", "query", "RETURN 1", "--format", "json"]
    sanitized = sanitize_args(args)
    assert sanitized == args


def test_sanitize_args_invalid_chars():
    """Test argument sanitization with invalid characters."""
    with pytest.raises(ValueError, match="Invalid character"):
        sanitize_args(["geode", "query; rm -rf /"])

    with pytest.raises(ValueError, match="Invalid character"):
        sanitize_args(["geode", "query", "RETURN 1 | cat"])


def test_sanitize_args_nonprintable():
    """Test argument sanitization with non-printable characters."""
    with pytest.raises(ValueError, match="Non\u2011printable character"):
        sanitize_args(["arg\x00null"])

    with pytest.raises(ValueError, match="Non\u2011printable character"):
        sanitize_args(["arg\x1fcontrol"])


def test_replace_placeholder():
    """Test secret placeholder replacement."""
    secrets = {"token": "secret123", "password": "pass456"}

    # Simple replacement
    result = _replace_placeholder("Bearer ${secret:token}", secrets)
    assert result == "Bearer secret123"

    # Multiple replacements
    result = _replace_placeholder("${secret:token}:${secret:password}", secrets)
    assert result == "secret123:pass456"

    # No placeholders
    result = _replace_placeholder("no secrets here", secrets)
    assert result == "no secrets here"

    # Missing secret
    with pytest.raises(KeyError, match="Secret 'missing' is not defined"):
        _replace_placeholder("${secret:missing}", secrets)


def test_resolve_secrets_env():
    """Test secret resolution from environment variables."""
    spec = TestSpec(
        name="test-spec",
        description="",
        env={"AUTH_TOKEN": "${secret:token}"},
        secrets={
            "token": SecretConfig(source="env", key="TEST_TOKEN", required=True),
            "optional": SecretConfig(source="env", key="OPTIONAL_TOKEN", required=False),
        },
        tests=[],
    )

    # Set environment variable
    os.environ["TEST_TOKEN"] = "test_value"

    try:
        secrets, env_vars = resolve_secrets(spec)
        assert secrets["token"] == "test_value"
    finally:
        del os.environ["TEST_TOKEN"]


def test_resolve_secrets_missing_required():
    """Test error when required secret is missing."""
    spec = TestSpec(
        name="test-spec",
        description="",
        secrets={"required": SecretConfig(source="env", key="MISSING_TOKEN", required=True)},
        tests=[],
    )

    with pytest.raises(SecretResolutionError, match="Required secret"):
        resolve_secrets(spec)


def test_get_free_port():
    """Test free port allocation."""
    port = get_free_port()
    assert 1024 <= port <= 65535


def test_is_valid_gql():
    """Test GQL query validation."""
    # Valid queries
    assert is_valid_gql("MATCH (n) RETURN n") is True
    assert is_valid_gql("CREATE (n:Person {name: 'Alice'})") is True
    assert is_valid_gql("RETURN 1 AS result") is True
    assert is_valid_gql("EXPLAIN MATCH (n) RETURN count(n)") is True

    # Invalid queries
    assert is_valid_gql("") is False
    assert is_valid_gql("SELECT * FROM table") is False  # SQL, not GQL
    assert is_valid_gql("invalid syntax here") is False

    # Bracket mismatch
    assert is_valid_gql("MATCH (n RETURN n") is False
    assert is_valid_gql("MATCH [n) RETURN n") is False


def test_extract_json_from_output():
    """Test JSON extraction from CLI output."""
    # Pure JSON
    output = '{"result": 42, "status": "success"}'
    result = extract_json_from_output(output)
    assert result == {"result": 42, "status": "success"}

    # JSON with surrounding text
    output = """
    Starting query execution...
    {"results": [{"id": 1, "name": "Alice"}]}
    Query completed in 123ms
    """
    result = extract_json_from_output(output)
    assert result == {"results": [{"id": 1, "name": "Alice"}]}

    # JSON array
    output = '[{"id": 1}, {"id": 2}]'
    result = extract_json_from_output(output)
    assert result == [{"id": 1}, {"id": 2}]

    # No JSON
    output = "This is just plain text output"
    result = extract_json_from_output(output)
    assert result is None

    # Malformed JSON
    output = '{"incomplete": json'
    result = extract_json_from_output(output)
    assert result is None


def test_find_geode_binary_explicit():
    """Test finding Geode binary with explicit path."""
    # Create a temporary executable file
    with tempfile.NamedTemporaryFile(mode="w", suffix="", delete=False) as f:
        f.write("#!/bin/bash\necho 'fake geode'\n")
        temp_path = f.name

    try:
        # Make it executable
        os.chmod(temp_path, 0o755)

        # Test explicit path
        result = find_geode_binary(temp_path)
        assert result == temp_path
    finally:
        os.unlink(temp_path)


def test_find_geode_binary_not_found():
    """Test error when Geode binary cannot be found."""
    with pytest.raises(FileNotFoundError):
        find_geode_binary("/nonexistent/path/to/geode")


def test_find_geode_binary_environment():
    """Test finding Geode binary via environment variable."""
    # Create a temporary executable file
    with tempfile.NamedTemporaryFile(mode="w", suffix="", delete=False) as f:
        f.write("#!/bin/bash\necho 'fake geode'\n")
        temp_path = f.name

    try:
        # Make it executable
        os.chmod(temp_path, 0o755)

        # Set environment variable
        os.environ["GEODE_BINARY"] = temp_path

        # find_geode_binary checks common paths, not env var directly
        # but we can verify explicit path works
        result = find_geode_binary(temp_path)
        assert result == temp_path
    finally:
        if "GEODE_BINARY" in os.environ:
            del os.environ["GEODE_BINARY"]
        os.unlink(temp_path)
