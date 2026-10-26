"""Failing-first reproduction for the geodetestlab `verify:` defects.

Two triage-confirmed defects are pinned here:

Defect 1 (silent drop / dead code)
    `TestCase` / `TestCase.from_dict` (lib/spec.py) has no `verify` field and
    `load_spec` does per-key `data.get()` with no unknown-key validation, so a
    `verify:` block on a test is silently discarded and NEVER executed. Three
    real specs (query_file_flag_comprehensive.yml, query_file_flag_edge_cases.yml,
    transaction_chunked_execution.yml — 38 verify blocks total) are dead.

Defect 2 (`;`-guard false positive)
    `sanitize_args` (lib/utils.py) rejects ';' as a shell metacharacter, and the
    query-positional exclusion heuristic in `_build_cli_command`
    (lib/executor.py ~l.649-682) mis-detects the query positional when a
    VALUELESS flag (e.g. `--insecure`) precedes it. It treats the query as the
    flag's value, never excludes it from the metachar scan, and so a legitimate
    multi-statement verify query `USE GRAPH x; MATCH ...` is rejected before it
    ever runs. subprocess is invoked with shell=False, so ';' is not a security
    risk — the guard is only a typo-guard and is over-broad here.

Fixer contract (what makes these go green):
    * spec.py: add a `verify_queries` field to TestCase, populated by
      from_dict from the `verify:` list (parallel to `setup_queries`).
    * executor.py: after the main command passes, run each verify item as a
      synthetic TestCase (mirror of the setup_queries loop ~l.827-859); a
      failing verify fails the whole test.
    * executor.py ~l.649-682: fix the query-positional heuristic so a valueless
      flag (`--insecure`) does not swallow the following positional query — the
      query must be excluded from the sanitize scan. Keep the typo-guard active
      for ';' in genuine NON-query args.
"""

from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import patch

import pytest

from geodetestlab.lib.executor import _build_cli_command, run_cli_test
from geodetestlab.lib.runner_types import TestResult
from geodetestlab.lib.spec import TestCase, load_spec

FIXTURE_SPEC = Path(__file__).parent / "fixtures" / "verify_selfcheck.yml"

_ENV = {"GEODE_SERVER_ADDRESS": "127.0.0.1:3141"}


def _make_case(**overrides: object) -> TestCase:
    defaults: dict[str, object] = {
        "name": "verify-case",
        "description": "test",
        "test_type": "cli",
    }
    defaults.update(overrides)
    return TestCase.from_dict(defaults)


class _FakeCompleted:
    """Minimal stand-in for subprocess.CompletedProcess."""

    def __init__(self, stdout: str = "", stderr: str = "", returncode: int = 0) -> None:
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode


def _query_of(cmd: list[str]) -> str:
    """Return the GQL query element of a built `geode query ...` command."""
    for token in cmd[1:]:
        if token.startswith("RETURN") or token.startswith("USE") or token.startswith("MATCH"):
            return token
    return ""


# ---------------------------------------------------------------------------
# Contract 1 — PARSER: verify: must survive onto TestCase as verify_queries
# ---------------------------------------------------------------------------


class TestVerifyParserSurfacesField:
    """Defect 1 (parser): a `verify:` block must be surfaced on the parsed
    TestCase as `verify_queries`, exactly as `setup:` is surfaced as
    `setup_queries`. It is silently dropped today."""

    def test_from_dict_surfaces_verify_queries(self) -> None:
        verify_items = [
            {
                "args": ["query", "--insecure", "MATCH (n:SingleChunk) RETURN count(n) AS cnt"],
                "expect": {"stdout_contains": ["3"]},
            }
        ]
        tc = _make_case(
            args=["query", "--insecure", "MATCH (n:SingleChunk) CREATE (n)"],
            expect={"exit_code": 0},
            verify=verify_items,
        )

        # RED today: TestCase has no `verify_queries` field at all.
        assert hasattr(tc, "verify_queries"), "TestCase dropped the verify: block (no verify_queries field)"
        assert tc.verify_queries == verify_items

    def test_load_spec_preserves_verify_queries(self) -> None:
        """End-to-end through load_spec (real fixture on disk)."""
        spec = load_spec(FIXTURE_SPEC)
        by_name = {t.name: t for t in spec.tests}

        false_case = by_name["verify-false-claim-must-fail"]
        # RED today: field missing → AttributeError.
        assert hasattr(false_case, "verify_queries"), "load_spec discarded the verify: block"
        assert len(false_case.verify_queries) == 1
        item = false_case.verify_queries[0]
        assert item["args"][-1] == "RETURN 999 AS x"
        assert item["expect"]["stdout_contains"] == ["424242"]


# ---------------------------------------------------------------------------
# Contract 2 — EXECUTION: the dead-code proof (verify actually runs & asserts)
# ---------------------------------------------------------------------------


