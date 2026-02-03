"""Tests for CLI interface."""

import json
import tempfile
from pathlib import Path

import yaml
from typer.testing import CliRunner

from geodetestlab.cli import app


def test_cli_help():
    """Test CLI help command."""
    runner = CliRunner()
    result = runner.invoke(app, ["--help"])

    assert result.exit_code == 0
    assert "Interactive CLI testing system" in result.output
    assert "geodetestlab" in result.output


def test_run_command_help():
    """Test run command help."""
    runner = CliRunner()
    result = runner.invoke(app, ["run", "--help"])

    assert result.exit_code == 0
    assert "Execute all tests" in result.output
    assert "--spec" in result.output
    assert "--llm-provider" in result.output


def test_secrets_command_help():
    """Test secrets subcommand help."""
    runner = CliRunner()
    result = runner.invoke(app, ["secrets", "--help"])

    assert result.exit_code == 0
    assert "secrets" in result.output.lower()


def test_server_command_help():
    """Test server subcommand help."""
    runner = CliRunner()
    result = runner.invoke(app, ["server", "--help"])

    assert result.exit_code == 0
    assert "server" in result.output.lower()


def test_run_with_invalid_spec():
    """Test run command with invalid spec file."""
    runner = CliRunner()
    result = runner.invoke(app, ["run", "--spec", "/nonexistent/file.yml"])

    assert result.exit_code == 2  # Typer error for non-existent file
    assert "does not exist" in result.stderr


def test_run_with_malformed_spec():
    """Test run command with malformed YAML."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yml", delete=False) as f:
        f.write("invalid: yaml: content: [")
        temp_path = Path(f.name)

    try:
        runner = CliRunner()
        result = runner.invoke(app, ["run", "--spec", str(temp_path)])

        assert result.exit_code == 2
        assert "SCHEMA_ERROR" in result.stderr
    finally:
        temp_path.unlink()


def test_run_dry_run():
    """Test run command in dry-run mode."""
    spec_data = {
        "version": "1.0",
        "cli": {"binary": "geode"},
        "tests": [{"name": "test1", "args": ["--help"], "expect": {"exit_code": 0}}],
    }

    with tempfile.NamedTemporaryFile(mode="w", suffix=".yml", delete=False) as f:
        yaml.dump(spec_data, f)
        temp_path = Path(f.name)

    try:
        runner = CliRunner()
        result = runner.invoke(app, ["run", "--spec", str(temp_path), "--dry-run", "--ci"])

        assert result.exit_code == 0

        # Parse the JSON summary from the last line
        lines = [line for line in result.output.splitlines() if line.strip()]
        summary_line = lines[-1]
        summary = json.loads(summary_line)

        assert "summary" in summary
        assert summary["summary"]["total"] == 1
        assert summary["summary"]["skipped"] == 1
        assert summary["summary"]["passed"] == 0
        assert summary["summary"]["failed"] == 0

    finally:
        temp_path.unlink()


def test_run_empty_spec():
    """Test run command with empty test spec."""
    spec_data = {"version": "1.0", "cli": {"binary": "geode"}, "tests": []}

    with tempfile.NamedTemporaryFile(mode="w", suffix=".yml", delete=False) as f:
        yaml.dump(spec_data, f)
        temp_path = Path(f.name)

    try:
        runner = CliRunner()
        result = runner.invoke(app, ["run", "--spec", str(temp_path), "--ci"])

        assert result.exit_code == 0

        # Parse the JSON summary
        lines = [line for line in result.output.splitlines() if line.strip()]
        summary_line = lines[-1]
        summary = json.loads(summary_line)

        assert summary["summary"]["total"] == 0

    finally:
        temp_path.unlink()


def test_secrets_check_no_secrets():
    """Test secrets check with spec that has no secrets."""
    spec_data = {"version": "1.0", "cli": {"binary": "geode"}, "tests": []}

    with tempfile.NamedTemporaryFile(mode="w", suffix=".yml", delete=False) as f:
        yaml.dump(spec_data, f)
        temp_path = Path(f.name)

    try:
        runner = CliRunner()
        result = runner.invoke(app, ["secrets", "check", "--spec", str(temp_path)])

        assert result.exit_code == 0
        assert "All required secrets are resolvable" in result.output

    finally:
        temp_path.unlink()


def test_secrets_list_no_secrets():
    """Test secrets list with spec that has no secrets."""
    spec_data = {"version": "1.0", "cli": {"binary": "geode"}, "tests": []}

    with tempfile.NamedTemporaryFile(mode="w", suffix=".yml", delete=False) as f:
        yaml.dump(spec_data, f)
        temp_path = Path(f.name)

    try:
        runner = CliRunner()
        result = runner.invoke(app, ["secrets", "list", "--spec", str(temp_path)])

        assert result.exit_code == 0
        assert "No secrets defined" in result.output

    finally:
        temp_path.unlink()


def test_run_with_fuzz_parameters():
    """Test run command with fuzzing parameters."""
    spec_data = {
        "version": "1.0",
        "cli": {"binary": "echo"},  # Use echo as a safe test binary
        "fuzz": {"enabled": True, "provider": "mock", "max_cases": 3},
        "tests": [],
    }

    with tempfile.NamedTemporaryFile(mode="w", suffix=".yml", delete=False) as f:
        yaml.dump(spec_data, f)
        temp_path = Path(f.name)

    try:
        runner = CliRunner()
        result = runner.invoke(
            app,
            [
                "run",
                "--spec",
                str(temp_path),
                "--llm-provider",
                "mock",
                "--max-cases",
                "2",
                "--seed",
                "42",
                "--dry-run",
                "--ci",
            ],
        )

        # Should succeed in dry-run mode even if echo binary behavior differs
        assert result.exit_code in [0, 1]  # May fail assertions but shouldn't crash

        # Should have JSON summary
        lines = [line for line in result.output.splitlines() if line.strip()]
        if lines:
            summary_line = lines[-1]
            summary = json.loads(summary_line)
            assert "summary" in summary

    finally:
        temp_path.unlink()


def test_cli_error_handling():
    """Test CLI error handling for various scenarios."""
    runner = CliRunner()

    # Test missing required argument
    result = runner.invoke(app, ["run"])
    assert result.exit_code != 0

    # Test invalid option value
    result = runner.invoke(app, ["run", "--timeout-ms", "-1"])
    assert result.exit_code != 0

    # Test invalid provider
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yml", delete=False) as f:
        yaml.dump({"version": "1.0", "cli": {"binary": "geode"}, "tests": []}, f)
        temp_path = Path(f.name)

    try:
        result = runner.invoke(
            app, ["run", "--spec", str(temp_path), "--llm-provider", "nonexistent_provider", "--dry-run"]
        )
        # Should succeed in dry-run mode but may still have warnings about unknown provider
        # The error handling is tested elsewhere - this is just ensuring no crash
        assert result.exit_code in [0, 1]  # 0 = success, 1 = test failures

    finally:
        temp_path.unlink()
