"""Unit tests for lib/server_manager.py."""

import os
import signal
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Add lib to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from lib.server_manager import ServerManager


class TestServerManagerInit:
    """Tests for ServerManager initialization."""

    def test_auto_allocates_port_when_none(self):
        """Port should be auto-allocated when not provided."""
        manager = ServerManager(binary_path="/fake/geode")
        assert manager.port is not None
        assert isinstance(manager.port, int)
        assert 1024 <= manager.port <= 65535

    def test_uses_provided_port(self):
        """Provided port should be used."""
        manager = ServerManager(binary_path="/fake/geode", port=9999)
        assert manager.port == 9999

    def test_default_values(self):
        """Default values should be set correctly."""
        manager = ServerManager(binary_path="/path/to/geode")
        assert manager.binary_path == "/path/to/geode"
        assert manager.startup_timeout_ms == 60000
        assert manager.cleanup is True
        assert manager.args == []
        assert manager.env == {}
        assert manager.verbose is False
        assert manager.disable_auth is True
        assert manager.process is None

    def test_custom_values(self):
        """Custom values should be accepted."""
        manager = ServerManager(
            binary_path="/path/to/geode",
            port=8443,
            data_dir="/custom/data",
            startup_timeout_ms=30000,
            cleanup=False,
            args=["--flag"],
            env={"KEY": "VALUE"},
            verbose=True,
            disable_auth=False,
        )
        assert manager.port == 8443
        assert manager.data_dir == "/custom/data"
        assert manager.startup_timeout_ms == 30000
        assert manager.cleanup is False
        assert manager.args == ["--flag"]
        assert manager.env == {"KEY": "VALUE"}
        assert manager.verbose is True
        assert manager.disable_auth is False


class TestServerManagerAddress:
    """Tests for ServerManager.address property."""

    def test_address_format(self):
        """Address should be in host:port format."""
        manager = ServerManager(binary_path="/fake/geode", port=3141)
        assert manager.address == "127.0.0.1:3141"

    def test_address_uses_allocated_port(self):
        """Address should use the allocated port."""
        manager = ServerManager(binary_path="/fake/geode")
        assert f":{manager.port}" in manager.address


class TestServerManagerStart:
    """Tests for ServerManager.start method."""

    def test_creates_temp_dir_when_none(self):
        """Temp data directory should be created when not provided."""
        manager = ServerManager(binary_path="/fake/geode")
        assert manager.data_dir is None

        with patch("subprocess.Popen") as mock_popen:
            mock_process = MagicMock()
            mock_process.poll.return_value = None
            mock_popen.return_value = mock_process

            with patch("socket.socket"):
                try:
                    # Will timeout but data_dir should be set
                    manager.startup_timeout_ms = 100
                    manager.start()
                except RuntimeError:
                    pass

        # data_dir should now be set to a temp directory
        assert manager.data_dir is not None

    def test_raises_on_binary_not_found(self):
        """FileNotFoundError from Popen should become RuntimeError."""
        manager = ServerManager(binary_path="/nonexistent/geode")

        with patch("subprocess.Popen") as mock_popen:
            mock_popen.side_effect = FileNotFoundError("not found")

            with pytest.raises(RuntimeError) as exc_info:
                manager.start()
            assert "not found" in str(exc_info.value).lower()

    def test_raises_on_process_exit(self):
        """RuntimeError should be raised if process exits during startup."""
        manager = ServerManager(binary_path="/fake/geode")
        manager.startup_timeout_ms = 500

        with patch("subprocess.Popen") as mock_popen:
            mock_process = MagicMock()
            mock_process.poll.return_value = 1  # Process exited with code 1
            mock_process.returncode = 1
            mock_popen.return_value = mock_process

            with pytest.raises(RuntimeError) as exc_info:
                manager.start()
            assert "exited" in str(exc_info.value).lower()


