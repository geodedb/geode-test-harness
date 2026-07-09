# Geode Test-Harness Spec Coverage Audit — Positive/Negative Gap Analysis (2026-07-09)

Research input for `docs/superpowers/plans/2026-07-09-spec-coverage-expansion.md`.
Produced by a full sweep of all 329 spec files.

## Method & harness facts

- **329 spec files** total: 308 in `geodetestlab-cli/specs/*.yml`, plus `encryption/` (5), `multi_node/` (1), `future/` (3, largely aspirational), `legacy/` (13, deprecated superseded suites), `quic/` (3 `.yaml`).
- **Assertion vocabulary** (how negatives are encoded):
  - `expect.exit_code: <nonzero>` — hard CLI failure (67 files use it).
  - `expect.stderr_contains` / `stderr_regex` — error-message assertions (44 files).
  - `expect.geode_query.status_class: '42xxx' | '22xxx' | '0Axxx' | '25000' | '2D...'` — SQLSTATE-style error classes asserted **with exit_code 0** (13 files, e.g. `42000` syntax, `22018` invalid cast, `0A000` unsupported, `22000` data exception). Main "soft negative" channel.
  - `expect.stdout_not_contains` (82 uses) — leak/secret-absence security negatives.
  - `expect_error` (10), `should_fail` (2), `error_contains` (1) — sparse legacy keys.
- **Positive** assertions dominate: 1,677 `stdout_contains`, 194 `stdout_json_assert`, 104 `result_contains`, plus `row_count`/`columns`.

**Coverage math:** 87 files carry at least one negative indicator; **245 files are effectively positive-only.**

## Feature-area coverage table

