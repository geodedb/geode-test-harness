"""Cluster-level readiness probe.

Polls ``SHOW CLUSTER STATUS`` on each node and waits for all nodes to
report a consistent ready cluster state:

  - leader_id is the same on every node
  - leader_id != 0  (election has actually completed)
  - member_count == expected node count

This is the gate ``start_cluster`` uses before returning a ``ClusterState``
to the spec runner. Previously start_cluster only waited for each node's
QUIC listener to come up; that was insufficient because raft election can
take an additional 100-500ms over real QUIC and specs that issued queries
before election completed got transient "no leader" errors.
"""

from __future__ import annotations

import json
import logging
import subprocess
import time

from .cluster_types import ClusterState

logger = logging.getLogger(__name__)


def _probe_node(
    binary: str,
    port: int,
    admin_password: str,
    timeout_s: float = 2.0,
) -> dict | None:
    """Issue ``SHOW CLUSTER STATUS`` against the node's client port via geode query.

    Returns a dict with keys ``leader_id``, ``member_count``, ``members`` (list
    of node_ids), and ``raw_rows`` if the probe succeeded. Returns ``None``
    on any failure (unreachable, malformed, timeout, not yet ready).
    """
    try:
        result = subprocess.run(
            [
                binary,
                "query",
                "--dsn",
                f"127.0.0.1:{port}?insecure=true",
                "--user",
                "geode",
                "--pass",
                admin_password,
                "--format",
                "json",
                "SHOW CLUSTER STATUS",
            ],
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )
        if result.returncode != 0:
            return None
        # `geode query --format json` outputs JSONL: one row per line.
        rows: list[dict] = []
        for line in result.stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                # Tolerate non-JSON log noise on stdout; only count parseable rows.
                continue
        if not rows:
            return None
        leader_ids = {r.get("leader_id") for r in rows if "leader_id" in r}
        leader_id = next(iter(leader_ids)) if len(leader_ids) == 1 else None
        return {
            "leader_id": leader_id,
            "member_count": len(rows),
            "members": [r.get("node_id") for r in rows],
            "raw_rows": rows,
        }
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return None


def wait_for_cluster_ready(
    cluster_state: ClusterState,
    *,
    binary: str,
    admin_password: str = "GeodeTestPassword123!",
    deadline_s: float = 60.0,
    poll_interval_s: float = 1.0,
) -> bool:
    """Wait until every node reports a consistent ready cluster state.

    Returns ``True`` if ready within ``deadline_s``; ``False`` otherwise.
    Logs progress at INFO so failures are debuggable.
    """
    expected_count = len(cluster_state.nodes)
    start = time.monotonic()
    last_log = 0.0
    last_obs_count = 0

    while time.monotonic() - start < deadline_s:
        observations: list[dict] = []
        for node in cluster_state.nodes:
            obs = _probe_node(binary, node.port, admin_password)
            if obs is None:
                break
            observations.append(obs)

        last_obs_count = len(observations)

        if len(observations) == expected_count:
            leader_ids = {o["leader_id"] for o in observations if o["leader_id"]}
            member_counts = {o["member_count"] for o in observations}
            if len(leader_ids) == 1 and 0 not in leader_ids and member_counts == {expected_count}:
                elapsed = time.monotonic() - start
                logger.info(
                    "Cluster ready: leader=%s, members=%d, elapsed=%.1fs",
                    next(iter(leader_ids)),
                    expected_count,
                    elapsed,
                )
                return True

        # Throttle log spam to once per 5s.
        now = time.monotonic()
        if now - last_log >= 5.0:
            logger.info(
                "Cluster not yet ready: observations=%d/%d",
                len(observations),
                expected_count,
            )
            last_log = now

        time.sleep(poll_interval_s)

    elapsed = time.monotonic() - start
    logger.error(
        "Cluster failed to reach ready within %.1fs (last observations=%d/%d)",
        elapsed,
        last_obs_count,
        expected_count,
    )
    return False
