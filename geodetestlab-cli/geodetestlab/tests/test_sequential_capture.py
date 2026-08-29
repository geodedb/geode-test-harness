"""Tests for the sequential gql step capture/compare facility.

Covers spec.py parsing of ``capture_regex`` / ``capture_as`` /
``gql_expected.equals_capture``, and the executor.py compare path in
``_run_sequential_test``'s gql branch (checks.py has no cross-step
comparison facility — this is the runner's own capture/compare support,
added for the BM25 score-stability pin in fts_bulk_merge_visibility.yml).

There were no existing executor unit tests exercising the gql branch of
``_run_sequential_test`` before this file (test_executor_security.py only
covers ``run_cli_test`` / ``_run_shell_test``); these tests establish that
coverage directly, following the same subprocess-mocking convention.
"""

from __future__ import annotations

from unittest.mock import patch

from geodetestlab.lib.executor import _run_sequential_test
from geodetestlab.lib.spec import TestCase, TestStep, load_spec


def _fake_result(stdout: str, returncode: int = 0, stderr: str = "") -> object:
    return type("R", (), {"stdout": stdout, "stderr": stderr, "returncode": returncode})()


def _run(steps: list[dict[str, object]]):
    tc = TestCase.from_dict(
        {
            "name": "capture-seq",
            "type": "sequential",
            "steps": steps,
        }
    )
    return _run_sequential_test(
        test_case=tc,
        binary="/usr/bin/geode",
        env={"GEODE_SERVER_ADDRESS": "127.0.0.1:3141"},
        secrets={},
        timeout_ms=5000,
        data_dir=None,
        verbose=False,
    )


class TestSpecParsing:
    """TestStep.from_dict accepts the three new fields."""

    def test_capture_fields_parsed(self) -> None:
        step = TestStep.from_dict(
            {
                "type": "gql",
                "query": "CALL geode.fts.search('idx', 'term')",
                "capture_regex": '"score":([0-9.]+)',
                "capture_as": "ref_score",
                "expect": {"status_class": "00000"},
            }
        )
        assert step.capture_regex == '"score":([0-9.]+)'
        assert step.capture_as == "ref_score"

    def test_equals_capture_in_gql_expected(self) -> None:
        step = TestStep.from_dict(
            {
                "type": "gql",
                "query": "CALL geode.fts.search('idx', 'term')",
                "capture_regex": '"score":([0-9.]+)',
                "expect": {"status_class": "00000", "equals_capture": "ref_score"},
            }
        )
        assert step.gql_expected is not None
        assert step.gql_expected["equals_capture"] == "ref_score"

    def test_full_spec_with_capture_steps_loads(self, tmp_path) -> None:
        spec_yaml = tmp_path / "capture.yml"
        spec_yaml.write_text(
            """
name: capture-test
tests:
  - name: capture-reference-score
    type: sequential
    steps:
      - type: gql
        query: "CALL geode.fts.search('idx', 'term')"
        capture_regex: '"score":([0-9.]+)'
        capture_as: ref_score
        expect: { status_class: "00000" }
      - type: gql
        query: "CALL geode.fts.search('idx', 'term')"
        capture_regex: '"score":([0-9.]+)'
        expect: { status_class: "00000", equals_capture: ref_score }
"""
        )
        spec = load_spec(spec_yaml)
        steps = spec.tests[0].steps
        assert steps[0].capture_as == "ref_score"
        assert steps[1].gql_expected["equals_capture"] == "ref_score"


