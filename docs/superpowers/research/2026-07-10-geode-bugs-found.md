# Geode Product Bugs Found During Spec-Coverage Expansion (2026-07-09/10)

While building negative/regression specs on branch `spec-expansion-2026-07-09`, probing
surfaced ~34 distinct geode product defects. Each is either captured as a self-activating
`*-limitation-pin` test (asserts today's wrong-but-real behavior; flips to failure when
fixed) or documented-only where reproducing it would crash the shared server. This list is
for filing GAPs against geode. Severity: **CRASH** = server panic/segfault; **SEC** =
security/authz; **CORRECTNESS** = wrong results; **VALIDATION** = missing input validation
(silent-accept); **BROKEN** = whole subsystem non-functional.

## Wholesale-broken subsystems

- **BROKEN — gRPC transport** (R6): gRPC handler globals are only initialized in the
  QUIC-listen branch of `main.zig`; every gRPC invocation times out. `make test-grpc`
  cannot pass any managed-server spec. Even the proven `--server X --grpc` form hangs.
- **BROKEN + CRASH — `geode migrate run --server`** (P24): hangs indefinitely AND crashes
  the managed server for BOTH valid and invalid migrations; when it returns it exits
  without applying (ledger unchanged). Migrate-path-specific — the same GQL via
  `geode query` exits 0 and the server survives. Root: `backup_cli.zig::execMigrationScript`
  / `connectMigrationClient` ← `migration/apply.zig::applyUpMigrations`. Unreachable host
  hangs instead of a clean connection error.

## Crashes (panic/segfault) — documented, not exercised

- **CRASH — repeated failing `CREATE INDEX`** (P9): issuing the same duplicate
  `CREATE INDEX` 4–5× in a row segfaults via double-free at `catalog.zig:777 addIndex`.
- **CRASH — `ORDER BY 0`** / any non-positive ordinal (P13): integer underflow in
  `getValueForKey`, `return_and_sorting.zig:203`.
- **CRASH — `CAST(1.0e308 AS INTEGER)`** (P14): panic "integer part of floating point value
  out of bounds".
- **CRASH — `Interval('P999999999Y')`** (P28): i32 multiply overflow, `datetime.zig:282`.
- **CRASH — `MakeInterval(2147483648, 1, 1)`** (P28): unchecked `@intCast` narrowing,
  `call_handlers.zig:1755`.
- **CRASH — unwritable audit sink at startup** (P6): `error.AccessDenied` unhandled at
  `main.zig:1447` (bare `try` on `AuditLogger.init` EACCES, `audit.zig:270`) + a
  leak-on-error-path artifact. Expected: graceful "cannot open audit log" refusal.
- **CRASH — missing `--data-dir`** (P6): server crashes when the data dir doesn't exist.
- **SEGFAULT — `labels(n),properties(n)` after crash+restart** (P3): `value_utilities.zig:235
  freeValue` map double-free/dangling.

## Security / authorization

- **SEC — non-admin can `CREATE POLICY`** (P26): a readonly user with zero grants creates a
  GPS policy and it persists. `execution.zig:2153` `.CreatePolicy` arm calls `addPolicy()`
  with only a cluster-replication gate — no `checkPermission()`/`gps.decide()`.
  `checkPermission()` (`execution.zig:915`) is never called anywhere. Policy-injection /
  privilege-escalation vector. Same dispatch-layer class as pre-existing CREATE GRAPH /
  CREATE INDEX gaps.
- **SEC — negative-authorization-cache poisoning** (R6): a denied graph-bind poisons later
  GRANTs for the same user (`gps.zig` `decision_cache` lacks invalidation on GRANT).
- **SEC/observability — denied DDL escalations emit no audit record** (P4): non-admin
  GRANT/CREATE USER/REVOKE denials (42501) are not audited; the admin-only gate returns
  `error.Unauthorized` before the audit path. Successful GRANTs are audited; denials are not.
- **SEC/observability — mid-run audit write failure is silent** (P6, `prlimit --fsize`):
  produces zero diagnostic anywhere (worse than the startup crash).

## Correctness (wrong results)

- **CORRECTNESS — label index not rebuilt after unclean crash** (P3): after a SIGKILL crash +
  reopen, `MATCH (n:Label) RETURN count(n)` returns 0 while `MATCH (n)` + property lookups
  return the full committed set. Graceful restart is correct 4/4. Distinct from the
  graceful-path fix geode 9a255a83.
- **CORRECTNESS — same-var path endpoints not unified at match time** (P19): `(n)-[*]->(n)`
  does NOT enforce endpoint identity. Non-aggregated `MATCH p=(n{id:'F'})-[:R*]->(n) RETURN
  nodes(p)` over an ACYCLIC DAG returns rows with start≠end. The existing
  `geode_graph_algorithms.yml` detect-cycles idiom `(n)-[*]-(n) WHERE length(p)>0 RETURN p`
  is broken (returns non-cycles as cycles).
- **CORRECTNESS — aggregate over var-length path drops WHERE** (P19): `count()` over a
  variable-length relationship pattern silently ignores an attached WHERE clause (count=2
  wrong vs `RETURN p` 0 rows correct).
- **CORRECTNESS — GROUP BY on unresolvable identifier collapses to one group** (R1):
  `RETURN n.x AS s, count(*) GROUP BY nosuch` silently collapses all rows into one null
  group instead of erroring.