| Feature area | Representative spec files | Positive | Negative |
|---|---|---|---|
| AuthN (pwd hashing, MFA/TOTP, API keys, rate-limit, mTLS, timing) | `authn_argon2id_min_params`, `authn_mfa_totp_edges`, `authn_apikey_revocation`, `api_key_auth`, `authn_rate_limiter(_expiry)`, `authn_mtls_rejection_matrix`, `authn_blake2b_migration`, `authn_timing_invariance`, `mfa_comprehensive_security` | yes | **yes** |
| AuthZ / RBAC | `rbac_users_roles_grants_audit`, `rbac_alter_user_nonexistent_role`, `rbac_revoke_invalidates_session`, `rbac_drop_user_terminates_sessions`, `rbac_grant_write_chain_corruption_pin`, `rbac_custom_role_binding_pin`, `rbac_concurrent_alter_user`, `geode_auth_ddl(_persistence)` | yes | **partial** (no grant/revoke-denied-to-non-admin, no privilege-escalation-denied) |
| RLS | `rls_injection_resistance`, `rls_indeterminate_denies`, `rls_cross_tenant_query_shapes`, `rls_fle_no_decrypt_on_deny`, `rls_policy_cache_invalidation`, `rls_vm_bounds`, `distributed_rls_enforcement` | yes | **yes** |
| ABAC | `abac_attribute_policies`, `abac_policy_expressions_audit`, `gap_0165_abac_enforcement`, `gps_phase6_abac_migration` | yes | **partial** (no malformed-policy-expression rejection, no unknown-attribute reference error) |
| FLE | `fle_comprehensive_security`, `fle_decrypt_denied_placeholder`, `fle_key_rotation_atomic`, `fle_blind_index_search`, `fle_plaintext_verification_*` (10), `encryption/*` | yes | **yes** |
| TDE | `tde_backup_envelope_wrong_kek`, `tde_bitflip_detection`, `tde_kms_unreachable_fails_closed`, `tde_nonce_uniqueness`, `tde_key_rotation_crash_safety`, `tde_plaintext_verification_*` (8) | yes | **yes** |
| Audit chain | `audit_ed25519_verification`, `audit_hmac_chain_restart`, `audit_config_change_events`, `audit_jsonl_atomic_writes`, `audit_sink_failure_recovery`, `geode_audit_*` | yes | **partial** (no sink hard-fail fail-closed/open policy assertion, no unauthorized-actor config-change rejection) |
| 2PC / distributed txn | `2pc_cluster_token_required/absent`, `2pc_nonce_replay_protection`, `2pc_coordinator_timeout`, `2pc_participant_recovery`, `2pc_frame_limit`, `distributed_2pc_undo`, `distributed_snapshot_serialization` | yes | **yes** |
| WAL / recovery / backup | `regression_issue_539_wal_recovery_checkpoint`, `storage_restart_persistence`, `backup_operations_basic`, `backup_restore_operations`, `gap_137_backup_tls`, `gap_0181_backup_lsn_tracking` | yes | **partial** (no corrupt/truncated-backup restore, no corrupt-WAL-record replay, no unwritable-target) |
| Indexes — auto-index | `auto_index_id`, `auto_index_id_advanced`, `auto_index_lifecycle` | yes | **no** |
| Indexes — vector/HNSW | `vector_hnsw_comprehensive`, `vector_operations_basic`, `issue_476/477_vector_*` | yes | **no** (dim-mismatch/metric/dropped-index only in deprecated `legacy/`) |
| Indexes — fulltext/BM25/FTS | `fulltext_search_basic`, `fulltext_bm25_comprehensive`, `fts_storage_basic` | yes | **no** |
| Indexes — spatial | `spatial_rtree_comprehensive`, `spatial_wkb_functions` | yes | **no** (no malformed-geometry rejection) |
| Indexes — general DDL | `geode_index_comprehensive` (39 tests), `geode_advanced_index_lifecycle` | yes | **no** (no dup-index/drop-nonexistent/bad-target errors) |
| Query — type system / cast | `gql_type_system_comprehensive`, `cast_type_keywords`, `geode_edge_cases_errors` | yes | **partial** (`cast_type_keywords` positive-only) |
| Query — WHERE / operators | `where_clause_operators`, `gql_expressions_comprehensive` | yes | **no** |
| Query — ORDER BY / sorting | `order_by_sorting_comprehensive`, `gap_0257_orderby_large_resultset` | yes | **no** |
| Query — MERGE | `gql_merge_properties`, `gql_merge_edge`, `gql_merge_bare_set`, `merge_oncreate_unit_tests`, `regression_match_merge_without_return` | yes | **no** |
| Query — set ops / aggregation / DISTINCT | `gql_set_operations_comprehensive`, `order_by_sorting_comprehensive` | yes | **partial** (no GROUP-BY non-grouped-column error) |
| Query — params / positional | `gql_parameter_binding`, `positional_parameters` | yes | **no** (no missing/extra/type-mismatch param) |
| Query — recursion / CTE / nested | `recursive_and_cte`, `nested_queries_basic/advanced`, `gql_parser_recursion_limit` | yes | **partial** (CTE/nested positive-only) |
| Query — pattern/catalog/DML/session/txn conformance | `gql_pattern_matching_comprehensive`, `gql_catalog_operations_comprehensive`, `gql_data_modification_comprehensive`, `gql_conformance_39075`, `gql_session_management_comprehensive`, `gql_transaction_management_comprehensive` | yes | **yes** (status_class error assertions) |
| Graph algorithms | `geode_graph_algorithms`, `geode_advanced_math_algorithms` | yes | **no** |
| CDC | `cdc_kafka_resume_token`, `cdc_webhook_retry_deadletter`, `geode_cdc_comprehensive` | yes | **no** (webhook DLQ/5xx-retry *named* but not actually exercised) |
| Connection / transport (QUIC/gRPC/pool) | `connection_pool_exhaustion`, `connection_pool_max_connections`, `quic_tls_pinning`, `grpc_mtls_rejection_matrix`, `quic_stream_cancel_rollback`, `quic_pollsync_stress`, `migration_quic_stability` | yes | **partial** (pool over-limit tests assert *survival*, not explicit admission-rejection error) |
| CLI flags / env / DSN | `cli_flags_comprehensive`, `environment_variables_basic`, `dsn_graph_binding`, `query_file_flag_comprehensive/edge_cases`, `gap_0256_insecure_flag_rename` | yes | **yes** |
| Shell | `shell_comprehensive_tests`, `shell_advanced/extended/enterprise_tests`, `shell_completion_comprehensive`, `shell_reconnection`, `shell_session_stability`, `shell_source_batch`, `shell_plain_mode` | yes | **partial** (no invalid meta-command / bad-source-file negatives) |
| HTTP / MCP / LSP | `gap_0166_prometheus_metrics`, `mcp_full_surface`, `lsp_full_surface`, `mcp_client_integration` | yes | **yes** |
| Time-series | `timeseries_basic`, `timeseries_case_insensitivity` | yes | **no** |
| GPS / graph-policy binding | `gps_phase2..7_*`, `gps_persistence_*`, `gps_decide_smoke`, `dsn_graph_binding` | yes | **partial** (no malformed-DECIDE / unauthorized-USE-GRAPH) |
| Network types | `network_types_basic`, `legacy/network_types_validation` | yes | **no** (validation only in deprecated legacy) |
| Migrations | `migration_engine`, `geode_migrations`, `migration_quic_stability` | yes | **partial** (no bad-migration-syntax / duplicate-version / failed-rollback) |
| Transactions (MVCC/large/chunked) | `transactions_mvcc_isolation`, `transaction_state_basic`, `transaction_large_commit`, `transactions_large_rollback`, `transactions_chunked_edges`, `large_transaction_rollback` | yes | **partial** (no write-skew/serialization-failure abort error, no commit-without-txn) |

