"""Tests for cluster_types.py data classes."""

from __future__ import annotations


class TestClusterNodeConfig:
    def test_from_dict_defaults(self) -> None:
        from geodetestlab.lib.cluster_types import ClusterNodeConfig

        node = ClusterNodeConfig.from_dict({})
        assert node.args == []
        assert node.env == {}
        assert node.port is None
        assert node.grpc_port is None

    def test_from_dict_with_overrides(self) -> None:
        from geodetestlab.lib.cluster_types import ClusterNodeConfig

        node = ClusterNodeConfig.from_dict(
            {
                "args": ["--log-level", "debug"],
                "env": {"CUSTOM": "val"},
                "port": 4000,
                "grpc_port": 50060,
            }
        )
        assert node.args == ["--log-level", "debug"]
        assert node.env == {"CUSTOM": "val"}
        assert node.port == 4000
        assert node.grpc_port == 50060


class TestClusterConfig:
    def test_from_dict_minimal(self) -> None:
        from geodetestlab.lib.cluster_types import ClusterConfig

        config = ClusterConfig.from_dict({"nodes": 3})
        assert config.node_count == 3
        assert config.target_node == "leader"
        assert config.shared_env == {}
        assert config.node_overrides == []
        assert config.startup_timeout_ms == 90000
        assert config.health_check_interval_ms == 5000

    def test_from_dict_full(self) -> None:
        from geodetestlab.lib.cluster_types import ClusterConfig

        config = ClusterConfig.from_dict(
            {
                "nodes": 5,
                "target_node": "round-robin",
                "shared_env": {"GEODE_CLUSTER_TOKEN": "secret"},
                "node_overrides": [
                    {"args": ["--log-level", "debug"]},
                    {},
                ],
                "startup_timeout_ms": 120000,
                "health_check_interval_ms": 2000,
                "shared_args": ["--log-level", "info"],
            }
        )
        assert config.node_count == 5
        assert config.target_node == "round-robin"
        assert config.shared_env == {"GEODE_CLUSTER_TOKEN": "secret"}
        assert len(config.node_overrides) == 2
        assert config.startup_timeout_ms == 120000
        assert config.shared_args == ["--log-level", "info"]

    def test_node_count_bounds(self) -> None:
        from geodetestlab.lib.cluster_types import ClusterConfig

        config_low = ClusterConfig.from_dict({"nodes": 1})
        assert config_low.node_count == 2  # Minimum is 2

        config_high = ClusterConfig.from_dict({"nodes": 15})
        assert config_high.node_count == 10  # Maximum is 10

    def test_from_size_creates_default(self) -> None:
        from geodetestlab.lib.cluster_types import ClusterConfig

        config = ClusterConfig.from_size(4)
        assert config.node_count == 4
        assert config.target_node == "leader"
        assert config.shared_env == {}


class TestClusterNodeState:
    def test_address_property(self) -> None:
        from geodetestlab.lib.cluster_types import ClusterNodeState

        state = ClusterNodeState(
            node_id=0,
            port=3141,
            grpc_port=50051,
            data_dir="/tmp/node0",
            process=None,
        )
        assert state.address == "127.0.0.1:3141"

    def test_grpc_address_property(self) -> None:
        from geodetestlab.lib.cluster_types import ClusterNodeState

        state = ClusterNodeState(
            node_id=0,
            port=3141,
            grpc_port=50051,
            data_dir="/tmp/node0",
            process=None,
        )
        assert state.grpc_address == "127.0.0.1:50051"

    def test_grpc_address_none(self) -> None:
        from geodetestlab.lib.cluster_types import ClusterNodeState

        state = ClusterNodeState(
            node_id=0,
            port=3141,
            grpc_port=None,
            data_dir="/tmp/node0",
            process=None,
        )
        assert state.grpc_address is None


class TestClusterState:
    def test_leader_node(self) -> None:
        from geodetestlab.lib.cluster_types import ClusterNodeState, ClusterState

        nodes = [
            ClusterNodeState(node_id=0, port=3141, grpc_port=None, data_dir="/tmp/0", process=None),
            ClusterNodeState(node_id=1, port=3142, grpc_port=None, data_dir="/tmp/1", process=None),
        ]
        state = ClusterState(nodes=nodes)
        assert state.leader_node is nodes[0]

    def test_target_node_by_index(self) -> None:
        from geodetestlab.lib.cluster_types import ClusterNodeState, ClusterState

        nodes = [
            ClusterNodeState(node_id=0, port=3141, grpc_port=None, data_dir="/tmp/0", process=None),
            ClusterNodeState(node_id=1, port=3142, grpc_port=None, data_dir="/tmp/1", process=None),
        ]
        state = ClusterState(nodes=nodes)
        assert state.get_target_node("1") is nodes[1]

    def test_target_node_leader(self) -> None:
        from geodetestlab.lib.cluster_types import ClusterNodeState, ClusterState

        nodes = [
            ClusterNodeState(node_id=0, port=3141, grpc_port=None, data_dir="/tmp/0", process=None),
            ClusterNodeState(node_id=1, port=3142, grpc_port=None, data_dir="/tmp/1", process=None),
        ]
        state = ClusterState(nodes=nodes)
        assert state.get_target_node("leader") is nodes[0]

    def test_round_robin(self) -> None:
        from geodetestlab.lib.cluster_types import ClusterNodeState, ClusterState

        nodes = [
            ClusterNodeState(node_id=0, port=3141, grpc_port=None, data_dir="/tmp/0", process=None),
            ClusterNodeState(node_id=1, port=3142, grpc_port=None, data_dir="/tmp/1", process=None),
            ClusterNodeState(node_id=2, port=3143, grpc_port=None, data_dir="/tmp/2", process=None),
        ]
        state = ClusterState(nodes=nodes)
        assert state.next_round_robin_node() is nodes[0]
        assert state.next_round_robin_node() is nodes[1]
        assert state.next_round_robin_node() is nodes[2]
        assert state.next_round_robin_node() is nodes[0]  # wraps
