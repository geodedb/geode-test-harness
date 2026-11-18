"""The harness default admin password must satisfy geode's passphrase policy.

geode rejects a weaker password with a forced reset on first login, which made
every spec need a per-run GEODE_ADMIN_PASSWORD override. Policy (geode
src/security/geode_auth_lib.zig PasswordPolicy defaults): at least 25
characters, at least 4 space-separated words, upper and lower case.
"""

from __future__ import annotations

import os
from pathlib import Path

from geodetestlab.lib import runner_types

OLD_DEFAULT = "GeodeTestPassword123" + "!"
SPECS = Path(__file__).resolve().parents[2] / "specs"


def _policy_violation(pw: str) -> str | None:
    if len(pw) < 25:
        return "too short"
    if len(pw.split()) < 4:
        return "fewer than 4 words"
    if not any(c.isupper() for c in pw) or not any(c.islower() for c in pw):
        return "needs upper and lower case"
    return None


def test_default_admin_password_satisfies_passphrase_policy() -> None:
    if "GEODE_ADMIN_PASSWORD" in os.environ:
        return  # the module constant reflects an operator override
    assert _policy_violation(runner_types.DEFAULT_ADMIN_PASSWORD) is None


def test_no_spec_falls_back_to_the_rejected_password() -> None:
    offenders = [p.name for p in SPECS.glob("*.yml") if OLD_DEFAULT in p.read_text(encoding="utf-8")]
    assert offenders == []
