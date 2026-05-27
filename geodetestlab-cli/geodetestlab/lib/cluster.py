"""Cluster lifecycle management for multi-node Geode testing.

Provides functions to start, stop, health-check, and restart
multi-node Geode clusters using the existing single-server primitives
from ``server.py``.
"""

from __future__ import annotations

import logging
import secrets
import shutil
import socket
import tempfile
import time
from pathlib import Path

from .cluster_types import ClusterConfig, ClusterNodeState, ClusterState
from .runner_types import DEFAULT_ADMIN_PASSWORD
from .server import start_server, stop_server
from .utils import get_free_port

logger = logging.getLogger(__name__)

# Maximum u16 port value. Used to guard against overflow when deriving
# cluster_port = client_port + CLUSTER_PORT_OFFSET.
U16_MAX_PORT = 65535


def _derive_cluster_port(client_port: int) -> int:
    """Derive a cluster_port for a given client_port that fits in u16.

    Adds 1000 normally; falls back to subtracting 1000 when the addition
    would exceed 65535 (geode's port parser rejects u16-overflowing
    values with InvalidPeerSpec). On Linux the kernel ephemeral port
    range can extend up to 65535, so `client_port = 65000` from
    get_free_port() would overflow if we naively added 1000.
    """
    if client_port + 1000 <= U16_MAX_PORT:
        return client_port + 1000
    # Fall back: subtract 1000 (client_port is always >= 1024 from kernel)
    return client_port - 1000


# Kept for backwards-compat with callers that still reference the constant.
CLUSTER_PORT_OFFSET = 1000


def _udp_port_bound(port: int) -> bool:
    """Return True iff the given UDP port is bound by another process.

    QUIC uses UDP; geode's intra-cluster QUIC listener binds the cluster_port.
    The bind-probe pattern matches server._port_is_bound: try to bind, OSError
    means the port is in use (= listener is up).
    """
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.bind(("127.0.0.1", port))
            return False
    except OSError:
        return True