## Prioritized gap list (proposed new specs)

### Tier 1 — security / data-integrity negatives

1. **`cdc_webhook_deadletter_on_5xx.yml`** — CDC — negative. `cdc_webhook_retry_deadletter.yml` is named for DLQ-on-persistent-failure but only asserts telemetry/health — never forces a failure. Cases: (a) point sink at an always-5xx endpoint, seed events, assert retry count increments; (b) after retry budget exhausted, assert event lands in DLQ; (c) error-rate telemetry reflects failures; (d) successful events after recovery NOT dead-lettered.
2. **`backup_restore_corruption.yml`** — backup — negative. Cases: (a) restore truncated backup → nonzero exit + integrity error; (b) restore missing path → clean error not panic; (c) restore flipped-byte backup → checksum/HMAC failure; (d) server startable after failed restore.
3. **`wal_corrupt_record_recovery.yml`** — WAL — negative. Cases: (a) corrupt a WAL record then restart → recovery stops at last-good LSN, no panic; (b) truncated final WAL entry tolerated (torn write); (c) committed-before-corruption data survives; (d) stderr/log signals recovery boundary.
4. **`rbac_privilege_escalation_denied.yml`** — RBAC — negative. Cases: (a) non-admin runs GRANT/CREATE USER → denied; (b) user cannot grant a privilege it lacks; (c) REVOKE by non-owner denied; (d) audit records the denied attempt.
5. **`abac_malformed_policy_rejection.yml`** — ABAC — negative. Cases: (a) syntactically invalid policy expression → rejected; (b) unknown attribute reference → error or documented deny-all; (c) duplicate policy name → conflict; (d) rejected policy did not partially install.
6. **`audit_sink_failclosed_policy.yml`** — audit — negative. Cases: (a) unwritable audit sink + audited op → fail-closed blocks (or fail-open documented); (b) unauthorized config-change → denied + audited; (c) chain-verify passes after sink recovery.

### Tier 2 — index negatives

7. **`vector_index_errors.yml`** — cases: wrong-dimension insert; invalid metric name; KNN on dropped/nonexistent index; malformed vector literal; k<=0. (Salvage from `legacy/vector_operations_comprehensive.yml`.)
8. **`fulltext_search_negative.yml`** — cases: malformed FTS syntax; search dropped index; search empty index; FTS index on non-text property.
9. **`index_ddl_errors.yml`** — cases: duplicate index name; DROP nonexistent; index on nonexistent label/property; invalid index type keyword.
10. **`spatial_geometry_errors.yml`** — cases: malformed WKT; ST_Point wrong arity; invalid polygon; inverted bbox bounds.
11. **`auto_index_edge_cases.yml`** — cases: DROP auto-created index; reserved-name collision; query by id on non-indexed label; duplicate id values.

