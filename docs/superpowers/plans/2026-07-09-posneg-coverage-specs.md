# Positive/Negative Spec Coverage Expansion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add 29 harness specs closing the positive/negative coverage gaps identified in the 2026-07-09 audit — chiefly negative-path coverage for the feature-functionality tier (indexes, query surface, time-series, network types, CDC, backup/WAL, shell, migrations).

**Architecture:** One self-contained YAML spec per task in `geodetestlab-cli/specs/`, run against a managed per-spec Geode server. Negative tests assert an explicit failure signal (nonzero exit, stderr text, or GQL error status), never bare success. Evidence: `docs/superpowers/research/2026-07-09-spec-coverage-audit.md`.

**Tech Stack:** YAML specs, geodetestlab-cli (Python 3.11 venv), Geode binary `../geode/zig-out/bin/geode`.

## Global Constraints

- Binary under test: `../geode/zig-out/bin/geode`. Never `/usr/bin/geode` (stale).
- Spec template: follow `geodetestlab-cli/specs/authn_rate_limiter_expiry.yml` — `version: '1.0'`, `name`, `description` ending with a `CANARY:` line (`REQ=REQ-<AREA>-<SLUG>-001; FEATURE="<Feature>"; ASPECT=<Aspect>; STATUS=TESTED; TEST=geodetestlab/specs/<file>.yml; OWNER=qa; UPDATED=2026-07-09`), `cli:` block (`binary: ./zig-out/bin/geode`, `server: {enabled: true, startup_timeout_ms: 60000, cleanup: true, args: [--log-level, info]}`), `invariants: [{type: server_running}]`, tagged tests.
- Error assertions may use any of: `expected.exit_code: <nonzero>`, `expected.stderr_contains: [...]`, or the `status_class` GQL error channel used by `gql_conformance_39075.yml` (`42000` syntax, `22018` invalid cast, `0A000` unsupported, `22000` data exception) — probe which channel the behavior actually uses.
- **Standard Task Steps** (all tasks):
  1. **Probe**: run each planned query/command against a scratch server (`../geode/zig-out/bin/geode serve --port 4141 --data-dir /tmp/probe-$$ &`) to capture real output/error strings; kill it after.
  2. **Write the spec** at `geodetestlab-cli/specs/<file>.yml` matching probed strings while preserving semantic intent (a negative case must assert a failure signal).
  3. **Run**: `cd geodetestlab-cli && source .venv/bin/activate && python -m geodetestlab run --spec specs/<file>.yml -v` → `"failed": 0`.
  4. **Bug rule**: if the server ACCEPTS what the task says must be rejected (or vice versa), do NOT weaken the assertion — add it as a `-limitation-pin` test asserting today's behavior, describe the expected contract in the test description, and report it in your task summary.
  5. **Commit**: `git add geodetestlab-cli/specs/<file>.yml && git commit -m "test(specs): <one-line>"`. NEVER `git add -A` (worktree has an unrelated modified `.geode_admin_password`).
- Salvage rule: Tasks 7, 23, 29 have deprecated negatives in `specs/legacy/` (`vector_operations_comprehensive.yml`, `network_types_validation.yml`, `advanced_types_integration.yml`) — read them first and port still-valid assertions instead of inventing new ones.
- Unique label prefix per spec (`PN1_`, `PN2_`, …) for `--parallel` safety.

---

## File Structure

