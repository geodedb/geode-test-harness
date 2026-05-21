# Spec Gap Closure — Authn Methods Sub-Plan

> **For agentic workers:** Use `superpowers:subagent-driven-development` or `superpowers:executing-plans`.

**Goal:** Close GAP-0310..GAP-0316 by producing 7 spec files covering Argon2id parameter floor, MFA TOTP edges, mTLS rejection matrix, API key revocation, BLAKE2b migration, rate limiter, and timing-attack invariance.

**Source references:**

- `../geode/src/security/authn.zig` — Argon2id config, session rotation, constant-time compares
- `../geode/src/security/mfa.zig`, `mfa_risk.zig` — MFA TOTP
- `../geode/src/security/mtls_provider.zig` — mTLS handshake
- `../geode/src/security/test_blake2b_migration.zig` — internal migration test (pattern reference)
- `../geode/src/security/test_timing_attacks.zig` — internal timing test (pattern reference)
- `../geode/src/server/auth_rate_limiter.zig` — rate limiter
- `../geode/src/cli/apikey_cli.zig` — API key CLI
- Existing: `api_key_auth.yml`, `mfa_comprehensive_security.yml`, `distributed_mfa_totp.yml`, `gap_0258_mtls_cli.yml`

---

## File Structure

```text
geodetestlab-cli/specs/
├── authn_argon2id_min_params.yml          # GAP-0310
├── authn_mfa_totp_edges.yml               # GAP-0311
├── authn_mtls_rejection_matrix.yml        # GAP-0312
├── authn_apikey_revocation.yml            # GAP-0313
├── authn_blake2b_migration.yml            # GAP-0314
├── authn_rate_limiter.yml                 # GAP-0315
└── authn_timing_invariance.yml            # GAP-0316
```

---

## Task 1: GAP-0310 — Argon2id parameter floor

**Files:** `geodetestlab-cli/specs/authn_argon2id_min_params.yml`

**Acceptance:**

- Server with `GEODE_ARGON2_MEMORY_MIB=1` env (or config file) → `geode serve` exits non-zero with `ARGON2_PARAMS_TOO_WEAK` on stderr.
- Same with `GEODE_ARGON2_ITERATIONS=1`.
- Default config → starts successfully; CREATE USER produces hash with documented params (verifiable in storage inspect if available, else implicit).

If geode does not expose these as configurable env vars, document that the floor is hardcoded and the spec verifies *current behavior* (hash format produces required parameters).

- [ ] **Step 1:** Write, [ ] **Step 2:** Validate, [ ] **Step 3:** Commit, [ ] **Step 4:** Update GAP_ANALYSIS.md.

---

## Task 2: GAP-0311 — MFA TOTP edge cases

**Files:** `geodetestlab-cli/specs/authn_mfa_totp_edges.yml`

**Acceptance:**

- Enable MFA for user; record TOTP secret.
- Submit TOTP at exact boundary (computed via `oathtool` or `python -c "import pyotp; print(pyotp.TOTP(s).now())"`) → accepted.
- Replay same TOTP within window → rejected (replay protection).
- 5 consecutive bad TOTPs → user locked out; next login blocked even with correct code.
- Lockout window expiry → login succeeds.

If `oathtool` not available in test env, document; alternative: use a fixed-time TOTP fixture via env var that shifts server clock (likely not supported), or test the failure cases only.

- [ ] **Step 1:** Write, [ ] **Step 2:** Validate, [ ] **Step 3:** Commit, [ ] **Step 4:** Update GAP_ANALYSIS.md.

---

## Task 3: GAP-0312 — mTLS rejection matrix

**Files:** `geodetestlab-cli/specs/authn_mtls_rejection_matrix.yml`

**Acceptance:**

- Pre-generated test certs in `geodetestlab-cli/specs/encryption/` (if exists; else generate in `bash` setup via `openssl req`).
- Three rejection cases:
  - Client cert expired → handshake fails, exit ≠ 0
  - Client CA not in server truststore → handshake fails
  - Client cert CN doesn't match expected → handshake fails
- One positive case: valid cert → connects.

- [ ] **Step 1:** Write, [ ] **Step 2:** Validate, [ ] **Step 3:** Commit, [ ] **Step 4:** Update GAP_ANALYSIS.md.

---

## Task 4: GAP-0313 — API key revocation latency

**Files:** `geodetestlab-cli/specs/authn_apikey_revocation.yml`

**Acceptance:**

- Issue API key via `geode apikey create`
- Authenticate via key → success
- Revoke key via `geode apikey revoke <id>`
- Authenticate within session-rotation interval → 28000

- [ ] **Step 1:** Write, [ ] **Step 2:** Validate, [ ] **Step 3:** Commit, [ ] **Step 4:** Update GAP_ANALYSIS.md.

---

## Task 5: GAP-0314 — BLAKE2b migration

**Files:** `geodetestlab-cli/specs/authn_blake2b_migration.yml`

**Acceptance:** Direct seeding of a BLAKE2b-format hash via `geode admin user-import` or a storage manipulation. If no admin path exists, document and seek alternate testing strategy (e.g. running an older geode version to seed, then upgrading).

If unable to seed legacy hash externally, mark `skip: true` with `skip_reason: "legacy hash seeding requires admin import command not yet available"` and close GAP-0314 as `Blocked` with rationale.

- [ ] **Step 1:** Write, [ ] **Step 2:** Validate, [ ] **Step 3:** Commit, [ ] **Step 4:** Update GAP_ANALYSIS.md.

---

## Task 6: GAP-0315 — Auth rate limiter

**Files:** `geodetestlab-cli/specs/authn_rate_limiter.yml`

**Acceptance:**

- 6 failed logins from same client (default limiter is 5)
- 7th attempt with correct password → still blocked (rate limited, not authn-rejected)
- Wait for window expiry; correct password succeeds
- Audit log records `rate_limited` events

- [ ] **Step 1:** Write, [ ] **Step 2:** Validate, [ ] **Step 3:** Commit, [ ] **Step 4:** Update GAP_ANALYSIS.md.

---

## Task 7: GAP-0316 — Timing invariance

**Files:** `geodetestlab-cli/specs/authn_timing_invariance.yml`

**Acceptance:**

- 1000 login attempts each scenario (valid-user-bad-password, invalid-user-any-password)
- Capture latency via shell `time` or `geode metrics`
- Mean latency diff < 1 ms (or per documented threshold)
- Statistical test: Welch's t-test p-value > 0.01

Implementation: A `bash` step runs a small Python helper inline that issues N requests and computes statistics. Document threshold based on first observed run if no explicit SLO exists.

- [ ] **Step 1:** Write, [ ] **Step 2:** Validate, [ ] **Step 3:** Commit, [ ] **Step 4:** Update GAP_ANALYSIS.md.

---

## Final Steps

- [ ] `python -m geodetestlab run --specs specs --filter authn -v` all green.
- [ ] Commit `docs(gap): close GAP-0310..GAP-0316 — Authn methods`.
