"""Unit tests for lib/utils.py."""

import os
import socket
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Add lib to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from lib.utils import (
    find_geode_binary,
    format_duration,
    get_free_port,
    sanitize_filename,
)


class TestGetFreePort:
    """Tests for get_free_port function."""

    def test_returns_integer(self):
        """get_free_port should return an integer."""
        port = get_free_port()
        assert isinstance(port, int)

    def test_returns_valid_port_range(self):
        """Port should be in valid range (1024-65535 for unprivileged)."""
        port = get_free_port()
        assert 1024 <= port <= 65535

    def test_port_is_available(self):
        """The returned port should be immediately bindable."""
        port = get_free_port()
        # Try to bind to the port
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            # This should succeed if the port is truly free
            s.bind(("127.0.0.1", port))
            s.listen(1)

    def test_returns_different_ports(self):
        """Multiple calls should return different ports."""
        ports = [get_free_port() for _ in range(10)]
        # All ports should be unique
        assert len(set(ports)) == len(ports)


class TestFormatDuration:
    """Tests for format_duration function."""

    def test_microseconds(self):
        """Duration < 1ms should be formatted as microseconds."""
        result = format_duration(0.5)
        assert "us" in result
        assert "500" in result

    def test_milliseconds(self):
        """Duration 1-999ms should be formatted as milliseconds."""
        result = format_duration(123.4)
        assert "ms" in result
        assert "123.4" in result

    def test_seconds(self):
        """Duration 1-59s should be formatted as seconds."""
        result = format_duration(1234)
        assert "s" in result
        assert "1.23" in result

    def test_minutes(self):
        """Duration >= 60s should be formatted as minutes."""
        result = format_duration(90000)  # 1.5 minutes
        assert "m" in result
        assert "1" in result

    def test_zero(self):
        """Zero duration should work."""
        result = format_duration(0)
        assert "us" in result


class TestSanitizeFilename:
    """Tests for sanitize_filename function."""

    def test_basic_string(self):
        """Basic string without special chars should be unchanged."""
        result = sanitize_filename("hello_world")
        assert result == "hello_world"

    def test_spaces(self):
        """Spaces should be replaced with underscores."""
        result = sanitize_filename("hello world")
        assert result == "hello_world"

    def test_slashes(self):
        """Slashes should be replaced with underscores."""
        result = sanitize_filename("path/to/file")
        assert result == "path_to_file"

    def test_backslashes(self):
        """Backslashes should be replaced with underscores."""
        result = sanitize_filename("path\\to\\file")
        assert result == "path_to_file"

    def test_special_chars(self):
        """Special characters should be replaced."""
        result = sanitize_filename('file:name*with?bad"chars<>|')
        assert ":" not in result
        assert "*" not in result
        assert "?" not in result
        assert '"' not in result
        assert "<" not in result
        assert ">" not in result
        assert "|" not in result

    def test_empty_string(self):
        """Empty string should return empty string."""
        result = sanitize_filename("")
        assert result == ""


class TestFindGeodeBinary:
    """Tests for find_geode_binary function."""

    def test_custom_path_exists(self):
        """Custom path that exists should be returned."""
        # Create a temporary file to use as a "binary"
        with tempfile.NamedTemporaryFile(delete=False, suffix="_geode") as f:
            temp_path = f.name

        try:
            # Mock subprocess to simulate a valid binary
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=0, stdout=b"geode")
                result = find_geode_binary(temp_path)
                assert Path(result).resolve() == Path(temp_path).resolve()
        finally:
            os.unlink(temp_path)

    def test_custom_path_not_exists(self):
        """Custom path that doesn't exist should raise FileNotFoundError."""
        with pytest.raises(FileNotFoundError) as exc_info:
            find_geode_binary("/nonexistent/path/to/geode")
        assert "not found" in str(exc_info.value).lower()

    def test_search_paths_checked(self):
        """When no custom path, search paths should be checked."""
        # This test verifies the function doesn't crash when searching
        # The actual result depends on whether geode is installed
        try:
            result = find_geode_binary()
            assert Path(result).exists()
        except FileNotFoundError:
            # Expected if geode is not installed
            pass

    def test_returns_absolute_path(self):
        """Result should be an absolute path."""
        with tempfile.NamedTemporaryFile(delete=False, suffix="_geode") as f:
            temp_path = f.name

        try:
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=0, stdout=b"geode")
                result = find_geode_binary(temp_path)
                assert Path(result).is_absolute()
        finally:
            os.unlink(temp_path)