```text
geodetestlab-cli/specs/
├── cdc_webhook_deadletter_on_5xx.yml        # Task 1
├── backup_restore_corruption.yml            # Task 2
├── wal_corrupt_record_recovery.yml          # Task 3
├── rbac_privilege_escalation_denied.yml     # Task 4
├── abac_malformed_policy_rejection.yml      # Task 5
├── audit_sink_failclosed_policy.yml         # Task 6
├── vector_index_errors.yml                  # Task 7
├── fulltext_search_negative.yml             # Task 8
├── index_ddl_errors.yml                     # Task 9
├── spatial_geometry_errors.yml              # Task 10
├── auto_index_edge_cases.yml                # Task 11
├── timeseries_argument_validation.yml       # Task 12
├── order_by_negative.yml                    # Task 13
├── cast_invalid.yml                         # Task 14
├── where_clause_negative.yml                # Task 15
├── merge_conflict_negative.yml              # Task 16
├── parameter_binding_negative.yml           # Task 17
├── recursive_cte_limits.yml                 # Task 18
├── graph_algorithm_edge_cases.yml           # Task 19
├── group_by_aggregation_negative.yml        # Task 20
├── connection_pool_rejection.yml            # Task 21
├── transaction_conflict_abort.yml           # Task 22
├── network_types_validation_active.yml      # Task 23
├── migration_failure_handling.yml           # Task 24
├── shell_error_handling.yml                 # Task 25
├── gps_decide_negative.yml                  # Task 26
├── env_var_invalid_values.yml               # Task 27
├── advanced_types_boundary.yml              # Task 28
└── multi_graph_isolation_negative.yml       # Task 29
```

---

### Task 1: CDC webhook dead-letter on persistent 5xx

**Files:** Create `geodetestlab-cli/specs/cdc_webhook_deadletter_on_5xx.yml`
**Context:** `cdc_webhook_retry_deadletter.yml` never forces a failure — its name overstates coverage. This spec actually exercises the retry→DLQ path.

Tests (probe CDC webhook config + telemetry surface via `cdc_webhook_retry_deadletter.yml` / `geode_cdc_comprehensive.yml`):
- `setup-failing-sink`: `pre_server`/bash starts a tiny always-500 HTTP responder (python3 one-liner `http.server` subclass or `while true; nc` loop) on a fixed port; configure CDC webhook sink at it.
- `seed-events`: create nodes to emit CDC events.
- `retries-observed` (KEY): after a bounded wait, retry counter/telemetry > 0 (probe the metrics endpoint or CDC status CLI).
- `deadletter-after-budget` (KEY negative-path): DLQ count ≥ 1 once retry budget exhausts.
- `recovery-not-deadlettered` (positive): swap responder to a 200 responder (or stop asserting), emit a new event → delivered, DLQ count unchanged.
- Teardown kills the responder.

- [ ] Probe — [ ] Write — [ ] Run — [ ] Bug rule — [ ] Commit `test(specs): CDC webhook retries then dead-letters on persistent 5xx`

---

### Task 2: Backup restore corruption handling

**Files:** Create `geodetestlab-cli/specs/backup_restore_corruption.yml`
**Context:** complements `backup_operations_basic.yml` / `backup_restore_operations.yml` (clean round-trips only).

Tests:
- `seed+backup` (positive): seed `PN2_N` nodes; run the CLI backup to a temp path (copy invocation from `backup_operations_basic.yml`).
- `restore-truncated` (KEY negative): bash `truncate -s 50%`-style copy of the backup, restore from it → nonzero exit + integrity/corrupt error text.
- `restore-missing-path` (negative): restore from `/tmp/pn2_nonexistent.backup` → clean error (no panic/stack trace in stderr).
- `restore-bitflipped` (negative): bash flips one byte mid-file (`dd`/printf), restore → checksum/verify failure.
- `server-still-healthy` (positive): after all failed restores, `RETURN 1` and original data intact.

- [ ] Probe — [ ] Write — [ ] Run — [ ] Bug rule — [ ] Commit `test(specs): backup restore rejects truncated/missing/bitflipped archives cleanly`

---

### Task 3: WAL corrupt-record recovery

**Files:** Create `geodetestlab-cli/specs/wal_corrupt_record_recovery.yml`
**Interfaces:** `cleanup: false`; needs data_dir path (pattern from `regression_issue_539_wal_recovery_checkpoint.yml`); `single_node_only: true`.

Tests:
- `seed-committed`: create `PN3_A` nodes (committed, pre-corruption).
- `stop-and-corrupt`: bash — locate the WAL file under the data_dir, append garbage bytes / flip a byte in the TAIL region (only the final record — committed prefix must stay valid), then `restart_server: true`. Probe WAL file layout first; corrupt conservatively (tail-append garbage = torn-write simulation).
- `recovers-no-panic` (KEY): server restarted successfully (the restart itself proves no startup panic) and `RETURN 1` works.
- `committed-data-survives` (KEY positive): count of `PN3_A` == seeded count.
- `torn-write-tolerated` (negative-path): second round with a truncated final WAL entry → same clean recovery.

