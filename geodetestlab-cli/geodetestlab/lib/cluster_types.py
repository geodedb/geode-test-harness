"""Data types for multi-node cluster test configurations."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field

_MIN_CLUSTER_NODES = 2
_MAX_CLUSTER_NODES = 10


@dataclass
class ClusterNodeConfig:
    """Per-node configuration overrides."""

    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    port: int | None = None
    grpc_port: int | None = None

    @classmethod
    def from_dict(cls, data: dict) -> ClusterNodeConfig:
        return cls(
            args=data.get("args", []),
            env=data.get("env", {}),
            port=data.get("port"),
            grpc_port=data.get("grpc_port"),
        )


@dataclass
class ClusterConfig:
    """Configuration for a multi-node Geode cluster."""

    node_count: int = 3
    target_node: str = "leader"  # "leader", "round-robin", "all", or "0"-"9"
    shared_env: dict[str, str] = field(default_factory=dict)
    shared_args: list[str] = field(default_factory=list)
    node_overrides: list[ClusterNodeConfig] = field(default_factory=list)
    startup_timeout_ms: int = 90000
    health_check_interval_ms: int = 5000

    @classmethod
    def from_dict(cls, data: dict) -> ClusterConfig:
        raw_count = data.get("nodes", 3)
        node_count = max(_MIN_CLUSTER_NODES, min(_MAX_CLUSTER_NODES, raw_count))

        node_overrides = [ClusterNodeConfig.from_dict(n) for n in data.get("node_overrides", [])]

        return cls(
            node_count=node_count,
            target_node=data.get("target_node", "leader"),
            shared_env=data.get("shared_env", {}),
            shared_args=data.get("shared_args", []),
            node_overrides=node_overrides,
            startup_timeout_ms=data.get("startup_timeout_ms", 90000),
            health_check_interval_ms=data.get("health_check_interval_ms", 5000),
        )

    @classmethod
    def from_size(cls, size: int) -> ClusterConfig:
        """Create a default cluster config with the given number of nodes."""
        return cls.from_dict({"nodes": size})


@dataclass
class ClusterNodeState:
    """Runtime state of a single node in a cluster."""

    node_id: int
    port: int
    grpc_port: int | None
    data_dir: str
    process: subprocess.Popen[str] | None

    @property
    def address(self) -> str:
        return f"127.0.0.1:{self.port}"

    @property
    def grpc_address(self) -> str | None:
        if self.grpc_port is None:
            return None
        return f"127.0.0.1:{self.grpc_port}"


@dataclass
class ClusterState:
    """Runtime state of a multi-node cluster."""

    nodes: list[ClusterNodeState] = field(default_factory=list)
    _round_robin_index: int = 0

    @property
    def leader_node(self) -> ClusterNodeState:
        """Node 0 is always treated as the leader."""
        return self.nodes[0]

    def get_target_node(self, target: str) -> ClusterNodeState:
        """Get the target node based on the target strategy."""
        if target == "leader":
            return self.leader_node
        if target == "round-robin":
            return self.next_round_robin_node()
        # Numeric index
        idx = int(target)
        return self.nodes[idx]

    def next_round_robin_node(self) -> ClusterNodeState:
        """Get next node in round-robin order."""
        node = self.nodes[self._round_robin_index % len(self.nodes)]
        self._round_robin_index += 1
        return node
