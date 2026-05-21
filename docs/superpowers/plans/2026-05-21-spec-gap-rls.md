# Spec Gap Closure — RLS (Row-Level Security) Sub-Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` or `superpowers:executing-plans` to implement this plan task-by-task.

**Goal:** Close GAP-0280..GAP-0286 by producing 7 spec files under `geodetestlab-cli/specs/` that exhaustively verify RLS behavior across cross-tenant SELECT, VM bounds, cache invalidation, indeterminate-policy → deny, ABAC integration, injection resistance, and RLS×FLE interaction.

**Architecture:** One spec per gap. Each spec follows the canonical pattern from `geodetestlab-cli/specs/distributed_rls_enforcement.yml` and `gps_phase2_decide_comprehensive.yml`: idempotent setup, seed data, baseline admin checks, policy creation, restricted-user assertions (negative pinned by `42501` / 0-row result), audit assertions, teardown.

**Tech Stack:** YAML spec format, `./zig-out/bin/geode` binary, `--transport quic` (default) or `--transport grpc`, audit JSONL at `/tmp/rls-audit.jsonl`, secrets via `${secret:admin_password}`.

**Source references (read these before writing):**

- `../geode/src/security/rls_core.zig` — policy cache, VM stack bounds
- `../geode/src/security/gps.zig:11-18` — Indeterminate policy → deny mapping
- `../geode/src/server/rls_filter.zig` — result-set filter implementation
- `../geode/src/security/policy_expression.zig` — ABAC expression VM
- `../geode/src/security/test_rls_injection.zig` — internal injection tests (pattern reference)
- Existing spec: `geodetestlab-cli/specs/distributed_rls_enforcement.yml` (template)

---

## File Structure

```text
geodetestlab-cli/specs/
├── rls_cross_tenant_query_shapes.yml        # GAP-0280
├── rls_vm_bounds.yml                         # GAP-0281
├── rls_policy_cache_invalidation.yml         # GAP-0282
├── rls_indeterminate_denies.yml              # GAP-0283
├── abac_attribute_policies.yml               # GAP-0284
├── rls_injection_resistance.yml              # GAP-0285
└── rls_fle_no_decrypt_on_deny.yml            # GAP-0286
```

---

## Task 1: GAP-0280 — Cross-tenant SELECT across all query shapes

**Files:**

- Create: `geodetestlab-cli/specs/rls_cross_tenant_query_shapes.yml`

- [ ] **Step 1: Write the spec**

The spec must seed two tenants, apply a deny policy for the restricted user on `:TenantA`, and prove zero rows of `:TenantA` reach the restricted user across at least 8 query shapes. Use the existing `distributed_rls_enforcement.yml` as the template.

