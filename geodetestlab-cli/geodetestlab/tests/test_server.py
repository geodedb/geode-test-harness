"""Tests for server.py lifecycle management.

Covers QG-005: Unit tests for server module.
"""

from __future__ import annotations

import socket

from geodetestlab.lib.server import _port_is_bound, kill_stale_servers, untrack_server


class TestPortIsBound:
    def test_free_port_returns_false(self) -> None:
        """A free port should return False (not bound)."""
        # Bind to a port, get its number, then release it
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
        # Port is now free
        assert not _port_is_bound(port, socket.SOCK_DGRAM)

    def test_bound_port_returns_true(self) -> None:
        """A bound port should return True."""
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
            # Port is still bound
            assert _port_is_bound(port, socket.SOCK_DGRAM)

    def test_tcp_port(self) -> None:
        """TCP ports should also work."""
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
            s.listen(1)
            port = s.getsockname()[1]
            assert _port_is_bound(port, socket.SOCK_STREAM)


class TestKillStaleServers:
    def test_does_not_raise(self) -> None:
        """kill_stale_servers should not raise even with no matching processes."""
        kill_stale_servers()  # Should complete without error


class TestUntrackServer:
    def test_untrack_nonexistent(self) -> None:
        """Untracking a process not in the list should not raise."""
        from unittest.mock import MagicMock

        fake_process = MagicMock()
        untrack_server(fake_process)  # Should not raise