- [ ] Probe — [ ] Write — [ ] Run — [ ] Bug rule — [ ] Commit `test(specs): WAL recovery survives tail corruption/torn write, keeps committed data`

---

### Task 4: RBAC privilege escalation denied

**Files:** Create `geodetestlab-cli/specs/rbac_privilege_escalation_denied.yml`

Tests (probe user/role DDL from `rbac_users_roles_grants_audit.yml`):
- `setup`: admin creates non-admin `pn4_user` (basic role).
- `nonadmin-create-user-denied` (KEY negative): as pn4_user, `user create pn4_evil …` → denied error.
- `nonadmin-grant-denied` (KEY negative): as pn4_user, GRANT a role/privilege → denied.
- `grant-privilege-you-lack-denied` (negative): pn4_user grants a privilege it doesn't hold → denied.
- `nonowner-revoke-denied` (negative): pn4_user REVOKEs admin's privilege → denied.
- `denied-attempt-audited` (positive): audit log/query records the denial (probe audit query surface from `rbac_users_roles_grants_audit.yml`; if not queryable, drop this case and note it).

- [ ] Probe — [ ] Write — [ ] Run — [ ] Bug rule — [ ] Commit `test(specs): RBAC denies non-admin user/grant/revoke escalation paths`

---

### Task 5: ABAC malformed policy rejection

**Files:** Create `geodetestlab-cli/specs/abac_malformed_policy_rejection.yml`

Tests (probe policy DDL from `abac_attribute_policies.yml`):
- `invalid-expression-rejected` (KEY negative): CREATE POLICY with unbalanced/garbage expression → syntax error, not accepted.
- `unknown-attribute-behavior`: policy referencing `attr.nosuch_xyz` → error OR documented deny-all (probe; assert whichever, describing the contract).
- `duplicate-policy-name` (negative): create same-named policy twice → conflict error.
- `no-partial-install` (positive): after the rejections, `SHOW POLICIES` (or equivalent) lists only the valid baseline policy created in setup.

- [ ] Probe — [ ] Write — [ ] Run — [ ] Bug rule — [ ] Commit `test(specs): ABAC rejects malformed/duplicate policies without partial install`

---

### Task 6: Audit sink hard-failure policy

**Files:** Create `geodetestlab-cli/specs/audit_sink_failclosed_policy.yml`
**Interfaces:** `single_node_only: true`; audit sink at a controlled path (env/args from `audit_sink_failure_recovery.yml`).

Tests:
- `setup`: audited server with file sink in a temp dir; one audited op succeeds (baseline).
- `sink-unwritable` (KEY): bash `chmod 000` the sink dir; run an audited op → assert the configured policy: fail-closed (op rejected) or fail-open (op succeeds, failure surfaced in health/log). Probe first; encode the actual contract explicitly in the test description.
- `restore-sink + chain-verify` (positive): `chmod 755` back; audited op works; offline chain verify (CLI from `auth_chain_cli_offline.yml`) passes.

- [ ] Probe — [ ] Write — [ ] Run — [ ] Bug rule — [ ] Commit `test(specs): audit sink hard-failure policy pinned + chain intact after recovery`

---

### Task 7: Vector index errors

**Files:** Create `geodetestlab-cli/specs/vector_index_errors.yml` (salvage from `specs/legacy/vector_operations_comprehensive.yml`)

Tests (vector DDL/KNN syntax from `vector_hnsw_comprehensive.yml`):
- `setup` (positive): create vector index dim=4, insert 3 valid vectors, one KNN works.
- `wrong-dimension-insert` (KEY negative): insert dim=3 vector into dim=4 index → error.
- `invalid-metric` (negative): create index with metric `banana` → error.
- `knn-on-dropped-index` (negative): drop index, KNN → clean error (or documented fallback scan — probe).
- `malformed-vector-literal` (negative): non-numeric component `[1.0, 'x', 2.0]` → error.
- `knn-k-zero` (negative): k=0 / k=-1 → error or empty (probe; assert).

