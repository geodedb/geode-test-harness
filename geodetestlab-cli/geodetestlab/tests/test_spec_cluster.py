"""Tests for cluster spec parsing."""

from __future__ import annotations

import tempfile
import textwrap
from pathlib import Path


def _write_spec(content: str) -> Path:
    """Write YAML content to a temp file and return the path."""
    with tempfile.NamedTemporaryFile(suffix=".yml", mode="w", delete=False) as f:
        f.write(textwrap.dedent(content))
    return Path(f.name)


class TestClusterSpecParsing:
    def test_no_cluster_returns_none(self) -> None:
        from geodetestlab.lib.spec import load_spec

        path = _write_spec("""
            name: basic test
            tests:
              - name: test1
                query: RETURN 1
        """)
        spec = load_spec(path)
        assert spec.cluster_config is None
        assert spec.mode == "server"

    def test_cluster_block_parsed(self) -> None:
        from geodetestlab.lib.spec import load_spec

        path = _write_spec("""
            name: cluster test
            cluster:
              nodes: 3
              target_node: round-robin
              shared_env:
                GEODE_CLUSTER_TOKEN: test-secret
              shared_args:
                - --log-level
                - info
            tests:
              - name: test1
                query: RETURN 1
        """)
        spec = load_spec(path)
        assert spec.cluster_config is not None
        assert spec.cluster_config.node_count == 3
        assert spec.cluster_config.target_node == "round-robin"
        assert spec.cluster_config.shared_env["GEODE_CLUSTER_TOKEN"] == "test-secret"
        assert spec.mode == "cluster"

    def test_cluster_with_node_overrides(self) -> None:
        from geodetestlab.lib.spec import load_spec

        path = _write_spec("""
            name: cluster override test
            cluster:
              nodes: 2
              node_overrides:
                - args: [--log-level, debug]
                  env:
                    EXTRA: val
                - {}
            tests:
              - name: test1
                query: RETURN 1
        """)
        spec = load_spec(path)
        assert spec.cluster_config is not None
        assert len(spec.cluster_config.node_overrides) == 2
        assert spec.cluster_config.node_overrides[0].args == ["--log-level", "debug"]

    def test_cluster_mode_set_automatically(self) -> None:
        from geodetestlab.lib.spec import load_spec

        path = _write_spec("""
            name: auto-cluster
            cluster:
              nodes: 2
            tests:
              - name: test1
                query: RETURN 1
        """)
        spec = load_spec(path)
        assert spec.mode == "cluster"

    def test_cluster_with_cli_server_block(self) -> None:
        from geodetestlab.lib.spec import load_spec

        path = _write_spec("""
            name: cluster with cli
            cli:
              server:
                enabled: true
                args: [--log-level, warn]
            cluster:
              nodes: 3
            tests:
              - name: test1
                query: RETURN 1
        """)
        spec = load_spec(path)
        assert spec.mode == "cluster"
        assert spec.cluster_config is not None
        assert spec.server_args == ["--log-level", "warn"]

    def test_cluster_overrides_mode_server(self) -> None:
        from geodetestlab.lib.spec import load_spec

        path = _write_spec("""
            name: cluster mode test
            cluster:
              nodes: 2
            mode: server
            tests:
              - name: test1
                query: RETURN 1
        """)
        spec = load_spec(path)
        assert spec.mode == "cluster"
