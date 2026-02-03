"""Tests for utility functions."""

import os
import tempfile

import pytest

from geodetestlab.core.spec import CliSpec, SecretConfig, Spec
from geodetestlab.core.utils import (
    GeodeBinaryNotFoundError,
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

    with pytest.raises(ValueError, match="Invalid character"):
        sanitize_args(["arg with\ttab"])


def test_sanitize_args_nonprintable():
    """Test argument sanitization with non-printable characters."""
    with pytest.raises(ValueError, match="Non‑printable character"):
        sanitize_args(["arg\x00null"])

    with pytest.raises(ValueError, match="Non‑printable character"):
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
    # Create a minimal spec
    spec = Spec(
        version="1.0",
        cli=CliSpec(binary="geode", env={"AUTH_TOKEN": "${secret:token}"}),
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
        assert secrets["optional"] == ""  # Missing but not required
        assert env_vars["AUTH_TOKEN"] == "test_value"
    finally:
        del os.environ["TEST_TOKEN"]


def test_resolve_secrets_missing_required():
    """Test error when required secret is missing."""
    spec = Spec(
        version="1.0",
        cli=CliSpec(binary="geode"),
        secrets={"required": SecretConfig(source="env", key="MISSING_TOKEN", required=True)},
        tests=[],
    )

    with pytest.raises(SecretResolutionError, match="Missing required secret"):
        resolve_secrets(spec)


def test_get_free_port():
    """Test free port allocation."""
    port = get_free_port()
    assert 1024 <= port <= 65535

    # Test with specific start port
    port = get_free_port(start_port=9000)
    assert port >= 9000


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
    # Clear environment variable if set
    old_env = os.environ.get("GEODE_BINARY")
    if old_env:
        del os.environ["GEODE_BINARY"]

    # Mock shutil.which to return None (no geode in PATH)
    from unittest.mock import MagicMock, patch

    # Mock Path.is_file to return False for all paths
    mock_path = MagicMock()
    mock_path.is_file.return_value = False
    mock_path.exists.return_value = False

    try:
        with (
            patch("shutil.which", return_value=None),
            patch("pathlib.Path", return_value=mock_path),
            patch("os.access", return_value=False),
            pytest.raises(GeodeBinaryNotFoundError),
        ):
            find_geode_binary("/nonexistent/path/to/geode")
    finally:
        if old_env:
            os.environ["GEODE_BINARY"] = old_env


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

        # Test environment variable lookup
        result = find_geode_binary()
        assert result == temp_path
    finally:
        if "GEODE_BINARY" in os.environ:
            del os.environ["GEODE_BINARY"]
        os.unlink(temp_path)
