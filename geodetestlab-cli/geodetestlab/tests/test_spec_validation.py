"""Tests for specification validation and parsing."""

import tempfile
from pathlib import Path

import pytest
import yaml

from geodetestlab.lib.spec import SpecValidationError, load_spec


def test_valid_basic_spec():
    """Test loading a valid basic specification."""
    spec_data = {
        "name": "basic-test",
        "tests": [{"name": "test1", "args": ["--help"], "expect": {"exit_code": 0}}],
    }

    with tempfile.NamedTemporaryFile(mode="w", suffix=".yml", delete=False) as f:
        yaml.dump(spec_data, f)
        temp_path = Path(f.name)

    try:
        spec = load_spec(temp_path)
        assert spec.name == "basic-test"
        assert len(spec.tests) == 1
        assert spec.tests[0].name == "test1"
    finally:
        temp_path.unlink()


def test_missing_required_fields():
    """Test that missing required fields raise errors."""
    # Missing 'name' field
    spec_data = {
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


def test_missing_tests_field():
    """Test that missing tests field raises error."""
    spec_data = {
        "name": "no-tests",
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
        "tests": [
            {
                "name": "geode_query_test",
                "description": "Test a GQL query",
                "args": ["query", "RETURN 1"],
                "expect": {"exit_code": 0},
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

        # Test secrets
        assert "test_secret" in spec.secrets
        assert spec.secrets["test_secret"].source == "env"
        assert spec.secrets["test_secret"].key == "TEST_SECRET"
        assert spec.secrets["test_secret"].required is False

        # Test test case
        test_case = spec.tests[0]
        assert test_case.name == "geode_query_test"
        assert test_case.description == "Test a GQL query"
        assert test_case.args == ["query", "RETURN 1"]

    finally:
        temp_path.unlink()


def test_json_assert_validation():
    """Test loading specs with stdout_json_assert expectations."""
    spec_data = {
        "name": "json-assert-test",
        "tests": [
            {
                "name": "test",
                "args": ["query", "RETURN 1"],
                "expect": {"exit_code": 0},
            }
        ],
    }

    with tempfile.NamedTemporaryFile(mode="w", suffix=".yml", delete=False) as f:
        yaml.dump(spec_data, f)
        temp_path = Path(f.name)

    try:
        spec = load_spec(temp_path)
        assert len(spec.tests) == 1
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
    with pytest.raises(FileNotFoundError):
        load_spec(Path("/nonexistent/file.yml"))


def test_http_test_spec():
    """Test loading a spec with HTTP test cases."""
    spec_data = {
        "name": "http-test",
        "tests": [
            {
                "name": "http-get",
                "type": "http",
                "requests": [
                    {"method": "GET", "url": "http://localhost:8080/health", "expect": {"status_code": 200}}
                ],
            }
        ],
    }

    with tempfile.NamedTemporaryFile(mode="w", suffix=".yml", delete=False) as f:
        yaml.dump(spec_data, f)
        temp_path = Path(f.name)

    try:
        spec = load_spec(temp_path)
        assert spec.tests[0].test_type == "http"
        assert len(spec.tests[0].http_requests) == 1
    finally:
        temp_path.unlink()


def test_sequential_test_spec():
    """Test loading a spec with sequential test cases."""
    spec_data = {
        "name": "sequential-test",
        "tests": [
            {
                "name": "multi-step",
                "type": "sequential",
                "steps": [
                    {"type": "gql", "query": "CREATE (n:Test {id: 1})"},
                    {"type": "wait", "wait_ms": 100},
                    {"type": "gql", "query": "MATCH (n:Test) RETURN n"},
                ],
            }
        ],
    }

    with tempfile.NamedTemporaryFile(mode="w", suffix=".yml", delete=False) as f:
        yaml.dump(spec_data, f)
        temp_path = Path(f.name)

    try:
        spec = load_spec(temp_path)
        assert spec.tests[0].test_type == "sequential"
        assert len(spec.tests[0].steps) == 3
    finally:
        temp_path.unlink()
