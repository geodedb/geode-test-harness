"""Unit tests for runners/shell_runner.py."""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch


# Add paths
sys.path.insert(0, str(Path(__file__).parent.parent))

from lib.utils import get_free_port
from runners.shell_runner import ShellTestRunner, run_spec


class TestShellTestRunnerInit:
    """Tests for ShellTestRunner initialization."""

    def test_default_server_address(self):
        """Default server should be 127.0.0.1:3141."""
        runner = ShellTestRunner()
        assert runner.server == "127.0.0.1:3141"

    def test_custom_server_address(self):
        """Custom server address should be used."""
        runner = ShellTestRunner(server="192.168.1.1:8443")
        assert runner.server == "192.168.1.1:8443"

    def test_auto_allocate_port(self):
        """Auto port allocation should work when enabled."""
        runner = ShellTestRunner(auto_allocate_port=True)
        assert runner._auto_allocate is True
        assert runner.server is None

    def test_auto_allocate_with_server_disables_auto(self):
        """Providing server should disable auto allocation."""
        runner = ShellTestRunner(server="127.0.0.1:9999", auto_allocate_port=True)
        # auto_allocate_port is ignored when server is provided
        assert runner.server == "127.0.0.1:9999"

    def test_default_binary_path(self):
        """Default binary path should be ./zig-out/bin/geode."""
        runner = ShellTestRunner()
        assert runner.geode_binary == "./zig-out/bin/geode"

    def test_custom_binary_path(self):
        """Custom binary path should be used."""
        runner = ShellTestRunner(geode_binary="/custom/path/geode")
        assert runner.geode_binary == "/custom/path/geode"

    def test_creates_temp_data_dir(self):
        """Temp data directory should be created when not provided."""
        runner = ShellTestRunner()
        assert runner.data_dir is not None
        assert "geode_shell_test_" in runner.data_dir

    def test_custom_data_dir(self):
        """Custom data directory should be used."""
        runner = ShellTestRunner(data_dir="/custom/data")
        assert runner.data_dir == "/custom/data"

    def test_verbose_default_false(self):
        """Verbose should be False by default."""
        runner = ShellTestRunner()
        assert runner.verbose is False

    def test_verbose_can_be_enabled(self):
        """Verbose can be enabled."""
        runner = ShellTestRunner(verbose=True)
        assert runner.verbose is True

    def test_shell_process_initially_none(self):
        """Shell process should be None initially."""
        runner = ShellTestRunner()
        assert runner.shell_process is None

    def test_server_manager_initially_none(self):
        """Server manager should be None initially."""
        runner = ShellTestRunner()
        assert runner.server_manager is None


class TestShellTestRunnerLog:
    """Tests for ShellTestRunner.log method."""

    def test_log_when_verbose(self, capsys):
        """Log should output when verbose is True."""
        runner = ShellTestRunner(verbose=True)
        runner.log("Test message")
        captured = capsys.readouterr()
        assert "Test message" in captured.err

    def test_no_log_when_not_verbose(self, capsys):
        """Log should not output when verbose is False."""
        runner = ShellTestRunner(verbose=False)
        runner.log("Test message")
        captured = capsys.readouterr()
        assert captured.err == ""


class TestShellTestRunnerStripAnsi:
    """Tests for ShellTestRunner.strip_ansi method."""

    def test_strips_color_codes(self):
        """ANSI color codes should be stripped."""
        runner = ShellTestRunner()
        text = "\x1b[31mRed text\x1b[0m"
        result = runner.strip_ansi(text)
        assert result == "Red text"

    def test_strips_cursor_codes(self):
        """ANSI cursor codes should be stripped."""
        runner = ShellTestRunner()
        text = "\x1b[2JCleared screen"
        result = runner.strip_ansi(text)
        assert result == "Cleared screen"

    def test_strips_carriage_return(self):
        """Carriage returns should be stripped."""
        runner = ShellTestRunner()
        text = "Line1\rLine2"
        result = runner.strip_ansi(text)
        assert "\r" not in result

    def test_preserves_normal_text(self):
        """Normal text should be preserved."""
        runner = ShellTestRunner()
        text = "Normal text with numbers 123"
        result = runner.strip_ansi(text)
        assert result == text