```yaml
version: '1.0'
name: RLS — cross-tenant SELECT blocked across all query shapes
description: |
  Exhaustively verify the RLS filter at src/server/rls_filter.zig removes
  every :TenantA row from a restricted user's result set, across every query
  shape geode supports: MATCH/WHERE, multi-hop, OPTIONAL MATCH, WHERE EXISTS,
  CTE, UNION, COLLECT/UNWIND, EXPLAIN.

  CANARY: REQ=REQ-RLS-XTENANT-001; FEATURE="RLS cross-tenant filter"; ASPECT=QueryShapeMatrix; STATUS=TESTED; OWNER=security; UPDATED=2026-05-21
cli:
  binary: ./zig-out/bin/geode
  server:
    enabled: true
    port:
    data_dir:
    startup_timeout_ms: 60000
    cleanup: true
    args: [--log-level, warn]
    env:
      GEODE_ALLOW_TEST_AUDIT_KEYS: '1'
  client:
    timeout_ms: 30000
    format: json
secrets:
  admin_password:
    source: env
    key: GEODE_ADMIN_PASSWORD
    required: false
    default: GeodeTestPassword123!
invariants:
- type: server_running
fuzz:
  enabled: false
tests:
- name: rls-xt-preflight-cleanup
  args: [query, -U, geode, -P, '${secret:admin_password}', '-']
  stdin: |
    DROP USER IF EXISTS rls_xt_alice;
    DROP USER IF EXISTS rls_xt_bob;
    DROP GRAPH IF EXISTS rls_xt;
  expect: { exit_code: 0 }
  tags: [rls, setup]

- name: rls-xt-create-graph
  args: [query, -U, geode, -P, '${secret:admin_password}', CREATE GRAPH rls_xt]
  expect: { exit_code: 0 }
  tags: [rls, setup]

- name: rls-xt-create-users
  args: [query, -U, geode, -P, '${secret:admin_password}', '-']
  stdin: |
    CREATE USER rls_xt_alice SET PASSWORD 'RlsXt-Alice-1234' ROLE readwrite;
    CREATE USER rls_xt_bob SET PASSWORD 'RlsXt-Bob-1234' ROLE readwrite;
  expect: { exit_code: 0 }
  tags: [rls, setup]

- name: rls-xt-seed
  args: [query, -U, geode, -P, '${secret:admin_password}', '-']
  stdin: |
    USE GRAPH rls_xt;
    CREATE (:TenantA {id: 1, owner: 'alice'})-[:LINK]->(:TenantA {id: 2, owner: 'alice'});
    CREATE (:TenantA {id: 3, owner: 'alice'});
    CREATE (:TenantB {id: 10, owner: 'bob'})-[:LINK]->(:TenantB {id: 11, owner: 'bob'});
    CREATE (:TenantB {id: 12, owner: 'bob'});
  expect: { exit_code: 0 }
  tags: [rls, setup]

- name: rls-xt-create-deny-policy-for-bob
  description: Deny :TenantA reads for rls_xt_bob.
  args: [policy, create, rls_xt_deny_a_for_bob, --table, TenantA, --condition, rls_xt_bob]
  expect: { exit_code: 0, stdout_contains: [created] }
  tags: [rls, policy]

# --- shape 1: simple MATCH ---
- name: rls-xt-shape1-bob-simple-match
  description: Bob queries :TenantA — must see 0 rows.
  args: [query, -U, rls_xt_bob, -P, RlsXt-Bob-1234, '-']
  stdin: |
    USE GRAPH rls_xt;
    MATCH (n:TenantA) RETURN count(n) AS c
  expect: { exit_code: 0, stdout_contains: ['"c":0'] }
  tags: [rls, shape1, negative]

# --- shape 2: multi-hop traversal ---
- name: rls-xt-shape2-bob-multi-hop
  args: [query, -U, rls_xt_bob, -P, RlsXt-Bob-1234, '-']
  stdin: |
    USE GRAPH rls_xt;
    MATCH (n:TenantA)-[:LINK]->(m:TenantA) RETURN count(*) AS c
  expect: { exit_code: 0, stdout_contains: ['"c":0'] }
  tags: [rls, shape2, negative]

# --- shape 3: OPTIONAL MATCH ---
- name: rls-xt-shape3-bob-optional-match
  args: [query, -U, rls_xt_bob, -P, RlsXt-Bob-1234, '-']
  stdin: |
    USE GRAPH rls_xt;
    OPTIONAL MATCH (n:TenantA) RETURN count(n) AS c
  expect: { exit_code: 0, stdout_contains: ['"c":0'] }
  tags: [rls, shape3, negative]

# --- shape 4: WHERE EXISTS pattern ---
- name: rls-xt-shape4-bob-where-exists
  args: [query, -U, rls_xt_bob, -P, RlsXt-Bob-1234, '-']
  stdin: |
    USE GRAPH rls_xt;
    MATCH (b:TenantB) WHERE EXISTS { MATCH (a:TenantA) WHERE a.owner = b.owner } RETURN count(b) AS c
  expect: { exit_code: 0, stdout_contains: ['"c":0'] }
  tags: [rls, shape4, negative]

# --- shape 5: WITH/CTE chain ---
- name: rls-xt-shape5-bob-with-cte
  args: [query, -U, rls_xt_bob, -P, RlsXt-Bob-1234, '-']
  stdin: |
    USE GRAPH rls_xt;
    MATCH (n:TenantA) WITH n LIMIT 100 RETURN count(n) AS c
  expect: { exit_code: 0, stdout_contains: ['"c":0'] }
  tags: [rls, shape5, negative]

# --- shape 6: UNION ---
- name: rls-xt-shape6-bob-union
  args: [query, -U, rls_xt_bob, -P, RlsXt-Bob-1234, '-']
  stdin: |
    USE GRAPH rls_xt;
    MATCH (n:TenantA) RETURN n.id AS id
    UNION
    MATCH (m:TenantB) RETURN m.id AS id
  expect:
    exit_code: 0
    stdout_contains: ['"id":10', '"id":11', '"id":12']
    stdout_not_contains: ['"id":1', '"id":2', '"id":3']
  tags: [rls, shape6, negative-and-positive]

# --- shape 7: COLLECT/UNWIND ---
- name: rls-xt-shape7-bob-collect-unwind
  args: [query, -U, rls_xt_bob, -P, RlsXt-Bob-1234, '-']
  stdin: |
    USE GRAPH rls_xt;
    MATCH (n:TenantA) WITH collect(n) AS xs UNWIND xs AS x RETURN count(x) AS c
  expect: { exit_code: 0, stdout_contains: ['"c":0'] }
  tags: [rls, shape7, negative]

# --- shape 8: EXPLAIN must not leak ---
- name: rls-xt-shape8-bob-explain
  description: |
    EXPLAIN for bob's :TenantA query must produce a plan, but the filter
    must still be applied at execute. Verify EXPLAIN does not leak owner
    plaintext from :TenantA rows.
  args: [query, -U, rls_xt_bob, -P, RlsXt-Bob-1234, '-']
  stdin: |
    USE GRAPH rls_xt;
    EXPLAIN MATCH (n:TenantA) RETURN n.owner
  expect:
    exit_code: 0
    stdout_not_contains: ['alice']
  tags: [rls, shape8, explain-no-leak]

# --- admin sanity: still sees all rows ---
- name: rls-xt-admin-sees-all
  args: [query, -U, geode, -P, '${secret:admin_password}', '-']
  stdin: |
    USE GRAPH rls_xt;
    MATCH (n:TenantA) RETURN count(n) AS c
  expect: { exit_code: 0, stdout_contains: ['"c":3'] }
  tags: [rls, admin, positive]

# --- alice (no deny) sees her own tenant ---
- name: rls-xt-alice-sees-tenant-a
  args: [query, -U, rls_xt_alice, -P, RlsXt-Alice-1234, '-']
  stdin: |
    USE GRAPH rls_xt;
    MATCH (n:TenantA) RETURN count(n) AS c
  expect: { exit_code: 0, stdout_contains: ['"c":3'] }
  tags: [rls, alice, positive]

# --- teardown ---
- name: rls-xt-cleanup
  args: [query, -U, geode, -P, '${secret:admin_password}', '-']
  stdin: |
    DROP GRAPH IF EXISTS rls_xt;
    DROP USER IF EXISTS rls_xt_alice;
    DROP USER IF EXISTS rls_xt_bob;
  expect: { exit_code: 0 }
  tags: [rls, teardown]

tags: [rls, cross-tenant, security, query-shapes, comprehensive]
```

