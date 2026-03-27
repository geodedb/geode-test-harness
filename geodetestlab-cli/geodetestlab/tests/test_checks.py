"""Tests for checks.py expectation verification.

Covers QG-005: Unit tests for the core expectation checking module.
"""

from __future__ import annotations

from geodetestlab.lib.checks import check_expectations
from geodetestlab.lib.spec import TestCase


def _case(expected: dict[str, object]) -> TestCase:
    """Build a minimal TestCase with the given expected dict."""
    return TestCase.from_dict(
        {
            "name": "check-test",
            "description": "test",
            "expected": expected,
        }
    )


class TestExitCode:
    def test_exact_match(self) -> None:
        tc = _case({"exit_code": 0})
        assert check_expectations(tc, output="", error="", exit_code=0)

    def test_exact_mismatch(self) -> None:
        tc = _case({"exit_code": 0})
        assert not check_expectations(tc, output="", error="", exit_code=1)

    def test_list_match(self) -> None:
        tc = _case({"exit_code": [0, 1]})
        assert check_expectations(tc, output="", error="", exit_code=1)

    def test_list_mismatch(self) -> None:
        tc = _case({"exit_code": [0, 1]})
        assert not check_expectations(tc, output="", error="", exit_code=2)


class TestStatus:
    def test_success_pass(self) -> None:
        tc = _case({"status": "success"})
        assert check_expectations(tc, output="", error="", exit_code=0)

    def test_success_fail(self) -> None:
        tc = _case({"status": "success"})
        assert not check_expectations(tc, output="", error="", exit_code=1)

    def test_error_pass(self) -> None:
        tc = _case({"status": "error"})
        assert check_expectations(tc, output="", error="", exit_code=1)

    def test_error_fail(self) -> None:
        tc = _case({"status": "error"})
        assert not check_expectations(tc, output="", error="", exit_code=0)


class TestStdoutContains:
    def test_present(self) -> None:
        tc = _case({"stdout_contains": ["hello", "world"]})
        assert check_expectations(tc, output="hello world", error="", exit_code=0)

    def test_missing(self) -> None:
        tc = _case({"stdout_contains": ["missing"]})
        assert not check_expectations(tc, output="hello", error="", exit_code=0)

    def test_dict_items(self) -> None:
        tc = _case({"stdout_contains": [{"key": "val"}]})
        assert check_expectations(tc, output="key val", error="", exit_code=0)

    def test_fallback_to_stderr(self) -> None:
        """stdout_contains falls back to stderr (Geode CLI behavior)."""
        tc = _case({"stdout_contains": ["in_stderr"]})
        assert check_expectations(tc, output="", error="in_stderr", exit_code=0)


class TestStdoutNotContains:
    def test_absent_passes(self) -> None:
        tc = _case({"stdout_not_contains": ["bad"]})
        assert check_expectations(tc, output="good", error="", exit_code=0)

    def test_present_fails(self) -> None:
        tc = _case({"stdout_not_contains": ["bad"]})
        assert not check_expectations(tc, output="bad output", error="", exit_code=0)


class TestStderrContains:
    def test_present(self) -> None:
        tc = _case({"exit_code": 1, "stderr_contains": ["error msg"]})
        assert check_expectations(tc, output="", error="error msg here", exit_code=1)

    def test_missing(self) -> None:
        tc = _case({"exit_code": 1, "stderr_contains": ["missing"]})
        assert not check_expectations(tc, output="", error="other", exit_code=1)


class TestStdoutRegex:
    def test_matches(self) -> None:
        tc = _case({"stdout_regex": [r"\d+ rows"]})
        assert check_expectations(tc, output="42 rows returned", error="", exit_code=0)

    def test_no_match(self) -> None:
        tc = _case({"stdout_regex": [r"\d+ rows"]})
        assert not check_expectations(tc, output="no results", error="", exit_code=0)


class TestStdoutExact:
    def test_matches(self) -> None:
        tc = _case({"stdout_exact": "hello"})
        assert check_expectations(tc, output="hello", error="", exit_code=0)

    def test_mismatch(self) -> None:
        tc = _case({"stdout_exact": "hello"})
        assert not check_expectations(tc, output="goodbye", error="", exit_code=0)

    def test_whitespace_trimmed(self) -> None:
        tc = _case({"stdout_exact": "hello"})
        assert check_expectations(tc, output="  hello  \n", error="", exit_code=0)


class TestResultContains:
    def test_string(self) -> None:
        tc = _case({"result_contains": "found"})
        assert check_expectations(tc, output="found it", error="", exit_code=0)

    def test_list(self) -> None:
        tc = _case({"result_contains": ["a", "b"]})
        assert check_expectations(tc, output="a and b", error="", exit_code=0)

    def test_missing(self) -> None:
        tc = _case({"result_contains": ["missing"]})
        assert not check_expectations(tc, output="nothing", error="", exit_code=0)


class TestErrorContains:
    def test_present(self) -> None:
        tc = _case({"exit_code": 1, "error_contains": "failed"})
        assert check_expectations(tc, output="", error="operation failed", exit_code=1)

    def test_missing(self) -> None:
        tc = _case({"exit_code": 1, "error_contains": "specific"})
        assert not check_expectations(tc, output="", error="generic error", exit_code=1)


class TestCombined:
    def test_all_pass(self) -> None:
        tc = _case(
            {
                "exit_code": 0,
                "stdout_contains": ["result"],
                "stderr_not_contains": ["error"],
            }
        )
        assert check_expectations(tc, output="result here", error="", exit_code=0)

    def test_one_fails(self) -> None:
        tc = _case(
            {
                "exit_code": 0,
                "stdout_contains": ["missing"],
            }
        )
        assert not check_expectations(tc, output="nothing", error="", exit_code=0)