class TestShellTestRunnerServerManagement:
    """Tests for server start/stop methods."""

    def test_start_server_creates_manager(self):
        """start_server should create a ServerManager."""
        runner = ShellTestRunner(auto_allocate_port=True)

        with patch("runners.shell_runner.ServerManager") as MockManager:
            mock_instance = MagicMock()
            mock_instance.start.return_value = "127.0.0.1:5000"
            mock_instance.data_dir = "/tmp/test"
            MockManager.return_value = mock_instance

            result = runner.start_server()

            assert result is True
            assert runner.server == "127.0.0.1:5000"
            MockManager.assert_called_once()

    def test_start_server_failure(self):
        """start_server should return False on failure."""
        runner = ShellTestRunner(auto_allocate_port=True)

        with patch("runners.shell_runner.ServerManager") as MockManager:
            mock_instance = MagicMock()
            mock_instance.start.side_effect = RuntimeError("Failed to start")
            MockManager.return_value = mock_instance

            result = runner.start_server()

            assert result is False

    def test_stop_server_calls_manager_stop(self):
        """stop_server should call ServerManager.stop."""
        runner = ShellTestRunner()
        mock_manager = MagicMock()
        runner.server_manager = mock_manager

        runner.stop_server()

        mock_manager.stop.assert_called_once()
        assert runner.server_manager is None

    def test_stop_server_safe_when_none(self):
        """stop_server should be safe when no manager exists."""
        runner = ShellTestRunner()
        runner.stop_server()  # Should not raise