- **CORRECTNESS — `sum()` of a string column returns 0** (P20): while `avg()` of the same
  column returns NULL (inconsistent), silently — wrong numeric data.
- **CORRECTNESS — statement after mid-txn error is not rejected** (P22): `BEGIN; CREATE;
  <type-error>; CREATE; COMMIT` commits BOTH CREATEs (ISO 39075 says post-error statements
  should be rejected until ROLLBACK). No corruption, but a spec-compliance gap.

## Missing input validation (silent-accept) — limitation-pinned

- **VALIDATION — CAST performs no semantic value validation** (P14): `CAST('abc' AS INTEGER)`,
  unsupported target types, overflow all silently → NULL / 00000 (never 22018/0A000). CAST
  rejects at PARSE time only.
- **VALIDATION — vector index has no input validation** (P7): wrong-dimension insert,
  invalid distance metric (`'banana'`), and malformed vector literals all silently accepted
  (data-integrity risk for the dim-mismatch case).
- **VALIDATION — FTS index on a numeric property** (P8): silently accepted, matches nothing,
  no diagnostic.
- **VALIDATION — ABAC malformed policy accepted** (P5): garbage `USING` expression silently
  accepted (`policy_catalog.zig:97` `catch null` lazy compile). NOT a privilege bug —
  `gps.zig::decide()` fail-closes null-compiled policies (verified end-to-end).
- **VALIDATION — duplicate ABAC policy name accepted** (P5): no uniqueness check; SHOW
  POLICIES lists two rows; DROP POLICY removes only the first → ghost duplicate.
- **VALIDATION — spatial bad geometry → NULL at bare-call level** (P10): malformed WKT /
  nonexistent function / degenerate polygon ring silently NULL (caught only when composed
  with a geometry consumer). Self-intersecting "bowtie" polygons accepted (no
  simple-polygon validation).
- **VALIDATION — `decimal_add` has no precision ceiling** (P28): unlike `decimal_mul`
  (which rejects with 58000), `decimal_add` silently produces a 39-digit result past the
  38-digit ceiling.
- **VALIDATION — WHERE unbound variable silently filters** (P15): `WHERE m.i = 1` with
  unbound `m` filters to 0 rows / 00000 instead of erroring "unknown variable m".
- **VALIDATION — MERGE unbound-var / null key** (P16): `MERGE (n {k: m.v})` (unbound m) or
  `MERGE (n {k: null})` silently creates a `k=null` node instead of erroring (dedups
  correctly, so no duplicates).
- **VALIDATION — parameter binding** (P17): out-of-range positional (`$2` with one param)
  and missing named params silently → NULL; extra params silently ignored. (Type-mismatch
  IS correctly rejected with 58000.)
- **VALIDATION — index on nonexistent label/property** (P9): `CREATE INDEX` on a nonexistent
  label or property silently succeeds and registers in SHOW INDEXES.
- **VALIDATION — aggregation edge cases** (P20): non-grouped column → first-inserted-row
  value; nested aggregate `sum(avg())` → NULL; HAVING on an unknown alias → NULL filters all
  rows — all silent.

## Operability / UX gaps (not bugs, but worth noting)

- **`--idle-timeout` decoupled** (P21): the flag only feeds the QUIC transport's
  `max_idle_timeout_ms`; the per-connection idle reap is a hardcoded 300000 ms
  (`quic_connection_handler.zig:1720`), so an abrupt SIGKILL doesn't reclaim the slot on the
  flag's schedule.
- **No explicit `POOL_EXHAUSTED` signal** (P21): over-cap connections queue and the client's
  own `--timeout` fires — operators never see a server-side admission rejection.
- **`GEODE_PORT` env var is inert** (P27): zero source references; only `--listen` binds.

## Harness (test-framework) issues found

- **Dead assertion keys**: `checks.py` is the authoritative runner path; `assertions.py`
  (which defines `row_count` / `geode_query` / `status_class`) is deprecated and unwired.
  So `geode_query: {...}` blocks and `row_count:` keys in existing specs
  (`per_graph_storage_resilience.yml`, `gql_transaction_management_comprehensive.yml`,
  `geode_edge_cases_errors.yml`, etc.) are silent no-ops → false coverage. Use
  `stdout_contains`/`exit_code`.
- **`plaintext_verification: patterns:` is a no-op** (R11): `PlaintextCheck.from_dict`
  (`spec.py:257`) reads only `search_patterns:`, so several TDE/FLE specs'
  `plaintext_verification` blocks are silent no-ops (their real protection is separate bash
  greps).
- **`CREATE FULLTEXT INDEX` DDL is unparsed** (R24): existing `fulltext_bm25_comprehensive.yml`
  tests fall back to `=~` scan with no index built (42000, exit 0). Working form is
  `CREATE INDEX … USING fulltext`.
- **Runtime bash gate-skips count as "passed"** (R6/R7/R23): the harness only tracks the
  static YAML `skip:` field; a `SKIPPED_*` bash exit-0 is counted as passed in the summary.
- **`cli.server.cleanup: false` / `data_dir:` are inert** (R21): `spec.py` never reads them;
  restart-durability works because the harness reuses one mktemp dir per run regardless.
- **Per-test `timeout_ms` below 30000 is inert** (R14): the runner uses
  `max(30000-default, per_test)`; a 30s subprocess timeout is the real hang backstop.
