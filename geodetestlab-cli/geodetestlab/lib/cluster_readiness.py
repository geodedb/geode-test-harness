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
    ca_cert: str | None = None,
) -> dict | None:
    """Issue ``SHOW CLUSTER STATUS`` against the node's client port via geode query.

    Returns a dict with keys ``leader_id``, ``member_count``, ``members`` (list
    of node_ids), and ``raw_rows`` if the probe succeeded. Returns ``None``
    on any failure (unreachable, malformed, timeout, not yet ready).

    When ``ca_cert`` is provided the probe VERIFIES the node's TLS cert against
    that CA (``--server`` + ``--ca-cert``) — required on a ReleaseSafe binary,
    which refuses the insecure skip. Otherwise it uses the legacy insecure DSN
    (Debug binaries / no CA provisioned).
    """
    if ca_cert is not None:
        tls_args = ["--server", f"127.0.0.1:{port}", "--ca-cert", ca_cert]
    else:
        tls_args = ["--dsn", f"127.0.0.1:{port}?insecure=true"]
    try:
        result = subprocess.run(
            [
                binary,
                "query",
                *tls_args,
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
        # `geode query --format json` emits a single JSON object per query
        # with a `rows` array containing the actual result rows. Older code
        # mistakenly treated each output line as one row (which gave
        # member_count=1 for any cluster). Parse the object and extract rows.
        rows: list[dict] = []
        for line in result.stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            inner = obj.get("rows")
            if isinstance(inner, list):
                rows.extend(r for r in inner if isinstance(r, dict))
            elif isinstance(obj, dict) and "node_id" in obj:
                # Defensive: if the harness ever switches to JSONL-of-rows,
                # this branch still works.
                rows.append(obj)
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
    ca_cert: str | None = None,
) -> bool:
    """Wait until every node reports a consistent ready cluster state.

    Returns ``True`` if ready within ``deadline_s``; ``False`` otherwise.
    Logs progress at INFO so failures are debuggable.

    ``ca_cert`` (the cluster's provisioned CA) makes the probe verify node TLS
    certs instead of skipping verification — required on ReleaseSafe binaries.
    """
    expected_count = len(cluster_state.nodes)
    start = time.monotonic()
    last_log = 0.0
    last_obs_count = 0

    while time.monotonic() - start < deadline_s:
        observations: list[dict] = []
        for node in cluster_state.nodes:
            obs = _probe_node(binary, node.port, admin_password, ca_cert=ca_cert)
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
    # One more probe + dump for triage. The deadline window collected
    # observations but never matched all three conditions; record the
    # final state so the next iteration of A6f investigation can see
    # exactly what disagreed.
    final = []
    for node in cluster_state.nodes:
        obs = _probe_node(binary, node.port, admin_password, ca_cert=ca_cert)
        final.append((node.port, obs))
    for port, obs in final:
        logger.error(
            "Final probe port=%d obs=%r",
            port,
            obs,
        )
    return False
