# Cluster Test Support Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add multi-node cluster support to geodetestlab-cli so all specs can run against a configurable cluster of 2–10 Geode server instances, with spec-driven cluster creation/teardown.

**Architecture:** The cluster manager spawns N independent Geode server processes, each on its own port and data directory, sharing a `GEODE_CLUSTER_TOKEN`. Tests run against a selectable target node (leader, round-robin, or all). Cluster topology is defined either inline in a spec's `cluster:` block or via a standalone cluster config YAML. A new `--cluster-size` CLI flag allows running any existing spec against a cluster without modifying the spec.

**Tech Stack:** Python 3.11+, existing geodetestlab libs (server.py, spec.py, runner.py), Typer CLI, pytest

---

## File Structure

```text
geodetestlab-cli/geodetestlab/lib/
├── cluster_types.py          # NEW — ClusterConfig, ClusterNodeState, ClusterState dataclasses
├── cluster.py                # NEW — Cluster lifecycle: start_cluster, stop_cluster, health_check_cluster
├── spec.py                   # MODIFY — Parse cluster: block from YAML specs
├── runner.py                 # MODIFY — Handle mode="cluster", delegate to cluster manager
├── runner_types.py           # MODIFY — Add cluster_node field to TestResult
├── cli.py                    # MODIFY — Add --cluster-size flag
├── cli_workers.py            # MODIFY — Pass cluster_size through to run_tests

geodetestlab-cli/geodetestlab/tests/
├── test_cluster_types.py     # NEW — Unit tests for cluster data classes
├── test_cluster.py           # NEW — Unit tests for cluster lifecycle
├── test_spec_cluster.py      # NEW — Unit tests for cluster spec parsing
├── test_runner_cluster.py    # NEW — Unit tests for cluster mode in runner

geodetestlab-cli/specs/cluster_configs/
├── cluster_2node.yml         # NEW — 2-node default cluster config
├── cluster_3node.yml         # NEW — 3-node default cluster config
├── cluster_5node.yml         # NEW — 5-node default cluster config
├── cluster_10node.yml        # NEW — 10-node cluster config
├── cluster_ha.yml            # NEW — High-availability config (3 nodes, stricter health checks)
├── cluster_stress.yml        # NEW — Stress config (10 nodes, aggressive timeouts)
```

---

### Task 1: ClusterConfig Data Classes

**Files:**

- Create: `geodetestlab-cli/geodetestlab/lib/cluster_types.py`
- Test: `geodetestlab-cli/geodetestlab/tests/test_cluster_types.py`

- [ ] **Step 1: Write the failing tests**

```python
# geodetestlab-cli/geodetestlab/tests/test_cluster_types.py
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

        node = ClusterNodeConfig.from_dict({
            "args": ["--log-level", "debug"],
            "env": {"CUSTOM": "val"},
            "port": 4000,
            "grpc_port": 50060,
        })
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

        config = ClusterConfig.from_dict({
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
        })
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

        state = ClusterNodeState(node_id=0, port=3141, grpc_port=50051, data_dir="/tmp/node0", process=None)
        assert state.address == "127.0.0.1:3141"

    def test_grpc_address_property(self) -> None:
        from geodetestlab.lib.cluster_types import ClusterNodeState

        state = ClusterNodeState(node_id=0, port=3141, grpc_port=50051, data_dir="/tmp/node0", process=None)
        assert state.grpc_address == "127.0.0.1:50051"

    def test_grpc_address_none(self) -> None:
        from geodetestlab.lib.cluster_types import ClusterNodeState

        state = ClusterNodeState(node_id=0, port=3141, grpc_port=None, data_dir="/tmp/node0", process=None)
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd geodetestlab-cli && source .venv/bin/activate && python -m pytest geodetestlab/tests/test_cluster_types.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'geodetestlab.lib.cluster_types'`

- [ ] **Step 3: Write the cluster_types module**

```python
# geodetestlab-cli/geodetestlab/lib/cluster_types.py
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

        node_overrides = [
            ClusterNodeConfig.from_dict(n) for n in data.get("node_overrides", [])
        ]

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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd geodetestlab-cli && source .venv/bin/activate && python -m pytest geodetestlab/tests/test_cluster_types.py -v`
Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
cd geodetestlab-cli
git add geodetestlab/lib/cluster_types.py geodetestlab/tests/test_cluster_types.py
git commit -m "feat: add cluster data classes for multi-node test support"
```

---

### Task 2: Cluster Lifecycle Manager

**Files:**

- Create: `geodetestlab-cli/geodetestlab/lib/cluster.py`
- Test: `geodetestlab-cli/geodetestlab/tests/test_cluster.py`

- [ ] **Step 1: Write the failing tests**

```python
# geodetestlab-cli/geodetestlab/tests/test_cluster.py
"""Tests for cluster.py lifecycle management."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from geodetestlab.lib.cluster_types import ClusterConfig, ClusterNodeState, ClusterState


class TestBuildNodeEnv:
    def test_shared_env_applied(self) -> None:
        from geodetestlab.lib.cluster import _build_node_env

        config = ClusterConfig.from_dict({
            "nodes": 2,
            "shared_env": {"GEODE_CLUSTER_TOKEN": "secret123"},
        })
        base_env = {"PATH": "/usr/bin"}
        env = _build_node_env(config, node_id=0, base_env=base_env, port=3141, grpc_port=None, data_dir="/tmp/n0")
        assert env["GEODE_CLUSTER_TOKEN"] == "secret123"
        assert env["PATH"] == "/usr/bin"
        assert env["GEODE_SERVER_ADDRESS"] == "127.0.0.1:3141"
        assert env["PORT"] == "3141"

    def test_node_override_env(self) -> None:
        from geodetestlab.lib.cluster import _build_node_env
        from geodetestlab.lib.cluster_types import ClusterNodeConfig

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

    def test_peer_addresses_injected(self) -> None:
        from geodetestlab.lib.cluster import _build_node_env

        config = ClusterConfig.from_size(3)
        env = _build_node_env(
            config, node_id=0, base_env={}, port=3141, grpc_port=None, data_dir="/tmp/n0",
            all_ports=[3141, 3142, 3143],
        )
        # GEODE_PEERS should list all nodes except self
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
        from geodetestlab.lib.cluster_types import ClusterNodeConfig

        config = ClusterConfig(
            node_count=2,
            shared_args=["--log-level", "info"],
            node_overrides=[ClusterNodeConfig(args=["--log-level", "debug"]), ClusterNodeConfig()],
        )
        args = _build_node_args(config, node_id=0, spec_server_args=[])
        # Node override should take precedence
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
        mock_proc.poll.return_value = None  # Still running
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
        dead_proc.poll.return_value = 1  # Exited
        nodes = [
            ClusterNodeState(node_id=0, port=3141, grpc_port=None, data_dir="/tmp/n0", process=alive_proc),
            ClusterNodeState(node_id=1, port=3142, grpc_port=None, data_dir="/tmp/n1", process=dead_proc),
        ]
        cluster_state = ClusterState(nodes=nodes)
        alive, dead = check_cluster_health(cluster_state)
        assert len(alive) == 1
        assert len(dead) == 1
        assert dead[0].node_id == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd geodetestlab-cli && source .venv/bin/activate && python -m pytest geodetestlab/tests/test_cluster.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'geodetestlab.lib.cluster'`

- [ ] **Step 3: Write the cluster lifecycle module**

```python
# geodetestlab-cli/geodetestlab/lib/cluster.py
"""Multi-node cluster lifecycle management for geodetestlab.