class TestCaptureCompareExecution:
    """_run_sequential_test's gql branch: capture, then compare."""

    def test_equal_captures_pass(self) -> None:
        """Two steps extracting the same score value pass equals_capture."""
        steps = [
            {
                "type": "gql",
                "query": "CALL geode.fts.search('idx', 'term')",
                "capture_regex": r'"score":([0-9.]+)',
                "capture_as": "ref_score",
                "expect": {"status_class": "00000"},
            },
            {
                "type": "gql",
                "query": "CALL geode.fts.search('idx', 'term')",
                "capture_regex": r'"score":([0-9.]+)',
                "expect": {"status_class": "00000", "equals_capture": "ref_score"},
            },
        ]
        with patch("geodetestlab.lib.executor.subprocess.run") as mock_run:
            mock_run.return_value = _fake_result('{"status_class":"00000","score":1.2345}')
            result = _run(steps)
        assert result.passed, result.error

    def test_mismatched_captures_fail_with_clear_message(self) -> None:
        """A drifted score fails the step with a clear equals_capture message."""
        responses = [
            _fake_result('{"status_class":"00000","score":1.2345}'),
            _fake_result('{"status_class":"00000","score":2.4690}'),
        ]
        steps = [
            {
                "type": "gql",
                "query": "CALL geode.fts.search('idx', 'term')",
                "capture_regex": r'"score":([0-9.]+)',
                "capture_as": "ref_score",
                "expect": {"status_class": "00000"},
            },
            {
                "type": "gql",
                "query": "CALL geode.fts.search('idx', 'term')",
                "capture_regex": r'"score":([0-9.]+)',
                "expect": {"status_class": "00000", "equals_capture": "ref_score"},
            },
        ]
        with patch("geodetestlab.lib.executor.subprocess.run") as mock_run:
            mock_run.side_effect = responses
            result = _run(steps)
        assert not result.passed
        assert "equals_capture mismatch" in result.error
        assert "ref_score" in result.error

    def test_unknown_capture_name_fails_step_not_crash(self) -> None:
        """Referencing a name nothing ever captured fails the step cleanly."""
        steps = [
            {
                "type": "gql",
                "query": "CALL geode.fts.search('idx', 'term')",
                "capture_regex": r'"score":([0-9.]+)',
                "expect": {"status_class": "00000", "equals_capture": "never_captured"},
            },
        ]
        with patch("geodetestlab.lib.executor.subprocess.run") as mock_run:
            mock_run.return_value = _fake_result('{"status_class":"00000","score":1.0}')
            result = _run(steps)
        assert not result.passed
        assert "unknown capture name" in result.error

    def test_regex_without_group_fails_step_not_crash(self) -> None:
        """A capture_regex with no capture group fails the step, not the process."""
        steps = [
            {
                "type": "gql",
                "query": "CALL geode.fts.search('idx', 'term')",
                "capture_regex": r'"score":[0-9.]+',  # no capture group
                "capture_as": "ref_score",
                "expect": {"status_class": "00000"},
            },
        ]
        with patch("geodetestlab.lib.executor.subprocess.run") as mock_run:
            mock_run.return_value = _fake_result('{"status_class":"00000","score":1.0}')
            result = _run(steps)
        assert not result.passed
        assert "exactly one capture group" in result.error

    def test_capture_as_without_capture_regex_fails_step_not_crash(self) -> None:
        """capture_as with no capture_regex fails the step, not the process."""
        steps = [
            {
                "type": "gql",
                "query": "CALL geode.fts.search('idx', 'term')",
                "capture_as": "ref_score",
                "expect": {"status_class": "00000"},
            },
        ]
        with patch("geodetestlab.lib.executor.subprocess.run") as mock_run:
            mock_run.return_value = _fake_result('{"status_class":"00000","score":1.0}')
            result = _run(steps)
        assert not result.passed
        assert "capture_as requires capture_regex" in result.error

    def test_no_regex_match_fails_step_not_crash(self) -> None:
        """A capture_regex that doesn't match stdout fails the step cleanly."""
        steps = [
            {
                "type": "gql",
                "query": "CALL geode.fts.search('idx', 'term')",
                "capture_regex": r'"nonexistent_field":([0-9.]+)',
                "capture_as": "ref_score",
                "expect": {"status_class": "00000"},
            },
        ]
        with patch("geodetestlab.lib.executor.subprocess.run") as mock_run:
            mock_run.return_value = _fake_result('{"status_class":"00000","score":1.0}')
            result = _run(steps)
        assert not result.passed
        assert "did not match stdout" in result.error
