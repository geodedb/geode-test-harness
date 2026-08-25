"""Regression tests: a managed server that never starts must fail loudly.

When a spec asks for a managed server (``cli.server.enabled: true`` /
``mode: server``) and the server never comes up — e.g. ``Server failed to
start within 60.0 seconds`` after the runner's port retries — zero tests can
execute. The runner used to abandon the run with an empty, all-zero summary,
which upstream renders as ``{"total":0,"passed":0,"failed":0}`` followed by
"✓ All tests passed!": a false green that hides a completely unexecuted spec.

A spec whose server never comes up must fail loudly: the summary must record
the infrastructure failure and the CLI must exit non-zero.
"""

from __future__ import annotations

import io
import json
import stat
import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import patch

import yaml
from rich.console import Console
from typer.testing import CliRunner

from geodetestlab.cli import app
from geodetestlab.lib.cli_formatters import _show_rich_summary
from geodetestlab.lib.server import ServerError


def _server_spec() -> Any:
    """A minimal spec that requires a managed server to run one query."""
    # Imported lazily: pytest tries to collect module-level ``Test*`` names.
    from geodetestlab.lib.spec import TestCase, TestSpec

    return TestSpec(
        name="server-startup-failure",
        description="",
        mode="server",
        tests=[TestCase.from_dict({"name": "trivial-query", "query": "RETURN 1 AS x"})],
    )


def _write_failing_binary(directory: Path) -> Path:
    """Write a fake geode binary whose ``serve`` subcommand never starts."""
    binary = directory / "fake-geode.sh"
    binary.write_text(
        "#!/bin/sh\n"
        'if [ "$1" = "serve" ]; then\n'
        '  echo "fatal: unable to bind listener" >&2\n'
        "  exit 1\n"
        "fi\n"
        "exit 0\n"
    )
    binary.chmod(binary.stat().st_mode | stat.S_IXUSR)
    return binary


def _summary_from_output(output: str) -> dict[str, Any]:
    """Extract the single-line JSON summary the CLI always prints."""
    for line in reversed(output.splitlines()):
        line = line.strip()
        if not line.startswith('{"summary"'):
            continue
        parsed: dict[str, Any] = json.loads(line)
        return parsed
    raise AssertionError(f"no JSON summary line in output:\n{output}")


class TestRunTestsServerStartFailure:
    def test_summary_records_server_start_failure(self) -> None:
        """run_tests must report a failed run, not an empty all-zero summary."""
        from geodetestlab.lib.runner import run_tests

        with (
            patch("geodetestlab.lib.runner.find_geode_binary", return_value="/usr/bin/geode"),
            patch("geodetestlab.lib.runner.provision_tls_certs", return_value=None),
            patch(
                "geodetestlab.lib.runner.start_server",
                side_effect=ServerError("Server failed to start within 60.0 seconds"),
            ) as mock_start,
        ):
            exit_code, summary = run_tests(
                spec=_server_spec(),
                secrets={},
                env_overrides={},
                verbose=False,
            )

        assert mock_start.called
        assert exit_code != 0
        assert summary["total"] >= 1
        assert summary["failed"] >= 1
        assert summary["passed"] == 0
        errors = " ".join(str(r.get("error", "")) for r in summary.get("results", []))
        assert "failed to start" in errors.lower()

    def test_report_json_records_server_start_failure(self) -> None:
        """The machine-readable report must show the failure, not an empty run."""
        from geodetestlab.lib.runner import run_tests

        with tempfile.TemporaryDirectory() as tmp:
            report = Path(tmp) / "report.json"
            with (
                patch("geodetestlab.lib.runner.find_geode_binary", return_value="/usr/bin/geode"),
                patch("geodetestlab.lib.runner.provision_tls_certs", return_value=None),
                patch(
                    "geodetestlab.lib.runner.start_server",
                    side_effect=ServerError("Server failed to start within 60.0 seconds"),
                ),
            ):
                run_tests(
                    spec=_server_spec(),
                    secrets={},
                    env_overrides={},
                    report_json=report,
                    spec_path="server-startup-failure.yml",
                    verbose=False,
                )

            data = json.loads(report.read_text())

        assert data["summary"]["failed"] >= 1
        assert data["specs"][0]["results"], "report must list the infrastructure failure"


class TestCliServerStartFailure:
    def test_cli_exits_nonzero_and_never_claims_success(self) -> None:
        """End-to-end: a spec whose server never starts is a loud failure."""
        spec_data = {
            "name": "server-never-starts",
            "cli": {"server": {"enabled": True}},
            "tests": [
                {
                    "name": "trivial-query",
                    "query": "RETURN 1 AS x",
                    "expected": {"exit_code": 0},
                }
            ],
        }

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            binary = _write_failing_binary(tmp_path)
            spec_path = tmp_path / "spec.yml"
            spec_path.write_text(yaml.safe_dump(spec_data))

            result = CliRunner().invoke(
                app,
                [
                    "run",
                    "--spec",
                    str(spec_path),
                    "--geode-binary",
                    str(binary),
                    "--server-timeout-ms",
                    "1000",
                    "--failure-file",
                    "",
                ],
            )

        assert result.exit_code != 0, result.output
        assert "All tests passed" not in result.output
        summary = _summary_from_output(result.output)["summary"]
        assert summary["failed"] >= 1
        assert summary["passed"] == 0


class TestRichSummaryHonesty:
    def _render(self, summary: dict[str, int]) -> str:
        buffer = io.StringIO()
        _show_rich_summary(summary, Console(file=buffer, width=100, no_color=True))
        return buffer.getvalue()

    def test_no_success_claim_when_nothing_ran(self) -> None:
        output = self._render({"total": 0, "passed": 0, "failed": 0, "skipped": 0})
        assert "All tests passed" not in output
        assert "No tests" in output

    def test_success_claim_for_a_real_passing_run(self) -> None:
        output = self._render({"total": 3, "passed": 3, "failed": 0, "skipped": 0})
        assert "All tests passed" in output

    def test_failure_claim_when_tests_failed(self) -> None:
        output = self._render({"total": 3, "passed": 2, "failed": 1, "skipped": 0})
        assert "All tests passed" not in output
        assert "failed" in output