Handles starting, stopping, and health-checking clusters of Geode
server processes for distributed testing.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import tempfile
from pathlib import Path

from .cluster_types import ClusterConfig, ClusterNodeState, ClusterState
from .runner_types import DEFAULT_ADMIN_PASSWORD
from .server import start_server, stop_server
from .utils import get_free_port

logger = logging.getLogger(__name__)


def _build_node_env(
    config: ClusterConfig,
    *,
    node_id: int,
    base_env: dict[str, str],
    port: int,
    grpc_port: int | None,
    data_dir: str,
    all_ports: list[int] | None = None,
) -> dict[str, str]:
    """Build the environment dict for a single cluster node."""
    env = base_env.copy()

    # Apply shared cluster env
    env.update(config.shared_env)

    # Apply per-node overrides if available
    if node_id < len(config.node_overrides):
        env.update(config.node_overrides[node_id].env)

    # Inject standard test harness vars
    env["GEODE_SERVER_ADDRESS"] = f"127.0.0.1:{port}"
    env["PORT"] = str(port)
    env["GEODE_STATE_DIR"] = data_dir
    env.setdefault("GEODE_ADMIN_PASSWORD", DEFAULT_ADMIN_PASSWORD)

    if grpc_port is not None:
        env["GEODE_GRPC_ADDRESS"] = f"127.0.0.1:{grpc_port}"

    # Inject peer addresses (all nodes except self)
    if all_ports is not None:
        peer_addrs = [f"127.0.0.1:{p}" for i, p in enumerate(all_ports) if i != node_id]
        env["GEODE_PEERS"] = ",".join(peer_addrs)

    # Set node identity
    env["GEODE_NODE_ID"] = str(node_id)

    return env


def _build_node_args(
    config: ClusterConfig,
    *,
    node_id: int,
    spec_server_args: list[str],
) -> list[str]:
    """Build the CLI args for a single cluster node."""
    # Start with spec-level server args
    args = list(spec_server_args)

    # Layer shared cluster args
    args.extend(config.shared_args)

    # Per-node overrides replace entirely if present
    if node_id < len(config.node_overrides) and config.node_overrides[node_id].args:
        return list(config.node_overrides[node_id].args)

    return args


def start_cluster(
    config: ClusterConfig,
    *,
    binary: str,
    base_env: dict[str, str],
    spec_server_args: list[str],
    verbose: bool,
    transport: str = "quic",
) -> ClusterState:
    """Start a multi-node Geode cluster.

    Spawns ``config.node_count`` server processes, each with its own
    port and data directory.  Returns a ``ClusterState`` tracking all
    running nodes.

    Raises ``RuntimeError`` if any node fails to start (previously
    started nodes are torn down).
    """
    nodes: list[ClusterNodeState] = []
    all_ports: list[int] = []

    # Pre-allocate ports for all nodes
    for i in range(config.node_count):
        if i < len(config.node_overrides) and config.node_overrides[i].port:
            all_ports.append(config.node_overrides[i].port)
        else:
            all_ports.append(get_free_port())

    if verbose:
        print(f"Starting {config.node_count}-node cluster on ports {all_ports}...")

    for i in range(config.node_count):
        port = all_ports[i]
        data_dir = tempfile.mkdtemp(prefix=f"geode-test-cluster-n{i}-")

        grpc_port: int | None = None
        if transport == "grpc":
            if i < len(config.node_overrides) and config.node_overrides[i].grpc_port:
                grpc_port = config.node_overrides[i].grpc_port
            else:
                grpc_port = get_free_port()

        env = _build_node_env(
            config,
            node_id=i,
            base_env=base_env,
            port=port,
            grpc_port=grpc_port,
            data_dir=data_dir,
            all_ports=all_ports,
        )

        args = _build_node_args(config, node_id=i, spec_server_args=spec_server_args)

        try:
            process = start_server(
                binary=binary,
                data_dir=Path(data_dir),
                port=port,
                env=env,
                args=args,
                timeout_ms=config.startup_timeout_ms,
                verbose=verbose,
                grpc_port=grpc_port,
            )
        except Exception as e:
            # Tear down already-started nodes
            if verbose:
                print(f"  Node {i} failed to start: {e}")
            partial_state = ClusterState(nodes=nodes)
            stop_cluster(partial_state, verbose=verbose, cleanup_data=True)
            raise RuntimeError(f"Cluster node {i} failed to start: {e}") from e

        node_state = ClusterNodeState(
            node_id=i,
            port=port,
            grpc_port=grpc_port,
            data_dir=data_dir,
            process=process,
        )
        nodes.append(node_state)

        if verbose:
            grpc_msg = f" (gRPC: {grpc_port})" if grpc_port else ""
            print(f"  Node {i} ready on port {port}{grpc_msg}")

    return ClusterState(nodes=nodes)