def _wait_for_cluster_port(port: int, deadline_s: float = 15.0) -> bool:
    """Wait until ``port`` is bound (i.e. the cluster's intra-cluster QUIC
    listener is up). Returns True on success, False on timeout.

    Without this gate, ``start_cluster`` proceeds to start node N+1 before
    node N's cluster_port is listening, which under simultaneous mutual
    dialing can cause asymmetric handshake failures (one direction of one
    peer pair fails permanently while others succeed).
    """
    start = time.monotonic()
    while time.monotonic() - start < deadline_s:
        if _udp_port_bound(port):
            return True
        time.sleep(0.05)
    return False


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
    # Raft (raft-0.1.3) rejects node_id=0 as InvalidId. Harness counters
    # are 0-indexed for cluster_state.nodes lookups, so we remap to 1-indexed
    # when injecting into geode's env. The geode-side subprocess smoke test
    # (tests/test_cluster_3node_subprocess.zig) uses the same 1-indexed
    # convention.
    env["GEODE_NODE_ID"] = str(node_id + 1)

    if grpc_port is not None:
        env["GEODE_GRPC_ADDRESS"] = f"127.0.0.1:{grpc_port}"

    # Inject the intra-cluster Raft QUIC port. Convention: client_port + 1000.
    # Geode's cluster_bootstrap reads GEODE_CLUSTER_PORT to bind the
    # intra-cluster listener separately from the client-facing QUIC port.
    cluster_port = _derive_cluster_port(port)
    env["GEODE_CLUSTER_PORT"] = str(cluster_port)

    # Auto-generate a per-spec cluster token if the spec did not set one.
    # All nodes in this start_cluster() invocation share the same env source
    # so they get the same token. The token authenticates intra-cluster RPC.
    if "GEODE_CLUSTER_TOKEN" not in env:
        env["GEODE_CLUSTER_TOKEN"] = secrets.token_hex(16)

    # Loopback cluster traffic still goes through QUIC+TLS but with
    # self-signed certs, so we must opt the test harness into the debug-only
    # insecure-TLS path. Specs can override by setting the env to "0".
    if "GEODE_CLUSTER_INSECURE" not in env:
        env["GEODE_CLUSTER_INSECURE"] = "1"

    # Build peer list using CLUSTER ports, not client ports. The intra-cluster
    # listener binds to cluster_port, so peers must dial that port to reach
    # the raft transport. Before this fix, peers pointed at client ports and
    # raft RPC silently dropped.
    #
    # We emit ALL nodes in the cluster (including self) in a stable order
    # so each geode bootstrap can derive a peer's node_id directly from its
    # position in the list (idx+1). The bootstrap skips the self entry by
    # matching the cluster port. This keeps node_id assignment globally
    # consistent — without it, when node N has self_id=N, peer position
    # collisions cause node N's view of the cluster to be smaller than
    # peers' views, which breaks Raft quorum.
    if all_ports is not None:
        all_cluster_ports = [_derive_cluster_port(p) for p in all_ports]
        env["GEODE_PEERS"] = ",".join(f"127.0.0.1:{cp}" for cp in all_cluster_ports)

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
    # Pre-generate ONE GEODE_CLUSTER_TOKEN for the whole cluster and inject
    # it into config.shared_env so every node sees the same token. Without
    # this, _build_node_env's per-node auto-generation gave each of the N
    # nodes a different token, and they rejected each other's raft frames
    # ("Raft frame rejected: invalid or missing cluster token from=X").
    #
    # Check both config.shared_env AND base_env so specs that explicitly
    # set GEODE_CLUSTER_TOKEN via spec.env (e.g. the 2pc cluster-token
    # enforcement test) keep their declared value when the harness promotes
    # them to cluster mode via --force-cluster-size.
    if "GEODE_CLUSTER_TOKEN" not in config.shared_env and "GEODE_CLUSTER_TOKEN" not in base_env:
        config.shared_env["GEODE_CLUSTER_TOKEN"] = secrets.token_hex(16)
    elif "GEODE_CLUSTER_TOKEN" in base_env and "GEODE_CLUSTER_TOKEN" not in config.shared_env:
        # Promote the spec-supplied token from base_env into shared_env so
        # _build_node_env's shared_env-wins-over-base_env layering doesn't
        # accidentally lose it when another shared_env key is set.
        config.shared_env["GEODE_CLUSTER_TOKEN"] = base_env["GEODE_CLUSTER_TOKEN"]

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

        # Wait for this node's intra-cluster QUIC listener to come up before
        # starting the next node. Otherwise the next node would immediately
        # try to dial all peers (including this one) while this one's
        # cluster_port is still binding, producing asymmetric handshake
        # failures under simultaneous startup.
        cluster_port = _derive_cluster_port(ports[i])
        if not _wait_for_cluster_port(cluster_port, deadline_s=15.0):
            logger.warning(
                "Node %d cluster_port %d did not bind within 15s; continuing anyway",
                i,
                cluster_port,
            )

    # Per-process QUIC listeners are up — now wait for raft to elect a leader
    # and for every node to agree on the membership view. This is the real
    # readiness gate; without it, specs that query the cluster right after
    # start_cluster would race the election window.
    from .cluster_readiness import wait_for_cluster_ready

    final_state = ClusterState(nodes=nodes)
    deadline_s = max(60.0, config.startup_timeout_ms / 1000.0)
    if not wait_for_cluster_ready(
        final_state,
        binary=binary,
        admin_password=base_env.get("GEODE_ADMIN_PASSWORD", DEFAULT_ADMIN_PASSWORD),
        deadline_s=deadline_s,
    ):
        stop_cluster(final_state, verbose=verbose, cleanup_data=True)
        msg = f"Cluster of {config.node_count} nodes failed to reach READY within {deadline_s:.0f}s"
        raise RuntimeError(msg)

    return final_state


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
