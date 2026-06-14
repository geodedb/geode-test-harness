"""Unit tests for cluster env injection (Task B1 of 2026-05-25 distributed plan).

Verifies that _build_node_env correctly injects GEODE_CLUSTER_PORT,
auto-generates GEODE_CLUSTER_TOKEN when not supplied, sets
GEODE_CLUSTER_INSECURE for loopback tests, and uses cluster ports
(not client ports) in GEODE_PEERS.
"""

from __future__ import annotations


def test_build_node_env_injects_cluster_port() -> None:
    from geodetestlab.lib.cluster import _build_node_env
    from geodetestlab.lib.cluster_types import ClusterConfig

    cfg = ClusterConfig(node_count=3, shared_env={"GEODE_CLUSTER_TOKEN": "tok-fixed"})
    env = _build_node_env(
        cfg,
        node_id=0,
        base_env={},
        port=3141,
        grpc_port=None,
        data_dir="/tmp/x",
        all_ports=[3141, 3142, 3143],
    )
    # cluster_port = client_port + 1000 by convention
    assert env["GEODE_CLUSTER_PORT"] == "4141"
    # Token preserved from shared_env
    assert env["GEODE_CLUSTER_TOKEN"] == "tok-fixed"
    # GEODE_PEERS must use CLUSTER ports (4141, 4142, 4143) and include
    # ALL nodes (self + peers) so geode's cluster_bootstrap can derive
    # consistent peer IDs from position in the list. Self is skipped by
    # the bootstrap when it sees an entry matching its own cluster_port.
    assert env["GEODE_PEERS"] == "127.0.0.1:4141,127.0.0.1:4142,127.0.0.1:4143"


def test_build_node_env_auto_generates_token() -> None:
    from geodetestlab.lib.cluster import _build_node_env
    from geodetestlab.lib.cluster_types import ClusterConfig

    cfg = ClusterConfig(node_count=2)  # no shared_env -> auto-token path
    env = _build_node_env(
        cfg,
        node_id=0,
        base_env={},
        port=3141,
        grpc_port=None,
        data_dir="/tmp/x",
        all_ports=[3141, 3142],
    )
    assert "GEODE_CLUSTER_TOKEN" in env
    # secrets.token_hex(16) yields a 32-char hex string
    assert len(env["GEODE_CLUSTER_TOKEN"]) == 32


def test_build_node_env_does_not_force_insecure_tls() -> None:
    from geodetestlab.lib.cluster import _build_node_env
    from geodetestlab.lib.cluster_types import ClusterConfig

    cfg = ClusterConfig(node_count=2)
    env = _build_node_env(
        cfg,
        node_id=0,
        base_env={},
        port=3141,
        grpc_port=None,
        data_dir="/tmp/x",
        all_ports=[3141, 3142],
    )
    # _build_node_env must NOT force GEODE_CLUSTER_INSECURE=1: geode refuses
    # that flag in release builds (cluster_auth.zig, GAP-0737), which silently
    # broke forced clusters on the shipping binary. Verified TLS is configured
    # by start_cluster() instead (shared CA + leaf). See
    # test_cluster_tls_provisioning.py.
    assert "GEODE_CLUSTER_INSECURE" not in env


def test_build_node_env_respects_explicit_insecure_override() -> None:
    from geodetestlab.lib.cluster import _build_node_env
    from geodetestlab.lib.cluster_types import ClusterConfig

    cfg = ClusterConfig(
        node_count=2,
        shared_env={"GEODE_CLUSTER_INSECURE": "0"},
    )
    env = _build_node_env(
        cfg,
        node_id=0,
        base_env={},
        port=3141,
        grpc_port=None,
        data_dir="/tmp/x",
        all_ports=[3141, 3142],
    )
    assert env["GEODE_CLUSTER_INSECURE"] == "0"


def test_build_node_env_remaps_node_id_to_one_indexed() -> None:
    """Geode raft rejects node_id=0 (InvalidId), so harness remaps to 1-indexed.

    cluster.py counters are 0-indexed for cluster_state.nodes lookups; the
    geode-side GEODE_NODE_ID env var is 1-indexed. The geode-side subprocess
    smoke test (tests/test_cluster_3node_subprocess.zig) uses the same
    1-indexed convention so this remap is the single source of truth.
    """
    from geodetestlab.lib.cluster import _build_node_env
    from geodetestlab.lib.cluster_types import ClusterConfig

    cfg = ClusterConfig(node_count=3)
    for i in range(3):
        env = _build_node_env(
            cfg,
            node_id=i,
            base_env={},
            port=3141 + i,
            grpc_port=None,
            data_dir=f"/tmp/n{i}",
            all_ports=[3141, 3142, 3143],
        )
        assert env["GEODE_NODE_ID"] == str(i + 1)