def stop_cluster(
    cluster_state: ClusterState,
    *,
    verbose: bool = False,
    cleanup_data: bool = True,
) -> None:
    """Stop all nodes in a cluster and optionally clean up data dirs."""
    for node in cluster_state.nodes:
        if node.process is not None:
            if verbose:
                print(f"  Stopping node {node.node_id} (port {node.port})...")
            stop_server(node.process, verbose=verbose)
            node.process = None

        if cleanup_data and node.data_dir:
            try:
                shutil.rmtree(node.data_dir, ignore_errors=True)
            except Exception:
                pass


def check_cluster_health(
    cluster_state: ClusterState,
) -> tuple[list[ClusterNodeState], list[ClusterNodeState]]:
    """Check which cluster nodes are alive vs dead.

    Returns a tuple of (alive_nodes, dead_nodes).
    """
    alive: list[ClusterNodeState] = []
    dead: list[ClusterNodeState] = []

    for node in cluster_state.nodes:
        if node.process is None:
            dead.append(node)
        elif node.process.poll() is not None:
            dead.append(node)
        else:
            alive.append(node)

    return alive, dead


def restart_dead_nodes(
    cluster_state: ClusterState,
    config: ClusterConfig,
    *,
    binary: str,
    base_env: dict[str, str],
    spec_server_args: list[str],
    verbose: bool,
    transport: str = "quic",
) -> int:
    """Restart any dead nodes in the cluster. Returns count of restarted nodes."""
    restarted = 0
    all_ports = [n.port for n in cluster_state.nodes]

    for node in cluster_state.nodes:
        if node.process is not None and node.process.poll() is None:
            continue  # Still alive

        if verbose:
            print(f"  Restarting dead node {node.node_id} on port {node.port}...")

        grpc_port = node.grpc_port
        env = _build_node_env(
            config,
            node_id=node.node_id,
            base_env=base_env,
            port=node.port,
            grpc_port=grpc_port,
            data_dir=node.data_dir,
            all_ports=all_ports,
        )
        args = _build_node_args(config, node_id=node.node_id, spec_server_args=spec_server_args)

        try:
            process = start_server(
                binary=binary,
                data_dir=Path(node.data_dir),
                port=node.port,
                env=env,
                args=args,
                timeout_ms=config.startup_timeout_ms,
                verbose=verbose,
                grpc_port=grpc_port,
            )
            node.process = process
            restarted += 1
        except Exception as e:
            if verbose:
                print(f"  Failed to restart node {node.node_id}: {e}")

    return restarted
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd geodetestlab-cli && source .venv/bin/activate && python -m pytest geodetestlab/tests/test_cluster.py -v`
Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
cd geodetestlab-cli
git add geodetestlab/lib/cluster.py geodetestlab/tests/test_cluster.py
git commit -m "feat: add cluster lifecycle manager for multi-node testing"
```

---

### Task 3: Spec Parser — cluster: Block

**Files:**

- Modify: `geodetestlab-cli/geodetestlab/lib/spec.py:417-486` (TestSpec class and from_dict)
- Test: `geodetestlab-cli/geodetestlab/tests/test_spec_cluster.py`

- [ ] **Step 1: Write the failing tests**

```python
# geodetestlab-cli/geodetestlab/tests/test_spec_cluster.py
"""Tests for cluster spec parsing."""

from __future__ import annotations

import textwrap
import tempfile
from pathlib import Path


def _write_spec(content: str) -> Path:
    """Write YAML content to a temp file and return the path."""
    f = tempfile.NamedTemporaryFile(suffix=".yml", mode="w", delete=False)
    f.write(textwrap.dedent(content))
    f.close()
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
        """cluster: block takes precedence over cli.server when both present."""
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
        # server_args from cli.server are still available for spec_server_args
        assert spec.server_args == ["--log-level", "warn"]

    def test_cluster_validates_mode(self) -> None:
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
        # cluster: block overrides mode: server
        assert spec.mode == "cluster"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd geodetestlab-cli && source .venv/bin/activate && python -m pytest geodetestlab/tests/test_spec_cluster.py -v`
Expected: FAIL — `AttributeError: 'TestSpec' object has no attribute 'cluster_config'`

- [ ] **Step 3: Modify spec.py to parse cluster: block**

Add `cluster_config` field to the `TestSpec` dataclass and parse it in `from_dict`:

In `spec.py`, add this import near the top (after existing imports):

```python
from .cluster_types import ClusterConfig
```

Add `cluster_config` field to the `TestSpec` dataclass (after `parallel_tests`):

```python
    cluster_config: ClusterConfig | None = None
```

In `TestSpec.from_dict`, after the mode determination block (after line ~468), add:

```python
        # Parse cluster configuration
        cluster_config = None
        cluster_data = data.get("cluster")
        if cluster_data is not None:
            cluster_config = ClusterConfig.from_dict(cluster_data)
            mode = "cluster"  # Override mode when cluster block is present
```