- [ ] Probe — [ ] Write — [ ] Run — [ ] Bug rule — [ ] Commit `test(specs): vector index negative paths — dim/metric/dropped/malformed/k`

---

### Task 8: Fulltext search negative

**Files:** Create `geodetestlab-cli/specs/fulltext_search_negative.yml`

Tests (FTS syntax from `fulltext_search_basic.yml` / `fulltext_bm25_comprehensive.yml`; includes the fts_storage fold-in):
- `setup` (positive): FTS index on `PN8_Doc.body`, seed 3 docs, one search hits.
- `malformed-query-syntax` (KEY negative): unbalanced quote/operator in the search string → error.
- `search-before-any-index` (negative): FTS call against a label with no FTS index → clean error.
- `search-dropped-index` (negative): drop the index, search → clean error.
- `search-empty-index` (positive-boundary): fresh index with 0 docs → 0 rows, exit 0.
- `index-on-numeric-property` (negative): create FTS index on an int property → rejected or documented (probe).

- [ ] Probe — [ ] Write — [ ] Run — [ ] Bug rule — [ ] Commit `test(specs): fulltext search negative paths — syntax/dropped/empty/non-text`

---

### Task 9: Index DDL errors

**Files:** Create `geodetestlab-cli/specs/index_ddl_errors.yml`

Tests (DDL from `geode_index_comprehensive.yml`):
- `setup` (positive): `CREATE INDEX pn9_idx …` on `PN9_N.k` succeeds.
- `duplicate-name` (KEY negative): identical CREATE INDEX again (no IF NOT EXISTS) → error.
- `if-not-exists-ok` (positive): with IF NOT EXISTS → exit 0 (if supported; probe).
- `drop-nonexistent` (negative): `DROP INDEX pn9_nosuch` → error; `IF EXISTS` variant → 0.
- `index-nonexistent-label-or-prop`: probe → assert error or documented no-op.
- `invalid-index-type` (negative): `CREATE BANANA INDEX …` → syntax error 42000-class.

- [ ] Probe — [ ] Write — [ ] Run — [ ] Bug rule — [ ] Commit `test(specs): index DDL negative paths — duplicate/drop-missing/bad-type`

---

### Task 10: Spatial geometry errors

**Files:** Create `geodetestlab-cli/specs/spatial_geometry_errors.yml`

Tests (function names from `spatial_wkb_functions.yml`):
- `setup` (positive): one valid `ST_Point`/`ST_GeomFromText` round-trip.
- `malformed-wkt` (KEY negative): `ST_GeomFromText('POINT(banana)')` → error.
- `wrong-arity` (negative): `ST_Point(1)` → error.
- `invalid-polygon`: self-intersecting/unclosed polygon into a predicate → error or documented result (probe).
- `inverted-bbox` (boundary): min>max bbox query → empty or error, never wrong rows (assert not-contains a known point).

- [ ] Probe — [ ] Write — [ ] Run — [ ] Bug rule — [ ] Commit `test(specs): spatial negative paths — WKT/arity/polygon/bbox`

---

### Task 11: Auto-index edge cases

**Files:** Create `geodetestlab-cli/specs/auto_index_edge_cases.yml`

Tests (behavior from `auto_index_id.yml` / `auto_index_lifecycle.yml`):
- `drop-auto-index` (KEY): attempt DROP of the auto-created id index → probe: rejected (assert error) or allowed-and-rebuilt (assert documented behavior).
- `reserved-name-collision` (negative): `CREATE INDEX` colliding with the auto-index name → error (no IF NOT EXISTS).
- `query-unindexed-label` (positive-boundary): id-lookup on a label never written → 0 rows, exit 0.
- `duplicate-id-values` (positive): two nodes same `id` prop value → both retrievable by id equality.

- [ ] Probe — [ ] Write — [ ] Run — [ ] Bug rule — [ ] Commit `test(specs): auto-index edge cases — drop/reserved-name/unindexed/duplicates`