class TestVerifyExecutionRuns:
    """Defect 1 (dead code): once surfaced, verify items must be executed after
    the main step and a false claim must fail the test.

    subprocess.run is mocked (a command-runner boundary, exactly as
    test_executor_security.py does) so the test is deterministic and needs no
    live server — the harness's verify-execution + expectation-checking logic is
    the real code under test."""

    def _run(self, tc: TestCase) -> tuple[TestResult, list[str]]:
        executed_queries: list[str] = []

        def _side_effect(cmd, *args, **kwargs):  # type: ignore[no-untyped-def]
            q = _query_of(cmd)
            executed_queries.append(q)
            # Deterministic stdout keyed off the literal RETURN value.
            if "RETURN 999" in q:
                return _FakeCompleted(stdout="x = 999\n", returncode=0)
            if "RETURN 7" in q:
                return _FakeCompleted(stdout="x = 7\n", returncode=0)
            return _FakeCompleted(stdout="x = 1\n", returncode=0)

        with patch("geodetestlab.lib.executor.subprocess.run", side_effect=_side_effect):
            result = run_cli_test(
                test_case=tc,
                binary="/usr/bin/geode",
                env=dict(_ENV),
                secrets={},
                timeout_ms=5000,
                data_dir=None,
                verbose=False,
            )
        return result, executed_queries

    def test_false_verify_claim_fails_the_test(self) -> None:
        """A verify block asserting an impossible substring must make the test
        FAIL. Today verify is dropped so the test passes green — that green is
        the bug."""
        tc = _make_case(
            name="verify-false-claim-must-fail",
            args=["query", "--insecure", "RETURN 1 AS x"],
            expect={"exit_code": 0},
            verify=[
                {
                    "args": ["query", "--insecure", "RETURN 999 AS x"],
                    "expect": {"stdout_contains": ["424242"]},
                }
            ],
        )
        result, executed = self._run(tc)

        # RED today: verify never runs, main passes → result.passed is True.
        assert result.passed is False, "false verify claim did not fail the test (verify block was dropped)"
        assert "RETURN 999 AS x" in executed, "verify query was never executed"

    def test_true_verify_claim_runs_and_passes(self) -> None:
        """The positive form: a TRUE verify claim must keep the test passing AND
        must actually be executed (proving it is no longer dead code)."""
        tc = _make_case(
            name="verify-true-claim-must-pass",
            args=["query", "--insecure", "RETURN 7 AS x"],
            expect={"exit_code": 0},
            verify=[
                {
                    "args": ["query", "--insecure", "RETURN 7 AS x"],
                    "expect": {"stdout_contains": ["7"]},
                }
            ],
        )
        result, executed = self._run(tc)

        assert result.passed is True, f"true verify claim should pass: {result.error}"
        # RED today: the verify query is never dispatched (dead code).
        assert executed.count("RETURN 7 AS x") >= 2, "verify query was never executed after the main step"


# ---------------------------------------------------------------------------
# Contract 3 — GUARD: the ;-typo-guard must not reject multi-statement queries
# ---------------------------------------------------------------------------


class TestSemicolonGuardQueryPositional:
    """Defect 2: the query-positional exclusion heuristic must exclude the
    positional query from the ';' typo-guard even when a valueless flag
    (`--insecure`) precedes it — while still rejecting ';' in genuine
    non-query args."""

    def _build(self, args: list[str]):  # type: ignore[no-untyped-def]
        return _build_cli_command(
            _make_case(args=args, expect={"exit_code": 0}),
            "/usr/bin/geode",
            dict(_ENV),
            {},
            5000,
            None,
            time.time(),
        )

    def test_multistatement_verify_query_is_allowed(self) -> None:
        """`query --insecure "USE GRAPH g; MATCH (n) RETURN n"` — the valueless
        --insecure precedes the multi-statement query. The query must be
        excluded from the metachar scan and NOT rejected."""
        cmd, err = self._build(["query", "--insecure", "USE GRAPH g; MATCH (n) RETURN n"])
        # RED today: query_text_idx stays None (heuristic thinks the query is
        # --insecure's value) → the ';' query is rejected.
        assert err is None, f"multi-statement query wrongly rejected: {err.error if err else ''}"
        assert "USE GRAPH g; MATCH (n) RETURN n" in cmd

    def test_semicolon_in_nonquery_arg_still_rejected(self) -> None:
        """Guard-positive: ';' in a genuine NON-query flag value must STILL be
        rejected. Pins the fixer to repair the heuristic, not nuke the guard."""
        cmd, err = self._build(["query", "RETURN 1 AS x", "--format", "json;rm -rf /"])
        assert err is not None, "typo-guard was nuked: ';' in a non-query arg slipped through"
        assert "Invalid character ';'" in err.error


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-v"]))
