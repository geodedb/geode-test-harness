"""Tests for the streaming failure log (geodetestlab.lib.failure_log)."""

from __future__ import annotations

import threading
from pathlib import Path

from geodetestlab.lib.failure_log import (
    append_failure,
    finalize_failure_log,
    init_failure_log,
)


def test_init_truncates_and_writes_header(tmp_path: Path) -> None:
    p = str(tmp_path / "test-failures.md")
    # Pre-existing content must be wiped by init.
    Path(p).write_text("STALE CONTENT FROM PRIOR RUN\n")
    init_failure_log(p, target="specs/", transport="quic", binary="/bin/geode")
    text = Path(p).read_text()
    assert "STALE CONTENT" not in text
    assert text.startswith("# Test Failures")
    assert "transport:** quic" in text
    assert "tail -f" in text


def test_append_writes_detailed_tailable_record(tmp_path: Path) -> None:
    p = str(tmp_path / "f.md")
    init_failure_log(p)
    append_failure(
        p,
        spec="geodetestlab/specs/foo.yml",
        test_name="my-negative-case",
        error="exit_code mismatch: expected 0 got 3\nstderr: Invalid username",
        output='{"status_class":"42000"}',
        duration_ms=123.4,
    )
    text = Path(p).read_text()
    # Self-contained, greppable record.
    assert "### FAIL [test] — foo.yml :: my-negative-case" in text
    assert "`geodetestlab/specs/foo.yml`" in text
    assert "exit_code mismatch: expected 0 got 3" in text
    assert '{"status_class":"42000"}' in text
    assert "duration_ms:** 123" in text


def test_append_truncates_huge_output(tmp_path: Path) -> None:
    p = str(tmp_path / "f.md")
    init_failure_log(p)
    append_failure(p, spec="s.yml", test_name="t", error="e", output="X" * 50_000)
    text = Path(p).read_text()
    assert "truncated" in text
    assert len(text) < 20_000  # bounded, not the full 50k


def test_finalize_writes_authoritative_list(tmp_path: Path) -> None:
    p = str(tmp_path / "f.md")
    init_failure_log(p)
    finalize_failure_log(
        p,
        aggregate={"total": 10, "passed": 8, "failed": 2, "skipped": 0},
        duration_ms=4200.0,
        failed_entries=[
            {"spec": "a.yml", "test": "t1", "error": "boom one\ndetail"},
            {"spec": "b.yml", "test": "t2", "error": "boom two"},
        ],
    )
    text = Path(p).read_text()
    assert "## Final" in text
    assert "2 failed, 8 passed" in text
    assert "`a.yml` :: `t1` — boom one" in text  # only the first error line
    assert "`b.yml` :: `t2` — boom two" in text


def test_finalize_clean_run_says_no_failures(tmp_path: Path) -> None:
    p = str(tmp_path / "f.md")
    init_failure_log(p)
    finalize_failure_log(p, aggregate={"total": 5, "passed": 5, "failed": 0, "skipped": 0})
    assert "No failures" in Path(p).read_text()


def test_concurrent_appends_do_not_corrupt(tmp_path: Path) -> None:
    """flock/lock serialisation: every record lands intact, none interleaved."""
    p = str(tmp_path / "f.md")
    init_failure_log(p)

    def worker(i: int) -> None:
        for j in range(20):
            append_failure(p, spec=f"s{i}.yml", test_name=f"t{i}-{j}", error=f"err-{i}-{j}")

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    text = Path(p).read_text()
    # 6 workers * 20 records = 120 intact FAIL headers.
    assert text.count("### FAIL [test]") == 120
    # Every record's error string is present intact (no interleaving/corruption).
    for i in range(6):
        for j in range(20):
            assert f"err-{i}-{j}" in text


def test_none_path_is_noop(tmp_path: Path) -> None:
    # Disabled failure logging: all functions are safe no-ops.
    init_failure_log(None)
    append_failure(None, spec="s", test_name="t", error="e")
    finalize_failure_log(None, aggregate={"failed": 1})
    # Nothing created in tmp_path.
    assert not list(tmp_path.iterdir())


def test_summarize_expected_renders_assertions() -> None:
    """The runner's expected-summary surfaces the query + assertions for a record."""
    from geodetestlab.lib.runner import _summarize_expected
    from geodetestlab.lib.spec import TestCase

    tc = TestCase.from_dict(
        {
            "name": "t",
            "args": ["query", "RETURN 1"],
            "expected": {"exit_code": 0, "stdout_contains": ["WANT"], "stdout_not_contains": ["NOPE"]},
        }
    )
    summary = _summarize_expected(tc)
    assert "args: ['query', 'RETURN 1']" in summary
    assert "exit_code == 0" in summary
    assert "stdout_contains: ['WANT']" in summary
    assert "stdout_not_contains: ['NOPE']" in summary