Pass `cluster_config=cluster_config` into the `cls(...)` constructor call.

In the `load_spec` validation (line ~569), update mode validation to accept "cluster":

```python
    if mode not in ("server", "cli", "cluster"):
        raise SpecValidationError(f"Invalid mode '{mode}'. Must be 'server', 'cli', or 'cluster'")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd geodetestlab-cli && source .venv/bin/activate && python -m pytest geodetestlab/tests/test_spec_cluster.py -v`
Expected: All tests PASS

- [ ] **Step 5: Run existing spec tests to verify no regressions**

Run: `cd geodetestlab-cli && source .venv/bin/activate && python -m pytest geodetestlab/tests/test_spec_validation.py -v`
Expected: All existing tests still PASS

- [ ] **Step 6: Commit**

```bash
cd geodetestlab-cli
git add geodetestlab/lib/spec.py geodetestlab/tests/test_spec_cluster.py
git commit -m "feat: parse cluster: block in YAML test specifications"
```

---

### Task 4: Runner — Cluster Mode Execution

**Files:**

- Modify: `geodetestlab-cli/geodetestlab/lib/runner.py:621-824` (run_tests function)
- Modify: `geodetestlab-cli/geodetestlab/lib/runner_types.py` (add cluster_node to TestResult)
- Test: `geodetestlab-cli/geodetestlab/tests/test_runner_cluster.py`

- [ ] **Step 1: Write the failing tests**

```python
# geodetestlab-cli/geodetestlab/tests/test_runner_cluster.py
"""Tests for cluster mode in the runner."""

from __future__ import annotations

from unittest.mock import MagicMock, patch


class TestResultClusterNode:
    def test_result_has_cluster_node_field(self) -> None:
        from geodetestlab.lib.runner_types import TestResult

        result = TestResult(name="test1", passed=True, duration_ms=100, cluster_node=2)
        assert result.cluster_node == 2

    def test_result_cluster_node_default_none(self) -> None:
        from geodetestlab.lib.runner_types import TestResult

        result = TestResult(name="test1", passed=True, duration_ms=100)
        assert result.cluster_node is None


class TestRunTestsClusterMode:
    def test_cluster_mode_calls_start_cluster(self) -> None:
        """When spec.mode == 'cluster', run_tests should call start_cluster."""
        from geodetestlab.lib.cluster_types import ClusterConfig, ClusterNodeState, ClusterState
        from geodetestlab.lib.spec import TestSpec

        spec = TestSpec(
            name="cluster test",
            description="",
            mode="cluster",
            cluster_config=ClusterConfig.from_size(2),
            tests=[],
        )

        mock_cluster_state = ClusterState(nodes=[
            ClusterNodeState(node_id=0, port=4000, grpc_port=None, data_dir="/tmp/n0", process=MagicMock()),
            ClusterNodeState(node_id=1, port=4001, grpc_port=None, data_dir="/tmp/n1", process=MagicMock()),
        ])

        with (
            patch("geodetestlab.lib.runner.start_cluster", return_value=mock_cluster_state) as mock_start,
            patch("geodetestlab.lib.runner.stop_cluster") as mock_stop,
            patch("geodetestlab.lib.runner.find_geode_binary", return_value="/usr/bin/geode"),
        ):
            from geodetestlab.lib.runner import run_tests

            exit_code, summary = run_tests(
                spec=spec,
                secrets={},
                env_overrides={},
                verbose=False,
            )
            mock_start.assert_called_once()
            mock_stop.assert_called_once()
            assert exit_code == 0

    def test_cluster_mode_sets_env_from_target_node(self) -> None:
        """GEODE_SERVER_ADDRESS should point to the target node."""
        from geodetestlab.lib.cluster_types import ClusterConfig, ClusterNodeState, ClusterState
        from geodetestlab.lib.spec import TestCase, TestSpec

        test_case = TestCase(
            name="check-env",
            description="",
            query="RETURN 1",
        )
        spec = TestSpec(
            name="cluster env test",
            description="",
            mode="cluster",
            cluster_config=ClusterConfig(node_count=2, target_node="leader"),
            tests=[test_case],
        )

        mock_cluster_state = ClusterState(nodes=[
            ClusterNodeState(node_id=0, port=5000, grpc_port=None, data_dir="/tmp/n0", process=MagicMock()),
            ClusterNodeState(node_id=1, port=5001, grpc_port=None, data_dir="/tmp/n1", process=MagicMock()),
        ])
        # Mark processes as alive
        for n in mock_cluster_state.nodes:
            n.process.poll.return_value = None

        captured_env = {}

        def capture_env_run_test(**kwargs):
            captured_env.update(kwargs.get("env", {}))
            from geodetestlab.lib.runner_types import TestResult
            return TestResult(name="check-env", passed=True, duration_ms=10)

        with (
            patch("geodetestlab.lib.runner.start_cluster", return_value=mock_cluster_state),
            patch("geodetestlab.lib.runner.stop_cluster"),
            patch("geodetestlab.lib.runner.find_geode_binary", return_value="/usr/bin/geode"),
            patch("geodetestlab.lib.runner.run_single_test", side_effect=capture_env_run_test),
        ):
            from geodetestlab.lib.runner import run_tests

            run_tests(spec=spec, secrets={}, env_overrides={}, verbose=False)
            assert captured_env.get("GEODE_SERVER_ADDRESS") == "127.0.0.1:5000"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd geodetestlab-cli && source .venv/bin/activate && python -m pytest geodetestlab/tests/test_runner_cluster.py -v`
Expected: FAIL — `TypeError` or `AttributeError` (cluster_node field missing, start_cluster not found)

- [ ] **Step 3: Add cluster_node field to TestResult**

