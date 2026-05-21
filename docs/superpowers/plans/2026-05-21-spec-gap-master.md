# Spec Gap Closure — Master Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Identify and close every gap in the `geodetestlab-cli/specs/` test suite for happy-path, negative, edge-case, security baseline, and performance behavior of the Geode graph database such that releases cannot be pushed in violation of expected functionality or security baselines.

**Architecture:** Master plan catalogs ~66 new gap clusters (GAP-0280 through GAP-0345). Each cluster maps 1:1 to a sub-plan file in `docs/superpowers/plans/` that contains a TDD task list with full executable YAML specs. Each closed gap produces one or more `geodetestlab-cli/specs/*.yml` files that run green against `../geode/zig-out/bin/geode`.

**Tech Stack:** YAML test specs (`geodetestlab-cli` test harness), Geode CLI (`./zig-out/bin/geode`), QUIC + gRPC transports, JSON audit sink, `make test-spec SPEC=…`, ruff/mypy gates already in CI.

---

## Scope

This plan covers gaps identified by a 2026-05-21 audit cross-referencing:

- 243 existing YAML specs in `geodetestlab-cli/specs/`
- ~300 modules under `../geode/src/` (~2.5M LOC)
- Known security invariants documented in geode source comments
- Existing CANARY tokens (REQ-* IDs) and prior gap analysis (GAP-0001..GAP-0279)

Gap clusters were prioritized by:

1. **Security baseline** — invariants that, if violated, would block a release (RLS, RBAC, TDE, FLE, audit, 2PC, authn)
2. **Functional release-quality** — features with thin coverage (indexes, MVCC, CDC, migrations)
3. **Hardening** — transport edge cases, performance/stress, error-mode coverage

## Hard Rules

- **Match existing spec conventions** — `version: '1.0'`, `cli.binary: ./zig-out/bin/geode`, `secrets.admin_password` block, `invariants: server_running`, etc. (see `geodetestlab-cli/specs/rbac_users_roles_grants_audit.yml` for template).
- **Every new spec carries a CANARY token** in the description: `CANARY: REQ=<id>; FEATURE="<area>"; ASPECT=<aspect>; STATUS=TESTED; OWNER=<team>; UPDATED=2026-05-21`
- **Every gap entry in `docs/GAP_ANALYSIS.md`** uses the existing format (Status / Category / Severity / Description / Acceptance Criteria).
- **Negative tests** must include `stdout_not_contains` or `stderr_contains` to pin known failure shapes (typically SQLSTATE codes like `42501`, `28000`, `23505`).
- **Cross-tenant tests** must use distinct user creations and prove the *other* tenant's data is unreachable.
- **No mutation under denial** — every negative authz test pairs with a follow-up positive read that proves the seed survived unchanged.
- **Idempotent setup/cleanup** — every spec uses `DROP X IF EXISTS` and finishes with teardown.
- **Cross-transport** — security-critical specs SHOULD have a parallel `…_grpc.yml` variant verifying gRPC enforces the same invariants as QUIC.

## File Structure

```text
docs/
├── GAP_ANALYSIS.md                           # appended with GAP-0280..GAP-0345
└── superpowers/plans/
    ├── 2026-05-21-spec-gap-master.md         # this file
    ├── 2026-05-21-spec-gap-rls.md            # GAP-0280..0286
    ├── 2026-05-21-spec-gap-rbac-escalation.md # GAP-0287..0292
    ├── 2026-05-21-spec-gap-tde-invariants.md  # GAP-0293..0298
    ├── 2026-05-21-spec-gap-fle-enforcement.md # GAP-0299..0304
    ├── 2026-05-21-spec-gap-audit-forensics.md # GAP-0305..0309
    ├── 2026-05-21-spec-gap-authn-methods.md   # GAP-0310..0316
    ├── 2026-05-21-spec-gap-2pc-distributed.md # GAP-0317..0322
    ├── 2026-05-21-spec-gap-transports.md      # GAP-0323..0327
    ├── 2026-05-21-spec-gap-indexes.md         # GAP-0328..0332
    ├── 2026-05-21-spec-gap-gql-types-parser.md # GAP-0333..0336
    ├── 2026-05-21-spec-gap-transactions.md    # GAP-0337..0339
    ├── 2026-05-21-spec-gap-cdc-mv.md          # GAP-0340..0342
    └── 2026-05-21-spec-gap-misc.md            # GAP-0343..0345

geodetestlab-cli/specs/
└── (~70 new *.yml files added by sub-plans)
```

