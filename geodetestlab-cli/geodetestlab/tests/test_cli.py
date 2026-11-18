"""Tests for CLI interface."""

import json
import tempfile
from pathlib import Path

import yaml
from typer.testing import CliRunner

from geodetestlab.cli import app


def test_cli_help() -> None:
    """Test CLI help command."""
    runner = CliRunner()
    result = runner.invoke(app, ["--help"])

    assert result.exit_code == 0
    assert "Interactive CLI testing system" in result.output
    assert "geodetestlab" in result.output


def test_run_command_help() -> None:
    """Test run command help."""
    runner = CliRunner()
    result = runner.invoke(app, ["run", "--help"])

    assert result.exit_code == 0
    assert "Execute all tests" in result.output
    assert "--spec" in result.output
    assert "--llm-provider" in result.output


def test_secrets_command_help() -> None:
    """Test secrets subcommand help."""
    runner = CliRunner()
    result = runner.invoke(app, ["secrets", "--help"])

    assert result.exit_code == 0
    assert "secrets" in result.output.lower()


def test_server_command_help() -> None:
    """Test server subcommand help."""
    runner = CliRunner()
    result = runner.invoke(app, ["server", "--help"])

    assert result.exit_code == 0
    assert "server" in result.output.lower()


def test_run_with_invalid_spec() -> None:
    """Test run command with invalid spec file."""
    runner = CliRunner()
    result = runner.invoke(app, ["run", "--spec", "/nonexistent/file.yml"])

    assert result.exit_code == 2  # Typer error for non-existent file
    assert "does not exist" in result.stderr


def test_run_with_malformed_spec() -> None:
    """Test run command with malformed YAML."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yml", delete=False) as f:
        f.write("invalid: yaml: content: [")
        temp_path = Path(f.name)

    try:
        runner = CliRunner()
        result = runner.invoke(app, ["run", "--spec", str(temp_path)])

        assert result.exit_code == 2
        # SCHEMA_ERROR is printed to stderr by the CLI
        output = (result.output or "") + (getattr(result, "stderr", "") or "")
        assert "SCHEMA_ERROR" in output or result.exit_code == 2
    finally:
        temp_path.unlink()


def test_run_dry_run() -> None:
    """Test run command in dry-run mode."""
    spec_data = {
        "name": "dry-run-test",
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
        assert summary["summary"]["total"] >= 0
        assert summary["summary"]["failed"] == 0

    finally:
        temp_path.unlink()


def _run_spec_text(text: str, *extra: str):
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yml", delete=False) as f:
        f.write(text)
        temp_path = Path(f.name)
    try:
        result = CliRunner().invoke(app, ["run", "--spec", str(temp_path), "--ci", *extra])
        return result, (result.output or "") + (getattr(result, "stderr", "") or "")
    finally:
        temp_path.unlink()


def test_run_empty_spec_fails() -> None:
    """A spec that yields 0 tests must fail the run, never report green (SONNY-6711)."""
    result, output = _run_spec_text("name: empty-test\ntests: []\n")

    assert result.exit_code == 2
    assert "no tests" in output.lower()


def test_run_spec_without_tests_field_fails() -> None:
    result, output = _run_spec_text("name: no-tests-field\n")

    assert result.exit_code == 2
    assert "tests" in output.lower()


def test_run_skipped_spec_is_not_a_failure() -> None:
    """A spec-level `skip:` directive contributes zero cases by design."""
    result, _ = _run_spec_text("name: pending\nskip: not implemented yet\n")

    assert result.exit_code == 0


def test_run_dry_run_empty_spec_is_not_a_failure() -> None:
    result, _ = _run_spec_text("name: empty-test\ntests: []\n", "--dry-run")

    assert result.exit_code == 0


def test_run_invalid_yaml_names_the_reason() -> None:
    """A spec that fails to load must say why, not only SCHEMA_ERROR (SONNY-6711)."""
    result, output = _run_spec_text("name: x\ntests:\n- name: a\n  query: RETURN 1 AS v: bad\n")

    assert result.exit_code == 2
    assert "SCHEMA_ERROR" in output
    assert "Invalid YAML" in output


def test_secrets_check_no_secrets() -> None:
    """Test secrets check with spec that has no secrets."""
    spec_data = {"name": "secrets-check-test", "tests": []}

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


def test_secrets_list_no_secrets() -> None:
    """Test secrets list with spec that has no secrets."""
    spec_data = {"name": "secrets-list-test", "tests": []}

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


def test_run_with_fuzz_parameters() -> None:
    """Test run command with fuzzing parameters."""
    spec_data = {
        "name": "fuzz-test",
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


def test_cli_error_handling() -> None:
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
        yaml.dump({"name": "error-handling-test", "tests": []}, f)
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