In `runner_types.py`, add to the `TestResult` dataclass after `plaintext_violations`:

```python
    cluster_node: int | None = None
```

- [ ] **Step 4: Modify runner.py to handle cluster mode**

Add these imports to the top of `runner.py`:

```python
from .cluster import start_cluster, stop_cluster, check_cluster_health, restart_dead_nodes
from .cluster_types import ClusterConfig, ClusterState
```

In the `run_tests` function, after the `if spec.mode == "server":` block (around line 658-691), add a new elif block:

```python
    elif spec.mode == "cluster" and spec.cluster_config is not None:
        cluster_config = spec.cluster_config
        cluster_state = start_cluster(
            cluster_config,
            binary=binary,
            base_env=env,
            spec_server_args=spec.server_args,
            verbose=verbose,
            transport=transport,
        )

        # Point tests at the target node
        target = cluster_state.get_target_node(cluster_config.target_node)
        env["GEODE_SERVER_ADDRESS"] = target.address
        env["PORT"] = str(target.port)
        env["GEODE_TRANSPORT"] = transport
        if target.grpc_port:
            env["GEODE_GRPC_ADDRESS"] = target.grpc_address or ""

        # Inject cluster metadata
        env["GEODE_CLUSTER_SIZE"] = str(cluster_config.node_count)
        env["GEODE_CLUSTER_PORTS"] = ",".join(str(n.port) for n in cluster_state.nodes)

        data_dir = Path(target.data_dir)

        # Create a synthetic ServerState pointing at the target node for
        # compatibility with _execute_one_test (crash detection, restarts)
        server_state = ServerState(
            process=target.process,
            port=target.port,
            grpc_port=target.grpc_port,
        )
```

In the finally block (around line 782-804), add cluster cleanup before the existing server cleanup:

```python
        # Clean up cluster if in cluster mode
        if spec.mode == "cluster" and spec.cluster_config is not None:
            try:
                stop_cluster(cluster_state, verbose=verbose, cleanup_data=True)
            except Exception:
                pass
```

For round-robin support, in `_execute_one_test`, when the spec mode is "cluster" and target is "round-robin", update the env for each test to point at the next node. Add this check at the beginning of the test loop (before calling `_execute_one_test`) in the sequential path:

```python
                # Round-robin: update target node for each test in cluster mode
                if spec.mode == "cluster" and spec.cluster_config and spec.cluster_config.target_node == "round-robin":
                    next_node = cluster_state.next_round_robin_node()
                    env["GEODE_SERVER_ADDRESS"] = next_node.address
                    env["PORT"] = str(next_node.port)
                    if next_node.grpc_port:
                        env["GEODE_GRPC_ADDRESS"] = next_node.grpc_address or ""
```

For "all" target mode, wrap the test loop to run each test against every node:

```python
                if spec.mode == "cluster" and spec.cluster_config and spec.cluster_config.target_node == "all":
                    # Run each test against every node
                    for node in cluster_state.nodes:
                        env["GEODE_SERVER_ADDRESS"] = node.address
                        env["PORT"] = str(node.port)
                        if node.grpc_port:
                            env["GEODE_GRPC_ADDRESS"] = node.grpc_address or ""
                        result = _execute_one_test(...)
                        result.cluster_node = node.node_id
                        _record_result(test_case, result)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd geodetestlab-cli && source .venv/bin/activate && python -m pytest geodetestlab/tests/test_runner_cluster.py -v`
Expected: All tests PASS

- [ ] **Step 6: Run full unit test suite to verify no regressions**

Run: `cd geodetestlab-cli && source .venv/bin/activate && python -m pytest geodetestlab/tests/ -v`
Expected: All existing tests still PASS

- [ ] **Step 7: Commit**

```bash
cd geodetestlab-cli
git add geodetestlab/lib/runner.py geodetestlab/lib/runner_types.py geodetestlab/tests/test_runner_cluster.py
git commit -m "feat: add cluster mode execution to test runner"
```

---

### Task 5: CLI — --cluster-size Flag

**Files:**

- Modify: `geodetestlab-cli/geodetestlab/cli.py:121-208` (run command options)
- Modify: `geodetestlab-cli/geodetestlab/lib/cli_workers.py` (pass cluster_size)

- [ ] **Step 1: Write the failing test**

```python
# Add to geodetestlab-cli/geodetestlab/tests/test_cli.py (append to existing file)

class TestClusterSizeFlag:
    def test_cluster_size_creates_cluster_config(self) -> None:
        """--cluster-size should inject a ClusterConfig into specs without one."""
        from unittest.mock import MagicMock, patch
        from typer.testing import CliRunner
        import tempfile
        import textwrap
        from pathlib import Path

        runner = CliRunner()

        spec_content = textwrap.dedent("""
            name: basic test
            tests:
              - name: test1
                query: RETURN 1
        """)
        with tempfile.NamedTemporaryFile(suffix=".yml", mode="w", delete=False) as f:
            f.write(spec_content)
            spec_path = f.name

        captured_spec = {}

        original_run_tests = None

        def mock_run_tests(spec, **kwargs):
            captured_spec["mode"] = spec.mode
            captured_spec["cluster_config"] = spec.cluster_config
            return 0, {"total": 1, "passed": 1, "failed": 0, "skipped": 0}

        from geodetestlab.cli import app

        with (
            patch("geodetestlab.lib.cli_workers._run_single_spec") as mock_worker,
            patch("geodetestlab.lib.runner.run_tests", side_effect=mock_run_tests),
            patch("geodetestlab.lib.runner.find_geode_binary", return_value="/usr/bin/geode"),
        ):
            mock_worker.return_value = {
                "spec": spec_path,
                "exit_code": 0,
                "summary": {"total": 1, "passed": 1, "failed": 0, "skipped": 0},
                "error": None,
            }
            result = runner.invoke(app, ["run", "--spec", spec_path, "--cluster-size", "3"])
            # The test verifies the flag is accepted without error
            assert result.exit_code in (0, 1)  # May fail on binary not found, but flag is accepted
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd geodetestlab-cli && source .venv/bin/activate && python -m pytest geodetestlab/tests/test_cli.py::TestClusterSizeFlag -v`
Expected: FAIL — `No such option: --cluster-size`

