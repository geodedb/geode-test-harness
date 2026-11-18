"""Which CLI subcommands the executor points at the managed server / data dir.

`geode migrate status|create|sign` and `geode auth validate|logout` reject the
--server / --data-dir options the executor used to append to them.
"""

from __future__ import annotations

import pytest

from geodetestlab.lib.executor import _accepts_data_dir, _is_remote_admin_command


@pytest.mark.parametrize(
    ("args", "remote"),
    [
        (["migrate", "run"], True),
        (["migrate", "up"], True),
        (["migrate", "status"], False),
        (["migrate", "create", "add_user"], False),
        (["migrate", "sign"], False),
        (["migrate"], False),
        (["restore", "x"], True),
        (["backup", "create"], True),
        (["backup", "list"], False),
        (["user", "create"], False),
        ([], False),
    ],
)
def test_remote_admin_command(args: list[str], remote: bool) -> None:
    assert _is_remote_admin_command(args) is remote


@pytest.mark.parametrize(
    ("args", "ok"),
    [
        (["auth", "validate"], False),
        (["auth", "logout"], False),
        (["auth", "login"], True),
        (["user", "create", "x"], True),
        (["role", "create", "r"], True),
    ],
)
def test_accepts_data_dir(args: list[str], ok: bool) -> None:
    assert _accepts_data_dir(args) is ok


def test_sequential_bash_step_sees_the_admin_password() -> None:
    """Cluster runs leave GEODE_ADMIN_PASSWORD out of the shared env; a bash step's
    client calls still need it (they failed with 'Authentication required')."""
    from geodetestlab.lib.executor import _run_sequential_test
    from geodetestlab.lib.runner_types import DEFAULT_ADMIN_PASSWORD
    from geodetestlab.lib.spec import TestCase

    tc = TestCase.from_dict(
        {
            "name": "bash-pw",
            "type": "sequential",
            "steps": [{"type": "bash", "command": 'printf "%s" "$GEODE_ADMIN_PASSWORD"'}],
        }
    )
    result = _run_sequential_test(
        test_case=tc,
        binary="/usr/bin/geode",
        env={"GEODE_SERVER_ADDRESS": "127.0.0.1:3141"},
        secrets={},
        timeout_ms=5000,
        data_dir=None,
        verbose=False,
    )
    assert result.passed, result.error
    assert DEFAULT_ADMIN_PASSWORD in result.output
