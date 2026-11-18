"""Process-group signalling must never reach a group the harness does not own.

A unit test faked a server with ``process=MagicMock()``. ``MagicMock().pid``
indexes as the integer 1, so ``os.getpgid(process.pid)`` returned 1 and
``_safe_killpg(1, SIGTERM)`` signalled process group 1. On a systemd host the
user manager (``systemd --user``) sits in that group, so running the harness's
own unit suite SIGTERMed the user manager and tore down the whole login
session: tmux, every shell and every process running in it.

The harness spawns servers with ``start_new_session=True``, so a server it may
signal by group always LEADS its group (pgid == pid). Anything else is refused.
"""

from __future__ import annotations

import os
import signal
import subprocess
from unittest.mock import MagicMock, patch

from geodetestlab.lib.server import _safe_killpg, signal_process_group


def _recording_killpg() -> tuple[list[tuple[int, int]], object]:
    calls: list[tuple[int, int]] = []

    def fake(pgid: int, sig: int) -> None:
        calls.append((pgid, sig))

    return calls, fake


def test_mock_process_pid_is_never_signalled() -> None:
    calls, fake = _recording_killpg()
    with patch("geodetestlab.lib.server.os.killpg", side_effect=fake):
        assert signal_process_group(MagicMock().pid, signal.SIGTERM) is False
    assert calls == []


def test_init_group_and_low_groups_are_refused() -> None:
    calls, fake = _recording_killpg()
    with patch("geodetestlab.lib.server.os.killpg", side_effect=fake):
        for pgid in (-1, 0, 1):
            _safe_killpg(pgid, signal.SIGTERM)
        assert signal_process_group(1, signal.SIGTERM) is False
        assert signal_process_group(0, signal.SIGTERM) is False
        assert signal_process_group(-1, signal.SIGTERM) is False
        assert signal_process_group(True, signal.SIGTERM) is False
    assert calls == []


def test_own_group_is_refused() -> None:
    calls, fake = _recording_killpg()
    with patch("geodetestlab.lib.server.os.killpg", side_effect=fake):
        _safe_killpg(os.getpgid(0), signal.SIGTERM)
        assert signal_process_group(os.getpid(), signal.SIGTERM) is False
    assert calls == []


def test_child_sharing_our_group_is_refused() -> None:
    """A child spawned WITHOUT a new session shares our group: never killpg it."""
    proc = subprocess.Popen(["sleep", "30"])
    try:
        calls, fake = _recording_killpg()
        with patch("geodetestlab.lib.server.os.killpg", side_effect=fake):
            assert signal_process_group(proc.pid, signal.SIGTERM) is False
        assert calls == []
    finally:
        proc.kill()
        proc.wait(timeout=5)


def test_group_leader_we_spawned_is_signalled() -> None:
    proc = subprocess.Popen(["sleep", "30"], start_new_session=True)
    try:
        assert signal_process_group(proc.pid, signal.SIGTERM) is True
        assert proc.wait(timeout=5) == -signal.SIGTERM
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=5)


def test_stop_server_with_mock_process_sends_no_group_signal() -> None:
    """The original crash: stop_server on a MagicMock process."""
    from geodetestlab.lib.server import stop_server

    calls, fake = _recording_killpg()
    with patch("geodetestlab.lib.server.os.killpg", side_effect=fake):
        stop_server(MagicMock(), verbose=False)
    assert calls == []


def test_orphan_cleanup_ignores_shells_that_mention_the_pattern() -> None:
    """A shell whose command text mentions `geode serve ... geode-test-` is not a server."""
    from geodetestlab.lib.server import _is_geode_test_server

    proc = subprocess.Popen(["sh", "-c", "sleep 30 # geode serve --data-dir /tmp/geode-test-x"])
    try:
        assert _is_geode_test_server(proc.pid) is False
    finally:
        proc.kill()
        proc.wait(timeout=5)