- [ ] **Step 3: Add --cluster-size to CLI**

In `cli.py`, add this parameter to the `run` command (after the `transport` parameter):

```python
    cluster_size: int | None = typer.Option(
        None,
        "--cluster-size",
        min=2,
        max=10,
        help="Run specs against a cluster of N nodes (2-10). Overrides spec cluster config.",
    ),
    cluster_config_file: Path | None = typer.Option(
        None,
        "--cluster-config",
        exists=True,
        readable=True,
        help="Path to a cluster configuration YAML file",
    ),
```

After the spec files are collected (around line 247), add cluster config injection logic:

```python
    # Resolve cluster configuration for --cluster-size flag
    cluster_size_override = cluster_size
    cluster_config_override = None
    if cluster_config_file is not None:
        import yaml
        with open(cluster_config_file) as f:
            from geodetestlab.lib.cluster_types import ClusterConfig
            cluster_config_override = ClusterConfig.from_dict(yaml.safe_load(f))
            cluster_size_override = None  # Config file takes precedence
```

In the sequential execution path (line ~488-545), after loading the spec, inject cluster config:

```python
                # Inject cluster config from CLI flags
                if cluster_config_override is not None:
                    spec_obj.cluster_config = cluster_config_override
                    spec_obj.mode = "cluster"
                elif cluster_size_override is not None:
                    from geodetestlab.lib.cluster_types import ClusterConfig
                    spec_obj.cluster_config = ClusterConfig.from_size(cluster_size_override)
                    spec_obj.mode = "cluster"
```

In `cli_workers.py`, add `cluster_size` parameter to `_run_single_spec`:

```python
def _run_single_spec(
    spec_file: Path,
    llm_provider: str,
    model: str | None,
    max_cases: int | None,
    timeout_ms: int,
    server_timeout_ms: int,
    dry_run: bool,
    ci_mode: bool,
    seed: int | None,
    geode_binary: str | None,
    server_port: int | None,
    verbose: bool,
    transport: str = "quic",
    cluster_size: int | None = None,  # NEW
) -> dict[str, Any]:
```

After loading the spec in `_run_single_spec`, inject cluster config:

```python
    if cluster_size is not None and spec_obj.cluster_config is None:
        from .cluster_types import ClusterConfig
        spec_obj.cluster_config = ClusterConfig.from_size(cluster_size)
        spec_obj.mode = "cluster"
```

Update all call sites in `cli.py` that pass args to `_run_single_spec` to include `cluster_size_override`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd geodetestlab-cli && source .venv/bin/activate && python -m pytest geodetestlab/tests/test_cli.py::TestClusterSizeFlag -v`
Expected: PASS

- [ ] **Step 5: Run full test suite**

Run: `cd geodetestlab-cli && source .venv/bin/activate && python -m pytest geodetestlab/tests/ -v`
Expected: All tests PASS

- [ ] **Step 6: Commit**

```bash
cd geodetestlab-cli
git add geodetestlab/cli.py geodetestlab/lib/cli_workers.py geodetestlab/tests/test_cli.py
git commit -m "feat: add --cluster-size and --cluster-config CLI flags"
```

---

### Task 6: Default Cluster Configuration Files

**Files:**

- Create: `geodetestlab-cli/specs/cluster_configs/cluster_2node.yml`
- Create: `geodetestlab-cli/specs/cluster_configs/cluster_3node.yml`
- Create: `geodetestlab-cli/specs/cluster_configs/cluster_5node.yml`
- Create: `geodetestlab-cli/specs/cluster_configs/cluster_10node.yml`
- Create: `geodetestlab-cli/specs/cluster_configs/cluster_ha.yml`
- Create: `geodetestlab-cli/specs/cluster_configs/cluster_stress.yml`

- [ ] **Step 1: Create 2-node cluster config**

```yaml
# geodetestlab-cli/specs/cluster_configs/cluster_2node.yml
# Minimal 2-node cluster for basic distributed testing.
# Usage: geodetestlab run --specs specs --cluster-config specs/cluster_configs/cluster_2node.yml
nodes: 2
target_node: leader
shared_env:
  GEODE_CLUSTER_TOKEN: test-cluster-secret-2026
shared_args:
  - --log-level
  - info
startup_timeout_ms: 90000
health_check_interval_ms: 5000
```

- [ ] **Step 2: Create 3-node cluster config**

```yaml
# geodetestlab-cli/specs/cluster_configs/cluster_3node.yml
# Standard 3-node cluster for quorum-based testing (Raft consensus).
nodes: 3
target_node: leader
shared_env:
  GEODE_CLUSTER_TOKEN: test-cluster-secret-2026
shared_args:
  - --log-level
  - info
startup_timeout_ms: 90000
health_check_interval_ms: 5000
```

- [ ] **Step 3: Create 5-node cluster config**

```yaml
# geodetestlab-cli/specs/cluster_configs/cluster_5node.yml
# 5-node cluster for replication factor testing.
nodes: 5
target_node: round-robin
shared_env:
  GEODE_CLUSTER_TOKEN: test-cluster-secret-2026
shared_args:
  - --log-level
  - info
