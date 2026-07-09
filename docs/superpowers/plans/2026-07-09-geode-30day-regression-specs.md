# Geode 30-Day Regression Specs Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add 23 harness specs pinning the user-observable contracts of behavior fixes landed in `../geode` between 2026-06-09 and 2026-07-09 that have no existing harness coverage.

**Architecture:** Each task produces one self-contained YAML spec in `geodetestlab-cli/specs/`, executed against a per-spec managed Geode server by `geodetestlab-cli`. Specs use the house `cli:` block format with CANARY markers, tagged tests, and positive + negative cases. Evidence: `docs/superpowers/research/2026-07-09-geode-30day-fix-mining.md`.

**Tech Stack:** YAML specs, geodetestlab-cli (Python 3.11 venv), Geode binary `../geode/zig-out/bin/geode`.

## Global Constraints

- Binary under test: `../geode/zig-out/bin/geode` (relative to repo root; harness auto-detects). Never use `/usr/bin/geode` (stale June build).
- Spec template: follow `geodetestlab-cli/specs/authn_rate_limiter_expiry.yml` — `version: '1.0'`, `name`, `description` (multi-line, ends with a `CANARY:` line: `REQ=REQ-<AREA>-<SLUG>-001; FEATURE="<Feature>"; ASPECT=<Aspect>; STATUS=TESTED; TEST=geodetestlab/specs/<file>.yml; OWNER=qa; UPDATED=2026-07-09`), `cli:` block (`binary: ./zig-out/bin/geode`, `server: {enabled: true, startup_timeout_ms: 60000, cleanup: true, args: [--log-level, info]}`), `invariants: [{type: server_running}]`, `tests:` with `tags:`, spec-level `tags:`.
- Restart-cycle specs MUST set `cleanup: false` under `cli.server` and use `restart_server: true` on the last test before the reopen phase (pattern: `regression_issue_539_wal_recovery_checkpoint.yml`).
- Query tests: prefer `args: [query, "<GQL>"]` for single statements; `query: |` for multi-statement. Assertions: `expected: {exit_code, stdout_contains, stderr_contains, stdout_not_contains, stdout_regex}`.
- **Standard Task Steps** (every task below uses these five steps; the task body supplies the content):
  1. **Probe**: start a scratch server (`../geode/zig-out/bin/geode serve --port 4141 --data-dir /tmp/probe-$$ &` or use existing spec runs) and run each planned query/command with the real CLI to capture the actual output/error strings. Kill the scratch server after.
  2. **Write the spec** at `geodetestlab-cli/specs/<file>.yml` with assertions matching the probed strings while preserving the semantic intent stated in the task (an "error" case must assert a failure signal: nonzero `exit_code`, `stderr_contains`, or an error `status_class` — never bare exit_code 0 with no error assertion).
  3. **Run**: `cd geodetestlab-cli && source .venv/bin/activate && python -m geodetestlab run --spec specs/<file>.yml -v`. Expected: `"failed": 0` in the JSON summary.
  4. **Bug rule**: if the server ACCEPTS input the task says must be rejected, or returns a wrong result, that is a product bug — do NOT weaken the assertion to green. Add the case as a limitation-pin test (name suffix `-limitation-pin`, description referencing the geode commit and stating the expected-but-unmet contract, asserting today's actual behavior), and report the finding in your task summary.
  5. **Commit**: `git add geodetestlab-cli/specs/<file>.yml && git commit -m "test(specs): <one-line> (<geode sha or gap ref>)"`. NEVER `git add -A` (the worktree has an unrelated modified `.geode_admin_password`).
- Test data: each spec uses a unique label prefix (e.g. `RG1_`, `RG2_`…) so specs stay independent under `--parallel`.
- Auth defaults: admin user `geode`, password `GeodeTestPassword123!` (`GEODE_ADMIN_PASSWORD`); harness injects credentials automatically for query tests.

---

## File Structure

```text
geodetestlab-cli/specs/
├── groupby_return_alias_correctness.yml          # Task 1  (B-1)
├── regression_merge_dedup_after_reopen.yml       # Task 2  (B-2)
├── regression_label_count_after_reopen.yml       # Task 3  (B-3)
├── regression_reverse_traversal_seed.yml         # Task 4  (B-4)
├── regression_gap0839_inmemory_graph_tenant_bind.yml # Task 5 (B-5)
├── security_graph_bind_authorization_861.yml     # Task 6  (B-6)
├── security_grpc_cdc_admin_gate_849.yml          # Task 7  (B-7)
├── security_reserved_username_guard_860.yml      # Task 8  (B-8)
├── security_graph_wal_durability_deferred_0026.yml # Task 9 (B-9)
├── regression_admin_auth_after_crash_reopen.yml  # Task 10 (B-10)
├── tde_hydration_snapshot_no_plaintext.yml       # Task 11 (B-11)
├── regression_index_reload_after_reopen.yml      # Task 12 (B-12)
├── regression_orderby_alias_and_freshstore.yml   # Task 13 (B-13)
├── regression_create_index_with_nodes_no_wedge.yml # Task 14 (B-14)
├── read_executor_budget_53200.yml                # Task 15 (B-15)
├── point_write_indexed_seek_parity.yml           # Task 16 (B-16)
├── quic_stream_multiplexing_default.yml          # Task 17 (B-17)
├── regression_sigterm_bounded_shutdown_0039.yml  # Task 18 (B-18)
├── config_buffer_pool_pages.yml                  # Task 19 (B-19)
├── fle_online_grant_plaintext_procedure.yml      # Task 20 (B-20)
├── typed_edge_count_durable.yml                  # Task 21 (B-21)
├── gql_backup_restore_refusal.yml                # Task 22 (GAP-0871)
└── cdc_unsupported_sink_failloud.yml             # Task 23 (GAP-0872)
```

Task 24 is a verification-only sweep (no new file).

---

### Task 1: GROUP BY alias correctness (geode ce8bd8f0, d50d0666)

**Files:** Create `geodetestlab-cli/specs/groupby_return_alias_correctness.yml`
**Interfaces:** Consumes nothing. Produces label `RG1_Item {category, src, v}`.

Contract: alias-grouped GROUP BY must not collapse rows into a single null group (pre-fix silent wrong result).

Tests (Standard Task Steps apply):
- `setup-seed`: `query: | CREATE (:RG1_Item {category:'a', src:'x', v:1}) …` — seed 9 nodes: 4×category `a`, 3×`b`, 2×`c`; 5 with `src:'x'`, 4 with `src:'y'`. Expect exit 0.
- `alias-grouped-count` (KEY, positive): `MATCH (n:RG1_Item) RETURN n.category AS s, count(*) AS c GROUP BY s` → stdout contains all three of `a`, `b`, `c` and counts `4`, `3`, `2`; `stdout_not_contains: ["null"]`.
- `alias-grouped-sum` (positive): `RETURN n.category AS s, sum(n.v) AS total GROUP BY s` → 3 groups, correct sums.
- `property-keyed-differential` (positive): `…GROUP BY n.category` → same groups/counts as alias form.
- `groupby-unknown-alias` (negative): `RETURN n.category AS s, count(*) AS c GROUP BY nosuch` → error (nonzero exit or stderr/status_class), NOT a single-row null-group result.
- `filtered-count-parity` (positive, d50d0666): `MATCH (n:RG1_Item) WHERE n.src='x' RETURN count(n)` → `5`.

- [ ] Step 1 Probe — [ ] Step 2 Write — [ ] Step 3 Run green — [ ] Step 4 Bug rule — [ ] Step 5 Commit `test(specs): GROUP BY RETURN-alias correctness + filtered count parity (geode ce8bd8f0)`

---

### Task 2: MERGE dedup after reopen (geode 35fe3549, GAP-0046)

**Files:** Create `geodetestlab-cli/specs/regression_merge_dedup_after_reopen.yml`
**Interfaces:** label `RG2_Taxon {taxon_id, source, rank}`; server `cleanup: false`.

Contract: after restart, re-MERGE of persisted nodes MATCHes (no duplicates).

Tests:
- `seed-merge-initial`: `query: |` with 6 statements `MERGE (n:RG2_Taxon {taxon_id: <i>, source: 'gbif'}) SET n.rank = 'species'` for i=1..6. Exit 0.
- `count-before-restart`: `MATCH (n:RG2_Taxon) RETURN count(n)` → `6`.
- `restart`: `type: bash`, `command: echo RESTART`, `restart_server: true`.
- `re-merge-after-reopen` (KEY): identical 6 MERGE statements with `SET n.rank = 'genus'`. Exit 0.
- `count-after-remerge` (KEY, positive): count → still `6`, and `MATCH (n:RG2_Taxon {taxon_id: 1}) RETURN n.rank` → `genus` (SET applied to matched node).
- `composite-key-merge`: before restart also seed `MERGE (:RG2_Pair {a:'k1', b:'k2'})`; after reopen re-merge same → `MATCH (n:RG2_Pair) RETURN count(n)` → `1`.
- `new-key-still-creates` (negative-control): post-reopen `MERGE (:RG2_Taxon {taxon_id: 99, source:'gbif'})` → count becomes `7`.

- [ ] Probe — [ ] Write — [ ] Run — [ ] Bug rule — [ ] Commit `test(specs): MERGE dedup after reopen under lazy hydration (geode 35fe3549 GAP-0046)`

---

### Task 3: Label count after reopen (geode 9a255a83)

**Files:** Create `geodetestlab-cli/specs/regression_label_count_after_reopen.yml`
**Interfaces:** labels `RG3_A`, `RG3_Empty`; `cleanup: false`.

Contract: FIRST post-reopen query `count(n:Label)` returns the full count (pre-fix: deferred-empty index served 0/partial).

Tests:
- `seed`: create 250 `RG3_A` nodes via `query: |` batch of `CREATE` statements (use FOREACH/UNWIND if supported — probe first; else 250-line query block). Exit 0.
- `count-before`: `MATCH (n:RG3_A) RETURN count(n)` → `250`.
- `restart`: bash echo + `restart_server: true`.
- `first-query-count` (KEY): `MATCH (n:RG3_A) RETURN count(n)` as the FIRST post-restart test → `250`.
- `restart-again` + `walk-vs-count`: second restart; then `MATCH (n:RG3_A) RETURN n.id LIMIT 5` first, then count → `250` (count correct after a partial walk).
- `empty-label-count` (negative-control): `MATCH (n:RG3_Empty) RETURN count(n)` → `0`.

- [ ] Probe — [ ] Write — [ ] Run — [ ] Bug rule — [ ] Commit `test(specs): single-label count(n) full total on first post-reopen read (geode 9a255a83)`

---

### Task 4: Reverse traversal seeded from bound endpoint (geode 2e6283f2, 7ef82b04)

**Files:** Create `geodetestlab-cli/specs/regression_reverse_traversal_seed.yml`
**Interfaces:** labels `RG4_Src`, `RG4_Dst`, edge `RG4_LINKS`.

Tests:
- `seed`: 3 `RG4_Src` nodes (`id: s1..s3`) each `-[:RG4_LINKS]->` a shared `RG4_Dst {id:'d1'}`; plus `RG4_Dst {id:'d2'}` with no in-edges.
- `reverse-bound-arrowhead` (KEY): `MATCH (b:RG4_Dst)<-[:RG4_LINKS]-(a) WHERE b.id='d1' RETURN a.id` → 3 rows `s1,s2,s3`.
- `forward-differential`: `MATCH (a:RG4_Src)-[:RG4_LINKS]->(b) WHERE b.id='d1' RETURN a.id` → same 3 ids.
- `reverse-no-inedges` (negative): `…WHERE b.id='d2'…` → 0 rows, exit 0.

- [ ] Probe — [ ] Write — [ ] Run — [ ] Bug rule — [ ] Commit `test(specs): reverse single-hop traversal seeds from bound endpoint (geode 2e6283f2)`

---

### Task 5: In-memory graph tenant bind (geode b350484d, GAP-0839)

**Files:** Create `geodetestlab-cli/specs/regression_gap0839_inmemory_graph_tenant_bind.yml`
**Interfaces:** server started WITHOUT `--data-dir` (probe how the harness config expresses in-memory mode; if the managed server always passes a data_dir, use `server_args` to omit/override, else document and pin).

Tests:
- `create-graph`: `CREATE GRAPH rg5_g1` → exit 0.
- `tenant-bound-session` (KEY): connect with graph-bound DSN (`--dsn` field on the test, pattern from `dsn_graph_binding.yml`) to `rg5_g1` → query `RETURN 1` succeeds.
- `bind-nonexistent-graph` (negative): DSN bound to `rg5_missing` → nonzero exit + error mentioning the graph.

- [ ] Probe — [ ] Write — [ ] Run — [ ] Bug rule — [ ] Commit `test(specs): in-memory CREATE GRAPH stable UUID + tenant-bound session (geode GAP-0839)`

---

### Task 6: Graph-bind authorization matrix (#861 + geode 6701e9bc)

**Files:** Create `geodetestlab-cli/specs/security_graph_bind_authorization_861.yml`
**Interfaces:** users `rg6_ro` (ReadOnly), `rg6_rw` (ReadWrite); graph `rg6_secret` created by admin, no grants.

Contract: ReadOnly non-admin binding an ungranted graph is denied (BOLA); ReadWrite non-admin allowed in non-strict single-tenant mode; strict tenancy denies both without GRANT.

Tests (probe role names/DDL syntax first — `CREATE USER … ; GRANT ROLE …`):
- `setup-users-graph`: admin creates both users + `CREATE GRAPH rg6_secret`.
- `readonly-bind-denied` (KEY negative): as `rg6_ro`, graph-bound connect/`USE GRAPH rg6_secret` → denied, stderr contains access-denied text.
- `readwrite-bind-allowed-nonstrict` (positive): as `rg6_rw` → allowed, can `RETURN 1`.
- `grpc-parity-denied` (negative): repeat the ReadOnly deny via `--transport grpc` (or a second command with the gRPC port) → same denial.
- If a strict-tenancy toggle (env/flag — probe `GEODE_STRICT_TENANCY` or docs) exists: `strict-denies-ungranted` (negative) + `strict-grant-allows` (positive) via a second spec-level env; otherwise document in the spec description and cover only non-strict.

- [ ] Probe — [ ] Write — [ ] Run — [ ] Bug rule — [ ] Commit `test(specs): graph-bind authorization matrix — RO denied, RW single-tenant allowed (#861, geode 6701e9bc)`

---

### Task 7: gRPC CDC admin gate (#849)

**Files:** Create `geodetestlab-cli/specs/security_grpc_cdc_admin_gate_849.yml`
**Interfaces:** non-admin user `rg7_user`; CDC control surface (probe: `geode cdc …` CLI subcommands / gRPC ctrl endpoints).

Tests:
- `unauthenticated-cdc-denied` (KEY negative): CDC ctrl/diag call with no credentials → rejected (auth error, not success and not crash).
- `nonadmin-cdc-denied` (negative): as `rg7_user` → rejected.
- `admin-cdc-allowed` (positive): as admin → succeeds (status/list op).

- [ ] Probe — [ ] Write — [ ] Run — [ ] Bug rule — [ ] Commit `test(specs): gRPC CDC control default-deny, admin-only (#849)`

---

### Task 8: Reserved username guard (#860)

**Files:** Create `geodetestlab-cli/specs/security_reserved_username_guard_860.yml`

Tests (probe the reserved list — check geode source `reserved` near the #860 commits; likely `geode`, `__geode_*`, `system`):
- `create-reserved-user-refused` (KEY negative): `user create <reserved> …` → nonzero exit + error naming the reserved/invalid username. One test per reserved name found (≥2).
- `auth-as-reserved-rejected` (negative): `auth login --user <reserved-internal>` → rejected.
- `ordinary-user-ok` (positive control): `user create rg8_normal …` → created.

- [ ] Probe — [ ] Write — [ ] Run — [ ] Bug rule — [ ] Commit `test(specs): reserved-username guard on CREATE USER and auth paths (#860)`

---

### Task 9: Security-graph durability under deferred WAL sync (geode be11253c, gap 0026)

**Files:** Create `geodetestlab-cli/specs/security_graph_wal_durability_deferred_0026.yml`
**Interfaces:** `cli.server.env: {GEODE_WAL_SYNC: deferred}`, `cleanup: false`.

Tests:
- `create-user-deferred`: `user create rg9_user rg9@test.example.com --password Rg9_Pass_2026!` → exit 0.
- `rotate-password`: alter rg9_user's password to `Rg9_New_2026!` (probe exact CLI: `user alter`/`ALTER USER`). Exit 0.
- `restart`: bash + `restart_server: true`.
- `new-password-works` (KEY positive): `auth login --user rg9_user --password Rg9_New_2026!` → success.
- `old-password-rejected` (KEY negative): old password → exit 3 / invalid-credentials error (no resurrection).
- `user-survives` (positive): user listed after restart.

- [ ] Probe — [ ] Write — [ ] Run — [ ] Bug rule — [ ] Commit `test(specs): security-graph mutations crash-durable under GEODE_WAL_SYNC=deferred (geode be11253c gap 0026)`

---

### Task 10: Admin auth after crash reopen (geode 90b3a75a GAP-0061, 88f82375)

**Files:** Create `geodetestlab-cli/specs/regression_admin_auth_after_crash_reopen.yml`
**Interfaces:** `cleanup: false`. Persisted admin password rotation (probe `geode admin` / `ALTER USER geode`).

Tests:
- `rotate-admin-password`: set admin password to `Rg10_Admin_2026!` (persisted).
- `restart`: bash + `restart_server: true`. NOTE: the managed server env still carries the original `GEODE_ADMIN_PASSWORD` — this is exactly the 88f82375 contract: persisted credential must win over env on reopen.
- `persisted-password-works` (KEY positive): login with `Rg10_Admin_2026!` → success.
- `env-password-rejected` (KEY negative): login with the original env password → rejected. (If harness credential injection interferes, use explicit `auth login` command tests with `-U/-P` suppressed via `dsn:` or raw `command:`.)
- `wrong-password-rejected` (negative): garbage password → rejected.
- Teardown consideration: final test restores the original admin password so harness cleanup can proceed; or keep `cleanup: false` and let the data_dir be discarded.

- [ ] Probe — [ ] Write — [ ] Run — [ ] Bug rule — [ ] Commit `test(specs): admin auth after crash reopen — persisted credential wins (geode GAP-0061)`

---

### Task 11: TDE hydration snapshots contain no plaintext (geode 7cc6858e)

**Files:** Create `geodetestlab-cli/specs/tde_hydration_snapshot_no_plaintext.yml`
**Interfaces:** TDE-enabled server (copy `tde_config`/env from `tde_bitflip_detection.yml` — probe it), `cleanup: false`. Sentinel `TDE_SENTINEL_RG11_XYZZY`.

Tests:
- `seed-sentinel`: create 50 nodes `(:RG11_Doc {secret:'TDE_SENTINEL_RG11_XYZZY<i>'})`.
- `force-persistence`: run a checkpoint-inducing op or `restart_server: true` (probing which flushes hydration snaps).
- `scan-datadir` (KEY negative): `type: bash`, `command: "! grep -r 'TDE_SENTINEL_RG11_XYZZY' ${GEODE_DATA_DIR}"` (probe the env var the harness exports for data_dir; `regression_issue_539…` shows the pattern) → exit 0 (no plaintext found). Alternatively use the spec-level `plaintext_verification`/`plaintext_check` block with `search_patterns: [TDE_SENTINEL_RG11_XYZZY]` — prefer the built-in scanner.
- `data-readable` (positive): query returns the sentinel values correctly through the API.

- [ ] Probe — [ ] Write — [ ] Run — [ ] Bug rule — [ ] Commit `test(specs): TDE hydration snapshots hold no plaintext property values (geode 7cc6858e)`

---

### Task 12: Index-served reads on first post-reopen query (geode GAP-ENT-0048 / GAP-0064/0065 family)

**Files:** Create `geodetestlab-cli/specs/regression_index_reload_after_reopen.yml`
**Interfaces:** label `RG12_P {k, grp}`; `cleanup: false`; per-test `timeout_ms: 15000` on post-reopen reads (prompt-response contract).

Tests:
- `seed`: 500 nodes with `k` = `key<i>`, `grp` = i mod 5; `CREATE INDEX` on `(RG12_P.k)` (probe exact DDL).
- `warm-checks`: `WHERE n.k='key42' RETURN n.grp` → correct; `RETURN DISTINCT n.grp` → 5 rows.
- `restart` (clean shutdown): bash + `restart_server: true`.
- `first-read-eq-seek` (KEY): `MATCH (n:RG12_P) WHERE n.k='key42' RETURN n.grp` → correct, within timeout.
- `groupby-post-reopen`: `RETURN n.grp AS g, count(*) AS c GROUP BY g` → 5 groups × 100.
- `distinct-post-reopen`: `RETURN DISTINCT n.grp` → 5 rows.
- `point-seek-post-reopen`: `MATCH (n:RG12_P {k:'key7'}) RETURN count(n)` → 1.

- [ ] Probe — [ ] Write — [ ] Run — [ ] Bug rule — [ ] Commit `test(specs): index-served reads correct+prompt on first post-reopen query (geode GAP-ENT-0048/GAP-0064)`

---

### Task 13: ORDER BY alias + fresh-store auto-build (geode f2c88ac4, a21d3b58, 06ecb13f)

**Files:** Create `geodetestlab-cli/specs/regression_orderby_alias_and_freshstore.yml`
**Interfaces:** label `RG13_N {v}` — NO `CREATE INDEX` anywhere in this spec.

Tests:
- `seed`: 100 nodes, `v` = shuffled 1..100 (write out literal CREATEs with non-monotonic values).
- `orderby-fresh-asc` (KEY): `MATCH (n:RG13_N) RETURN n.v ORDER BY n.v LIMIT 10` → stdout_regex asserting `1..10` in order (probe output format, then anchor a regex like `1\D+2\D+3…`).
- `orderby-alias-parity` (KEY): `RETURN n.v AS a ORDER BY a LIMIT 10` → identical values/order to previous.
- `orderby-desc`: `ORDER BY n.v DESC LIMIT 3` → `100, 99, 98` in order (guards the DESC prev() OOB fix).
- `orderby-alias-desc`: `AS a ORDER BY a DESC LIMIT 3` → same.

- [ ] Probe — [ ] Write — [ ] Run — [ ] Bug rule — [ ] Commit `test(specs): aliased ORDER BY fast path + fresh-store ordered auto-build (geode GAP-0064 FIX C)`

---

### Task 14: CREATE INDEX with pre-existing nodes doesn't wedge (geode 4a1efca4)

**Files:** Create `geodetestlab-cli/specs/regression_create_index_with_nodes_no_wedge.yml`
**Interfaces:** label `RG14_N {k}`; per-test `timeout_ms: 20000` so a wedge fails fast instead of hanging the suite.

Tests (order matters — nodes BEFORE index is the deadlock trigger):
- `seed-first`: 200 `RG14_N` nodes.
- `create-index-on-populated` (KEY): `CREATE INDEX` on `RG14_N.k` → exit 0 within timeout.
- `server-alive-followup` (KEY): `MATCH (n:RG14_N) RETURN count(n)` → 200 (a wedged server would time out).
- `constraint-after-index`: `CREATE CONSTRAINT`/second DDL (probe supported syntax) → succeeds.
- `show-drop-index`: `SHOW INDEX` lists it; `DROP INDEX` succeeds; count still 200.
- `create-index-empty-label` (control): index on fresh label with 0 nodes → exit 0.

- [ ] Probe — [ ] Write — [ ] Run — [ ] Bug rule — [ ] Commit `test(specs): CREATE INDEX on populated label returns promptly, no self-deadlock (geode 4a1efca4)`

---

### Task 15: Read-executor memory budget (geode de9a769d, GAP-ENT-0044/0045)

**Files:** Create `geodetestlab-cli/specs/read_executor_budget_53200.yml`
**Interfaces:** `cli.server.env: {GEODE_READ_EXECUTOR_BUDGET_MB: '1'}`; big label `RG15_Big {k, pad}`.

Tests:
- `seed-large`: enough rows with a fat `pad` string (e.g. 2000 nodes × 1KB pad; probe how much trips a 1MB budget) — split across several `query: |` tests if needed.
- `oversized-read-budget-error` (KEY negative): `MATCH (n:RG15_Big) RETURN n.k, n.pad, count(*) GROUP BY n.k, n.pad` (materializing aggregation) → error containing `53200` or `ReadQueryBudgetExceeded` (probe the exact surface), nonzero or error-status; server MUST stay alive.
- `server-alive-after` (positive): `RETURN 1` → success.
- `small-read-ok` (positive): `MATCH (n:RG15_Big) RETURN count(n)` → succeeds under budget.
- Second env variant via a follow-on spec-level check is NOT possible in one spec — instead add `budget-disabled` coverage as a `type: bash` test that runs a one-off CLI against a scratch server with `GEODE_READ_EXECUTOR_BUDGET_MB=0` OR document the =0 contract in the description and cover only the enabled path. Prefer probing; if infeasible keep enabled-path only.

- [ ] Probe — [ ] Write — [ ] Run — [ ] Bug rule — [ ] Commit `test(specs): read-executor budget aborts oversized reads with 53200, server survives (geode GAP-ENT-0044/0045)`

---

### Task 16: Point-write indexed-seek parity + write budget (geode c8b67533)

**Files:** Create `geodetestlab-cli/specs/point_write_indexed_seek_parity.yml`
**Interfaces:** label `RG16_N {k, other, val}` with `CREATE INDEX` on `k`; `cleanup: false`.

Tests:
- `seed+index`: 50 nodes `k='pk<i>'`, `val=0`; index on `k`.
- `indexed-seek-set` (KEY): `MATCH (n:RG16_N) WHERE n.k='pk7' SET n.val=42` → exit 0; `RETURN n.val` for pk7 → 42; count of `val=42` → 1 (exactly one node touched).
- `legacy-path-differential`: `MATCH (n:RG16_N) WHERE n.other IS NULL AND n.k='pk8' SET n.val=43` (non-indexed predicate forces legacy path) → same observable semantics.
- `indexed-seek-remove`: `…WHERE n.k='pk7' REMOVE n.val` → property gone.
- `persists-across-restart`: restart; `pk8.val` still 43.

- [ ] Probe — [ ] Write — [ ] Run — [ ] Bug rule — [ ] Commit `test(specs): engine-direct point-write parity via indexed seek + persistence (geode c8b67533)`

---

### Task 17: QUIC stream multiplexing default + opt-out (geode 68618e60)

**Files:** Create `geodetestlab-cli/specs/quic_stream_multiplexing_default.yml` (default-ON assertions) — opt-out runs as a `pre_server`-less second spec would be cleaner, but a single spec with default env covers the primary contract; cover opt-out via `type: bash` scratch-server test.

Tests:
- `rapid-sequential-queries`: 10 consecutive query tests (or one bash loop invoking `geode query` 10×) → all succeed (secondary streams don't hang).
- `parallel-burst`: `type: bash` launching 5 concurrent `geode query 'RETURN 1' --server ${GEODE_SERVER_ADDRESS}` with `wait` → all exit 0.
- `optout-boots-and-serves`: `type: bash` — start scratch server with `GEODE_QUIC_ENABLE_STREAM_MULTIPLEXING=0` on a free port, run one query, kill it → exit 0.

- [ ] Probe — [ ] Write — [ ] Run — [ ] Bug rule — [ ] Commit `test(specs): QUIC stream multiplexing default-ON + env opt-out (geode 68618e60)`

---

### Task 18: SIGTERM bounded shutdown (geode 221a97f1, gap 0039)

**Files:** Create `geodetestlab-cli/specs/regression_sigterm_bounded_shutdown_0039.yml`
**Interfaces:** entirely `type: bash` tests against scratch servers (the managed server must stay up for the harness); `single_node_only: true`.

Tests:
- `sigterm-bounded` (KEY): bash script — start scratch geode with `GEODE_SHUTDOWN_DRAIN_TIMEOUT_MS=2000` on a free port, wait for ready, open a client query in background, send SIGTERM, poll for process exit with a 15 s ceiling; assert exited (echo `EXITED_WITHIN_BOUND`). Generous gates to avoid CI flake.
- `sigterm-immediate`: same with `=0` → exits within 10 s.

- [ ] Probe — [ ] Write — [ ] Run — [ ] Bug rule — [ ] Commit `test(specs): SIGTERM shutdown drain is bounded, no busy-spin (geode gap 0039)`

---

### Task 19: Buffer pool pages config (geode 1b9ee266)

**Files:** Create `geodetestlab-cli/specs/config_buffer_pool_pages.yml`
**Interfaces:** `cli.server.env: {GEODE_BUFFER_POOL_PAGES: '8192'}`, `cleanup: false`.

Tests:
- `crud-under-override` (positive): create/read/update/delete a handful of `RG19_N` nodes → all green.
- `survives-restart`: restart; data intact.
- `garbage-value-fallback` (negative→graceful): `type: bash` scratch server with `GEODE_BUFFER_POOL_PAGES=garbage` → boots (or exits with a clean config error — probe; assert whichever contract holds, no crash/panic text).

- [ ] Probe — [ ] Write — [ ] Run — [ ] Bug rule — [ ] Commit `test(specs): GEODE_BUFFER_POOL_PAGES override + garbage-value fallback (geode 1b9ee266)`

---

### Task 20: Online FLE grantPlaintext procedure (geode ad6982d4, b0b4b3bd)

**Files:** Create `geodetestlab-cli/specs/fle_online_grant_plaintext_procedure.yml`
**Interfaces:** FLE-enabled server (copy env/setup from `fle_plaintext_verification_access_control.yml` — probe), role `rg20_analyst`, user `rg20_user`, FLE field `RG20_Rec.ssn`; `cleanup: false`.

Tests:
- `setup`: FLE field config + user/role + seed `(:RG20_Rec {ssn:'123-45-6789'})`.
- `read-before-grant` (KEY negative): as rg20_user, `RETURN n.ssn` → placeholder/denied (NOT plaintext; `stdout_not_contains: ['123-45-6789']`).
- `grant-online` (KEY): `CALL geode.fle.grantPlaintext('RG20_Rec','ssn','rg20_analyst')` as admin → exit 0, NO restart.
- `read-after-grant` (positive): same user query now returns `123-45-6789`.
- `grant-survives-restart`: restart; read still plaintext.

- [ ] Probe — [ ] Write — [ ] Run — [ ] Bug rule — [ ] Commit `test(specs): geode.fle.grantPlaintext grants online without restart, restart-safe (geode ad6982d4)`

---

### Task 21: Typed edge count durable (geode 8eb24fd2, c0d5d3d5, f7d16c4a)

**Files:** Create `geodetestlab-cli/specs/typed_edge_count_durable.yml`
**Interfaces:** edges `RG21_KNOWS`, `RG21_LIKES`; `cleanup: false`.

Tests:
- `seed`: 12 `RG21_KNOWS` + 5 `RG21_LIKES` edges between fresh nodes.
- `typed-count` (KEY): `MATCH ()-[r:RG21_KNOWS]->() RETURN count(r)` → 12; `RG21_LIKES` → 5.
- `restart` + `typed-count-after-reopen` (KEY): both counts unchanged.
- `type-isolation`: delete 2 KNOWS edges → KNOWS 10, LIKES still 5.
- `nonexistent-type` (negative): `count(r:RG21_NOSUCH)` → 0.

- [ ] Probe — [ ] Write — [ ] Run — [ ] Bug rule — [ ] Commit `test(specs): per-type edge count exact and durable across reopen (geode 8eb24fd2)`

---

### Task 22: GQL BACKUP/RESTORE stable refusal (geode 6264a7e0, GAP-0871)

**Files:** Create `geodetestlab-cli/specs/gql_backup_restore_refusal.yml`

Tests:
- `gql-backup-refused` (KEY negative): `query: "BACKUP DATABASE TO '/tmp/x'"` (probe the exact syntax the parser recognizes-then-refuses) → clean stable "unsupported/not supported" error, server alive; NOT a crash.
- `gql-restore-refused` (negative): same for RESTORE.
- `server-alive` (positive): `RETURN 1` after both.
- `cli-backup-works` (positive control): the supported CLI backup path (`geode backup …`, from `backup_operations_basic.yml`) still succeeds — refusal is GQL-surface-only.

- [ ] Probe — [ ] Write — [ ] Run — [ ] Bug rule — [ ] Commit `test(specs): GQL BACKUP/RESTORE returns stable refusal, CLI path unaffected (geode GAP-0871)`

---

### Task 23: CDC unsupported sink fails loud (geode 3c56fef1, GAP-0872)

**Files:** Create `geodetestlab-cli/specs/cdc_unsupported_sink_failloud.yml`

Tests (probe CDC config surface from `cdc_kafka_resume_token.yml` / `geode_cdc_comprehensive.yml`):
- `kinesis-sink-rejected` (KEY negative): configure a CDC sink of type `kinesis` → explicit rejection error naming the unsupported sink (not silent accept).
- `pubsub-sink-rejected` (negative): same for `pubsub`.
- `supported-sink-ok` (positive control): `webhook` (or kafka if a broker isn't required for config-accept) config accepted.

- [ ] Probe — [ ] Write — [ ] Run — [ ] Bug rule — [ ] Commit `test(specs): CDC unsupported sinks (kinesis/pubsub) fail loud (geode GAP-0872)`

---

### Task 24: Tier-6 coverage verification sweep (no new spec by default)

**Files:** Modify (only if gaps found): `geodetestlab-cli/specs/timeseries_basic.yml`, `fulltext_bm25_comprehensive.yml`, `explain_profile_unit_tests.yml`, `mv_refresh_latency_envelope.yml`, `authn_mfa_totp_edges.yml`, `fle_key_rotation_atomic.yml`.

For each item in the mining report's Tier 6 list (GAP-0865/0880/0869/0876/0867/0868/0884/0890): read the named spec, check whether it asserts the fixed contract (e.g. PROFILE shows non-zero real timing; FTS phrase/proximity/highlight queries exist; MV rewrite hit). Where a contract is unasserted, ADD 1-3 tests to the existing spec (not a new file), run that spec, commit as `test(specs): assert <contract> (geode GAP-08xx)` — one commit per touched spec. Where already asserted, record "covered" in the task summary.

- [ ] Audit all 8 items — [ ] Extend + run any deficient specs — [ ] Commit(s) — [ ] Report covered/extended list

---

## Deliberately Deferred (out of scope for this plan)

- **B-22** `multi_node/cluster_write_idempotency_retry.yml` (geode 97a0a8b8/33e3ad13) and **B-23** edge orphan-slot self-heal (2cdc053a/ab700319): both require multi-node churn/timeout injection that today's cluster harness cannot drive deterministically — high flake risk. Revisit when the cluster `signal`/`restart_node` step gains fault-injection timing control.

## Final Steps

- [ ] `cd geodetestlab-cli && source .venv/bin/activate && python -m geodetestlab run --specs specs --parallel 4 -v` — full suite green (or no NEW failures vs a pre-plan baseline run; record baseline first).
- [ ] Update `docs/GAP_ANALYSIS.md` only if the Bug rule surfaced product bugs (list limitation-pins).
