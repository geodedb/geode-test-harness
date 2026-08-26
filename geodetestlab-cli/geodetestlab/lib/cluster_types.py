"""Data types for multi-node cluster test configurations."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from typing import Any

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
    def from_dict(cls, data: dict[str, Any]) -> ClusterNodeConfig:
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
    # When True, start N INDEPENDENT standalone geode servers instead of a Raft
    # cluster: no GEODE_CLUSTER_TOKEN / GEODE_PEERS, and readiness is per-node
    # (each client port answers) rather than leader election. Used by specs whose
    # contract is "independent servers" (e.g. node-signal survivability), which
    # must not depend on inter-node Raft TLS (the blocked GAP-0838 handshake).
    independent: bool = False

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ClusterConfig:
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
            independent=bool(data.get("independent", False)),
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
    # Temp directory holding the shared CA + leaf provisioned by start_cluster()
    # for verified inter-node TLS. None when a spec supplied its own certs or
    # opted into the debug-only insecure path. stop_cluster() removes it.
    cert_dir: str | None = None
    _round_robin_index: int = 0

    def node_by_target(self, target: str) -> ClusterNodeState:
        """Resolve a ``node:N`` target string to its ClusterNodeState.

        Accepts both ``"node:0"`` and a bare ``"0"``.  Raises ``ValueError``
        for malformed or out-of-range targets so callers can surface a
        clear failure rather than an IndexError.
        """
        raw = target.split(":", 1)[1] if target.startswith("node:") else target
        try:
            idx = int(raw)
        except ValueError as exc:  # pragma: no cover - defensive
            raise ValueError(f"invalid signal target {target!r}: expected 'node:N'") from exc
        if idx < 0 or idx >= len(self.nodes):
            raise ValueError(f"signal target {target!r} out of range (cluster has {len(self.nodes)} nodes)")
        return self.nodes[idx]

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
        if target == "all":
            # 'all' fans tests out across every node in runner.py's
            # per-test loop. The 'default' target node used for
            # GEODE_SERVER_ADDRESS etc. is the leader.
            return self.leader_node
        # Numeric index
        idx = int(target)
        return self.nodes[idx]

    def next_round_robin_node(self) -> ClusterNodeState:
        """Get next node in round-robin order."""
        node = self.nodes[self._round_robin_index % len(self.nodes)]
        self._round_robin_index += 1
        return node


@dataclass
class ClusterControlContext:
    """Everything a cluster-control test step (signal / restart_node) needs.

    Threaded from the runner through ``run_single_test`` into the sequential
    executor so a step can resolve a named node, send it a Unix signal, or
    restart it on its original port + data directory.
    """

    cluster_state: ClusterState
    cluster_config: ClusterConfig
    binary: str
    base_env: dict[str, str]
    spec_server_args: list[str] = field(default_factory=list)
    verbose: bool = False
    transport: str = "quic"