- [ ] **Step 2: Run spec to verify it passes**

```bash
cd geodetestlab-cli && source .venv/bin/activate
python -m geodetestlab run --spec specs/rls_cross_tenant_query_shapes.yml -v
```

Expected: All steps pass (exit 0).

- [ ] **Step 3: Commit**

```bash
git add geodetestlab-cli/specs/rls_cross_tenant_query_shapes.yml
git commit -m "test(rls): close GAP-0280 — cross-tenant query-shape matrix"
```

- [ ] **Step 4: Update GAP_ANALYSIS.md**

Change GAP-0280 `Status: Open` to `Status: Closed` and add `- **Resolution:** New spec`specs/rls_cross_tenant_query_shapes.yml` covers 8 query shapes; verified green via `make test-spec`.`

---

## Task 2: GAP-0281 — RLS VM stack overflow / underflow bounds

**Files:**

- Create: `geodetestlab-cli/specs/rls_vm_bounds.yml`

**Reference:** `../geode/src/security/rls_core.zig:49-55` (64-entry stack, push/pop guards). Geode does not expose direct bytecode injection via CLI — exercise the bound via deeply-nested policy expression that compiles to many stack frames.

- [ ] **Step 1: Write spec covering two scenarios**

  - Deeply-nested policy condition (e.g. `(a OR (b OR (c OR (...)) ))` with 65+ levels) → expect either parse error at policy-create OR evaluation error at query time → row denied
  - Malformed condition that compiles but evaluates to an unbalanced stack at runtime → row denied (indeterminate-policy mapping per GAP-0283)

YAML pattern: follow Task 1; use `policy create` CLI with a synthesized condition string. Document on PASS the exact failure mode observed.

- [ ] **Step 2: Validate**

```bash
python -m geodetestlab run --spec specs/rls_vm_bounds.yml -v
```

- [ ] **Step 3: Commit**

```bash
git add geodetestlab-cli/specs/rls_vm_bounds.yml
git commit -m "test(rls): close GAP-0281 — VM stack bounds"
```

- [ ] **Step 4: Update GAP_ANALYSIS.md** mark GAP-0281 Closed.

---

## Task 3: GAP-0282 — RLS policy cache invalidation under churn

**Files:**

- Create: `geodetestlab-cli/specs/rls_policy_cache_invalidation.yml`

**Acceptance scenarios:**

1. User has ALLOW; query succeeds.
2. Admin REVOKE policy for user.
3. User's next query within 60s must observe DENY (cache invalidated, not waiting for TTL).
4. Optional secondary: bulk policy churn to validate LRU eviction doesn't leak ALLOW after revoke.

Build using the same template; key assertions:

- Initial restricted-user query → expected positive count
- Admin `policy delete` or equivalent REVOKE
- Restricted-user immediate re-query → 0 rows
- Tag: `cache_invalidation`

