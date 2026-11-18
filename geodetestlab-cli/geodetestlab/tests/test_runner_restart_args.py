"""SONNY-6722: a restarted managed server must keep its TLS args.

The runner provisions a CA and a leaf certificate for a managed server and
starts it with ``--cert/--key`` (the client verifies against that CA). A
``restart_server: true`` test used to restart it with only the spec's own
args: the server then minted a fresh self-signed certificate the client's CA
does not verify, and every query after the restart hung in the TLS handshake
until the harness timed out.
"""

from __future__ import annotations

import ast
import stat
import subprocess
import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import patch

from geodetestlab.lib import runner as runner_mod
from geodetestlab.lib.runner import ServerState, _restart_args, run_tests


def _spec(args: list[str]) -> Any:
    from geodetestlab.lib.spec import TestCase, TestSpec

    spec = TestSpec(
        name="restart-args",
        description="",
        mode="server",
        tests=[
            TestCase.from_dict({"name": "before", "query": "RETURN 1 AS x", "restart_server": True}),
            TestCase.from_dict({"name": "after", "query": "RETURN 2 AS x"}),
        ],
    )
    spec.server_args = args
    return spec


def test_restart_args_prefers_the_args_the_server_started_with() -> None:
    spec = _spec(["--log-level", "warn"])
    started = ServerState(
        process=None, port=1, grpc_port=None, server_args=["--log-level", "warn", "--cert", "c", "--key", "k"]
    )
    assert _restart_args(started, spec) == ["--log-level", "warn", "--cert", "c", "--key", "k"]
    assert _restart_args(ServerState(process=None, port=1, grpc_port=None), spec) == ["--log-level", "warn"]


def test_every_server_restart_passes_the_started_args() -> None:
    """No `_restart_server(...)` call may pass the bare spec args."""
    tree = ast.parse(Path(runner_mod.__file__).read_text())
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and getattr(n.func, "id", "") == "_restart_server"]
    assert calls, "no _restart_server call found"
    for call in calls:
        kw = {k.arg: k.value for k in call.keywords}
        assert "server_args" in kw
        arg = kw["server_args"]
        assert isinstance(arg, ast.Call), ast.dump(arg)
        assert isinstance(arg.func, ast.Name) and arg.func.id == "_restart_args", ast.dump(arg)


def test_restart_server_test_restarts_with_the_provisioned_cert_and_key() -> None:
    """run_tests: the server restarted after `restart_server: true` gets --cert/--key again."""
    with tempfile.TemporaryDirectory() as tmp:
        binary = Path(tmp) / "fake-geode.sh"
        binary.write_text(
            '#!/bin/sh\nif [ "$1" = "query" ]; then\n  echo \'{"status_class":"00000","rows":[{"x":1},{"x":2}]}\'\nfi\nexit 0\n'
        )
        binary.chmod(binary.stat().st_mode | stat.S_IXUSR)
        starts: list[list[str]] = []

        def fake_start(**kwargs: Any) -> subprocess.Popen[str]:
            starts.append(list(kwargs["args"]))
            return subprocess.Popen(["sleep", "30"], text=True)

        certs = (tmp, "/ca.crt", "/leaf.crt", "/leaf.key")
        with (
            patch("geodetestlab.lib.runner.provision_tls_certs", return_value=certs),
            patch("geodetestlab.lib.runner.start_server", side_effect=fake_start),
            patch("geodetestlab.lib.runner.stop_server"),
        ):
            run_tests(
                spec=_spec(["--log-level", "warn"]),
                secrets={},
                env_overrides={},
                geode_binary=str(binary),
                verbose=False,
            )
        assert len(starts) >= 2, f"the server was not restarted: {starts}"
        for args in starts:
            assert "--cert" in args and "/leaf.crt" in args, args
            assert "--key" in args and "/leaf.key" in args, args