---

### Task 12: Time-series argument validation

**Files:** Create `geodetestlab-cli/specs/timeseries_argument_validation.yml`

Tests (procedure names from `timeseries_basic.yml`):
- `setup` (positive): one valid `CALL geode.ts.insert(...)` + read-back.
- `wrong-arity` (KEY negative): `ts.insert` with a missing arg → error.
- `invalid-aggregation` (negative): `ts.sample_by(..., 'banana')` → error listing/naming invalid aggregation.
- `non-numeric-value` (negative): string value / float timestamp → type error.
- `malformed-insert-many` (negative): ragged nested array → error.
- `inverted-range` (boundary): start>end query → 0 rows, exit 0, no crash.

- [ ] Probe — [ ] Write — [ ] Run — [ ] Bug rule — [ ] Commit `test(specs): time-series procedure argument validation negatives`

---

### Task 13: ORDER BY negative

**Files:** Create `geodetestlab-cli/specs/order_by_negative.yml`

Tests:
- `setup`: seed `PN13_N {v}` ints.
- `nonexistent-column` : `ORDER BY n.nosuch` → probe: error OR nulls-ordering; assert the contract found.
- `invalid-direction` (KEY negative): `ORDER BY n.v ASCENDING` → 42000 syntax error.
- `mixed-incomparable-types`: seed one string `v`; `ORDER BY n.v` → error or documented total order (probe/assert).
- `out-of-range-ordinal` (negative): `ORDER BY 99` (if ordinals supported; else skip with reason).

- [ ] Probe — [ ] Write — [ ] Run — [ ] Bug rule — [ ] Commit `test(specs): ORDER BY negative paths — bad column/direction/mixed types`

---

### Task 14: CAST invalid

**Files:** Create `geodetestlab-cli/specs/cast_invalid.yml`

Tests (complements `cast_type_keywords.yml`; status_class channel from `gql_conformance_39075.yml`):
- `string-to-int` (KEY negative): `RETURN CAST('abc' AS INTEGER)` → 22018/error.
- `unsupported-target` (negative): CAST to a bogus/unsupported type → 0A000 or 42000.
- `numeric-overflow` (negative): oversized literal into a narrow type (probe supported narrow types; else INTEGER overflow via huge literal).
- `cast-null` (positive-boundary): `CAST(null AS INTEGER)` → null row, exit 0.
- `valid-cast-control` (positive): `CAST('42' AS INTEGER)` → 42.

- [ ] Probe — [ ] Write — [ ] Run — [ ] Bug rule — [ ] Commit `test(specs): CAST negative paths — invalid string/unsupported/overflow/null`

---

### Task 15: WHERE clause negative

**Files:** Create `geodetestlab-cli/specs/where_clause_negative.yml`

Tests:
- `setup`: seed `PN15_N {s: 'x', i: 1}`.
- `incompatible-compare`: `WHERE n.s < 5` → probe: error or false-rows; assert contract.
- `nonexistent-property` (boundary): `WHERE n.nosuch = 1` → 0 rows exit 0 (null semantics) — assert.
- `invalid-operator` (KEY negative): `WHERE n.i <> <> 1` / garbage token → 42000.
- `unbound-variable` (negative): `MATCH (n:PN15_N) WHERE m.i = 1 RETURN n` → error naming `m`.

- [ ] Probe — [ ] Write — [ ] Run — [ ] Bug rule — [ ] Commit `test(specs): WHERE negative paths — type-compare/missing-prop/op/unbound`

---

### Task 16: MERGE conflict negative

**Files:** Create `geodetestlab-cli/specs/merge_conflict_negative.yml`

Tests:
- `merge-undefined-var-pattern` (KEY negative): `MERGE (n:PN16_N {k: m.v})` with unbound `m` → error.
- `contradictory-oncreate-onmatch` : same key set differently in ON CREATE/ON MATCH → runs (semantics: only one arm fires) — assert the fired arm's value both on first (CREATE) and second (MATCH) execution.
- `merge-null-key` (negative): `MERGE (n:PN16_N {k: null})` → probe: error or documented; assert.
- `merge-without-return` (positive control): bare MERGE, no RETURN → exit 0 (complements `regression_match_merge_without_return.yml`).

