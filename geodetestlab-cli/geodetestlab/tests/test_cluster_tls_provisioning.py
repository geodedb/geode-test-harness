"""Regression tests: forced-cluster mode must use VERIFIED inter-node TLS.

geode's ``cluster_auth.zig`` (GAP-0737 / SEC-INFRA-01) REFUSES
``GEODE_CLUSTER_INSECURE=1`` in any non-Debug build. The harness used to force
that flag for every ``--force-cluster-size`` cluster, so a forced cluster
against the shipping ReleaseSafe binary could never complete its inter-node
Raft TLS handshake: every peer dial failed with ``HandshakeError``, no leader
was elected, and ``wait_for_cluster_ready`` timed out after ~90s (every
promoted spec then reported failed).

``start_cluster`` now provisions a shared CA + leaf certificate and drives
geode's *verified*-TLS path (``GEODE_CLUSTER_CA_CERT`` + ``--cert`` / ``--key``)
instead, mirroring geode's own ``tests/cluster/netns_cluster_replication_test.sh``.
This works on Debug AND ReleaseSafe binaries and exercises the real peer-cert
verification path.

These tests fail against the old behavior (insecure forced, no CA cert) and
pass after the fix.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

openssl_required = pytest.mark.skipif(
    shutil.which("openssl") is None,
    reason="openssl not available — verified-TLS provisioning is skipped",
)


class _FakeProc:
    """Stand-in for subprocess.Popen so start_cluster never spawns geode."""

    def poll(self) -> None:  # alive
        return None


def _patch_cluster_io(monkeypatch) -> list[dict]:
    """Patch start_cluster's heavy I/O so the env/args wiring is testable.

    Returns a list that accumulates ``{"env": ..., "args": ...}`` for each
    node start_cluster would have launched.
    """
    import geodetestlab.lib.cluster as clustermod

    captured: list[dict] = []

    def fake_start_server(**kwargs):
        captured.append({"env": dict(kwargs["env"]), "args": list(kwargs["args"])})
        return _FakeProc()

    monkeypatch.setattr(clustermod, "start_server", fake_start_server)
    monkeypatch.setattr(clustermod, "stop_server", lambda *a, **k: None)
    monkeypatch.setattr(clustermod, "_wait_for_cluster_port", lambda *a, **k: True)
    monkeypatch.setattr(
        "geodetestlab.lib.cluster_readiness.wait_for_cluster_ready",
        lambda *a, **k: True,
    )
    return captured


@openssl_required
def test_provision_cluster_tls_emits_verifiable_ca_and_leaf() -> None:
    """The provisioned leaf must verify against the CA and carry the 127.0.0.1
    SAN that loopback cluster peers dial — i.e. it satisfies geode's
    verified-TLS handshake."""
    from geodetestlab.lib.cluster import _provision_cluster_tls

    provisioned = _provision_cluster_tls()
    assert provisioned is not None, "openssl present but provisioning returned None"
    cert_dir, ca_crt, leaf_crt, leaf_key = provisioned
    try:
        for p in (ca_crt, leaf_crt, leaf_key):
            assert Path(p).exists(), f"{p} was not generated"

        verify = subprocess.run(
            ["openssl", "verify", "-CAfile", ca_crt, leaf_crt],
            capture_output=True,
            text=True,
        )
        assert verify.returncode == 0, verify.stdout + verify.stderr

        leaf_text = subprocess.run(
            ["openssl", "x509", "-in", leaf_crt, "-noout", "-text"],
            capture_output=True,
            text=True,
        ).stdout
        assert "127.0.0.1" in leaf_text, "leaf is missing the IP:127.0.0.1 SAN"
    finally:
        shutil.rmtree(cert_dir, ignore_errors=True)


@openssl_required
def test_start_cluster_uses_verified_tls_not_insecure(monkeypatch) -> None:
    """Default forced-cluster path: every node gets GEODE_CLUSTER_CA_CERT plus
    --cert/--key and NObody gets the debug-only GEODE_CLUSTER_INSECURE=1."""
    from geodetestlab.lib.cluster import start_cluster, stop_cluster
    from geodetestlab.lib.cluster_types import ClusterConfig

    captured = _patch_cluster_io(monkeypatch)

    cfg = ClusterConfig(node_count=2)
    state = start_cluster(
        cfg,
        binary="/nonexistent/geode",
        base_env={},
        spec_server_args=["--log-level", "warn"],
        verbose=False,
    )
    cert_dir = state.cert_dir
    try:
        assert cert_dir is not None and Path(cert_dir).exists()
        assert len(captured) == 2, "expected two nodes launched"
        for node in captured:
            env, args = node["env"], node["args"]
            # The debug-only flag geode refuses in release must NOT be set.
            assert env.get("GEODE_CLUSTER_INSECURE") != "1"
            # Verified-TLS path is wired end to end.
            ca = env.get("GEODE_CLUSTER_CA_CERT")
            assert ca is not None and Path(ca).exists()
            assert "--cert" in args and "--key" in args
            assert Path(args[args.index("--cert") + 1]).exists()
            assert Path(args[args.index("--key") + 1]).exists()
    finally:
        stop_cluster(state, cleanup_data=True)
    # stop_cluster removes the provisioned cert material.
    assert not Path(cert_dir).exists()


def test_start_cluster_honors_explicit_insecure_override(monkeypatch) -> None:
    """A spec that explicitly opts into GEODE_CLUSTER_INSECURE (Debug-only)
    keeps that choice and skips cert provisioning."""
    from geodetestlab.lib.cluster import start_cluster, stop_cluster
    from geodetestlab.lib.cluster_types import ClusterConfig

    captured = _patch_cluster_io(monkeypatch)

    cfg = ClusterConfig(node_count=2, shared_env={"GEODE_CLUSTER_INSECURE": "1"})
    state = start_cluster(
        cfg,
        binary="/nonexistent/geode",
        base_env={},
        spec_server_args=["--log-level", "warn"],
        verbose=False,
    )
    try:
        assert state.cert_dir is None, "cert provisioning should be skipped"
        for node in captured:
            assert node["env"].get("GEODE_CLUSTER_INSECURE") == "1"
            assert "GEODE_CLUSTER_CA_CERT" not in node["env"]
    finally:
        stop_cluster(state, cleanup_data=True)
