"""Cluster lifecycle management for multi-node Geode testing.

Provides functions to start, stop, health-check, and restart
multi-node Geode clusters using the existing single-server primitives
from ``server.py``.
"""

from __future__ import annotations

import logging
import shutil
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
    """Build the environment dict for a single cluster node.

    Layering order (later wins):
      1. base_env (inherited from the test runner)
      2. config.shared_env
      3. per-node override env (if present)
      4. injected cluster variables
    """
    env: dict[str, str] = {}
    env.update(base_env)
    env.update(config.shared_env)

    # Apply per-node overrides if available
    if node_id < len(config.node_overrides):
        env.update(config.node_overrides[node_id].env)

    # Injected cluster variables
    env["GEODE_SERVER_ADDRESS"] = f"127.0.0.1:{port}"
    env["PORT"] = str(port)
    env["GEODE_STATE_DIR"] = data_dir
    env["GEODE_ADMIN_PASSWORD"] = env.get("GEODE_ADMIN_PASSWORD", DEFAULT_ADMIN_PASSWORD)
    # Geode + its bundled raft library reserve node id 0 as the invalid
    # sentinel (raft node.zig: `if (self.id == 0) return InvalidId`), and
    # geode's bootstrap numbers nodes 1-based to match (see geode's
    # tests/test_cluster_3node_subprocess.zig which spawns GEODE_NODE_ID=i+1).
    # `node_id` stays 0-based internally (it indexes ports/overrides); only
    # the injected env value is shifted to 1-based so node 0 does not exit on
    # startup with InvalidNodeId.
    env["GEODE_NODE_ID"] = str(node_id + 1)

    if grpc_port is not None:
        env["GEODE_GRPC_ADDRESS"] = f"127.0.0.1:{grpc_port}"

    # Build peer list (all ports except this node's port)
    if all_ports is not None:
        peers = [f"127.0.0.1:{p}" for p in all_ports if p != port]
        env["GEODE_PEERS"] = ",".join(peers)

    return env


