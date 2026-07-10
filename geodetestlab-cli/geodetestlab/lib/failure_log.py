"""Streaming, tailable failure log for geodetestlab runs.

Purpose
-------
When ``geodetestlab run`` (e.g. via ``make test``) executes a large suite,
this module writes every test FAILURE to a single human- and agent-readable
file **as it happens**, so you can:

* ``tail -f reports/test-failures.md`` while a run is in progress, and
* point a coding agent at the finished file to fix the failures.

Concurrency
-----------
``geodetestlab`` runs specs across a ``ProcessPoolExecutor`` (separate
processes) and, within a spec, tests across a ``ThreadPoolExecutor``. A single
shared in-memory object cannot span processes, so every append opens the file,
takes an advisory ``flock`` (which serialises writers across BOTH processes and
threads), writes one self-contained record, flushes, and unlocks. The only
picklable state a worker needs is the **path** (a str).

Lifecycle
---------
* ``init_failure_log(path, ...)`` — called ONCE by the parent before any worker
  runs. Truncates the file and writes the header.
* ``append_failure(path, ...)`` — called by whichever process/thread records a
  failed result. Appends one record and flushes (tailable).
* ``finalize_failure_log(path, ...)`` — called ONCE by the parent after the run.
  Appends the authoritative post-retry summary + a compact actionable list.

All functions are best-effort: a logging error never crashes a test run.
"""

from __future__ import annotations

import os
import threading
from datetime import UTC, datetime
from typing import Any

try:  # POSIX advisory file locking; degrade gracefully if unavailable.
    import fcntl

    _HAVE_FLOCK = True
except ImportError:  # pragma: no cover - non-POSIX
    fcntl = None  # type: ignore[assignment]
    _HAVE_FLOCK = False

# In-process fallback lock (also guards the flock-less path).
_PROC_LOCK = threading.Lock()

# Keep individual records bounded so the file stays tailable, not enormous.
_MAX_OUTPUT_CHARS = 2000
_MAX_ERROR_CHARS = 4000


def _now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _truncate(text: str, limit: int) -> str:
    text = text or ""
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n… [truncated, {len(text) - limit} more chars]"


def _write_atomic(path: str, data: str, *, mode: str) -> None:
    """Write ``data`` to ``path`` under an advisory lock, then flush.

    ``mode`` is ``"w"`` (truncate: header) or ``"a"`` (append: records/footer).
    The lock serialises concurrent writers across processes and threads so
    records never interleave.
    """
    try:
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with _PROC_LOCK, open(path, mode, encoding="utf-8") as fh:
            if _HAVE_FLOCK:
                try:
                    fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
                except OSError:
                    pass
            fh.write(data)
            fh.flush()  # flush is enough for `tail -f`; fsync not needed
            if _HAVE_FLOCK:
                try:
                    fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
                except OSError:
                    pass
    except Exception:
        # Never let failure logging break a run.
        pass


def init_failure_log(
    path: str | None,
    *,
    target: str = "",
    transport: str = "",
    binary: str = "",
) -> None:
    """Truncate ``path`` and write the header. Called once by the parent."""
    if not path:
        return
    header = (
        f"# Test Failures\n\n"
        f"- **started:** {_now_iso()}\n"
        f"- **target:** {target or '(unspecified)'}\n"
        f"- **transport:** {transport or 'quic'}\n"
        f"- **binary:** {binary or '(auto-detected)'}\n\n"
        f"Failures are appended **live** as they occur — `tail -f` this file "
        f"during a run. Point an agent at this file to fix them; the authoritative "
        f"post-retry list is in the `## Final` section at the bottom once the run "
        f"completes.\n\n"
        f"Each record below is one failing test: the spec + test name, the "
        f"assertion error, and a bounded output excerpt.\n\n"
        f"---\n\n"
    )
    _write_atomic(path, header, mode="w")


def append_failure(
    path: str | None,
    *,
    spec: str,
    test_name: str,
    error: str = "",
    output: str = "",
    expected: str = "",
    duration_ms: float = 0.0,
    cluster_node: int | None = None,
    plaintext_violations: list[str] | None = None,
    kind: str = "test",
) -> None:
    """Append one failure record and flush. Safe across processes/threads.

    ``kind`` distinguishes ``"test"`` (assertion failure) from ``"spec"``
    (schema error / runner crash / server death for a whole spec). ``expected``
    is a compact summary of the test's expectations, shown so a reader sees
    expected-vs-actual even when the runner did not populate ``error``.
    """
    if not path:
        return
    node = f" (node {cluster_node})" if cluster_node is not None else ""
    lines = [
        f"### FAIL [{kind}] — {os.path.basename(spec)} :: {test_name}{node}\n",
        f"- **spec:** `{spec}`\n",
        f"- **test:** `{test_name}`\n",
        f"- **when:** {_now_iso()}\n",
        f"- **duration_ms:** {duration_ms:.0f}\n",
    ]
    if plaintext_violations:
        lines.append(f"- **plaintext_violations:** {plaintext_violations}\n")
    if expected.strip():
        lines.append("\n**expected:**\n\n")
        lines.append("```\n" + _truncate(expected, _MAX_ERROR_CHARS).strip() + "\n```\n")
    err = _truncate(error, _MAX_ERROR_CHARS).strip()
    if err:
        lines.append("\n**error:**\n\n")
        lines.append("```\n" + err + "\n```\n")
    out = _truncate(output, _MAX_OUTPUT_CHARS).strip()
    if out:
        lines.append("\n**actual output (excerpt):**\n\n")
        lines.append("```\n" + out + "\n```\n")
    if not err and not out:
        lines.append("\n(no error text or output captured)\n")
    lines.append("\n---\n\n")
    _write_atomic(path, "".join(lines), mode="a")


def finalize_failure_log(
    path: str | None,
    *,
    aggregate: dict[str, int],
    duration_ms: float = 0.0,
    failed_entries: list[dict[str, Any]] | None = None,
) -> None:
    """Append the authoritative post-retry summary + actionable list.

    ``failed_entries`` are ``{"spec": str, "test": str, "error": str}`` dicts
    computed by the parent from the final aggregated results.
    """
    if not path:
        return
    total = aggregate.get("total", 0)
    passed = aggregate.get("passed", 0)
    failed = aggregate.get("failed", 0)
    skipped = aggregate.get("skipped", 0)
    entries = failed_entries or []
    body = [
        "## Final\n\n",
        f"- **finished:** {_now_iso()}\n",
        f"- **duration_s:** {duration_ms / 1000.0:.1f}\n",
        f"- **result:** {failed} failed, {passed} passed, {skipped} skipped, {total} total\n\n",
    ]
    if failed == 0 and not entries:
        body.append("**No failures.** ✅\n")
    else:
        body.append(
            "**Actionable failure list (authoritative, post-retry).** Fix each; "
            "re-run its spec with "
            "`cd geodetestlab-cli && python -m geodetestlab run --spec <spec> -v`:\n\n"
        )
        for e in entries:
            first_line = (e.get("error") or "").strip().splitlines()
            summary = first_line[0] if first_line else "(see live record above)"
            body.append(f"- `{e.get('spec', '?')}` :: `{e.get('test', '?')}` — {summary}\n")
    body.append("\n")
    _write_atomic(path, "".join(body), mode="a")