### Tier 3 — query/GQL correctness negatives

12. **`timeseries_argument_validation.yml`** — wrong arity; invalid aggregation name; non-numeric value/timestamp; malformed insert_many; inverted range.
13. **`order_by_negative.yml`** — nonexistent column; invalid direction keyword; incomparable mixed types; out-of-range ordinal.
14. **`cast_invalid.yml`** — 'abc'→INTEGER (22018); unsupported target (0A000); numeric overflow; CAST(null) semantics.
15. **`where_clause_negative.yml`** — incompatible-type compare; nonexistent property semantics; invalid operator; unbound variable.
16. **`merge_conflict_negative.yml`** — contradictory ON CREATE/ON MATCH SET; invalid pattern; uniqueness violation; MERGE-without-RETURN edge.
17. **`parameter_binding_negative.yml`** — $2 with one param; extra params; missing named param; type-mismatch param.
18. **`recursive_cte_limits.yml`** — cyclic-graph termination; depth-limit error; huge var-length bound; missing base case.
19. **`graph_algorithm_edge_cases.yml`** — disconnected shortest-path; DAG cycle-detection none; empty graph; unsatisfiable filter.
20. **`group_by_aggregation_negative.yml`** — non-grouped column; sum of strings; nested aggregate; HAVING unknown alias.

### Tier 4 — transport / transaction / infra robustness

21. **`connection_pool_rejection.yml`** — explicit over-cap rejection error (not hang); pool-acquire timeout error; reconnect after drain; rejection logged.
22. **`transaction_conflict_abort.yml`** — concurrent same-key writes → serialization abort (40001); COMMIT without txn; statement-after-abort; ROLLBACK without txn.
23. **`network_types_validation_active.yml`** — invalid IPv4/IPv6/MAC/CIDR. (Salvage from `legacy/network_types_validation.yml`.)
24. **`migration_failure_handling.yml`** — syntax-error migration; duplicate version; failed-mid-batch state; unreachable server.
25. **`shell_error_handling.yml`** — unknown meta-command; SOURCE nonexistent file; malformed query then next works; graceful reconnect failure.
26. **`gps_decide_negative.yml`** — malformed policy ref; USE GRAPH unauthorized/nonexistent; unknown action verb; policy DDL by unauthorized user.

### Tier 5 — completeness

27. **`fts_dropped_index_query.yml`** — (can fold into #8).
28. **`env_var_invalid_values.yml`** — invalid numeric env; env vs flag precedence; unknown env; malformed DSN.
29. **`advanced_types_boundary.yml`** — decimal precision overflow; interval overflow; datetime out-of-range; numeric literal overflow.
30. **`multi_graph_isolation_negative.yml`** — dropped-graph query; cross-graph without USE; duplicate graph name; isolation assertion.

## Cross-cutting observations

- Negative discipline is strong in security areas (AuthN, RLS, FLE, TDE, 2PC, mTLS, HTTP/MCP/LSP) and ISO-GQL conformance specs (`status_class`). New negatives there add marginal value.
- Systematic blind spot: feature-functionality tier — indexes (auto/vector/FTS/spatial/DDL), query-language surface (ORDER BY, CAST, WHERE, MERGE, params, CTE/recursion, GROUP BY, graph algorithms), time-series, network types.
- `legacy/` contains negative coverage not carried forward (`vector_operations_comprehensive.yml`, `network_types_validation.yml`, `advanced_types_integration.yml`) — salvage assertions rather than write from scratch (#7, #23, #29).
- `cdc_webhook_retry_deadletter.yml` overstates its coverage — highest-value single fix (#1).
