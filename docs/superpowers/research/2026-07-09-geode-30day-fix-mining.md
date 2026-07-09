# Regression-Spec Mining Report: Geode (last 30 days) → Test-Harness (2026-07-09)

Research input for the 2026-07-09 spec-expansion plans. Produced from a sweep of 642 geode commits since 2026-06-09.

## Harness mechanics confirmed

- Geode gap numbers (`GAP-ENT-0048`, `GAP-0064`, `GAP-0900`, `GAP-0839`…) do NOT map to harness `gap_NNNN` spec filenames. Coverage judged by behavior/keywords.
- Verified harness capabilities:
  - `cli.server.args` — server flags; `cli.server.env` — env vars; `cli.server.cleanup: false` — preserve data_dir across the spec.
  - Test with `type: bash`, `command: …`, `restart_server: true` — restarts the server against the same data_dir (see `regression_issue_539_wal_recovery_checkpoint.yml`).
  - `type: bash` + `command:` — arbitrary shell (grep data_dir, send signals).
  - Query tests: `args: [query, "<GQL>"]` or `query: |`; assertions `expect: {row_count, values, min_rows, exit_code, error}`.

## A. Already covered (verify only)

| Commit | Behavior | Existing spec |
|---|---|---|
| 9a1ed6a1 stream ALL inline pages (>1000-row truncation) | unordered scan returns all rows | `gap_0257_orderby_large_resultset.yml` (`min_rows: 1500` baseline test) |
| 7cc6858e TDE plaintext hydration snapshots | sentinel absent on disk | partially: `tde_bitflip_detection.yml`, `tde_backup_envelope_wrong_kek.yml` — see B-11 |
| a21d3b58/f2c88ac4 GAP-0064 ORDER BY | sorted output | partially: `order_by_sorting_comprehensive.yml`, `gap_0257_…` — aliased + fresh-store auto-build NOT covered (B-13) |
| 4a5f4bba/b79fc5f7 insecure-TLS flag gating | `--insecure` rename | `gap_0256_insecure_flag_rename.yml` |
| 43c23d91/868954c0 unlabeled count(n) O(1) | full total | covered transitively by count specs |
| property-keyed GROUP BY | `GROUP BY n.dep` | `gap_0209_batch3_coverage.yml` etc. — alias form NOT covered (B-1) |

## B. Uncovered behaviors needing specs

### Tier 1 — silent data-correctness

- **B-1 (ce8bd8f0, d50d0666)** `groupby_return_alias_correctness.yml` — alias-grouped `RETURN n.prop AS s, count(*) AS c GROUP BY s` must not collapse to one null group; filtered `count(n)` parity. Pure GQL.
- **B-2 (35fe3549 GAP-0046)** `regression_merge_dedup_after_reopen.yml` — post-restart re-MERGE must MATCH not CREATE (single + composite keys). cleanup:false + restart_server.
- **B-3 (9a255a83)** `regression_label_count_after_reopen.yml` — first post-reopen `count(n:Label)` returns full count, never 0/partial.
- **B-4 (2e6283f2/7ef82b04)** `regression_reverse_traversal_seed.yml` — reverse single-hop bound on arrowhead endpoint returns correct neighbors.
- **B-5 (b350484d/09f18baa GAP-0839)** `regression_gap0839_inmemory_graph_tenant_bind.yml` — in-memory CREATE GRAPH gets stable UUID; tenant-bound session accepted.

### Tier 2 — security-observable