- [ ] **Step 1:** Write spec, [ ] **Step 2:** Validate, [ ] **Step 3:** Commit `test(rls): close GAP-0282 — cache invalidation`, [ ] **Step 4:** Update GAP_ANALYSIS.md.

---

## Task 4: GAP-0283 — Indeterminate policy maps to deny

**Files:**

- Create: `geodetestlab-cli/specs/rls_indeterminate_denies.yml`

**Acceptance scenarios:**

- Create policy with intentionally broken expression. Geode CLI may or may not allow such a policy at create time; if create rejects, the spec asserts the rejection. If create accepts and evaluation fails, the spec asserts query returns 0 rows for restricted user and audit log shows `policy_evaluation_error` / `access_denied`.
- Admin still sees all rows (filter is per-user).

Reference: `../geode/src/security/gps.zig:11-18` indeterminate→deny mapping. Tag: `indeterminate-denies`.

- [ ] **Step 1:** Write spec, [ ] **Step 2:** Validate, [ ] **Step 3:** Commit `test(rls): close GAP-0283 — indeterminate→deny`, [ ] **Step 4:** Update GAP_ANALYSIS.md.

---

## Task 5: GAP-0284 — ABAC end-to-end

**Files:**

- Create: `geodetestlab-cli/specs/abac_attribute_policies.yml`

**Acceptance scenarios:**

- Users with `dept` attribute (alice=eng, bob=sales). Set via `ALTER USER ... SET ATTRIBUTE dept='eng'` if supported, otherwise via metadata column.
- Rows :Doc {dept:'eng'}, :Doc {dept:'sales'}.
- Policy: `user.dept == row.dept`. alice sees only `eng` docs, bob sees only `sales`.
- Mutating user.dept changes visibility within cache TTL.

Reference: `../geode/src/security/policy_expression.zig`, `../geode/src/security/rls_core.zig:88`. Tag: `abac`.

If geode does not yet support setting user attributes via DDL, mark the spec `skip: true` with `skip_reason` and file as a `known_limitation`; close GAP-0284 as `Blocked` with rationale.

- [ ] **Step 1:** Write spec, [ ] **Step 2:** Validate, [ ] **Step 3:** Commit, [ ] **Step 4:** Update GAP_ANALYSIS.md.

---

## Task 6: GAP-0285 — Policy injection resistance

**Files:**

- Create: `geodetestlab-cli/specs/rls_injection_resistance.yml`

**Acceptance scenarios:**

- Create a policy whose `--condition` or `--table` argument contains GQL syntax: `; DROP GRAPH x; --`, `' OR 1=1 --`, `\`; DELETE * FROM TenantA; \``.
- Verify policy stored literally; no DROP/DELETE executed (verify by counting rows before/after).
- A user under that policy receives consistent deny (or accept) per the literal interpretation, not the injected payload.

Tag: `injection-resistance`.

- [ ] **Step 1:** Write spec, [ ] **Step 2:** Validate, [ ] **Step 3:** Commit `test(rls): close GAP-0285 — injection resistance`, [ ] **Step 4:** Update GAP_ANALYSIS.md.

---

## Task 7: GAP-0286 — RLS × FLE no-decrypt-on-deny

**Files:**

- Create: `geodetestlab-cli/specs/rls_fle_no_decrypt_on_deny.yml`

**Acceptance scenarios:**

- Schema with FLE-encrypted property `secret_value` on `:Doc`.
- RLS policy: tenant_b denied on `:Doc`.
- Audit log captures `decrypt_field` for admin reads, NO `decrypt_field` for tenant_b's reads (because filter rejects row before FLE hook fires).
- Audit assertion via `grep` on the JSONL: assert presence for admin, absence for tenant_b.

Reference: `../geode/src/execution/fle_hooks.zig`, `../geode/src/server/rls_filter.zig`. Tag: `rls-fle-interaction`.

- [ ] **Step 1:** Write spec, [ ] **Step 2:** Validate, [ ] **Step 3:** Commit, [ ] **Step 4:** Update GAP_ANALYSIS.md.

---

## Final Steps

- [ ] **Step 8: Run full RLS spec suite together**

```bash
cd geodetestlab-cli && source .venv/bin/activate
python -m geodetestlab run --specs specs --filter rls -v
```

Expect: All new RLS specs pass.

- [ ] **Step 9: Commit summary**

```bash
git add docs/GAP_ANALYSIS.md
git commit -m "docs(gap): close GAP-0280..GAP-0286 — RLS comprehensive coverage"
```

- [ ] **Step 10: Self-review**

Confirm every gap has:

- A spec file in `geodetestlab-cli/specs/`
- A CANARY token in the description
- At least one positive case proving the contract holds
- At least one negative case proving violation is blocked
- An admin sanity check (filter is per-user)
- Idempotent teardown
