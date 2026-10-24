"""Tests for the ``run --shard K/N`` spec selector."""

from pathlib import Path

import pytest

from geodetestlab.cli import parse_shard, select_shard


def test_parse_shard_valid() -> None:
    assert parse_shard("1/3") == (1, 3)
    assert parse_shard("3/3") == (3, 3)
    assert parse_shard("1/1") == (1, 1)


@pytest.mark.parametrize("value", ["0/3", "4/3", "1/0", "a/b", "1", "1/2/3", ""])
def test_parse_shard_invalid(value: str) -> None:
    with pytest.raises(ValueError):
        parse_shard(value)


def test_shards_partition_every_spec_once() -> None:
    files = [Path(f"spec_{i:03d}.yml") for i in range(394)]
    shards = [select_shard(files, k, 3) for k in (1, 2, 3)]
    combined = [f for s in shards for f in s]
    assert sorted(combined) == files
    assert len(set(combined)) == len(files)
    assert max(len(s) for s in shards) - min(len(s) for s in shards) <= 1


def test_shard_cli_rejects_bad_selector(tmp_path: Path) -> None:
    from typer.testing import CliRunner

    from geodetestlab.cli import app

    (tmp_path / "a.yml").write_text("version: '1.0'\n")
    result = CliRunner().invoke(app, ["run", "--specs", str(tmp_path), "--shard", "5/3", "--dry-run"])
    assert result.exit_code == 2