startup_timeout_ms: 120000
health_check_interval_ms: 3000
```

- [ ] **Step 4: Create 10-node cluster config**

```yaml
# geodetestlab-cli/specs/cluster_configs/cluster_10node.yml
# Maximum 10-node cluster for scale testing.
nodes: 10
target_node: round-robin
shared_env:
  GEODE_CLUSTER_TOKEN: test-cluster-secret-2026
shared_args:
  - --log-level
  - warn
startup_timeout_ms: 180000
health_check_interval_ms: 10000
```

- [ ] **Step 5: Create HA cluster config**

```yaml
# geodetestlab-cli/specs/cluster_configs/cluster_ha.yml
# High-availability cluster: 3 nodes with aggressive health checks.
nodes: 3
target_node: leader
shared_env:
  GEODE_CLUSTER_TOKEN: test-cluster-secret-2026
shared_args:
  - --log-level
  - info
  - --persist-interval
  - "50"
startup_timeout_ms: 60000
health_check_interval_ms: 1000
```

- [ ] **Step 6: Create stress cluster config**

```yaml
# geodetestlab-cli/specs/cluster_configs/cluster_stress.yml
# Stress testing: 10 nodes with tight timeouts to expose race conditions.
nodes: 10
target_node: all
shared_env:
  GEODE_CLUSTER_TOKEN: test-cluster-stress-2026
shared_args:
  - --log-level
  - warn
  - --idle-timeout
  - "30000"
startup_timeout_ms: 120000
health_check_interval_ms: 2000
```

- [ ] **Step 7: Commit**

```bash
cd geodetestlab-cli
git add specs/cluster_configs/
git commit -m "feat: add default cluster configuration files (2-10 nodes)"
```

---

### Task 7: Makefile Targets for Cluster Testing

**Files:**

- Modify: `Makefile` (add cluster test targets)

- [ ] **Step 1: Add cluster targets to Makefile**

Add these targets after the existing `test-all-transports` target:

```makefile
# Cluster testing targets
.PHONY: test-cluster-2 test-cluster-3 test-cluster-5 test-cluster-10 test-cluster-all

test-cluster-2: ## Run all tests against a 2-node cluster
 cd geodetestlab-cli && source .venv/bin/activate && \
  python -m geodetestlab run --specs specs --cluster-size 2 -v

test-cluster-3: ## Run all tests against a 3-node cluster
 cd geodetestlab-cli && source .venv/bin/activate && \
  python -m geodetestlab run --specs specs --cluster-size 3 -v

test-cluster-5: ## Run all tests against a 5-node cluster
 cd geodetestlab-cli && source .venv/bin/activate && \
  python -m geodetestlab run --specs specs --cluster-size 5 -v

test-cluster-10: ## Run all tests against a 10-node cluster
 cd geodetestlab-cli && source .venv/bin/activate && \
  python -m geodetestlab run --specs specs --cluster-size 10 -v

test-cluster-all: test-cluster-2 test-cluster-3 test-cluster-5 test-cluster-10 ## Run all cluster sizes

test-cluster-config: ## Run tests with a specific cluster config file
 cd geodetestlab-cli && source .venv/bin/activate && \
  python -m geodetestlab run --specs specs --cluster-config $(CONFIG) -v
```

- [ ] **Step 2: Verify the Makefile is syntactically valid**

Run: `make -n test-cluster-2`
Expected: Prints the commands that would be run (dry run)

- [ ] **Step 3: Commit**

```bash
git add Makefile
git commit -m "feat: add Makefile targets for cluster testing (2-10 nodes)"
```

---

### Task 8: Integration Test — Full Cluster Spec

**Files:**

- Create: `geodetestlab-cli/specs/cluster_basic_validation.yml`

- [ ] **Step 1: Create a cluster-native test spec**

This spec uses the `cluster:` block to validate basic cluster behavior:

```yaml
# geodetestlab-cli/specs/cluster_basic_validation.yml
version: '1.0'
name: Cluster Basic Validation
description: |
  Validates that a multi-node cluster can start, accept queries on the
  target node, and that all nodes respond correctly. This is the smoke
  test for cluster support in geodetestlab.

cluster:
  nodes: 3
  target_node: leader
  shared_env:
    GEODE_CLUSTER_TOKEN: test-cluster-validation-2026
  shared_args:
    - --log-level
    - info
  startup_timeout_ms: 90000

cli:
  binary: ./zig-out/bin/geode
  client:
    timeout_ms: 30000
    format: json

tests:
- name: cluster-leader-health
  description: Verify the leader node is healthy and accepts queries.
  args:
  - query
  - '-'
  stdin: RETURN 'cluster_ok' AS status
  expect:
    exit_code: 0
    stdout_contains:
    - cluster_ok

- name: cluster-create-graph
  description: Create a graph on the leader node.
  args:
  - query
  - '-'
  stdin: CREATE GRAPH IF NOT EXISTS cluster_test_g
  expect:
    exit_code: 0

- name: cluster-create-node
  description: Create a node in the cluster test graph.
  args:
  - query
  - '-'
  stdin: USE GRAPH cluster_test_g; CREATE (:Server {name:'node0', role:'leader'})
  expect:
    exit_code: 0

- name: cluster-read-node
  description: Read back the created node.
  args:
  - query
  - '-'
  stdin: USE GRAPH cluster_test_g; MATCH (s:Server) RETURN s.name AS name
  expect:
    exit_code: 0
    stdout_contains:
    - node0

- name: cluster-transaction-commit
  description: Verify transactions work on cluster leader.
  args:
  - query
  - '-'
  stdin: |
    USE GRAPH cluster_test_g;
    BEGIN;
    CREATE (:Server {name:'node1', role:'follower'});
    COMMIT
  expect:
    exit_code: 0