def _build_node_args(
    config: ClusterConfig,
    *,
    node_id: int,
    spec_server_args: list[str],
) -> list[str]:
    """Build CLI args for a single cluster node.

    If the node has override args, those replace everything.
    Otherwise: spec_server_args + shared_args.
    """
    # Check for per-node override args
    if node_id < len(config.node_overrides):
        override = config.node_overrides[node_id]
        if override.args:
            return list(override.args)

    # Default: spec args + shared args
    args = list(spec_server_args)
    args.extend(config.shared_args)
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

    Pre-allocates ports for all nodes, starts servers sequentially,
    and rolls back on failure (stops already-started nodes).

    Returns a ``ClusterState`` describing the running cluster.
    Raises ``RuntimeError`` if any node fails to start.
    """
    # Pre-allocate ports
    ports: list[int] = []
    grpc_ports: list[int | None] = []

    for i in range(config.node_count):
        override = config.node_overrides[i] if i < len(config.node_overrides) else None

        if override and override.port is not None:
            ports.append(override.port)
        else:
            ports.append(get_free_port())

        if transport == "grpc" or (override and override.grpc_port is not None):
            if override and override.grpc_port is not None:
                grpc_ports.append(override.grpc_port)
            else:
                grpc_ports.append(get_free_port())
        else:
            grpc_ports.append(None)

    # Start nodes sequentially
    nodes: list[ClusterNodeState] = []

    for i in range(config.node_count):
        data_dir = tempfile.mkdtemp(prefix=f"geode-test-cluster-n{i}-")
        node_env = _build_node_env(
            config,
            node_id=i,
            base_env=base_env,
            port=ports[i],
            grpc_port=grpc_ports[i],
            data_dir=data_dir,
            all_ports=ports,
        )
        node_args = _build_node_args(config, node_id=i, spec_server_args=spec_server_args)

        try:
            process = start_server(
                binary=binary,
                data_dir=Path(data_dir),
                port=ports[i],
                env=node_env,
                args=node_args,
                timeout_ms=config.startup_timeout_ms,
                verbose=verbose,
                grpc_port=grpc_ports[i],
            )
        except Exception as exc:
            logger.error("Failed to start cluster node %d: %s", i, exc)
            # Roll back: stop already-started nodes
            rollback_state = ClusterState(nodes=nodes)
            stop_cluster(rollback_state, verbose=verbose, cleanup_data=True)
            msg = f"Cluster startup failed at node {i}: {exc}"
            raise RuntimeError(msg) from exc

        nodes.append(
            ClusterNodeState(
                node_id=i,
                port=ports[i],
                grpc_port=grpc_ports[i],
                data_dir=data_dir,
                process=process,
            )
        )

    return ClusterState(nodes=nodes)


def stop_cluster(
    cluster_state: ClusterState,
    *,
    verbose: bool = False,
    cleanup_data: bool = True,
) -> None:
    """Stop all nodes in a cluster.

    Skips nodes whose process is ``None``.  If ``cleanup_data`` is
    true, removes each node's data directory.
    """
    for node in cluster_state.nodes:
        if node.process is not None:
            try:
                stop_server(node.process, verbose=verbose)
            except Exception:
                logger.warning("Error stopping cluster node %d", node.node_id, exc_info=True)

        if cleanup_data:
            try:
                shutil.rmtree(node.data_dir, ignore_errors=True)
            except Exception:
                logger.warning("Error cleaning data dir for node %d: %s", node.node_id, node.data_dir)


def check_cluster_health(
    cluster_state: ClusterState,
) -> tuple[list[ClusterNodeState], list[ClusterNodeState]]:
    """Check which cluster nodes are alive.

    Returns a tuple of ``(alive_nodes, dead_nodes)`` based on
    ``process.poll()``.  A node with no process is considered dead.
    """
    alive: list[ClusterNodeState] = []
    dead: list[ClusterNodeState] = []

    for node in cluster_state.nodes:
        if node.process is None or node.process.poll() is not None:
            dead.append(node)
        else:
            alive.append(node)

    return alive, dead


def restart_cluster_node(
    cluster_state: ClusterState,
    config: ClusterConfig,
    node_id: int,
    *,
    binary: str,
    base_env: dict[str, str],
    spec_server_args: list[str],
    verbose: bool,
    transport: str = "quic",
) -> ClusterNodeState:
    """Stop (if still running) and restart a single cluster node.

    The node is re-spawned on its **original port and data directory** so a
    restart exercises WAL replay against the existing on-disk state.  Used by
    the harness ``restart_node`` step type.

    Returns the (mutated) ``ClusterNodeState`` for the restarted node.
    Raises ``ValueError`` for an out-of-range ``node_id`` and ``RuntimeError``
    if the node fails to come back up.
    """
    if node_id < 0 or node_id >= len(cluster_state.nodes):
        msg = f"restart_cluster_node: node_id {node_id} out of range ({len(cluster_state.nodes)} nodes)"
        raise ValueError(msg)

    node = cluster_state.nodes[node_id]

    # Stop the node if its process is still alive (a SIGKILLed node is
    # already gone — poll() returns non-None — and stop_server is a no-op).
    if node.process is not None and node.process.poll() is None:
        try:
            stop_server(node.process, verbose=verbose)
        except Exception:
            logger.warning("Error stopping node %d before restart", node_id, exc_info=True)

    all_ports = [n.port for n in cluster_state.nodes]
    node_env = _build_node_env(
        config,
        node_id=node_id,
        base_env=base_env,
        port=node.port,
        grpc_port=node.grpc_port,
        data_dir=node.data_dir,
        all_ports=all_ports,
    )
    node_args = _build_node_args(config, node_id=node_id, spec_server_args=spec_server_args)

    try:
        process = start_server(
            binary=binary,
            data_dir=Path(node.data_dir),
            port=node.port,
            env=node_env,
            args=node_args,
            timeout_ms=config.startup_timeout_ms,
            verbose=verbose,
            grpc_port=node.grpc_port,
        )
    except Exception as exc:
        logger.error("Failed to restart cluster node %d: %s", node_id, exc)
        msg = f"restart_cluster_node: node {node_id} failed to restart: {exc}"
        raise RuntimeError(msg) from exc

    node.process = process
    return node


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
    """Restart any dead nodes in the cluster.

    Returns the number of nodes successfully restarted.
    """
    _, dead_nodes = check_cluster_health(cluster_state)
    if not dead_nodes:
        return 0

    all_ports = [n.port for n in cluster_state.nodes]
    restarted = 0

    for node in dead_nodes:
        node_env = _build_node_env(
            config,
            node_id=node.node_id,
            base_env=base_env,
            port=node.port,
            grpc_port=node.grpc_port,
            data_dir=node.data_dir,
            all_ports=all_ports,
        )
        node_args = _build_node_args(config, node_id=node.node_id, spec_server_args=spec_server_args)

        try:
            process = start_server(
                binary=binary,
                data_dir=Path(node.data_dir),
                port=node.port,
                env=node_env,
                args=node_args,
                timeout_ms=config.startup_timeout_ms,
                verbose=verbose,
                grpc_port=node.grpc_port,
            )
            node.process = process
            restarted += 1
        except Exception:
            logger.error("Failed to restart cluster node %d", node.node_id, exc_info=True)

    return restarted
