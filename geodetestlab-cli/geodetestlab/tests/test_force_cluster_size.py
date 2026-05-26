"""Unit tests for the --force-cluster-size CLI flag (Task B3).

Verifies that _apply_force_cluster_size:
  - is a no-op when size <= 1
  - synthesizes a ClusterConfig and switches mode to "cluster" when size > 1
    on a spec without a cluster: block
  - respects an existing cluster: block (spec wins over CLI)
  - respects the single_node_only opt-out flag
"""

from __future__ import annotations

import tempfile
import textwrap
from pathlib import Path


def _write_spec(content: str) -> Path:
    """Write YAML content to a temp file and return the path."""
    with tempfile.NamedTemporaryFile(suffix=".yml", mode="w", delete=False) as f:
        f.write(textwrap.dedent(content))
    return Path(f.name)


def test_force_cluster_size_1_is_noop() -> None:
    from geodetestlab.lib.runner import _apply_force_cluster_size
    from geodetestlab.lib.spec import load_spec

    spec_path = _write_spec("""
        name: test
        tests:
          - name: t1
            args: [query, '-']
            stdin: "RETURN 1"
            expect:
              exit_code: 0
    """)
    spec = load_spec(spec_path)
    assert spec.cluster_config is None
    assert spec.mode == "server"

    _apply_force_cluster_size(spec, 1)
    assert spec.cluster_config is None
    assert spec.mode == "server"


def test_force_cluster_size_promotes_spec_without_cluster_block() -> None:
    from geodetestlab.lib.runner import _apply_force_cluster_size
    from geodetestlab.lib.spec import load_spec

    spec_path = _write_spec("""
        name: test
        tests:
          - name: t1
            args: [query, '-']
            stdin: "RETURN 1"
            expect:
              exit_code: 0
    """)
    spec = load_spec(spec_path)

    _apply_force_cluster_size(spec, 3)
    assert spec.cluster_config is not None
    assert spec.cluster_config.node_count == 3
    assert spec.mode == "cluster"


def test_force_cluster_size_respects_existing_cluster_block() -> None:
    """A spec that already declares its own cluster: block wins over the flag."""
    from geodetestlab.lib.runner import _apply_force_cluster_size
    from geodetestlab.lib.spec import load_spec

    spec_path = _write_spec("""
        name: test
        cluster:
          nodes: 2
        tests:
          - name: t1
            query: "RETURN 1"
    """)
    spec = load_spec(spec_path)
    assert spec.cluster_config is not None
    assert spec.cluster_config.node_count == 2

    # CLI flag asks for 5; spec block already declared 2 → spec wins
    _apply_force_cluster_size(spec, 5)
    assert spec.cluster_config.node_count == 2


def test_force_cluster_size_respects_single_node_only_optout() -> None:
    """Specs with single_node_only: true skip promotion."""
    from geodetestlab.lib.runner import _apply_force_cluster_size
    from geodetestlab.lib.spec import load_spec

    spec_path = _write_spec("""
        name: test
        single_node_only: true
        tests:
          - name: t1
            query: "RETURN 1"
    """)
    spec = load_spec(spec_path)
    assert spec.single_node_only is True

    _apply_force_cluster_size(spec, 3)
    # Promotion suppressed
    assert spec.cluster_config is None
    assert spec.mode == "server"


def test_force_cluster_size_idempotent() -> None:
    """Calling the helper twice does not double-promote."""
    from geodetestlab.lib.runner import _apply_force_cluster_size
    from geodetestlab.lib.spec import load_spec

    spec_path = _write_spec("""
        name: test
        tests:
          - name: t1
            query: "RETURN 1"
    """)
    spec = load_spec(spec_path)
    _apply_force_cluster_size(spec, 5)
    assert spec.cluster_config is not None
    assert spec.cluster_config.node_count == 5

    _apply_force_cluster_size(spec, 10)
    # Already promoted; second call is no-op (spec already has cluster_config)
    assert spec.cluster_config.node_count == 5


def test_force_cluster_size_sizes_3_5_10() -> None:
    """The matrix the user asked for: 1, 3, 5, 10 nodes."""
    from geodetestlab.lib.runner import _apply_force_cluster_size
    from geodetestlab.lib.spec import load_spec

    for size in (3, 5, 10):
        spec_path = _write_spec("""
            name: test
            tests:
              - name: t1
                query: "RETURN 1"
        """)
        spec = load_spec(spec_path)
        _apply_force_cluster_size(spec, size)
        assert spec.cluster_config is not None
        assert spec.cluster_config.node_count == size, f"size={size}"
        assert spec.mode == "cluster"