- [ ] Probe — [ ] Write — [ ] Run — [ ] Bug rule — [ ] Commit `test(specs): MERGE negative/conflict paths — unbound/contradictory/null-key`

---

### Task 17: Parameter binding negative

**Files:** Create `geodetestlab-cli/specs/parameter_binding_negative.yml`

Tests (param CLI flags from `gql_parameter_binding.yml` / `positional_parameters.yml`):
- `positional-out-of-range` (KEY negative): query references `$2`, one param supplied → error.
- `missing-named-param` (negative): `$name` never provided → error naming it.
- `extra-params`: supply 3, use 1 → probe: error or ignored; assert.
- `type-mismatch-param` (negative): string param in arithmetic → 22xxx-class error.
- `valid-control` (positive): correct binding returns the value.

- [ ] Probe — [ ] Write — [ ] Run — [ ] Bug rule — [ ] Commit `test(specs): parameter binding negatives — missing/extra/out-of-range/type`

---

### Task 18: Recursion / CTE limits

**Files:** Create `geodetestlab-cli/specs/recursive_cte_limits.yml`
**Interfaces:** per-test `timeout_ms: 30000` — a hang is the failure mode under test.

Tests (syntax from `recursive_and_cte.yml`; limit behavior from `gql_parser_recursion_limit.yml`):
- `setup`: build a 4-node cycle `PN18_A→B→C→D→A`.
- `cycle-terminates` (KEY): variable-length/recursive traversal over the cycle → terminates within timeout, finite rows.
- `depth-limit-exceeded` (negative): recursion past the configured max depth → clean error (probe the knob/limit).
- `huge-varlength-bound` (boundary): `[*1..100000]` on the small graph → completes bounded or errors cleanly — must NOT hang.
- `cte-missing-base-case` (negative): self-referential CTE without base → error (if CTE syntax supports it; else skip with reason).

- [ ] Probe — [ ] Write — [ ] Run — [ ] Bug rule — [ ] Commit `test(specs): recursion/CTE limit paths — cycle/depth/huge-bound terminate cleanly`

---

### Task 19: Graph algorithm edge cases

**Files:** Create `geodetestlab-cli/specs/graph_algorithm_edge_cases.yml`

Tests (call surface from `geode_graph_algorithms.yml`):
- `disconnected-shortest-path` (KEY boundary): shortestPath between two components → 0 rows/null, exit 0, no crash.
- `cycle-detect-on-dag` (boundary): cycle detection over a DAG → none found.
- `algorithm-on-empty-graph` (boundary): fresh label, algorithm call → empty result, exit 0.
- `unsatisfiable-filter` (boundary): var-length path with impossible property filter → 0 rows.

- [ ] Probe — [ ] Write — [ ] Run — [ ] Bug rule — [ ] Commit `test(specs): graph algorithm boundaries — disconnected/DAG/empty/unsatisfiable`

---

### Task 20: GROUP BY / aggregation negative

**Files:** Create `geodetestlab-cli/specs/group_by_aggregation_negative.yml`

Tests:
- `setup`: `PN20_N {g, v, s}` — ints + one string field.
- `non-grouped-column` (KEY): `RETURN n.g, n.v, count(*) GROUP BY n.g` → probe: error or implicit first-value; assert contract.
- `sum-of-strings` (negative): `RETURN sum(n.s)` → type error.
- `nested-aggregate` (negative): `RETURN sum(avg(n.v))` → error.
- `having-unknown-alias` (negative): HAVING referencing an undefined alias → error (if HAVING supported; probe, else skip with reason).
- `valid-control` (positive): plain grouped count correct.

- [ ] Probe — [ ] Write — [ ] Run — [ ] Bug rule — [ ] Commit `test(specs): aggregation negatives — non-grouped/sum-strings/nested/HAVING`

---

### Task 21: Connection pool explicit rejection