---

## Gap Catalog (GAP-0280 through GAP-0345)

Each gap below is one cluster of related missing test scenarios. Severity drives sub-plan ordering.

### Tier 1 — Security baseline (must close before release)

| GAP-ID | Severity | Cluster | Sub-plan |
|--------|----------|---------|----------|
| GAP-0280 | Critical | RLS cross-tenant SELECT must block at filter layer for every label and every query shape | rls |
| GAP-0281 | Critical | RLS bytecode VM stack overflow / underflow must abort policy and deny | rls |
| GAP-0282 | High     | RLS policy cache TTL/eviction under churn must not leak stale ALLOW | rls |
| GAP-0283 | High     | RLS indeterminate policy MUST map to deny, not allow-fallback | rls |
| GAP-0284 | High     | ABAC attribute-based policy evaluation (user.dept == row.dept) end-to-end | rls |
| GAP-0285 | Medium   | RLS policy injection via crafted label/identifier names | rls |
| GAP-0286 | Medium   | RLS interaction with FLE — denied row never decrypts FLE field | rls |
| GAP-0287 | Critical | RBAC privilege escalation via ALTER USER race / concurrent SET ROLE | rbac-escalation |
| GAP-0288 | High     | RBAC custom role binding (header gap #3) — explicit pin test until fixed | rbac-escalation |
| GAP-0289 | High     | RBAC GRANT WRITE auth chain corruption (header gap #1) — pin until fixed | rbac-escalation |
| GAP-0290 | High     | RBAC REVOKE while user is mid-session — session must be revalidated | rbac-escalation |
| GAP-0291 | Medium   | RBAC ALTER USER target = non-existent role must error, not silently bind to .User | rbac-escalation |
| GAP-0292 | Medium   | RBAC DROP USER while user has active sessions must terminate them | rbac-escalation |
| GAP-0293 | Critical | TDE plaintext-on-disk verification across WAL, checkpoint, snapshot, S3 backup, swap region | tde-invariants |
| GAP-0294 | Critical | TDE nonce reuse detection — duplicate IV in same key generation must be impossible | tde-invariants |
| GAP-0295 | High     | TDE key rotation atomicity — crash mid-rotation must leave DB readable | tde-invariants |
| GAP-0296 | High     | TDE KMS unreachable at startup must fail closed, not fall back to plaintext | tde-invariants |
| GAP-0297 | Medium   | TDE backup key envelope unwrap with wrong KEK must fail with auth tag error | tde-invariants |
| GAP-0298 | Medium   | TDE encrypted page bit-flip must fail decrypt (AES-GCM auth tag check) | tde-invariants |
| GAP-0299 | Critical | FLE per-field plaintext never persisted across all paths — node prop, edge prop, index value, WAL, backup | fle-enforcement |
| GAP-0300 | High     | FLE schema catalog ALTER FIELD must re-encrypt or fail closed | fle-enforcement |
| GAP-0301 | High     | FLE decrypt under denied policy must return ENCRYPTED placeholder, not plaintext | fle-enforcement |
| GAP-0302 | High     | FLE blind index search returns correct rows without exposing plaintext | fle-enforcement |
| GAP-0303 | Medium   | FLE per-field key derivation determinism across restart | fle-enforcement |
| GAP-0304 | Medium   | FLE key rotation re-encrypts existing rows; failed rotation rolls back | fle-enforcement |
| GAP-0305 | Critical | Audit Ed25519 forensic export signature verifies; tampering detected | audit-forensics |
| GAP-0306 | High     | Audit JSONL is append-only — concurrent writers cannot interleave partial records | audit-forensics |
| GAP-0307 | High     | Audit sink failure (disk full, permission denied) must NOT crash server, must surface alarm | audit-forensics |
| GAP-0308 | Medium   | Audit HMAC chain seq continues across restart; broken chain detected on replay | audit-forensics |
| GAP-0309 | Medium   | Audit configuration_change emits event with old/new values | audit-forensics |
| GAP-0310 | Critical | Argon2id password rejected for weak parameters (memory < 19 MiB or iterations < 2) | authn-methods |
| GAP-0311 | High     | MFA TOTP — time-window edges, replay within window, lockout after N failures | authn-methods |
| GAP-0312 | High     | mTLS — expired cert, untrusted CA, CN mismatch all rejected at handshake | authn-methods |
| GAP-0313 | High     | API key revocation takes effect within session-rotation interval | authn-methods |
| GAP-0314 | Medium   | BLAKE2b password hash migration — legacy hash auto-upgrades on next login | authn-methods |
| GAP-0315 | Medium   | Authn rate limiter — N failed logins/IP within window blocks further attempts | authn-methods |
| GAP-0316 | Medium   | Timing-attack constant — login latency variance below detectable threshold | authn-methods |
| GAP-0317 | Critical | 2PC coordinator timeout must rollback participants; no half-committed state | 2pc-distributed |
| GAP-0318 | Critical | 2PC participant crash post-prepare must replay decision on recovery | 2pc-distributed |
| GAP-0319 | High     | 2PC nonce replay attack rejected (replayed prepare/commit message) | 2pc-distributed |
| GAP-0320 | High     | 2PC frame > 16 MiB rejected — no allocation bomb | 2pc-distributed |
| GAP-0321 | High     | GEODE_CLUSTER_TOKEN missing or wrong rejects 2PC handshake | 2pc-distributed |
| GAP-0322 | Medium   | 2PC principal envelope across shards preserves user identity for RLS | 2pc-distributed |
| GAP-0323 | High     | QUIC concurrent stream registry — PollSync prevents HashMap SIGABRT under churn | transports |
| GAP-0324 | High     | QUIC TLS verification — cert pinning, peer-cert chain validation | transports |
| GAP-0325 | High     | gRPC mTLS chain rejection parity with QUIC | transports |
| GAP-0326 | Medium   | QUIC stream cancellation mid-query must rollback transaction | transports |
| GAP-0327 | Medium   | Connection pool exhaustion returns clean error, not hang | transports |

### Tier 2 — Functional release-quality

| GAP-ID | Severity | Cluster | Sub-plan |
|--------|----------|---------|----------|
| GAP-0328 | High     | Vector HNSW index — cosine/L2/dot, persistence after restart, recall on 10k vectors | indexes |
| GAP-0329 | High     | Spatial R-tree — WKB roundtrip, bounding-box query, point/polygon/multipoint | indexes |
| GAP-0330 | High     | Fulltext BM25 — multi-token, stemming on/off, phrase query, scoring stability | indexes |
| GAP-0331 | Medium   | Blind index — encrypted column equality search returns correct rows | indexes |
| GAP-0332 | Medium   | Auto-index lifecycle — creation on first query, eviction on disuse | indexes |
| GAP-0333 | High     | GQL parser expression recursion depth > 128 must error, not stack overflow | gql-types-parser |
| GAP-0334 | High     | GQL type system — Date, Time, Duration, Point, Path, Interval roundtrip | gql-types-parser |
| GAP-0335 | Medium   | GQL temporal interval comparisons (overlap, contains, before/after) | gql-types-parser |
| GAP-0336 | Medium   | GQL undirected pattern matching with multi-hop and labels | gql-types-parser |
| GAP-0337 | High     | MVCC isolation enforcement — READ COMMITTED, SNAPSHOT, SERIALIZABLE differentials | transactions |
| GAP-0338 | High     | Long transaction undo — 10k+ row rollback completes, no leak | transactions |
| GAP-0339 | Medium   | Transaction chunked execution — large COMMIT split across messages | transactions |
| GAP-0340 | High     | CDC Kafka sink — backfill from resume token, ordered delivery under restart | cdc-mv |
| GAP-0341 | Medium   | CDC webhook sink — retry on 5xx, dead-letter on persistent failure | cdc-mv |
| GAP-0342 | Medium   | Materialized view refresh latency variance envelope holds under load | cdc-mv |

### Tier 3 — Hardening / coverage

| GAP-ID | Severity | Cluster | Sub-plan |
|--------|----------|---------|----------|
| GAP-0343 | Medium   | Sustained-load stress — 30-minute mixed RW workload at target QPS | misc |
| GAP-0344 | Low      | LSP schema completion — basic completions, hover, go-to-definition | misc |
| GAP-0345 | Low      | MCP client tool invocation surface — list_tools, call_tool, error mapping | misc |

---

## Execution Order

Sub-plans execute in priority tiers; within a tier they may run in parallel:

**Wave 1 (parallel, Tier 1A — most critical):**

- [ ] **Step 1:** Dispatch sub-agents for rls, rbac-escalation, tde-invariants, fle-enforcement
- [ ] **Step 2:** Each sub-agent: read its sub-plan, write specs to `geodetestlab-cli/specs/`, run `make test` on each, iterate to green
- [ ] **Step 3:** Each sub-agent commits with `feat(spec): close GAP-NNNN,NNNN — <cluster>` and updates `docs/GAP_ANALYSIS.md` status to Closed
- [ ] **Step 4:** Master loop verifies green, advances to next wave

**Wave 2 (parallel, Tier 1B):**

- [ ] **Step 1:** Dispatch sub-agents for audit-forensics, authn-methods, 2pc-distributed, transports

**Wave 3 (parallel, Tier 2):**

- [ ] **Step 1:** Dispatch sub-agents for indexes, gql-types-parser, transactions, cdc-mv

**Wave 4 (parallel, Tier 3):**

- [ ] **Step 1:** Dispatch sub-agent for misc (stress/LSP/MCP)

**Final verification:**

- [ ] **Step 5:** Run `make test-all` end-to-end with all new specs included
- [ ] **Step 6:** Confirm `docs/GAP_ANALYSIS.md` shows GAP-0280..GAP-0345 all Closed (or explicit Won't Do with rationale)
- [ ] **Step 7:** Commit master change `chore: close GAP-0280..GAP-0345 — spec gap closure`

---

## Acceptance — Done When

1. Every GAP-0280..GAP-0345 entry in `docs/GAP_ANALYSIS.md` is `Closed` or `Won't Do` with explicit rationale.
2. New specs live under `geodetestlab-cli/specs/` and execute green via `make test-spec SPEC=specs/<name>.yml`.
3. `make test-all` includes all new specs and remains green.
4. Each spec has a CANARY token tying it back to the gap that motivated it.
5. Security-critical specs have parallel gRPC variants where transport differences could mask a defect.

## What is OUT of scope

- Re-implementing the test harness itself (no changes to `geodetestlab-cli/geodetestlab/`)
- Fixing `geode` source bugs surfaced by the new tests — those become new issues, with the test pinned as `known_limitation` until the fix lands
- Closing the previously-resolved gaps GAP-0001..GAP-0279
- Re-doing the GPS phase 2-7 coverage already in `gps_phase*_*.yml`

---

## Self-Review

- [x] Every section in `ARGUMENTS` maps to a gap cluster
- [x] No placeholder markers in catalog
- [x] Severity tiers consistent with `docs/GAP_ANALYSIS.md` precedent
- [x] Sub-plan filenames consistent; GAP-IDs sequential and non-overlapping
- [x] Hard rules match conventions in existing rbac_users_roles_grants_audit.yml and gps_phase2_decide_comprehensive.yml
