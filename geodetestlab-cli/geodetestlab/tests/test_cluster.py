"""Tests for cluster.py lifecycle management."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from geodetestlab.lib.cluster_types import ClusterConfig, ClusterNodeConfig, ClusterNodeState, ClusterState


class TestBuildNodeEnv:
    def test_shared_env_applied(self) -> None:
        from geodetestlab.lib.cluster import _build_node_env

        config = ClusterConfig.from_dict(
            {
                "nodes": 2,
                "shared_env": {"GEODE_CLUSTER_TOKEN": "secret123"},
            }
        )
        base_env = {"PATH": "/usr/bin"}
        env = _build_node_env(config, node_id=0, base_env=base_env, port=3141, grpc_port=None, data_dir="/tmp/n0")
        assert env["GEODE_CLUSTER_TOKEN"] == "secret123"
        assert env["PATH"] == "/usr/bin"
        assert env["GEODE_SERVER_ADDRESS"] == "127.0.0.1:3141"
        assert env["PORT"] == "3141"

    def test_node_override_env(self) -> None:
        from geodetestlab.lib.cluster import _build_node_env

        config = ClusterConfig(
            node_count=2,
            shared_env={"KEY": "shared"},
            node_overrides=[ClusterNodeConfig(env={"KEY": "override0"}), ClusterNodeConfig()],
        )
        env = _build_node_env(config, node_id=0, base_env={}, port=3141, grpc_port=None, data_dir="/tmp/n0")
        assert env["KEY"] == "override0"

    def test_grpc_port_set(self) -> None:
        from geodetestlab.lib.cluster import _build_node_env

        config = ClusterConfig.from_size(2)
        env = _build_node_env(config, node_id=0, base_env={}, port=3141, grpc_port=50051, data_dir="/tmp/n0")
        assert env["GEODE_GRPC_ADDRESS"] == "127.0.0.1:50051"

    def test_node_id_is_one_based(self) -> None:
        # Geode + the bundled raft library reserve node id 0 as the invalid
        # sentinel (zig-pkg/raft-*/src/node.zig: `if (self.id == 0) return
        # ConfigError.InvalidId`). Geode's own ground-truth 3-node test
        # (geode/tests/test_cluster_3node_subprocess.zig) spawns nodes with
        # GEODE_NODE_ID = i + 1. So the harness must inject 1-based ids;
        # a 0-based id makes node 0 exit on startup with InvalidNodeId.
        from geodetestlab.lib.cluster import _build_node_env

        config = ClusterConfig.from_size(3)
        env0 = _build_node_env(config, node_id=0, base_env={}, port=3141, grpc_port=None, data_dir="/tmp/n0")
        env2 = _build_node_env(config, node_id=2, base_env={}, port=3143, grpc_port=None, data_dir="/tmp/n2")
        assert env0["GEODE_NODE_ID"] == "1"
        assert env2["GEODE_NODE_ID"] == "3"

    def test_peer_addresses_injected(self) -> None:
        from geodetestlab.lib.cluster import _build_node_env

        config = ClusterConfig.from_size(3)
        env = _build_node_env(
            config,
            node_id=0,
            base_env={},
            port=3141,
            grpc_port=None,
            data_dir="/tmp/n0",
            all_ports=[3141, 3142, 3143],
        )
        assert "3142" in env.get("GEODE_PEERS", "")
        assert "3143" in env.get("GEODE_PEERS", "")
        assert "3141" not in env.get("GEODE_PEERS", "")


class TestBuildNodeArgs:
    def test_shared_args_applied(self) -> None:
        from geodetestlab.lib.cluster import _build_node_args

        config = ClusterConfig(node_count=2, shared_args=["--log-level", "debug"])
        args = _build_node_args(config, node_id=0, spec_server_args=[])
        assert "--log-level" in args
        assert "debug" in args

    def test_node_override_args(self) -> None:
        from geodetestlab.lib.cluster import _build_node_args

        config = ClusterConfig(
            node_count=2,
            shared_args=["--log-level", "info"],
            node_overrides=[ClusterNodeConfig(args=["--log-level", "debug"]), ClusterNodeConfig()],
        )
        args = _build_node_args(config, node_id=0, spec_server_args=[])
        assert args == ["--log-level", "debug"]

    def test_spec_args_included(self) -> None:
        from geodetestlab.lib.cluster import _build_node_args

        config = ClusterConfig.from_size(2)
        args = _build_node_args(config, node_id=0, spec_server_args=["--persist-interval", "50"])
        assert "--persist-interval" in args
        assert "50" in args


class TestStopCluster:
    def test_stops_all_nodes(self) -> None:
        from geodetestlab.lib.cluster import stop_cluster

        mock_procs = [MagicMock(), MagicMock()]
        nodes = [
            ClusterNodeState(node_id=0, port=3141, grpc_port=None, data_dir="/tmp/n0", process=mock_procs[0]),
            ClusterNodeState(node_id=1, port=3142, grpc_port=None, data_dir="/tmp/n1", process=mock_procs[1]),
        ]
        cluster_state = ClusterState(nodes=nodes)

        with patch("geodetestlab.lib.cluster.stop_server") as mock_stop:
            stop_cluster(cluster_state, verbose=False)
            assert mock_stop.call_count == 2

    def test_handles_none_process(self) -> None:
        from geodetestlab.lib.cluster import stop_cluster

        nodes = [
            ClusterNodeState(node_id=0, port=3141, grpc_port=None, data_dir="/tmp/n0", process=None),
        ]
        cluster_state = ClusterState(nodes=nodes)

        with patch("geodetestlab.lib.cluster.stop_server") as mock_stop:
            stop_cluster(cluster_state, verbose=False)
            mock_stop.assert_not_called()


class TestClusterHealthCheck:
    def test_all_alive(self) -> None:
        from geodetestlab.lib.cluster import check_cluster_health

        mock_proc = MagicMock()
        mock_proc.poll.return_value = None
        nodes = [
            ClusterNodeState(node_id=0, port=3141, grpc_port=None, data_dir="/tmp/n0", process=mock_proc),
            ClusterNodeState(node_id=1, port=3142, grpc_port=None, data_dir="/tmp/n1", process=mock_proc),
        ]
        cluster_state = ClusterState(nodes=nodes)
        alive, dead = check_cluster_health(cluster_state)
        assert len(alive) == 2
        assert len(dead) == 0

    def test_one_dead(self) -> None:
        from geodetestlab.lib.cluster import check_cluster_health

        alive_proc = MagicMock()
        alive_proc.poll.return_value = None
        dead_proc = MagicMock()
        dead_proc.poll.return_value = 1
        nodes = [
            ClusterNodeState(node_id=0, port=3141, grpc_port=None, data_dir="/tmp/n0", process=alive_proc),
            ClusterNodeState(node_id=1, port=3142, grpc_port=None, data_dir="/tmp/n1", process=dead_proc),
        ]
        cluster_state = ClusterState(nodes=nodes)
        alive, dead = check_cluster_health(cluster_state)
        assert len(alive) == 1
        assert len(dead) == 1
        assert dead[0].node_id == 1