- **B-6 (#861 + 6701e9bc)** `security_graph_bind_authorization_861.yml` — ReadOnly non-admin bind of ungranted graph denied; ReadWrite allowed in non-strict tenancy; strict tenancy requires GRANT; gRPC parity.
- **B-7 (#849: c51c7d66 et al.)** `security_grpc_cdc_admin_gate_849.yml` — CDC ctrl/diag default-deny unauthenticated; non-Admin denied; Admin allowed.
- **B-8 (#860: 6e88807e et al.)** `security_reserved_username_guard_860.yml` — CREATE USER with reserved username refused; principal-envelope with reserved name rejected.
- **B-9 (be11253c gap 0026)** `security_graph_wal_durability_deferred_0026.yml` — GEODE_WAL_SYNC=deferred: acked security mutations survive restart; old password rejected.
- **B-10 (90b3a75a GAP-0061, 88f82375)** `regression_admin_auth_after_crash_reopen.yml` — admin auth works after hard restart with persisted credential; persisted credential wins over env.
- **B-11 (7cc6858e)** `tde_hydration_snapshot_no_plaintext.yml` — TDE on: `hydration_*.snap` contain no plaintext sentinel (bash grep of data_dir).

### Tier 3 — durability / restart-reload

- **B-12 (GAP-ENT-0048 family, GAP-0064/0065)** `regression_index_reload_after_reopen.yml` — first post-reopen index-served reads (WHERE eq, GROUP BY, DISTINCT, point seek) correct and prompt.
- **B-13 (f2c88ac4/a21d3b58/06ecb13f)** `regression_orderby_alias_and_freshstore.yml` — ORDER BY on fresh store w/o CREATE INDEX sorted; `ORDER BY a` (alias) == `ORDER BY n.v`; DESC correct.
- **B-14 (4a1efca4)** `regression_create_index_with_nodes_no_wedge.yml` — CREATE INDEX with pre-existing nodes returns promptly, server alive; +CONSTRAINT; +SHOW/DROP INDEX.

### Tier 4 — config / operability

- **B-15 (de9a769d GAP-ENT-0044/0045)** `read_executor_budget_53200.yml` — GEODE_READ_EXECUTOR_BUDGET_MB=1: oversized read → SQLSTATE 53200, server alive; =0 disables.
- **B-16 (c8b67533)** `point_write_indexed_seek_parity.yml` — indexed-seek SET/REMOVE parity with legacy path; persists across restart; GEODE_WRITE_EXECUTOR_BUDGET_MB=1 clean error.
- **B-17 (68618e60)** `quic_stream_multiplexing_default.yml` — multiplexing default ON; opt-out env `GEODE_QUIC_ENABLE_STREAM_MULTIPLEXING=0` boots and serves.
- **B-18 (221a97f1 gap 0039)** `regression_sigterm_bounded_shutdown_0039.yml` — SIGTERM exits within GEODE_SHUTDOWN_DRAIN_TIMEOUT_MS (generous CI gates).
- **B-19 (1b9ee266)** `config_buffer_pool_pages.yml` — GEODE_BUFFER_POOL_PAGES override works; garbage value falls back to default.
- **B-20 (ad6982d4/b0b4b3bd)** `fle_online_grant_plaintext_procedure.yml` — `CALL geode.fle.grantPlaintext(label, field, role)` online, no restart; restart-safe. Zero existing specs reference it.
- **B-21 (8eb24fd2/c0d5d3d5/f7d16c4a)** `typed_edge_count_durable.yml` — `count(r:TYPE)` exact + durable across restart; type isolation; nonexistent type → 0.

### Tier 5 — cluster (deferred; flaky/complex)

- **B-22 (97a0a8b8/33e3ad13)** `multi_node/cluster_write_idempotency_retry.yml` — committed-write timeout-retry idempotency.
- **B-23 (2cdc053a/ab700319)** edge orphan-slot self-heal after churn/reopen.

### Tier 6 — honest-scaffold refusal/feature fixes (verify existing, extend or add negatives)

- 521fd629 GAP-0865 ts durability → extend `timeseries_basic.yml`
- 4e615e46 GAP-0880 backup upload/codec → verify `backup_*` specs
- 794bae40 GAP-0869 phrase/proximity/highlight FTS → verify `fulltext_*`
- b920251d GAP-0876 MV rewrite → verify `mv_refresh_latency_envelope.yml`
- **6264a7e0 GAP-0871** GQL BACKUP/RESTORE stable refusal → NEW negative spec (likely uncovered)
- **3c56fef1 GAP-0872** CDC Kinesis/PubSub sinks fail loud → NEW negative spec
- 5f7dc7a8 GAP-0867 / 017e7b1d GAP-0868 truthful EXPLAIN/PROFILE → verify `explain_profile_unit_tests.yml`
- d86dbcb5 GAP-0884 MFA step-up classification → verify `authn_mfa_totp_edges.yml`
- 973e27e7 GAP-0890 / 732cbd58 key-rotation tick → verify `fle_key_rotation_atomic.yml`, `tde_key_rotation_crash_safety.yml`

## Priority order

1. B-1, B-2, B-3 (silent wrong results) 2. B-6..B-9 (security) 3. B-12..B-14 (durability/wedge) 4. B-15..B-17, B-20 (config/feature contracts) 5. B-4, B-5, B-10, B-11, B-18, B-19, B-21 6. B-22/B-23 + Tier 6.

Note: fips + graph-storage bump commits are internal; exercised transitively. fix(ci)/chore/build filtered out.
