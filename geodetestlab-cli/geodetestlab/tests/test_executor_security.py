"""Tests for executor.py security guards.

Covers:
- GAP-0265: Shell metacharacter routing (#48)
- GAP-0265: setup_files path traversal sandbox (#49)
- SEC-017: Path.is_relative_to() sandbox check
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import patch

from geodetestlab.lib.executor import run_cli_test
from geodetestlab.lib.spec import TestCase


def _make_case(**overrides: object) -> TestCase:
    """Helper to build a minimal TestCase with overrides."""
    defaults: dict[str, object] = {
        "name": "security-test",
        "description": "test",
        "test_type": "cli",
    }
    defaults.update(overrides)
    return TestCase.from_dict(defaults)


class TestShellMetacharacterRouting:
    """Verify that shell metacharacters are NOT routed through bash
    unless test_type is explicitly 'shell'."""

    def test_metachar_in_cli_test_uses_shlex(self) -> None:
        """CLI test with metacharacters should use shlex, not bash -c."""
        tc = _make_case(
            command="echo hello | cat",
            test_type="cli",
            expected={"exit_code": 0},
        )
        with patch("geodetestlab.lib.executor.subprocess.run") as mock_run:
            mock_run.return_value = type("R", (), {"stdout": "", "stderr": "", "returncode": 0})()
            run_cli_test(
                test_case=tc,
                binary="/usr/bin/geode",
                env={"GEODE_SERVER_ADDRESS": "127.0.0.1:3141"},
                secrets={},
                timeout_ms=5000,
                data_dir=None,
                verbose=False,
            )
            # Should NOT be ["bash", "-c", ...]
            cmd = mock_run.call_args[0][0]
            assert cmd[0] != "bash", f"CLI test should not use bash: {cmd}"

    def test_shell_test_type_uses_bash(self) -> None:
        """Shell test type should explicitly use bash -c."""
        tc = _make_case(
            command="echo hello",
            test_type="shell",
            expected={"exit_code": 0},
        )
        with patch("geodetestlab.lib.executor.subprocess.run") as mock_run:
            mock_run.return_value = type("R", (), {"stdout": "", "stderr": "", "returncode": 0})()
            # Need a valid geode source dir
            with patch("geodetestlab.lib.executor.Path.exists", return_value=True):
                from geodetestlab.lib.executor import _run_shell_test

                _run_shell_test(
                    test_case=tc,
                    env={},
                    verbose=False,
                )
                cmd = mock_run.call_args[0][0]
                assert cmd[0] == "bash", f"Shell test should use bash: {cmd}"
                assert cmd[1] == "-c"


class TestSetupFilesSandbox:
    """Verify that setup_files rejects paths outside the sandbox."""

    def test_rejects_path_traversal(self) -> None:
        """Paths outside /tmp should be rejected."""
        tc = _make_case(
            command="echo test",
            setup={"files": [{"path": "/etc/evil.conf", "content": "pwned"}]},
            expected={"exit_code": 0},
        )
        result = run_cli_test(
            test_case=tc,
            binary="/usr/bin/geode",
            env={"GEODE_SERVER_ADDRESS": "127.0.0.1:3141"},
            secrets={},
            timeout_ms=5000,
            data_dir=None,
            verbose=False,
        )
        assert not result.passed
        assert "setup_files path must be under" in (result.error or "")

    def test_allows_tmp_path(self) -> None:
        """Paths under /tmp should be allowed."""
        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "test.txt"
            tc = _make_case(
                command="echo test",
                setup={"files": [{"path": str(target), "content": "safe content"}]},
                expected={"exit_code": 0},
            )
            with patch("geodetestlab.lib.executor.subprocess.run") as mock_run:
                mock_run.return_value = type("R", (), {"stdout": "", "stderr": "", "returncode": 0})()
                result = run_cli_test(
                    test_case=tc,
                    binary="/usr/bin/geode",
                    env={"GEODE_SERVER_ADDRESS": "127.0.0.1:3141"},
                    secrets={},
                    timeout_ms=5000,
                    data_dir=None,
                    verbose=False,
                )
                # Should NOT fail due to sandbox check
                assert "setup_files path must be under" not in (result.error or "")