class TestServerManagerStop:
    """Tests for ServerManager.stop method."""

    def test_stop_when_not_running(self):
        """Stop should be safe to call when no process is running."""
        manager = ServerManager(binary_path="/fake/geode")
        manager.stop()  # Should not raise

    def test_stop_terminates_process(self):
        """Stop should terminate the server process."""
        manager = ServerManager(binary_path="/fake/geode")
        mock_process = MagicMock()
        mock_process.wait.return_value = None
        manager.process = mock_process

        with patch("os.killpg"):
            manager.stop()

        assert manager.process is None

    def test_stop_cleans_up_temp_dir(self):
        """Stop should clean up temp directory when cleanup=True."""
        manager = ServerManager(binary_path="/fake/geode", cleanup=True)

        # Create a mock temp directory
        mock_temp_dir = MagicMock()
        manager._temp_dir = mock_temp_dir

        manager.stop()

        mock_temp_dir.cleanup.assert_called_once()
        assert manager._temp_dir is None

    def test_stop_preserves_dir_when_no_cleanup(self):
        """Stop should not clean up when cleanup=False."""
        manager = ServerManager(binary_path="/fake/geode", cleanup=False)

        mock_temp_dir = MagicMock()
        manager._temp_dir = mock_temp_dir

        manager.stop()

        mock_temp_dir.cleanup.assert_not_called()


class TestServerManagerIsRunning:
    """Tests for ServerManager.is_running method."""

    def test_false_when_no_process(self):
        """is_running should be False when no process exists."""
        manager = ServerManager(binary_path="/fake/geode")
        assert manager.is_running() is False

    def test_false_when_process_exited(self):
        """is_running should be False when process has exited."""
        manager = ServerManager(binary_path="/fake/geode")
        mock_process = MagicMock()
        mock_process.poll.return_value = 0  # Exited
        manager.process = mock_process
        assert manager.is_running() is False

    def test_true_when_process_running(self):
        """is_running should be True when process is running."""
        manager = ServerManager(binary_path="/fake/geode")
        mock_process = MagicMock()
        mock_process.poll.return_value = None  # Still running
        manager.process = mock_process
        assert manager.is_running() is True


class TestServerManagerContextManager:
    """Tests for ServerManager context manager protocol."""

    def test_enter_calls_start(self):
        """__enter__ should call start()."""
        manager = ServerManager(binary_path="/fake/geode")

        with patch.object(manager, "start") as mock_start:
            mock_start.return_value = "127.0.0.1:3141"
            result = manager.__enter__()

        mock_start.assert_called_once()
        assert result is manager

    def test_exit_calls_stop(self):
        """__exit__ should call stop()."""
        manager = ServerManager(binary_path="/fake/geode")

        with patch.object(manager, "stop") as mock_stop:
            manager.__exit__(None, None, None)

        mock_stop.assert_called_once()

    def test_exit_calls_stop_on_exception(self):
        """__exit__ should call stop() even on exception."""
        manager = ServerManager(binary_path="/fake/geode")

        with patch.object(manager, "stop") as mock_stop:
            manager.__exit__(ValueError, ValueError("test"), None)

        mock_stop.assert_called_once()


@pytest.mark.integration
class TestServerManagerIntegration:
    """Integration tests that require the actual geode binary."""

    @pytest.fixture
    def geode_binary(self):
        """Find the geode binary or skip."""
        from lib.utils import find_geode_binary

        try:
            return find_geode_binary()
        except FileNotFoundError:
            pytest.skip("Geode binary not found")

    def test_start_and_stop_real_server(self, geode_binary):
        """Test starting and stopping a real server instance."""
        manager = ServerManager(
            binary_path=geode_binary,
            startup_timeout_ms=30000,
        )

        try:
            address = manager.start()
            assert address is not None
            assert ":" in address
            assert manager.is_running()

            # Verify port is in use
            port = int(address.split(":")[1])
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.settimeout(1)
                # UDP send should succeed (QUIC server)
                s.sendto(b"test", ("127.0.0.1", port))

        finally:
            manager.stop()

        assert not manager.is_running()

    def test_context_manager_real_server(self, geode_binary):
        """Test using context manager with real server."""
        with ServerManager(
            binary_path=geode_binary,
            startup_timeout_ms=30000,
        ) as manager:
            assert manager.is_running()
            assert manager.address is not None

        assert not manager.is_running()

    def test_multiple_servers_different_ports(self, geode_binary):
        """Test running multiple servers on different ports."""
        manager1 = ServerManager(binary_path=geode_binary, startup_timeout_ms=30000)
        manager2 = ServerManager(binary_path=geode_binary, startup_timeout_ms=30000)

        try:
            addr1 = manager1.start()
            addr2 = manager2.start()

            # Should be on different ports
            port1 = int(addr1.split(":")[1])
            port2 = int(addr2.split(":")[1])
            assert port1 != port2

            assert manager1.is_running()
            assert manager2.is_running()

        finally:
            manager1.stop()
            manager2.stop()