class TestRunSpec:
    """Tests for run_spec function."""

    def test_loads_spec_file(self, tmp_path):
        """run_spec should load the spec file."""
        spec_file = tmp_path / "test.yaml"
        spec_file.write_text("""
version: "1.0"
name: "Test Spec"
manage_server: false
tests: []
""")

        with patch("runners.shell_runner.ShellTestRunner") as MockRunner:
            mock_instance = MagicMock()
            mock_instance.start_shell.return_value = True
            MockRunner.return_value = mock_instance

            run_spec(str(spec_file))

            MockRunner.assert_called_once()

    def test_starts_server_when_manage_server_true(self, tmp_path):
        """Server should be started when manage_server=true."""
        spec_file = tmp_path / "test.yaml"
        spec_file.write_text("""
version: "1.0"
name: "Test Spec"
manage_server: true
tests: []
""")

        with patch("runners.shell_runner.ShellTestRunner") as MockRunner:
            mock_instance = MagicMock()
            mock_instance.start_server.return_value = True
            mock_instance.start_shell.return_value = True
            MockRunner.return_value = mock_instance

            run_spec(str(spec_file))

            mock_instance.start_server.assert_called_once()

    def test_auto_allocate_port_when_manage_server(self, tmp_path):
        """Port should be auto-allocated when manage_server=true and no server specified."""
        spec_file = tmp_path / "test.yaml"
        spec_file.write_text("""
version: "1.0"
name: "Test Spec"
manage_server: true
tests: []
""")

        with patch("runners.shell_runner.ShellTestRunner") as MockRunner:
            mock_instance = MagicMock()
            mock_instance.start_server.return_value = True
            mock_instance.start_shell.return_value = True
            MockRunner.return_value = mock_instance

            run_spec(str(spec_file))

            # Check that auto_allocate_port=True was passed
            call_kwargs = MockRunner.call_args[1]
            assert call_kwargs.get("auto_allocate_port") is True

    def test_returns_error_on_server_start_failure(self, tmp_path):
        """Error should be returned if server fails to start."""
        spec_file = tmp_path / "test.yaml"
        spec_file.write_text("""
version: "1.0"
name: "Test Spec"
manage_server: true
tests: []
""")

        with patch("runners.shell_runner.ShellTestRunner") as MockRunner:
            mock_instance = MagicMock()
            mock_instance.start_server.return_value = False
            mock_instance.server = "127.0.0.1:3141"
            MockRunner.return_value = mock_instance

            results = run_spec(str(spec_file))

            assert len(results) == 1
            assert results[0]["status"] == "error"
            assert "server" in results[0]["error"].lower()

    def test_returns_error_on_shell_start_failure(self, tmp_path):
        """Error should be returned if shell fails to start."""
        spec_file = tmp_path / "test.yaml"
        spec_file.write_text("""
version: "1.0"
name: "Test Spec"
manage_server: false
tests: []
""")

        with patch("runners.shell_runner.ShellTestRunner") as MockRunner:
            mock_instance = MagicMock()
            mock_instance.start_shell.return_value = False
            mock_instance.server = "127.0.0.1:3141"
            MockRunner.return_value = mock_instance

            results = run_spec(str(spec_file))

            assert len(results) == 1
            assert results[0]["status"] == "error"
            assert "shell" in results[0]["error"].lower()

    def test_runs_all_tests(self, tmp_path):
        """All tests in spec should be run."""
        spec_file = tmp_path / "test.yaml"
        spec_file.write_text("""
version: "1.0"
name: "Test Spec"
manage_server: false
tests:
  - name: "test1"
    type: shell_query
    query: "RETURN 1"
  - name: "test2"
    type: shell_query
    query: "RETURN 2"
""")

        with patch("runners.shell_runner.ShellTestRunner") as MockRunner:
            mock_instance = MagicMock()
            mock_instance.start_shell.return_value = True
            mock_instance.run_test.return_value = {
                "status": "passed",
                "test_name": "test",
            }
            MockRunner.return_value = mock_instance

            run_spec(str(spec_file))

            assert mock_instance.run_test.call_count == 2

    def test_stops_shell_and_server_after_tests(self, tmp_path):
        """Shell and server should be stopped after tests complete."""
        spec_file = tmp_path / "test.yaml"
        spec_file.write_text("""
version: "1.0"
name: "Test Spec"
manage_server: true
tests: []
""")

        with patch("runners.shell_runner.ShellTestRunner") as MockRunner:
            mock_instance = MagicMock()
            mock_instance.start_server.return_value = True
            mock_instance.start_shell.return_value = True
            MockRunner.return_value = mock_instance

            run_spec(str(spec_file))

            mock_instance.stop_shell.assert_called_once()
            mock_instance.stop_server.assert_called_once()


class TestShellTestRunnerTestExecution:
    """Tests for test execution methods."""

    def test_run_test_unknown_type(self):
        """Unknown test type should return error."""
        runner = ShellTestRunner()

        result = runner.run_test({"name": "test", "type": "unknown_type"})

        assert result["status"] == "error"
        assert "unknown" in result["error"].lower()

    def test_run_query_test_no_query(self):
        """Query test without query should return error."""
        from runners.shell_test_methods import run_query_test

        runner = ShellTestRunner()

        result = run_query_test(runner, {"name": "test"})

        assert result["status"] == "error"
        assert "query" in result["error"].lower()

    def test_run_source_test_no_content(self):
        """Source test without content should return error."""
        from runners.shell_test_methods import run_source_test

        runner = ShellTestRunner()

        result = run_source_test(runner, {"name": "test"})

        assert result["status"] == "error"


class TestGetFreePort:
    """Tests for get_free_port in shell_runner module."""

    def test_imported_correctly(self):
        """get_free_port should be importable from lib.utils."""

        port = get_free_port()
        assert isinstance(port, int)
        assert 1024 <= port <= 65535
