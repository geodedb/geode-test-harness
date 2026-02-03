"""Tests for specification validation and parsing."""

import tempfile
from pathlib import Path

import pytest
import yaml

from geodetestlab.core.spec import SpecValidationError, load_spec


def test_valid_basic_spec():
    """Test loading a valid basic specification."""
    spec_data = {
        "version": "1.0",
        "cli": {"binary": "geode"},
        "tests": [{"name": "test1", "args": ["--help"], "expect": {"exit_code": 0}}],
    }

    with tempfile.NamedTemporaryFile(mode="w", suffix=".yml", delete=False) as f:
        yaml.dump(spec_data, f)
        temp_path = Path(f.name)

    try:
        spec = load_spec(temp_path)
        assert spec.version == "1.0"
        assert spec.cli.binary == "geode"
        assert len(spec.tests) == 1
        assert spec.tests[0].name == "test1"
    finally:
        temp_path.unlink()


def test_invalid_version():
    """Test that invalid version raises error."""
    spec_data = {
        "version": "2.0",  # Invalid version
        "cli": {"binary": "geode"},
        "tests": [],
    }

    with tempfile.NamedTemporaryFile(mode="w", suffix=".yml", delete=False) as f:
        yaml.dump(spec_data, f)
        temp_path = Path(f.name)

    try:
        with pytest.raises(SpecValidationError):
            load_spec(temp_path)
    finally:
        temp_path.unlink()


def test_missing_required_fields():
    """Test that missing required fields raise errors."""
    spec_data = {
        "version": "1.0",
        # Missing 'cli' field
        "tests": [],
    }

    with tempfile.NamedTemporaryFile(mode="w", suffix=".yml", delete=False) as f:
        yaml.dump(spec_data, f)
        temp_path = Path(f.name)

    try:
        with pytest.raises(SpecValidationError):
            load_spec(temp_path)
    finally:
        temp_path.unlink()


def test_geode_specific_fields():
    """Test Geode-specific specification fields."""
    spec_data = {
        "version": "1.0",
        "name": "Test Suite",
        "description": "A test suite for Geode",
        "cli": {
            "binary": "geode",
            "server": {
                "enabled": True,
                "port": 8443,
                "data_dir": "/tmp/test",
                "startup_timeout_ms": 60000,
                "cleanup": True,
                "args": ["--log-level", "debug"],
                "env": {"TEST_VAR": "value"},
            },
            "client": {"server_address": "127.0.0.1:8443", "timeout_ms": 30000, "tls_verify": False, "format": "json"},
        },
        "secrets": {"test_secret": {"source": "env", "key": "TEST_SECRET", "required": False}},
        "fuzz": {
            "enabled": True,
            "provider": "geode-ai",
            "max_cases": 10,
            "seed": 42,
            "geode_specific": True,
            "include_gql": True,
            "include_auth": True,
        },
        "tests": [
            {
                "name": "geode_query_test",
                "description": "Test a GQL query",
                "args": ["query", "RETURN 1"],
                "expect": {"exit_code": 0, "geode_query": {"row_count": 1, "columns": ["1"]}},
                "tags": ["query", "basic"],
                "timeout_ms": 5000,
            }
        ],
        "tags": ["geode", "integration"],
    }

    with tempfile.NamedTemporaryFile(mode="w", suffix=".yml", delete=False) as f:
        yaml.dump(spec_data, f)
        temp_path = Path(f.name)

    try:
        spec = load_spec(temp_path)

        # Test basic fields
        assert spec.name == "Test Suite"
        assert spec.description == "A test suite for Geode"
        assert spec.tags == ["geode", "integration"]

        # Test server config
        assert spec.cli.server is not None
        assert spec.cli.server.enabled is True
        assert spec.cli.server.port == 8443
        assert spec.cli.server.data_dir == "/tmp/test"
        assert spec.cli.server.startup_timeout_ms == 60000
        assert spec.cli.server.cleanup is True
        assert spec.cli.server.args == ["--log-level", "debug"]
        assert spec.cli.server.env == {"TEST_VAR": "value"}

        # Test client config
        assert spec.cli.client.server_address == "127.0.0.1:8443"
        assert spec.cli.client.timeout_ms == 30000
        assert spec.cli.client.tls_verify is False
        assert spec.cli.client.format == "json"

        # Test secrets
        assert "test_secret" in spec.secrets
        assert spec.secrets["test_secret"].source == "env"
        assert spec.secrets["test_secret"].key == "TEST_SECRET"
        assert spec.secrets["test_secret"].required is False

        # Test fuzz config
        assert spec.fuzz is not None
        assert spec.fuzz.enabled is True
        assert spec.fuzz.provider == "geode-ai"
        assert spec.fuzz.max_cases == 10
        assert spec.fuzz.seed == 42
        assert spec.fuzz.geode_specific is True
        assert spec.fuzz.include_gql is True
        assert spec.fuzz.include_auth is True

        # Test test case
        test_case = spec.tests[0]
        assert test_case.name == "geode_query_test"
        assert test_case.description == "Test a GQL query"
        assert test_case.args == ["query", "RETURN 1"]
        assert test_case.tags == ["query", "basic"]
        assert test_case.timeout_ms == 5000

        # Test Geode-specific expectations
        assert test_case.expect.geode_query is not None
        assert test_case.expect.geode_query.row_count == 1
        assert test_case.expect.geode_query.columns == ["1"]

    finally:
        temp_path.unlink()


def test_json_assert_validation():
    """Test JSON assertion validation."""
    # Valid with equals
    spec_data = {
        "version": "1.0",
        "cli": {"binary": "geode"},
        "tests": [
            {
                "name": "test",
                "args": ["query", "RETURN 1"],
                "expect": {"stdout_json_assert": [{"expression": "result", "equals": 1}]},
            }
        ],
    }

    with tempfile.NamedTemporaryFile(mode="w", suffix=".yml", delete=False) as f:
        yaml.dump(spec_data, f)
        temp_path = Path(f.name)

    try:
        spec = load_spec(temp_path)
        assert len(spec.tests[0].expect.stdout_json_assert) == 1
    finally:
        temp_path.unlink()

    # Invalid - no assertion type specified
    spec_data["tests"][0]["expect"]["stdout_json_assert"][0] = {
        "expression": "result"
        # Missing equals, not_equals, or matches_regex
    }

    with tempfile.NamedTemporaryFile(mode="w", suffix=".yml", delete=False) as f:
        yaml.dump(spec_data, f)
        temp_path = Path(f.name)

    try:
        with pytest.raises(SpecValidationError):
            load_spec(temp_path)
    finally:
        temp_path.unlink()


def test_malformed_yaml():
    """Test handling of malformed YAML."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yml", delete=False) as f:
        f.write("invalid: yaml: content: [unclosed")
        temp_path = Path(f.name)

    try:
        with pytest.raises(SpecValidationError):
            load_spec(temp_path)
    finally:
        temp_path.unlink()


def test_nonexistent_file():
    """Test handling of non-existent file."""
    with pytest.raises(SpecValidationError):
        load_spec(Path("/nonexistent/file.yml"))