**Files:** Create `geodetestlab-cli/specs/connection_pool_rejection.yml`
**Interfaces:** server_args capping connections (probe the flag used by `connection_pool_max_connections.yml`, e.g. `--max-connections 4`); `single_node_only: true`.

Tests:
- `saturate` (bash): open N long-running client streams in background (long query or shell sessions).
- `over-cap-explicit-error` (KEY negative): N+1-th `geode query 'RETURN 1'` with a client timeout → exits nonzero within the timeout with a connection-rejected/limit error — NOT a hang (bash wraps with `timeout 15`).
- `recovers-after-drain` (positive): kill the background clients; a new query succeeds.

- [ ] Probe — [ ] Write — [ ] Run — [ ] Bug rule — [ ] Commit `test(specs): connection pool over-cap yields explicit rejection, recovers after drain`

---

### Task 22: Transaction conflict / state errors

**Files:** Create `geodetestlab-cli/specs/transaction_conflict_abort.yml`

Tests (txn surface from `gql_transaction_management_comprehensive.yml`, `transactions_mvcc_isolation.yml`):
- `commit-without-txn` (KEY negative): bare `COMMIT` → 25000-class invalid-transaction-state error.
- `rollback-without-txn` (negative): bare `ROLLBACK` → error or documented no-op (probe/assert).
- `statement-after-abort` (negative): in one session (shell/sequential test): BEGIN; failing statement; next statement → rejected until ROLLBACK.
- `concurrent-writes-conflict` (KEY): two overlapping sessions (sequential steps or bash background) writing the same node property → one gets a serialization/conflict abort (40001-class). If genuinely not reproducible black-box, pin what IS observable and report.

- [ ] Probe — [ ] Write — [ ] Run — [ ] Bug rule — [ ] Commit `test(specs): transaction state/conflict negatives — bare COMMIT, post-abort, write-write`

---

### Task 23: Network types validation (re-homed from legacy)

**Files:** Create `geodetestlab-cli/specs/network_types_validation_active.yml` (salvage from `specs/legacy/network_types_validation.yml`)

Tests:
- `invalid-ipv4` (KEY negative): `999.1.1.1` literal → error.
- `malformed-ipv6` (negative): `::gggg` → error.
- `bad-mac` (negative): `zz:zz:zz:zz:zz:zz` → error.
- `invalid-cidr` (negative): `10.0.0.0/33` → error.
- `valid-controls` (positive): one valid IPv4/IPv6/MAC/CIDR each round-trips.

- [ ] Probe — [ ] Write — [ ] Run — [ ] Bug rule — [ ] Commit `test(specs): network type validation negatives re-homed from legacy`

---

### Task 24: Migration failure handling

**Files:** Create `geodetestlab-cli/specs/migration_failure_handling.yml`

Tests (migration surface from `migration_engine.yml`; uses `setup_files` to create migration files):
- `valid-migration-control` (positive): one good migration applies; version advances.
- `syntax-error-migration` (KEY negative): migration file with bad GQL → apply fails, version NOT advanced (re-query version).
- `duplicate-version` (negative): second file with same version → rejected.
- `unreachable-server` (negative): migrate CLI pointed at a dead port → clean connection error, nonzero exit.

- [ ] Probe — [ ] Write — [ ] Run — [ ] Bug rule — [ ] Commit `test(specs): migration failure handling — syntax/duplicate/unreachable`

---

### Task 25: Shell error handling

**Files:** Create `geodetestlab-cli/specs/shell_error_handling.yml`

Tests (shell test type from `shell_comprehensive_tests.yml`, `shell_source_batch.yml` — stdin-driven):
- `unknown-meta-command` (KEY negative): stdin `\banana` then a valid query → error message for the meta-command AND the follow-up query still returns (session survives).
- `source-missing-file` (negative): `\source /tmp/pn25_nosuch.gql` → error, prompt returns, next command works.
- `malformed-query-session-survives` (KEY): garbage GQL then `RETURN 1` → error then success in same session.
- `exit-code-clean` : session ends with expected exit code.

- [ ] Probe — [ ] Write — [ ] Run — [ ] Bug rule — [ ] Commit `test(specs): shell error handling — meta/source/malformed leave session alive`

---

