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


def test_no_spec_expectation_loaded_as_a_yaml_boolean_or_null() -> None:
    """`- yes` / `- off` unquoted load as booleans (YAML 1.1) and never match output.

    A formatter that strips quotes turned `'yes'` into `True`; keep such scalars quoted.
    """
    import yaml

    bad: list[str] = []
    keys = {"stdout_contains", "stdout_not_contains", "stderr_contains", "stderr_not_contains", "args"}

    def walk(x: object, where: str) -> None:
        if isinstance(x, dict):
            for k, v in x.items():
                if k in keys and isinstance(v, list):
                    bad.extend(f"{where}:{k}={i!r}" for i in v if isinstance(i, bool) or i is None)
                walk(v, where)
        elif isinstance(x, list):
            for i in x:
                walk(i, where)

    for p in sorted(SPECS.glob("*.yml")):
        walk(yaml.safe_load(p.read_text(encoding="utf-8")), p.name)
    assert bad == []