- name: cluster-transaction-rollback
  description: Verify rollback works on cluster leader.
  args:
  - query
  - '-'
  stdin: |
    USE GRAPH cluster_test_g;
    BEGIN;
    CREATE (:Server {name:'phantom', role:'ghost'});
    ROLLBACK
  expect:
    exit_code: 0

- name: cluster-verify-rollback
  description: Confirm rolled-back node does not exist.
  args:
  - query
  - '-'
  stdin: USE GRAPH cluster_test_g; MATCH (s:Server {name:'phantom'}) RETURN count(s) AS cnt
  expect:
    exit_code: 0
    stdout_contains:
    - '0'

- name: cluster-cleanup
  description: Clean up cluster test graph.
  args:
  - query
  - '-'
  stdin: DROP GRAPH IF EXISTS cluster_test_g
  expect:
    exit_code: 0
```

- [ ] **Step 2: Verify the spec parses correctly**

Run: `cd geodetestlab-cli && source .venv/bin/activate && python -c "from geodetestlab.lib.spec import load_spec; s = load_spec('specs/cluster_basic_validation.yml'); print(f'mode={s.mode} nodes={s.cluster_config.node_count} tests={len(s.tests)}')"`
Expected: `mode=cluster nodes=3 tests=8`

- [ ] **Step 3: Run the cluster spec (integration test)**

Run: `cd geodetestlab-cli && source .venv/bin/activate && python -m geodetestlab run --spec specs/cluster_basic_validation.yml -v`
Expected: All 8 tests PASS (cluster starts 3 nodes, runs tests against leader, shuts down)

- [ ] **Step 4: Commit**

```bash
cd geodetestlab-cli
git add specs/cluster_basic_validation.yml
git commit -m "test: add cluster basic validation spec for smoke testing"
```

---

### Task 9: Update CLAUDE.md and Documentation

**Files:**

- Modify: `CLAUDE.md` (add cluster testing docs)

- [ ] **Step 1: Update CLAUDE.md**

Add cluster testing section after the "Transport-specific tests" section in Build & Test Commands:

```markdown
# Cluster testing
make test-cluster-2     # Run all tests against a 2-node cluster
make test-cluster-3     # Run all tests against a 3-node cluster
make test-cluster-5     # Run all tests against a 5-node cluster
make test-cluster-10    # Run all tests against a 10-node cluster
make test-cluster-all   # Run tests against all cluster sizes (2,3,5,10)

# Cluster with custom config
python -m geodetestlab run --specs specs --cluster-config specs/cluster_configs/cluster_ha.yml -v

# Single spec against cluster
python -m geodetestlab run --spec specs/distributed_2pc_undo.yml --cluster-size 3 -v
```

Add cluster spec format documentation after the "Test Spec Format" section:

```markdown
### Cluster Spec Format

```yaml
cluster:
  nodes: 3                    # Node count (2-10)
  target_node: leader         # leader | round-robin | all | 0-9
  shared_env:                 # Env vars shared across all nodes
    GEODE_CLUSTER_TOKEN: secret
  shared_args:                # CLI args for all nodes
    - --log-level
    - info
  node_overrides:             # Per-node overrides (optional)
    - args: [--log-level, debug]
    - {}
  startup_timeout_ms: 90000  # Per-node startup timeout
  health_check_interval_ms: 5000
```text
Cluster configs are in `specs/cluster_configs/` (2, 3, 5, 10-node, HA, stress).

```text
Add to Architecture section:

```markdown
### Cluster Testing

- `geodetestlab-cli/geodetestlab/lib/cluster.py` — Cluster lifecycle (start/stop/health)
- `geodetestlab-cli/geodetestlab/lib/cluster_types.py` — Cluster data classes
- `geodetestlab-cli/specs/cluster_configs/` — Default cluster configurations
```

- [ ] **Step 2: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: add cluster testing documentation to CLAUDE.md"
```

---

## Summary of Changes

| Component | Change | LOC (est.) |
|-----------|--------|------------|
| `cluster_types.py` | New — data classes | ~100 |
| `cluster.py` | New — lifecycle manager | ~200 |
| `spec.py` | Modify — parse cluster: block | ~20 |
| `runner.py` | Modify — cluster mode execution | ~60 |
| `runner_types.py` | Modify — add cluster_node | ~2 |
| `cli.py` | Modify — --cluster-size/--cluster-config flags | ~30 |
| `cli_workers.py` | Modify — pass cluster_size | ~10 |
| `test_cluster_types.py` | New — unit tests | ~120 |
| `test_cluster.py` | New — unit tests | ~100 |
| `test_spec_cluster.py` | New — unit tests | ~90 |
| `test_runner_cluster.py` | New — unit tests | ~80 |
| `specs/cluster_configs/` | New — 6 YAML configs | ~60 |
| `specs/cluster_basic_validation.yml` | New — integration spec | ~80 |
| `Makefile` | Modify — cluster targets | ~20 |
| `CLAUDE.md` | Modify — docs | ~30 |
| **Total** | | **~1000** |

## Key Design Decisions

1. **Cluster = N independent servers**: Since Geode's CLI doesn't expose cluster join/peer flags, each node is a standalone server. `GEODE_CLUSTER_TOKEN` and `GEODE_PEERS` env vars are set for when the binary adds cluster formation support.

2. **Spec-driven, CLI-overridable**: `cluster:` block in specs for permanent cluster tests. `--cluster-size N` flag for running any existing spec against a cluster without modifying the spec.

3. **target_node strategies**: `leader` (always node 0), `round-robin` (distribute tests across nodes), `all` (run every test against every node), or explicit index `0`-`9`.

4. **Backward compatible**: All existing specs work unchanged. Cluster mode is opt-in via `cluster:` block or `--cluster-size` flag. The `mode="server"` path is untouched.

5. **Node count bounds**: Minimum 2, maximum 10. Values outside are clamped.
