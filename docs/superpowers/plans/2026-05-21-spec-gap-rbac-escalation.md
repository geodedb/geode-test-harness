# Spec Gap Closure — RBAC Escalation Prevention Sub-Plan

> **For agentic workers:** Use `superpowers:subagent-driven-development` or `superpowers:executing-plans`.

**Goal:** Close GAP-0287..GAP-0292 by producing 6 spec files that pin RBAC privilege-escalation invariants and the documented limitations (custom role binding, GRANT WRITE chain corruption).

**Architecture:** Template is `geodetestlab-cli/specs/rbac_users_roles_grants_audit.yml`. Each spec stresses one escalation vector. Pinning gaps (#1, #3) are explicit trip-wires: they assert current broken behavior and must fail once the underlying server bug is fixed.

**Source references:**

- `../geode/src/security/auth_graph_manager.zig` — HMAC chain & policy persistence (lines :786, :1037, :1158)
- `../geode/src/security/user_manager.zig`, `user_management.zig`
- `../geode/src/server/quic_connection_handler.zig:3382` — runtime mutation gate
- `../geode/src/server/server_init.zig:723-731` — admin path role assignment
- Existing spec: `geodetestlab-cli/specs/rbac_users_roles_grants_audit.yml`

---

## File Structure

```text
geodetestlab-cli/specs/
├── rbac_concurrent_alter_user.yml             # GAP-0287
├── rbac_custom_role_binding_pin.yml           # GAP-0288 (trip-wire)
├── rbac_grant_write_chain_corruption_pin.yml  # GAP-0289 (trip-wire)
├── rbac_revoke_invalidates_session.yml        # GAP-0290
├── rbac_alter_user_nonexistent_role.yml       # GAP-0291
└── rbac_drop_user_terminates_sessions.yml     # GAP-0292
```

---

## Task 1: GAP-0287 — Concurrent ALTER USER race

**Files:**

- Create: `geodetestlab-cli/specs/rbac_concurrent_alter_user.yml`

**Test approach (the harness runs sequentially; race is simulated via tight back-to-back ALTERs and chain-verification after):**

- [ ] **Step 1: Write spec**

Use `bash` test steps that fire 2-3 parallel `geode query ALTER USER bob SET ROLE X` via `&` and `wait`. Then assert:

- Final role is one of the requested values (last writer wins)
- HMAC chain seals correctly on restart (no `AuthChainTampered`)
- No intermediate state granted bob `admin` (verify via audit log scan)

Acceptance: spec uses two parallel ALTERs (`readwrite` and `readonly`), restarts, asserts final role is exactly one of those two, never `admin`, and chain is intact.

- [ ] **Step 2: Validate** via `python -m geodetestlab run --spec specs/rbac_concurrent_alter_user.yml -v`
- [ ] **Step 3: Commit** `test(rbac): close GAP-0287 — concurrent ALTER USER race`
- [ ] **Step 4: Update GAP_ANALYSIS.md** mark GAP-0287 Closed.

---

## Task 2: GAP-0288 — Custom role binding trip-wire

**Files:**

- Create: `geodetestlab-cli/specs/rbac_custom_role_binding_pin.yml`

**Pin current broken behavior; flip is the regression-of-fix detector.**

- [ ] **Step 1: Write spec**

```yaml
version: '1.0'
name: RBAC — custom role binding pin (header gap #3 trip-wire)
description: |
  PIN test for the documented limitation in rbac_users_roles_grants_audit.yml
  header gap #3: CREATE USER ... ROLE custom_role silently maps the user
  to the .User builtin (no privileges from custom_role).
  This spec ASSERTS the broken behavior. When the bug is fixed, this spec
  MUST fail — that is the regression-of-fix detector. Update the spec at
  that point to flip the assertion to positive (write succeeds).
  CANARY: REQ=REQ-RBAC-CUSTOM-BIND-PIN; FEATURE="RBAC custom role binding"; ASPECT=KnownLimitationPin; STATUS=PIN; OWNER=security; UPDATED=2026-05-21
cli:
  binary: ./zig-out/bin/geode
  server:
    enabled: true
    args: [--log-level, warn]
  client:
    timeout_ms: 30000
    format: json
secrets:
  admin_password: { source: env, key: GEODE_ADMIN_PASSWORD, required: false, default: Geode Test Admin Passphrase }
invariants:
- type: server_running
tests:
- name: pin-cleanup
  args: [query, -U, geode, -P, '${secret:admin_password}', '-']
  stdin: |
    DROP USER IF EXISTS rbac_pin_dan;
    DROP ROLE IF EXISTS rbac_pin_writer;
  expect: { exit_code: 0 }
  tags: [rbac, setup]
- name: pin-create-custom-role
  args: [query, -U, geode, -P, '${secret:admin_password}', CREATE ROLE rbac_pin_writer]
  expect: { exit_code: 0 }
  tags: [rbac, setup]
- name: pin-create-user-with-custom-role
  args: [query, -U, geode, -P, '${secret:admin_password}', CREATE USER rbac_pin_dan SET PASSWORD 'RbacPin-Dan-1234' ROLE rbac_pin_writer]
  expect: { exit_code: 0 }
  tags: [rbac, setup]
- name: pin-write-denied-because-fallback-to-user
  description: |
    KNOWN LIMITATION — custom role does not actually bind. dan is effectively
    .User and CANNOT write. When this fails, the bind has been fixed; flip
    this assertion.
  args: [query, -U, rbac_pin_dan, -P, RbacPin-Dan-1234, '-']
  stdin: 'CREATE (n:RbacPinNode {v: 1}) RETURN n'
  expect:
    exit_code: 0
    stdout_contains: ['42501', Permission denied]
  tags: [rbac, pin, negative, known_limitation, trip_wire]
- name: pin-cleanup-final
  args: [query, -U, geode, -P, '${secret:admin_password}', '-']
  stdin: |
    DROP USER IF EXISTS rbac_pin_dan;
    DROP ROLE IF EXISTS rbac_pin_writer;
  expect: { exit_code: 0 }
  tags: [rbac, teardown]
tags: [rbac, pin, known_limitation, trip_wire, security]
```

- [ ] **Step 2:** Validate, [ ] **Step 3:** Commit `test(rbac): pin GAP-0288 — custom role binding limitation`, [ ] **Step 4:** Update GAP_ANALYSIS.md.

---

## Task 3: GAP-0289 — GRANT WRITE chain corruption trip-wire

**Files:**

- Create: `geodetestlab-cli/specs/rbac_grant_write_chain_corruption_pin.yml`

**Pattern:** Mirror Task 2 — issue `GRANT WRITE ON GRAPH g TO u`, restart, assert restart fails with `AuthChainTampered` or `RecordHmacMismatch`. When the underlying server bug is fixed, restart succeeds and this spec must fail — flip the assertion.

WARNING: This spec corrupts the auth chain. Each run must start with a clean data dir (`cleanup: true` in `server:` block). Document this in the spec description.

- [ ] **Step 1:** Write spec, [ ] **Step 2:** Validate, [ ] **Step 3:** Commit `test(rbac): pin GAP-0289 — GRANT WRITE chain corruption`, [ ] **Step 4:** Update GAP_ANALYSIS.md.

---

## Task 4: GAP-0290 — REVOKE invalidates active session

**Files:**

- Create: `geodetestlab-cli/specs/rbac_revoke_invalidates_session.yml`

**Acceptance:** Use `geode shell` (interactive runner) to hold a session open, admin ALTERs role to readonly via a separate process, then send a WRITE command via the held session and assert 42501.

This requires the interactive shell runner pattern. Reference: existing shell-stability specs like `shell_session_stability.yml`. If the harness cannot reliably keep a session open across admin actions, the spec uses the regular query runner with a short-lived session and a `sleep` step in between — document the limitation.

- [ ] **Step 1:** Write spec, [ ] **Step 2:** Validate, [ ] **Step 3:** Commit, [ ] **Step 4:** Update GAP_ANALYSIS.md.

---

## Task 5: GAP-0291 — ALTER USER nonexistent role

**Files:**

- Create: `geodetestlab-cli/specs/rbac_alter_user_nonexistent_role.yml`

**Pin current behavior (silent fallback to .User).** Assert: ALTER USER bob SET ROLE this_role_dne returns exit_code 0 (silent) AND bob is still readonly (verify via SHOW USERS or a write attempt → 42501). Tag `known_limitation`; flip when geode rejects unknown roles explicitly.

- [ ] **Step 1:** Write spec, [ ] **Step 2:** Validate, [ ] **Step 3:** Commit, [ ] **Step 4:** Update GAP_ANALYSIS.md.

---

## Task 6: GAP-0292 — DROP USER terminates sessions

**Files:**

- Create: `geodetestlab-cli/specs/rbac_drop_user_terminates_sessions.yml`

**Acceptance:** Hold session for bob; admin DROP USER bob; bob's next query returns 28000 or 42501.

- [ ] **Step 1:** Write spec, [ ] **Step 2:** Validate, [ ] **Step 3:** Commit, [ ] **Step 4:** Update GAP_ANALYSIS.md.

---

## Final Steps

- [ ] **Step 7:** `python -m geodetestlab run --specs specs --filter rbac -v` all green.
- [ ] **Step 8:** Commit `docs(gap): close GAP-0287..GAP-0292 — RBAC escalation prevention`.
