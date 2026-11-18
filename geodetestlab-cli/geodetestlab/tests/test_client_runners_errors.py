"""Error handling of the Python-client and shell runners.

Teardown/close failures are logged (never silently dropped), the step-error
boundary catches only the errors a step can raise, and runner bugs propagate.
"""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

# The client library may be installed but incompatible with this environment's
# grpcio (it raises RuntimeError on import); these tests never talk to a server,
# so treat it as absent exactly like a missing package.
try:
    import geode_client  # noqa: F401
except Exception:  # noqa: BLE001
    sys.modules["geode_client"] = None  # type: ignore[assignment]

from runners import python_runner  # noqa: E402


def _import_shell_runner() -> Any:
    """Import runners.shell_runner against the repo-root ``lib`` package.

    The harness package puts its own ``geodetestlab/lib`` on sys.path as ``lib``;
    the legacy runner needs the repo-root ``lib`` (server_manager). Swap the
    cached modules for the duration of the import.
    """
    import importlib

    saved = {k: sys.modules.pop(k) for k in list(sys.modules) if k == "lib" or k.startswith("lib.")}
    try:
        return importlib.import_module("runners.shell_runner")
    finally:
        for k in [k for k in sys.modules if k == "lib" or k.startswith("lib.")]:
            sys.modules.pop(k)
        sys.modules.update(saved)


shell_runner = _import_shell_runner()


class _Conn:
    def __init__(self, close_error: BaseException | None = None) -> None:
        self.close_error = close_error
        self.closed = False

    async def close(self) -> None:
        self.closed = True
        if self.close_error is not None:
            raise self.close_error


def _runner() -> Any:
    r = object.__new__(python_runner.PythonTestRunner)
    r.connection = None
    r.connections = {}
    r.verbose = False
    return r


def test_teardown_logs_and_continues_after_a_close_error(caplog: pytest.LogCaptureFixture) -> None:
    r = _runner()
    bad, good = _Conn(OSError("boom")), _Conn()
    r.connection, r.connections = bad, {"a": good}
    with caplog.at_level(logging.DEBUG, logger=python_runner.logger.name):
        asyncio.run(r.teardown())
    assert bad.closed and good.closed and r.connections == {}
    assert any("close error" in rec.getMessage() for rec in caplog.records)


def test_teardown_does_not_swallow_a_runner_bug() -> None:
    r = _runner()
    r.connection = _Conn(ZeroDivisionError())
    with pytest.raises(ZeroDivisionError):
        asyncio.run(r.teardown())


def test_pool_release_logs_close_error_and_forgets_the_connection(caplog: pytest.LogCaptureFixture) -> None:
    r = _runner()
    r.connections = {"a": _Conn(RuntimeError("x"))}
    with caplog.at_level(logging.DEBUG, logger=python_runner.logger.name):
        asyncio.run(r.pool_release("a"))
    assert r.connections == {}
    assert caplog.records


def test_unknown_connection_id_is_a_runner_error() -> None:
    with pytest.raises(python_runner.RunnerError, match="'nope' not found"):
        asyncio.run(_runner().run_query("RETURN 1", None, "nope"))
    with pytest.raises(python_runner.RunnerError, match="No active connection for c1"):
        asyncio.run(_runner().commit_transaction("c1"))


def _stub_query(r: Any, result: dict[str, Any]) -> None:
    async def run_query(*_a: Any, **_k: Any) -> dict[str, Any]:
        return result

    r.run_query = run_query


def test_column_mismatch_fails_the_test() -> None:
    r = _runner()
    _stub_query(r, {"rows": 1, "columns": ["a"], "data": [{"a": 1}]})
    out = asyncio.run(r._run_single_test({"query": "Q", "expect": {"columns": ["b"]}}))
    assert out["status"] == "failed" and "Expected columns" in out["error"]
    ok = asyncio.run(r._run_single_test({"query": "Q", "expect": {"columns": ["a"]}}))
    assert ok["status"] == "passed"


def test_step_row_mismatch_is_tolerated_only_with_expect_error() -> None:
    r = _runner()
    _stub_query(r, {"rows": 2, "columns": [], "data": []})
    step = {"type": "query", "text": "Q", "expect": {"rows": 1}}
    failed = asyncio.run(r._run_single_test({"steps": [step]}))
    assert failed["status"] == "failed" and "Expected 1 rows, got 2" in failed["error"]
    tolerated = asyncio.run(r._run_single_test({"steps": [{**step, "expect_error": True}]}))
    assert tolerated["status"] == "passed"


def test_step_error_with_expect_error_passes_and_otherwise_errors() -> None:
    r = _runner()

    async def boom(*_a: Any, **_k: Any) -> None:
        raise OSError("down")

    r.run_query = boom
    assert asyncio.run(r._run_single_test({"query": "Q"})) == {"status": "error", "error": "down"}
    out = asyncio.run(r._run_single_test({"query": "Q", "expect_error": True}))
    assert out == {"status": "passed", "error_expected": "down"}


class _Shell:
    def __init__(self, error: BaseException | None) -> None:
        self.error, self.terminated = error, False

    def sendline(self, _s: str) -> None:
        if self.error is not None:
            raise self.error

    def expect(self, *_a: Any, **_k: Any) -> None:
        return None

    def isalive(self) -> bool:
        return True

    def terminate(self, force: bool = False) -> None:
        self.terminated = force


def _shell_runner(shell: _Shell) -> Any:
    r = object.__new__(shell_runner.ShellTestRunner)
    r.shell_process = shell
    r.verbose = True
    logs: list[str] = []
    r.log = logs.append
    r.logs = logs
    return r


def test_stop_shell_logs_a_failed_quit_and_still_terminates() -> None:
    sh = _Shell(OSError("pty gone"))
    r = _shell_runner(sh)
    r.stop_shell()
    assert sh.terminated and r.shell_process is None
    assert any("did not quit cleanly" in m and "pty gone" in m for m in r.logs)


def test_stop_shell_does_not_swallow_a_runner_bug() -> None:
    sh = _Shell(ZeroDivisionError())
    r = _shell_runner(sh)
    with pytest.raises(ZeroDivisionError):
        r.stop_shell()
    assert sh.terminated  # the finally block still cleans up
