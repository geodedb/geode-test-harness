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