### Task 26: GPS DECIDE negative

**Files:** Create `geodetestlab-cli/specs/gps_decide_negative.yml`

Tests (DECIDE/USE GRAPH syntax from `gps_phase2_decide_comprehensive.yml`, `gps_phase3_use_graph_authorization.yml`):
- `malformed-decide` (KEY negative): DECIDE with garbage policy reference → error.
- `unknown-action-verb` (negative): DECIDE with unsupported action → error.
- `use-graph-nonexistent` (negative): `USE GRAPH pn26_nosuch` → error.
- `use-graph-unauthorized` (negative): non-admin without grant `USE GRAPH` on admin's graph → denied.
- `policy-ddl-unauthorized` (negative): non-admin creates a GPS policy → denied.

- [ ] Probe — [ ] Write — [ ] Run — [ ] Bug rule — [ ] Commit `test(specs): GPS DECIDE/USE GRAPH negatives — malformed/unknown/unauthorized`

---

### Task 27: Env var invalid values

**Files:** Create `geodetestlab-cli/specs/env_var_invalid_values.yml`
**Interfaces:** mostly `type: bash` scratch-server probes; `single_node_only: true`.

Tests:
- `invalid-port-env` (KEY negative): scratch server with `GEODE_PORT=banana` → exits nonzero with a config error (not a hang/panic) — bash with `timeout`.
- `invalid-numeric-env` (negative): a numeric knob (`GEODE_AUTH_RATE_LOCKOUT_SECS=xyz`) → startup error or documented default-fallback (probe/assert).
- `unknown-env-ignored` (positive): `GEODE_TOTALLY_UNKNOWN=1` → boots fine.
- `malformed-dsn` (negative): client with `--dsn 'geode://:::bad'` → clean parse error (complements `dsn_graph_binding.yml`).

- [ ] Probe — [ ] Write — [ ] Run — [ ] Bug rule — [ ] Commit `test(specs): env/DSN invalid-value handling — port/numeric/unknown/DSN`

---

### Task 28: Advanced types boundary

**Files:** Create `geodetestlab-cli/specs/advanced_types_boundary.yml` (salvage from `specs/legacy/advanced_types_integration.yml`)

Tests:
- `decimal-precision-overflow` (KEY negative): value exceeding declared scale/precision → error or documented rounding (probe/assert).
- `interval-overflow` (negative): interval arithmetic overflowing → error (complements `gql_interval_comparisons.yml`).
- `datetime-out-of-range` (negative): year 999999 / month 13 → error.
- `numeric-literal-overflow` (negative): literal beyond i64 → parse/range error.
- `valid-controls` (positive): near-boundary valid values round-trip.

- [ ] Probe — [ ] Write — [ ] Run — [ ] Bug rule — [ ] Commit `test(specs): advanced type boundary negatives — decimal/interval/datetime/overflow`

---

### Task 29: Multi-graph isolation negative

**Files:** Create `geodetestlab-cli/specs/multi_graph_isolation_negative.yml`

Tests (multi-graph syntax from `multi_graph.yml`, `per_graph_storage_isolation.yml`):
- `setup`: create graphs `pn29_a`, `pn29_b`; write a node into `pn29_a`.
- `isolation` (KEY positive): query in `pn29_b` for the node → 0 rows.
- `duplicate-graph-name` (negative): `CREATE GRAPH pn29_a` again → conflict error.
- `query-dropped-graph` (KEY negative): `DROP GRAPH pn29_b`; `USE GRAPH pn29_b` / bound query → error.
- `cross-graph-without-use` (negative): referencing a graph-qualified name without USE → error or documented (probe/assert).

- [ ] Probe — [ ] Write — [ ] Run — [ ] Bug rule — [ ] Commit `test(specs): multi-graph isolation negatives — dup name/dropped/cross-graph`

---

## Final Steps

- [ ] `cd geodetestlab-cli && source .venv/bin/activate && python -m geodetestlab run --specs specs --parallel 4 -v` — no NEW failures vs pre-plan baseline.
- [ ] Record any Bug-rule findings (limitation-pins) in the run summary for GAP filing.
