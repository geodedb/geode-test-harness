"""Shared TLS-certificate provisioning for the test harness.

geode's release builds (``cluster_auth.zig`` GAP-0737 for cluster transport,
``insecure_tls_gate.zig`` for the ``geode query`` client) REFUSE every
"skip TLS verification" knob — ``GEODE_CLUSTER_INSECURE=1`` and
``--insecure-tls-skip-verify``. To run the whole suite against a ReleaseSafe
binary we instead provision a private CA + a leaf certificate (loopback SANs),
start every server with that leaf (``--cert``/``--key``), and point both the
intra-cluster transport (``GEODE_CLUSTER_CA_CERT``) and the client
(``--ca-cert``) at the CA so they VERIFY peers/servers over QUIC+TLS.

This is the same recipe geode's own
``tests/cluster/netns_cluster_replication_test.sh`` uses, and it works
identically on Debug and ReleaseSafe binaries — no security knob disabled.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)


def args_contain_flag(args: list[str], flag: str) -> bool:
    """Return True if ``args`` already carries ``flag`` (``--x`` or ``--x=v``)."""
    return any(a == flag or a.startswith(flag + "=") for a in args)


def provision_tls_certs() -> tuple[str, str, str, str] | None:
    """Generate a private CA + leaf certificate for loopback TLS.

    Returns ``(cert_dir, ca_crt, leaf_crt, leaf_key)`` or ``None`` when
    ``openssl`` is unavailable (callers then fall back to the debug-only
    insecure path).

    The leaf carries loopback SANs (``IP:127.0.0.1``, ``DNS:localhost``) and is
    signed by the CA, so geode's verified-TLS paths accept it without any
    insecure flag — see module docstring.
    """
    if shutil.which("openssl") is None:
        return None

    cert_dir = tempfile.mkdtemp(prefix="geode-test-tls-")
    ca_key = str(Path(cert_dir) / "ca.key")
    ca_crt = str(Path(cert_dir) / "ca.crt")
    leaf_key = str(Path(cert_dir) / "leaf.key")
    leaf_csr = str(Path(cert_dir) / "leaf.csr")
    leaf_crt = str(Path(cert_dir) / "leaf.crt")
    leaf_ext = str(Path(cert_dir) / "leaf.ext")

    Path(leaf_ext).write_text("subjectAltName=IP:127.0.0.1,DNS:localhost\nextendedKeyUsage=serverAuth,clientAuth\n")

    def _run(cmd: list[str]) -> None:
        subprocess.run(cmd, check=True, capture_output=True)

    try:
        _run(["openssl", "ecparam", "-name", "prime256v1", "-genkey", "-noout", "-out", ca_key])
        _run(
            [
                "openssl",
                "req",
                "-x509",
                "-new",
                "-key",
                ca_key,
                "-days",
                "2",
                "-subj",
                "/CN=geode-test-ca",
                "-addext",
                "basicConstraints=critical,CA:TRUE",
                "-out",
                ca_crt,
            ]
        )
        _run(["openssl", "ecparam", "-name", "prime256v1", "-genkey", "-noout", "-out", leaf_key])
        _run(
            [
                "openssl",
                "req",
                "-new",
                "-key",
                leaf_key,
                "-subj",
                "/CN=geode-node",
                "-out",
                leaf_csr,
            ]
        )
        _run(
            [
                "openssl",
                "x509",
                "-req",
                "-in",
                leaf_csr,
                "-CA",
                ca_crt,
                "-CAkey",
                ca_key,
                "-CAcreateserial",
                "-days",
                "2",
                "-extfile",
                leaf_ext,
                "-out",
                leaf_crt,
            ]
        )
    except (subprocess.CalledProcessError, OSError):
        logger.warning("openssl TLS provisioning failed; falling back to insecure path", exc_info=True)
        shutil.rmtree(cert_dir, ignore_errors=True)
        return None

    return cert_dir, ca_crt, leaf_crt, leaf_key


def client_tls_args(env: dict[str, str], existing_args: list[str] | None = None) -> list[str]:
    """Return the TLS args a ``geode query`` client should use.

    - If ``GEODE_TEST_CA_CERT`` names a readable CA file → verified TLS via
      ``--ca-cert <ca>`` (works on Debug AND ReleaseSafe).
    - Otherwise → ``--insecure-tls-skip-verify`` (the legacy debug-only path,
      for environments without openssl / when no CA was provisioned).

    If the caller's ``existing_args`` already specify a TLS posture
    (``--ca-cert``, ``--insecure-tls-skip-verify``, or ``--insecure``), returns
    an empty list so the explicit choice is preserved.
    """
    if existing_args is not None and (
        args_contain_flag(existing_args, "--ca-cert")
        or args_contain_flag(existing_args, "--insecure-tls-skip-verify")
        or args_contain_flag(existing_args, "--insecure")
    ):
        return []
    ca = env.get("GEODE_TEST_CA_CERT")
    if ca and Path(ca).exists():
        return ["--ca-cert", ca]
    return ["--insecure-tls-skip-verify"]


def reconcile_client_tls(cmd: list[str], args: list[str], env: dict[str, str]) -> list[str]:
    """Reconcile an already-built QUIC client command's TLS posture.

    A release / ReleaseSafe geode binary REFUSES ``--insecure`` and
    ``--insecure-tls-skip-verify`` (``insecure_tls_gate.zig``). Many specs were
    authored against a Debug binary and pass one of those flags explicitly in
    their ``args:``. When a verified CA has been provisioned for this run
    (``GEODE_TEST_CA_CERT``), drop that spec-supplied insecure flag from the
    built command and verify against the CA via ``--ca-cert`` instead — the
    connection then works identically on Debug AND release with no security knob
    disabled (the same recipe geode's own netns cluster tests use).

    Without a provisioned CA (openssl missing, or the spec brought its own
    ``--cert``) keep the legacy debug-only behaviour: honour an explicit
    insecure/``--ca-cert`` posture, otherwise add ``--insecure-tls-skip-verify``.

    ``args`` is the spec's raw argument list (used to detect an explicit posture);
    ``cmd`` is the fully built ``[binary, ...]`` command to be executed.
    """
    # An INTENTIONAL insecure escape hatch (GEODE_ALLOW_INSECURE_TLS=1) must be
    # respected — it is used for the backup/restore streaming commands whose
    # verified-TLS (--ca-cert) handshake stalls on a release binary (a tracked
    # geode bug). Do not swap their insecure flag back to --ca-cert.
    if env.get("GEODE_ALLOW_INSECURE_TLS") == "1" and ("--insecure" in cmd or "--insecure-tls-skip-verify" in cmd):
        return cmd
    ca = env.get("GEODE_TEST_CA_CERT")
    if ca and Path(ca).exists():
        cmd = [c for c in cmd if c not in ("--insecure", "--insecure-tls-skip-verify")]
        if "--ca-cert" not in cmd:
            cmd = cmd + ["--ca-cert", ca]
        return cmd
    # No provisioned CA → legacy debug-only path; respect an explicit posture.
    already = (
        args_contain_flag(args, "--insecure-tls-skip-verify")
        or args_contain_flag(args, "--insecure")
        or args_contain_flag(args, "--ca-cert")
        or "--ca-cert" in cmd
        or "--insecure-tls-skip-verify" in cmd
        or "--insecure" in cmd
    )
    if not already:
        cmd = cmd + ["--insecure-tls-skip-verify"]
    return cmd
