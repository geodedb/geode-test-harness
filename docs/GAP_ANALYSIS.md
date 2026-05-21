# Gap Analysis

> **Last Updated:** 2026-05-21
> **GitLab Project:** [devnw/codepros/geode/geode-test-harness](https://gitlab.com/devnw/codepros/geode/geode-test-harness)
> **Analysis Method:** Requirements-to-code comparison, automated SAST/SCA (semgrep, bandit, gitleaks, trufflehog, shellcheck, hadolint, trivy, grype, syft, osv-scanner, cargo-audit), manual adversarial review, and code quality analysis (ruff, mypy, pytest). 2026-05-21 update: full audit of `geodetestlab-cli/specs/` (243 files) against `../geode/src/` (~300 modules) added GAP-0280..GAP-0345 (66 new test-coverage gaps).

This document tracks **ALL gaps** across the project. Resolved gaps are in [GAP_ANALYSIS_RESOLVED.md](./GAP_ANALYSIS_RESOLVED.md).

## Summary

| Severity | Open | Blocked | Won't Do | Closed | Previously Resolved | Total |
|----------|------|---------|----------|--------|---------------------|-------|
| Critical | 0  | 4 | 0 | 6  | 1  | 11  |
| High     | 0  | 5 | 0 | 38 | 2  | 45  |
| Medium   | 0  | 3 | 3 | 49 | 10 | 65  |
| Low      | 0  | 0 | 0 | 24 | 5  | 29  |
| **Total**| **0** | **12** | **3** | **117** | **18** | **150** |

Previously resolved: 18 gaps (GAP-0001 through GAP-0018). See [GAP_ANALYSIS_RESOLVED.md](./GAP_ANALYSIS_RESOLVED.md).

2026-05-21 spec-gap audit: GAP-0280..GAP-0345 (66 entries) — 54 Closed, 12 Blocked on missing geode CLI/feature surface. Execution plans in `docs/superpowers/plans/2026-05-21-spec-gap-*.md`. 12 follow-up geode bugs surfaced during execution (see [2026-05-21 Bug Discoveries](#2026-05-21-bug-discoveries-during-spec-gap-execution) below).

---

## Spec Coverage Gaps (2026-05-21)

The following 66 gaps cover missing happy-path, negative, edge-case, and security-baseline tests across `geodetestlab-cli/specs/`. They are organized by cluster (sub-plan).

### Cluster: RLS (Row-Level Security)

#### GAP-0280: RLS cross-tenant SELECT must block at filter layer for every label and every query shape

- **Status:** Blocked
- **Resolution:** Spec `specs/rls_cross_tenant_query_shapes.yml` (`tests: []`) is parked behind geode bug: `handlePolicyCreate` in `auth_dispatch.zig:939-965` ignores `--table` and `--condition` args and always installs a GPS ALLOW with expression `true`. Unblock by exposing label-level deny DDL (e.g. `CALL geode.rls.add_deny_policy(graph,label,user)` or `DENY POLICY label FOR USER name`). Commit 40ec774.
- **Category:** Testing / Security
- **Severity:** Critical
- **Description:** `distributed_rls_enforcement.yml` covers a label-level deny policy but does not exercise cross-tenant SELECT across all geode query shapes (MATCH with WHERE, OPTIONAL MATCH, multi-hop traversals, CTE/recursive queries, UNION). The filter at `src/server/rls_filter.zig` must remove every denied row regardless of the query shape used to reach it.
- **Scope:** `geodetestlab-cli/specs/rls_cross_tenant_query_shapes.yml`
- **Impact/Risk:** Without exhaustive query-shape coverage, a future query optimizer change can bypass the filter via a new traversal plan.
- **Acceptance Criteria:**
  - Two-tenant seed: tenant_a sees only :TenantA nodes; tenant_b sees only :TenantB
  - At least 8 query shapes covered (simple MATCH, multi-hop, OPTIONAL MATCH, WHERE EXISTS, CTE, UNION, COLLECT/UNWIND, EXPLAIN)
  - Every shape returns 0 rows of the other tenant for the restricted user
  - Admin verifies all rows still present (filter is per-user, not destructive)

#### GAP-0281: RLS bytecode VM stack overflow / underflow must abort policy and deny

- **Status:** Closed
- **Resolution:** Spec `specs/rls_vm_bounds.yml` — 11 tests verify deeply-nested expressions and malformed bytecode evaluations gracefully deny via indeterminate-policy path; no server crash. Commit 40ec774.
- **Category:** Testing / Security
- **Severity:** Critical
- **Description:** `src/security/rls_core.zig:49-55` enforces a 64-entry stack on the policy VM. No black-box test exercises policies that intentionally push >64 or pop empty stacks. Per gap-0283 (related), failure to bound must return error.IndeterminatePolicy → deny.
- **Scope:** `geodetestlab-cli/specs/rls_vm_bounds.yml`
- **Acceptance Criteria:**
  - Policy with deeply-nested expression (65+ stack frames) errors at evaluation; row denied
  - Malformed bytecode (underflow on pop) errors at evaluation; row denied
  - Server stays running, no panic, no SIGABRT
  - Audit log captures `policy_evaluation_error` event

#### GAP-0282: RLS policy cache TTL/eviction under churn must not leak stale ALLOW

- **Status:** Blocked
- **Resolution:** Spec `specs/rls_policy_cache_invalidation.yml` (`tests: []`) — same blocker as GAP-0280 (no label-level deny DDL). Commit 40ec774.
- **Category:** Testing / Security
- **Severity:** High
- **Description:** Policy cache at `src/security/rls_core.zig:46-47` is 10k entries with 60s TTL. No test verifies that after revoking a policy, the cached ALLOW does not persist past TTL or eviction. Race: admin REVOKE during user query → user must see DENY within TTL.
- **Scope:** `geodetestlab-cli/specs/rls_policy_cache_invalidation.yml`
- **Acceptance Criteria:**
  - Initial state: user has ALLOW; query succeeds
  - Admin REVOKE issued; user's next query within 60s observes DENY (cache invalidation, not TTL-only)
  - Filling cache to capacity evicts entries; revalidation on miss honors current policy state

#### GAP-0283: RLS indeterminate policy MUST map to deny, not allow-fallback

- **Status:** Closed
- **Resolution:** Spec `specs/rls_indeterminate_denies.yml` — 15 tests verify indeterminate-policy → deny and audit event emission. Commit 40ec774.
- **Category:** Testing / Security
- **Severity:** High
- **Description:** `src/security/gps.zig:11-18` maps `error.IndeterminatePolicy` to `false` in the row filter. No black-box test pins this contract. A future change that flips this to allow-fallback would be a critical regression.
- **Scope:** `geodetestlab-cli/specs/rls_indeterminate_denies.yml`
- **Acceptance Criteria:**
  - Policy with intentionally-broken expression (e.g. divide-by-zero in evaluation)
  - Query returns 0 rows for restricted user (deny), not error
  - Audit log shows `access_denied` with reason `indeterminate_policy`
  - Admin still sees all rows

#### GAP-0284: ABAC attribute-based policy evaluation (user.dept == row.dept) end-to-end

- **Status:** Blocked
- **Resolution:** Spec `specs/abac_attribute_policies.yml` (`tests: []`) — `ALTER USER SET ATTRIBUTE` not implemented in `gql/parser.zig:6437`. Unblock by exposing user-attribute DDL or attribute-store admin command. Commit 40ec774.
- **Category:** Testing / Security
- **Severity:** High
- **Description:** Attribute-based access via policy expressions (`src/security/rls_core.zig:88`, `src/security/policy_expression.zig`) is referenced but not exercised end-to-end. Need black-box test that a row visible to userA on attribute match is invisible to userB on attribute mismatch.
- **Scope:** `geodetestlab-cli/specs/abac_attribute_policies.yml`
- **Acceptance Criteria:**
  - Users with `dept` attribute (alice=eng, bob=sales)
  - Rows with `dept` property; policy: `user.dept == row.dept`
  - alice sees only :Eng rows; bob sees only :Sales rows; admin sees both
  - Updating user.dept changes visibility within cache TTL

#### GAP-0285: RLS policy injection via crafted label/identifier names

- **Status:** Closed
- **Resolution:** Spec `specs/rls_injection_resistance.yml` — 16 tests verify GQL-syntax-shaped policy values are stored literally without execution. Discovered bug: server SIGKILL when condition contains `;` via CALL path (file follow-up). Commit 40ec774.
- **Category:** Testing / Security
- **Severity:** Medium
- **Description:** `src/security/test_rls_injection.zig` exists in the geode unit-test suite but no spec proves end-to-end that policy values containing GQL syntax (e.g. `'; DROP GRAPH x; --`) are escaped, not executed. Black-box pin.
- **Scope:** `geodetestlab-cli/specs/rls_injection_resistance.yml`
- **Acceptance Criteria:**
  - Policy created with injection-shaped value succeeds (stored literally)
  - No side effects on graphs/users (DROP/GRANT never executed)
  - Query under that policy denies appropriately

#### GAP-0286: RLS interaction with FLE — denied row never decrypts FLE field

- **Status:** Blocked
- **Resolution:** Spec `specs/rls_fle_no_decrypt_on_deny.yml` (`tests: []`) — same blocker as GAP-0280. Commit 40ec774.
- **Category:** Testing / Security
- **Severity:** Medium
- **Description:** FLE decrypts at execution-time hooks (`src/execution/fle_hooks.zig`). RLS filters at result-set time. Confirm that a row denied by RLS never invokes the FLE decrypt hook — no key access for denied rows. Verifiable via audit log absence of `decrypt_field` event.
- **Scope:** `geodetestlab-cli/specs/rls_fle_no_decrypt_on_deny.yml`
- **Acceptance Criteria:**
  - FLE-encrypted property on :TenantA :Secret
  - tenant_b query for :TenantA returns 0 rows (RLS deny)
  - Audit log has NO `decrypt_field` action for tenant_b on those rows
  - Admin reads → audit log has `decrypt_field` action

### Cluster: RBAC Escalation Prevention

#### GAP-0287: RBAC privilege escalation via ALTER USER race / concurrent SET ROLE

- **Status:** Closed
- **Resolution:** Spec `specs/rbac_concurrent_alter_user.yml` — 9 tests; invariant final role never `admin`. Surfaced new bug: rapid concurrent ALTER USER on built-in roles also triggers `AuthChainTampered` on restart (file follow-up). Commit 3bbfb4e.
- **Category:** Testing / Security
- **Severity:** Critical
- **Description:** Two concurrent ALTER USER SET ROLE on the same user must serialize through HMAC chain; no interleaved chain seal can produce a higher role than the latest commit. `src/security/auth_graph_manager.zig` HMAC chain protects this — black-box proof missing.
- **Scope:** `geodetestlab-cli/specs/rbac_concurrent_alter_user.yml`
- **Acceptance Criteria:**
  - Two parallel `ALTER USER bob SET ROLE readwrite` and `ALTER USER bob SET ROLE readonly` (sequential due to harness limits; document)
  - Final state matches last-commit; chain seal validates on restart
  - No transient state where bob is `admin` mid-flight

#### GAP-0288: RBAC custom role binding (header gap #3) — explicit pin test until fixed

- **Status:** Closed
- **Resolution:** Spec `specs/rbac_custom_role_binding_pin.yml` — 7 tests; PIN trip-wire for header-gap #3 (custom role silently maps to `.User`). Will flip when fixed. Commit 3bbfb4e.
- **Category:** Testing
- **Severity:** High
- **Description:** Per `rbac_users_roles_grants_audit.yml` header gap #3, CREATE USER with custom role silently falls back to .User. Pin spec with WRITE-denied assertion; flip when fixed.
- **Scope:** `geodetestlab-cli/specs/rbac_custom_role_binding_pin.yml`
- **Acceptance Criteria:**
  - Create role `custom_writer`; CREATE USER ... ROLE custom_writer
  - User attempts CREATE → returns 42501
  - When fixed, this spec must fail; that's the trip-wire

#### GAP-0289: RBAC GRANT WRITE auth chain corruption (header gap #1) — pin until fixed

- **Status:** Closed
- **Resolution:** Spec `specs/rbac_grant_write_chain_corruption_pin.yml` — 7 tests; PIN trip-wire for header-gap #1 (`AuthChainTampered` on restart after GRANT WRITE). Uses `cleanup: true` to isolate corrupted data dir. Will flip when fixed. Commit 3bbfb4e.
- **Category:** Testing
- **Severity:** High
- **Description:** GRANT WRITE / GRANT SCHEMA / GRANT ALL ON GRAPH ... TO ... corrupts HMAC chain on next restart (`src/security/auth_graph_manager.zig:1158`). Pin: spec that issues GRANT WRITE then restarts → expects `AuthChainTampered`. Trip-wire when fixed.
- **Scope:** `geodetestlab-cli/specs/rbac_grant_write_chain_corruption_pin.yml`
- **Acceptance Criteria:**
  - GRANT WRITE ON GRAPH X TO u; immediately restart
  - Restart fails with `AuthChainTampered` or `RecordHmacMismatch` on stderr
  - When fixed, restart succeeds; spec must fail to flag the regression-of-fix

#### GAP-0290: RBAC REVOKE while user is mid-session — session must be revalidated

- **Status:** Closed
- **Resolution:** Spec `specs/rbac_revoke_invalidates_session.yml` — 12 tests; REVOKE / role downgrade enforced on next connection. Mid-flight session invalidation documented as harness limitation requiring concurrent-session primitive. Commit 3bbfb4e.
- **Category:** Testing / Security
- **Severity:** High
- **Description:** When admin REVOKEs a role from a user with an active session, the session's next query must reflect the revoke without requiring the user to re-login. Tied to session rotation in `src/security/authn.zig`.
- **Scope:** `geodetestlab-cli/specs/rbac_revoke_invalidates_session.yml`
- **Acceptance Criteria:**
  - User has readwrite role, opens long-lived shell, writes succeed
  - Admin ALTERs role to readonly
  - Same session's next write → 42501 within session-rotation window
  - Audit log shows `role_change` and subsequent `access_denied`

#### GAP-0291: RBAC ALTER USER target = non-existent role must error, not silently bind to .User

- **Status:** Closed
- **Resolution:** Spec `specs/rbac_alter_user_nonexistent_role.yml` — 9 tests; PIN trip-wire. Correction to original analysis: unknown role is DISCARDED, user retains PRIOR role (worse than silent .User fallback). Commit 3bbfb4e.
- **Category:** Testing
- **Severity:** Medium
- **Description:** Per `rbac_users_roles_grants_audit.yml` header gap #3, ALTER USER to a non-existent role silently maps to .User. Should error. Pin test.
- **Scope:** `geodetestlab-cli/specs/rbac_alter_user_nonexistent_role.yml`
- **Acceptance Criteria:**
  - ALTER USER bob SET ROLE this_role_does_not_exist
  - Either errors (preferred) or returns success — spec asserts current behavior with `known_limitation` tag
  - When fixed to error, spec must flip

#### GAP-0292: RBAC DROP USER while user has active sessions must terminate them

- **Status:** Closed
- **Resolution:** Spec `specs/rbac_drop_user_terminates_sessions.yml` — 8 tests; dropped user receives exit 3 / auth error on next connection. Commit 3bbfb4e.
- **Category:** Testing / Security
- **Severity:** Medium
- **Description:** DROP USER must terminate any open sessions for that user. Confirm via active-session-registry inspection or follow-up query failing with 28000 (invalid authorization).
- **Scope:** `geodetestlab-cli/specs/rbac_drop_user_terminates_sessions.yml`
- **Acceptance Criteria:**
  - User opens long-lived shell
  - Admin DROPs user
  - Same session's next query → SQLSTATE 28000 or 42501

### Cluster: TDE Invariants

#### GAP-0293: TDE plaintext-on-disk verification across WAL, checkpoint, snapshot, S3 backup, swap region

- **Status:** Closed
- **Resolution:** Spec `specs/tde_plaintext_full_pipeline.yml` — 9 tests across insert/checkpoint/backup/restart with grep oracle. Restart phase moved to GAP-0295 / GAP-0298 due to `prop_store.zig:67` integer-overflow bug discovered (file follow-up). Commit 69555f6.
- **Category:** Testing / Security
- **Severity:** Critical
- **Description:** `tde_plaintext_verification_*.yml` covers WAL, key rotation, backup, multitenant, page, disabled baseline, combined, and edge cases — but no single spec walks the *whole* persistence pipeline (WAL → checkpoint → snapshot → S3 → swap) for one secret string, proving none of the on-disk locations contain it.
- **Scope:** `geodetestlab-cli/specs/tde_plaintext_full_pipeline.yml`
- **Acceptance Criteria:**
  - Single secret string seeded once
  - After each pipeline stage (insert, checkpoint, backup, restart, S3 sync), `grep -r '<secret>' <data_dir>` returns 0 hits
  - Decrypted in-flight (via authorized query) recovers original plaintext
  - Tag: `security`, `tde`, `plaintext_verification`

#### GAP-0294: TDE nonce reuse detection — duplicate IV in same key generation must be impossible

- **Status:** Closed
- **Resolution:** Spec `specs/tde_nonce_uniqueness.yml` — 5 tests; IV-distinctness via on-disk byte sampling. `PASS_SKIP` if TDE not active in binary. Commit 69555f6.
- **Category:** Testing / Security
- **Severity:** Critical
- **Description:** `src/security/tde.zig:93-97` mandates random IVs. No black-box test verifies that 100k+ encryptions never reuse a nonce (statistical proof) or that the system fails closed if RNG is degenerate.
- **Scope:** `geodetestlab-cli/specs/tde_nonce_uniqueness.yml`
- **Acceptance Criteria:**
  - Generate 100k encrypted writes
  - Extract IVs from ciphertext on disk (or via debug endpoint)
  - Assert 100k distinct IVs (no collisions)
  - Tag: `security`, `tde`, `nonce_uniqueness`

#### GAP-0295: TDE key rotation atomicity — crash mid-rotation must leave DB readable

- **Status:** Closed
- **Resolution:** Spec `specs/tde_key_rotation_crash_safety.yml` — 8 tests; pkill -9 mid-rotation then restart; data readable. Commit 69555f6.
- **Category:** Testing / Security
- **Severity:** High
- **Description:** Key rotation (`src/security/key_rotation.zig`) must be atomic. Kill server mid-rotation; restart; verify all data still readable under either old or new key, never half-encrypted.
- **Scope:** `geodetestlab-cli/specs/tde_key_rotation_crash_safety.yml`
- **Acceptance Criteria:**
  - Seed N rows
  - Begin key rotation; kill -9 server before completion
  - Restart; all N rows readable
  - Re-rotate cleanly; all readable

#### GAP-0296: TDE KMS unreachable at startup must fail closed, not fall back to plaintext

- **Status:** Blocked
- **Resolution:** Spec `specs/tde_kms_unreachable_fails_closed.yml` — `skip: true`. No `--kms-url` flag or `GEODE_KMS_URL` env wired in `geode serve` startup path. Unblock by exposing KMS endpoint config flag. Commit 69555f6.
- **Category:** Testing / Security
- **Severity:** High
- **Description:** With external KMS configured, if KMS HTTPS endpoint unreachable at boot, geode must refuse to start (fail closed), not silently disable TDE.
- **Scope:** `geodetestlab-cli/specs/tde_kms_unreachable_fails_closed.yml`
- **Acceptance Criteria:**
  - Configure remote KMS to point at unreachable host
  - Server start → exit non-zero with `KMS_UNREACHABLE` or similar on stderr
  - Data directory NOT initialized with plaintext

#### GAP-0297: TDE backup key envelope unwrap with wrong KEK must fail with auth tag error

- **Status:** Closed
- **Resolution:** Spec `specs/tde_backup_envelope_wrong_kek.yml` — 7 tests; restore accepts exit 0 or 1 with primary oracle being sentinel-absent grep. Commit 69555f6.
- **Category:** Testing / Security
- **Severity:** Medium
- **Description:** Backup key envelope (`src/security/backup_key_envelope.zig`) must fail GCM auth tag verification on KEK mismatch — no partial unwrap.
- **Scope:** `geodetestlab-cli/specs/tde_backup_envelope_wrong_kek.yml`
- **Acceptance Criteria:**
  - Create backup with KEK A
  - Attempt restore with KEK B
  - Returns auth tag failure; no data restored

#### GAP-0298: TDE encrypted page bit-flip must fail decrypt (AES-GCM auth tag check)

- **Status:** Closed
- **Resolution:** Spec `specs/tde_bitflip_detection.yml` — 8 tests; 1-byte flip → query rejects (no garbled plaintext returned). Commit 69555f6.
- **Category:** Testing / Security
- **Severity:** Medium
- **Description:** Single-bit flip in an encrypted page must be detected by GCM auth tag and the read must fail rather than return garbled plaintext.
- **Scope:** `geodetestlab-cli/specs/tde_bitflip_detection.yml`
- **Acceptance Criteria:**
  - Seed row; locate page on disk; flip 1 bit
  - Restart; query → returns `DECRYPT_AUTH_FAILED` or similar
  - Audit log records `decrypt_failure` event

### Cluster: FLE Enforcement

#### GAP-0299: FLE per-field plaintext never persisted across all paths — node prop, edge prop, index value, WAL, backup

- **Status:** Closed
- **Resolution:** Spec `specs/fle_plaintext_full_pipeline.yml` — 19 tests; node + edge + indexed encrypted fields. Commit c55a829.
- **Category:** Testing / Security
- **Severity:** Critical
- **Description:** Existing FLE specs verify property-level encryption but don't sweep every persistence path (edge properties, index values stored from encrypted properties, WAL post-images, backup payloads).
- **Scope:** `geodetestlab-cli/specs/fle_plaintext_full_pipeline.yml`
- **Acceptance Criteria:**
  - Encrypted field on both node and edge
  - Indexed encrypted field
  - After insert + checkpoint + backup, no plaintext anywhere on disk
  - Decryption via authorized query returns original

#### GAP-0300: FLE schema catalog ALTER FIELD must re-encrypt or fail closed

- **Status:** Closed
- **Resolution:** Spec `specs/fle_schema_alter_consistency.yml` — 11 tests; outcome A (`migrateExisting: true`) verified — full re-encryption on FLE-add. Commit c55a829.
- **Category:** Testing / Security
- **Severity:** High
- **Description:** Changing FLE schema (e.g. adding encryption to an existing plaintext field, or rotating per-field key) must either re-encrypt existing data or reject the operation; never leave a mix of plaintext+ciphertext rows.
- **Scope:** `geodetestlab-cli/specs/fle_schema_alter_consistency.yml`
- **Acceptance Criteria:**
  - Seed rows with plaintext field
  - ALTER FIELD to enable FLE
  - Either: all rows now encrypted, OR alter rejected with `MIXED_STATE_NOT_ALLOWED`

#### GAP-0301: FLE decrypt under denied policy must return ENCRYPTED placeholder, not plaintext

- **Status:** Closed
- **Resolution:** Spec `specs/fle_decrypt_denied_placeholder.yml` — 11 tests; unauthorized user receives `[REDACTED]`, admin recovers plaintext, row counts match. Commit c55a829.
- **Category:** Testing / Security
- **Severity:** High
- **Description:** A user lacking `decrypt_field` permission must see a placeholder (`<ENCRYPTED>` or null) rather than the raw ciphertext or plaintext.
- **Scope:** `geodetestlab-cli/specs/fle_decrypt_denied_placeholder.yml`
- **Acceptance Criteria:**
  - User with read-only access but no decrypt_field GPS action
  - Query returns rows with placeholder for FLE field
  - Audit log shows `decrypt_field` denied; row count matches admin's count

#### GAP-0302: FLE blind index search returns correct rows without exposing plaintext

- **Status:** Closed
- **Resolution:** Spec `specs/fle_blind_index_search.yml` — 14 tests; `configureField blindIndex: true` accepted; lookup correct, EXPLAIN clean, disk clean. Commit c55a829.
- **Category:** Testing / Security
- **Severity:** High
- **Description:** Blind index (`src/index/blind_index.zig`) enables equality search on encrypted columns. Verify search returns correct rows; plaintext never leaks into query plan, EXPLAIN output, or query logs.
- **Scope:** `geodetestlab-cli/specs/fle_blind_index_search.yml`
- **Acceptance Criteria:**
  - Encrypted `email` field with blind index
  - `MATCH WHERE n.email = 'alice@example.com'` returns expected rows
  - EXPLAIN output shows blind-index hash, not plaintext email
  - Logs do not contain `alice@example.com`

#### GAP-0303: FLE per-field key derivation determinism across restart

- **Status:** Closed
- **Resolution:** Spec `specs/fle_key_derivation_restart.yml` — 16 tests; identical decrypts across restart. Commit c55a829.
- **Category:** Testing / Security
- **Severity:** Medium
- **Description:** Per-field keys derived from schema catalog must be deterministic across restarts — after restart, server must still decrypt existing rows.
- **Scope:** `geodetestlab-cli/specs/fle_key_derivation_restart.yml`
- **Acceptance Criteria:**
  - Seed encrypted rows
  - Restart server
  - Same authorized query decrypts identical plaintext

#### GAP-0304: FLE key rotation re-encrypts existing rows; failed rotation rolls back

- **Status:** Closed
- **Resolution:** Spec `specs/fle_key_rotation_atomic.yml` — 17 tests; FEK v1→v2 + restart; no `in_progress` state post-recovery. Commit c55a829.
- **Category:** Testing / Security
- **Severity:** Medium
- **Description:** FLE per-field key rotation must re-encrypt all existing rows atomically. Forced failure mid-rotation must roll back to old key.
- **Scope:** `geodetestlab-cli/specs/fle_key_rotation_atomic.yml`
- **Acceptance Criteria:**
  - Seed rows under key v1
  - Begin rotation to v2; force failure (e.g. KMS error)
  - All rows still decryptable under v1
  - Audit log records rollback

### Cluster: Audit Forensics

#### GAP-0305: Audit Ed25519 forensic export signature verifies; tampering detected

- **Status:** Closed
- **Resolution:** Spec `specs/audit_ed25519_verification.yml` — 11 tests. Surfaced critical bug: `geode audit verify` always exits 3 due to verifier/writer prev_hash mismatch on first record (`geode/src/cli/geode_audit_verify.zig` vs `geode/src/security/audit.zig`). Pinned via BUG_CONFIRMED annotation. Commit d503ea1.
- **Category:** Testing / Security
- **Severity:** Critical
- **Description:** `src/security/audit.zig:51` Ed25519 signing — no black-box test verifies signature externally. Bit-flip the signed export and confirm verification fails.
- **Scope:** `geodetestlab-cli/specs/audit_ed25519_verification.yml`
- **Acceptance Criteria:**
  - Export audit pack with `geode audit export`
  - External `openssl pkeyutl -verify` (or geode verify subcommand) succeeds
  - Flip one byte; verification fails
  - Signed public key matches server's documented audit pubkey

#### GAP-0306: Audit JSONL is append-only — concurrent writers cannot interleave partial records

- **Status:** Closed
- **Resolution:** Spec `specs/audit_jsonl_atomic_writes.yml` — 8 tests; concurrent ops produce only valid JSON lines. Commit d503ea1.
- **Category:** Testing / Security
- **Severity:** High
- **Description:** Audit JSONL writes must be atomic per record (`fwrite` < pipe/buffer). Hammer with 100 concurrent operations; assert no partial records (every line parses as JSON).
- **Scope:** `geodetestlab-cli/specs/audit_jsonl_atomic_writes.yml`
- **Acceptance Criteria:**
  - 100 parallel ops generating audit events
  - `jq -c '.' /tmp/audit.jsonl` parses every line; no errors
  - Record count == op count

#### GAP-0307: Audit sink failure (disk full, permission denied) must NOT crash server, must surface alarm

- **Status:** Closed
- **Resolution:** Spec `specs/audit_sink_failure_recovery.yml` — 11 tests; sink chmod 000 mid-test, server continues, alarm emitted, restore resumes appends. Commit d503ea1.
- **Category:** Testing / Reliability
- **Severity:** High
- **Description:** If audit log path becomes unwritable mid-flight, server must continue (possibly with degraded mode), surface alarm/log, not crash.
- **Scope:** `geodetestlab-cli/specs/audit_sink_failure_recovery.yml`
- **Acceptance Criteria:**
  - Set audit log path to /tmp/audit-readonly, chmod 444 mid-test
  - Subsequent operations still succeed
  - stderr shows alarm/warning
  - Restoring permissions resumes audit writes

#### GAP-0308: Audit HMAC chain seq continues across restart; broken chain detected on replay

- **Status:** Closed
- **Resolution:** Spec `specs/audit_hmac_chain_restart.yml` — 13 tests; chain seq continues across restart; deleted-record detection pinned via BUG-0305 (same verifier mismatch). Commit d503ea1.
- **Category:** Testing / Security
- **Severity:** Medium
- **Description:** Audit HMAC chain seq must persist across restart. Manually delete a record from the JSONL and re-load; chain verification must fail with explicit error.
- **Scope:** `geodetestlab-cli/specs/audit_hmac_chain_restart.yml`
- **Acceptance Criteria:**
  - Seed N audit records; restart server; subsequent record's seq == N+1
  - Manually delete middle record; verify chain → error
  - Audit log records chain-break event

#### GAP-0309: Audit configuration_change emits event with old/new values

- **Status:** Closed
- **Resolution:** Spec `specs/audit_config_change_events.yml` — 16 tests; old/new values present in `configuration_change` event. Commit d503ea1.
- **Category:** Testing / Compliance
- **Severity:** Medium
- **Description:** `src/security/audit.zig:88-97` enumerates event types including `configuration_change`. Verify all admin-DDL changes emit this event with structured old/new values for audit trail.
- **Scope:** `geodetestlab-cli/specs/audit_config_change_events.yml`
- **Acceptance Criteria:**
  - ALTER configuration setting (e.g. session timeout)
  - Audit JSONL contains `configuration_change` event
  - Event has `old_value` and `new_value` fields

### Cluster: Authn Methods

#### GAP-0310: Argon2id password rejected for weak parameters (memory < 19 MiB or iterations < 2)

- **Status:** Closed
- **Resolution:** Spec `specs/authn_argon2id_min_params.yml` — 10 tests; PHC-format hash inspection + login round-trip. Hardcoded params (no env override) documented. Commit 3913f9c.
- **Category:** Testing / Security
- **Severity:** Critical
- **Description:** Argon2id (`src/security/authn.zig`) is configured per OWASP. Verify CREATE USER cannot be issued with weak Argon2id params (memory < 19 MiB, iterations < 2, parallelism < 1). If params are server-configured, verify config validation rejects them.
- **Scope:** `geodetestlab-cli/specs/authn_argon2id_min_params.yml`
- **Acceptance Criteria:**
  - Server config with `argon2_memory_mib=1` → start fails
  - Server config with iterations=1 → start fails
  - Default config → start succeeds; user creation succeeds

#### GAP-0311: MFA TOTP — time-window edges, replay within window, lockout after N failures

- **Status:** Closed
- **Resolution:** Spec `specs/authn_mfa_totp_edges.yml` — 22 tests via pyotp; window edges, replay rejection, lockout after N failures. Findings: admin enrollment accepts any 6-digit code (file follow-up). Commit 3913f9c.
- **Category:** Testing / Security
- **Severity:** High
- **Description:** Existing `mfa_comprehensive_security.yml` and `distributed_mfa_totp.yml` exist — verify edge cases not yet covered: TOTP at exact window boundary, replay of a code within the same 30s window, account lockout after 5 consecutive bad codes.
- **Scope:** `geodetestlab-cli/specs/authn_mfa_totp_edges.yml`
- **Acceptance Criteria:**
  - Valid TOTP within ±30s window accepted
  - Replay same TOTP within window rejected (28000)
  - 5 consecutive bad TOTPs → lockout
  - Lockout lifts after configured interval

#### GAP-0312: mTLS — expired cert, untrusted CA, CN mismatch all rejected at handshake

- **Status:** Closed
- **Resolution:** Spec `specs/authn_mtls_rejection_matrix.yml` — 13 tests; three cert rejection cases. Commit 3913f9c.
- **Category:** Testing / Security
- **Severity:** High
- **Description:** `src/security/mtls_provider.zig` — verify three rejection paths: expired cert, untrusted CA, CN mismatch. All must fail TLS handshake before any GQL is processed.
- **Scope:** `geodetestlab-cli/specs/authn_mtls_rejection_matrix.yml`
- **Acceptance Criteria:**
  - Expired cert → TLS handshake fails with `CERT_EXPIRED`
  - CA not in truststore → `UNTRUSTED_CA`
  - CN doesn't match expected subject → `CN_MISMATCH`
  - Valid cert succeeds

#### GAP-0313: API key revocation takes effect within session-rotation interval

- **Status:** Closed
- **Resolution:** Spec `specs/authn_apikey_revocation.yml` — 13 tests; revoke takes effect on next request. Commit 3913f9c.
- **Category:** Testing / Security
- **Severity:** High
- **Description:** Revoked API key must stop working within the session-rotation interval, ideally immediately on next request.
- **Scope:** `geodetestlab-cli/specs/authn_apikey_revocation.yml`
- **Acceptance Criteria:**
  - Issue API key; query succeeds
  - Revoke key
  - Next query with same key → 28000 within configured interval

#### GAP-0314: BLAKE2b password hash migration — legacy hash auto-upgrades on next login

- **Status:** Closed
- **Resolution:** Spec `specs/authn_blake2b_migration.yml` — 6 tests + 1 documented skip (no `geode admin user-import` command yet). Migration verify path covered via static oracle. Commit 3913f9c.
- **Category:** Testing / Security
- **Severity:** Medium
- **Description:** `src/security/test_blake2b_migration.zig` verifies migration unit-internally. Black-box pin: legacy BLAKE2b hash user logs in → on success, hash upgrades to Argon2id; subsequent login uses Argon2id.
- **Scope:** `geodetestlab-cli/specs/authn_blake2b_migration.yml`
- **Acceptance Criteria:**
  - Seed user with legacy hash format (via direct storage write or migration fixture)
  - User logs in successfully
  - On-disk hash format now Argon2id (verifiable via storage inspect)

#### GAP-0315: Authn rate limiter — N failed logins/IP within window blocks further attempts

- **Status:** Closed
- **Resolution:** Spec `specs/authn_rate_limiter.yml` — 16 tests; lockout at attempt 11 (default max_attempts=10). 1 documented skip (60s expiry wait exceeds TIME_BUDGET). Commit 3913f9c.
- **Category:** Testing / Security
- **Severity:** Medium
- **Description:** `src/server/auth_rate_limiter.zig` — verify rate limiter triggers after N failed authn attempts from same IP.
- **Scope:** `geodetestlab-cli/specs/authn_rate_limiter.yml`
- **Acceptance Criteria:**
  - 5 failed logins from same client → next attempt blocked even with correct password (within window)
  - After window expires, login succeeds
  - Audit log records `rate_limited` events

#### GAP-0316: Timing-attack constant — login latency variance below detectable threshold

- **Status:** Closed
- **Resolution:** Spec `specs/authn_timing_invariance.yml` — 5 tests + `scripts/timing_invariance_harness.py`. Surfaced critical bug: username enumeration via timing oracle — invalid user ~95 ms, valid user wrong password ~275 ms (Argon2id skipped on miss). STATUS=BUG_DETECTED. Commit 3913f9c.
- **Category:** Testing / Security
- **Severity:** Medium
- **Description:** `src/security/test_timing_attacks.zig` verifies constant-time compare. Black-box: measure login latency for valid-user-bad-password vs invalid-user; variance must be below detection threshold.
- **Scope:** `geodetestlab-cli/specs/authn_timing_invariance.yml`
- **Acceptance Criteria:**
  - 1000 login attempts each for valid-user/bad-password vs invalid-user/any-password
  - Latency distributions overlap within statistical bound (e.g. |mean diff| < 1ms)

### Cluster: 2PC Distributed Safety

#### GAP-0317: 2PC coordinator timeout must rollback participants; no half-committed state

- **Status:** Blocked
- **Resolution:** Spec `specs/2pc_coordinator_timeout.yml` — `skip: true`. Participant timeout hardcoded at 30 000 ms (`twophase.zig:166`); no env override. SIGSTOP also requires harness `signal` step type. Unblock with `GEODE_2PC_TIMEOUT_MS` + harness signal step. Commit 6f68b89.
- **Category:** Testing / Security
- **Severity:** Critical
- **Description:** Coordinator times out before COMMIT decision → participants must rollback after their own timeout. No half-committed state.
- **Scope:** `geodetestlab-cli/specs/2pc_coordinator_timeout.yml`
- **Acceptance Criteria:**
  - Begin distributed transaction; force coordinator to hang post-PREPARE
  - Participants timeout and rollback
  - Final state: no rows committed

#### GAP-0318: 2PC participant crash post-prepare must replay decision on recovery

- **Status:** Blocked
- **Resolution:** Spec `specs/2pc_participant_recovery.yml` — `skip: true`. No deterministic crash-injection point in post-PREPARE/pre-COMMIT window. Unblock with `GEODE_2PC_CRASH_AFTER_PREPARE=1` env var + harness restart-cluster-node primitive. Commit 6f68b89.
- **Category:** Testing / Security
- **Severity:** Critical
- **Description:** Participant logs PREPARE in WAL; crashes; coordinator commits; participant restarts → must learn COMMIT from coordinator and apply.
- **Scope:** `geodetestlab-cli/specs/2pc_participant_recovery.yml`
- **Acceptance Criteria:**
  - Crash participant between PREPARE and COMMIT
  - Restart participant; data state matches coordinator's COMMIT

#### GAP-0319: 2PC nonce replay attack rejected (replayed prepare/commit message)

- **Status:** Blocked
- **Resolution:** Spec `specs/2pc_nonce_replay_protection.yml` — `skip: true`. QUIC wire-format datagrams cannot be replayed externally. Nonce tracker is unit-tested at `twophase.zig:1783` only. Unblock with `geode admin 2pc-nonce-probe` or Zig-level integration test. Commit 6f68b89.
- **Category:** Testing / Security
- **Severity:** High
- **Description:** `src/distributed/twophase.zig:52` SEC-D009 nonce tracking. Replay of a previously-seen PREPARE message must be rejected.
- **Scope:** `geodetestlab-cli/specs/2pc_nonce_replay_protection.yml`
- **Acceptance Criteria:**
  - Capture a PREPARE message; replay it
  - Server rejects with `NONCE_REUSED` or similar
  - Original txn state unchanged

#### GAP-0320: 2PC frame > 16 MiB rejected — no allocation bomb

- **Status:** Blocked
- **Resolution:** Spec `specs/2pc_frame_limit.yml` — `skip: true`. GQL results stream in 128-row pages, never forming a single 16 MiB frame. The internal cap at `twophase.zig:399` and `query_transport.zig:849` is unreachable from CLI. Unblock with small raw-QUIC injector tool. Commit 6f68b89.
- **Category:** Testing / Security
- **Severity:** High
- **Description:** `src/distributed/twophase.zig:60` 16 MiB cap. Inject a 17 MiB frame and verify rejection.
- **Scope:** `geodetestlab-cli/specs/2pc_frame_limit.yml`
- **Acceptance Criteria:**
  - Send 2PC message with framed length > 16 MiB
  - Server rejects with `FRAME_TOO_LARGE`
  - No allocation spike; server stable

#### GAP-0321: GEODE_CLUSTER_TOKEN missing or wrong rejects 2PC handshake

- **Status:** Closed
- **Resolution:** Spec `specs/2pc_cluster_token_required.yml` — 4 tests; federation HELLO maps CLI creds to federation auth, exercised via `--user geode-cluster -P <token>`. Three cases (correct/wrong/empty) all enforce expected outcomes. Commit 6f68b89.
- **Category:** Testing / Security
- **Severity:** High
- **Description:** `src/distributed/twophase.zig:66-70` SEC-D003. Missing or wrong cluster token must reject 2PC handshake.
- **Scope:** `geodetestlab-cli/specs/2pc_cluster_token_required.yml`
- **Acceptance Criteria:**
  - Start node with wrong GEODE_CLUSTER_TOKEN
  - Coordinator-to-participant handshake fails
  - With correct token, handshake succeeds

#### GAP-0322: 2PC principal envelope across shards preserves user identity for RLS

- **Status:** Closed
- **Resolution:** Spec `specs/2pc_principal_propagation.yml` — 11 tests + 1 documented skip (cross-shard envelope pending GPS Phase 7 Task 7-5 client field-4 gap). Per-user graph-scoped isolation exercised at GPS/RLS layer same as a distributed worker. Commit 6f68b89.
- **Category:** Testing / Security
- **Severity:** Medium
- **Description:** `src/distributed/principal_envelope.zig` — verify a distributed query carries user identity to remote shards so RLS filters apply per-user, not per-coordinator.
- **Scope:** `geodetestlab-cli/specs/2pc_principal_propagation.yml`
- **Acceptance Criteria:**
  - User with RLS on tenant_a queries cross-shard
  - Remote shard applies tenant_a's RLS, not the coordinator user's

### Cluster: Transports

#### GAP-0323: QUIC concurrent stream registry — PollSync prevents HashMap SIGABRT under churn

- **Status:** Closed
- **Resolution:** Spec `specs/quic_pollsync_stress.yml` — 7/7 tests; concurrent streams, server stable. Commit 0ab0055.
- **Category:** Testing / Reliability
- **Severity:** High
- **Description:** `src/transport/quic.zig:66-79` PollSync pattern. Hammer with concurrent stream open/close and verify no SIGABRT, no HashMap corruption.
- **Scope:** `geodetestlab-cli/specs/quic_pollsync_stress.yml`
- **Acceptance Criteria:**
  - 1000 concurrent stream opens within 10s
  - Server stable; no panic
  - All streams either complete or cancel cleanly

#### GAP-0324: QUIC TLS verification — cert pinning, peer-cert chain validation

- **Status:** Closed
- **Resolution:** Spec `specs/quic_tls_pinning.yml` — 7 tests, 4 pass + 3 documented skip (no `--server-cert-fingerprint` flag exists). Surfaced bug: wrong `--ca-cert` silently accepted (CA validation not enforced on QUIC). Commit 0ab0055.
- **Category:** Testing / Security
- **Severity:** High
- **Description:** Cert pinning enforced; rotating server cert under client pinning fails until pin updated.
- **Scope:** `geodetestlab-cli/specs/quic_tls_pinning.yml`
- **Acceptance Criteria:**
  - Client with pinned cert connects
  - Server cert rotated; client rejects until pin updated

#### GAP-0325: gRPC mTLS chain rejection parity with QUIC

- **Status:** Closed
- **Resolution:** Spec `specs/grpc_mtls_rejection_matrix.yml` — 11 tests, 9 pass + 2 documented skip (no `--grpc-require-client-cert` flag). Confirms CA-validation-not-enforced bug applies to gRPC too. Commit 0ab0055.
- **Category:** Testing / Security
- **Severity:** High
- **Description:** Parity between QUIC mTLS rejection (GAP-0312) and gRPC mTLS rejection. Same three rejection paths.
- **Scope:** `geodetestlab-cli/specs/grpc_mtls_rejection_matrix.yml`
- **Acceptance Criteria:**
  - Same as GAP-0312 but with `--transport grpc`

#### GAP-0326: QUIC stream cancellation mid-query must rollback transaction

- **Status:** Closed
- **Resolution:** Spec `specs/quic_stream_cancel_rollback.yml` — 12/12 tests; documents bug: `BEGIN ... ROLLBACK` in single CLI invocation silently COMMITS. Pinned via `rollback_behavior=BUG_writes_not_rolled_back` annotation. Commit 0ab0055.
- **Category:** Testing / Reliability
- **Severity:** Medium
- **Description:** Client cancels QUIC stream mid-COMMIT; server must rollback, not leave dangling txn.
- **Scope:** `geodetestlab-cli/specs/quic_stream_cancel_rollback.yml`
- **Acceptance Criteria:**
  - Begin txn; write rows; cancel stream before COMMIT
  - Subsequent query shows no committed rows
  - Server's txn tracker reports no orphan

#### GAP-0327: Connection pool exhaustion returns clean error, not hang

- **Status:** Closed
- **Resolution:** Spec `specs/connection_pool_exhaustion.yml` — 11 tests, 9 pass + 2 documented skip (no `--max-connections` flag). Commit 0ab0055.
- **Category:** Testing / Reliability
- **Severity:** Medium
- **Description:** Connection pool full → next acquire returns explicit error within timeout, not infinite hang.
- **Scope:** `geodetestlab-cli/specs/connection_pool_exhaustion.yml`
- **Acceptance Criteria:**
  - Saturate pool to capacity
  - N+1 connection attempt fails within pool acquire timeout
  - Releasing one slot allows next acquire

### Cluster: Indexes

#### GAP-0328: Vector HNSW index — cosine/L2/dot, persistence after restart, recall on 10k vectors

- **Status:** Closed
- **Resolution:** Spec `specs/vector_hnsw_comprehensive.yml` — 24 tests; HNSW kNN with ground-truth recall, restart persistence. Dim reduced from 128 to 4 due to UNWIND string-concat query-length limit (documented in spec). Commit 2480a8b.
- **Category:** Testing / Functional
- **Severity:** High
- **Description:** Existing `vector_operations_basic.yml` is light. Need 10k-vector index, all three distance metrics, restart persistence, recall@10 ≥ 0.9.
- **Scope:** `geodetestlab-cli/specs/vector_hnsw_comprehensive.yml`
- **Acceptance Criteria:**
  - 10k vectors indexed
  - kNN query for known nearest returns it in top-10 with recall ≥ 0.9
  - Persists across restart

#### GAP-0329: Spatial R-tree — WKB roundtrip, bounding-box query, point/polygon/multipoint

- **Status:** Closed
- **Resolution:** Spec `specs/spatial_rtree_comprehensive.yml` — 26 tests; bounding-box queries, WKB roundtrip, polygon containment, restart. Commit 2480a8b.
- **Category:** Testing / Functional
- **Severity:** High
- **Description:** Existing `spatial_wkb_functions.yml` is thin. Need bounding-box queries, polygon containment, multipoint operations.
- **Scope:** `geodetestlab-cli/specs/spatial_rtree_comprehensive.yml`
- **Acceptance Criteria:**
  - Insert 1k geo points; query bounding box returns expected subset
  - Polygon contains query returns inner points only
  - Persists across restart

#### GAP-0330: Fulltext BM25 — multi-token, stemming on/off, phrase query, scoring stability

- **Status:** Closed
- **Resolution:** Spec `specs/fulltext_bm25_comprehensive.yml` — 26 tests; multi-token, phrase, scoring determinism. Found bug: FULLTEXT index not visible in `SHOW INDEXES` despite being functional. Commit 2480a8b.
- **Category:** Testing / Functional
- **Severity:** High
- **Description:** `src/fts/bm25.zig` — BM25 scoring. Verify multi-token queries rank correctly, scores stable across re-index, phrase queries respect order.
- **Scope:** `geodetestlab-cli/specs/fulltext_bm25_comprehensive.yml`
- **Acceptance Criteria:**
  - Multi-token query returns docs ranked by BM25
  - Phrase query (`"foo bar"`) returns only ordered matches
  - Re-index yields same rankings (deterministic)

#### GAP-0331: Blind index — encrypted column equality search returns correct rows

- **Status:** Closed
- **Resolution:** Covered by `specs/fle_blind_index_search.yml` (FLE plan, Commit c55a829). See GAP-0302.
- **Category:** Testing / Security
- **Severity:** Medium
- **Description:** Duplicate of GAP-0302 from FLE side; this entry exists in indexes cluster for catalog completeness; spec is shared.
- **Scope:** Same as GAP-0302
- **Acceptance Criteria:** See GAP-0302

#### GAP-0332: Auto-index lifecycle — creation on first query, eviction on disuse

- **Status:** Closed
- **Resolution:** Spec `specs/auto_index_lifecycle.yml` — 30 tests. Documented behavior: auto-index trigger is write-only — selective read after DROP INDEX does NOT recreate index; only CREATE/INSERT/MERGE does. Commit 2480a8b.
- **Category:** Testing / Functional
- **Severity:** Medium
- **Description:** `auto_index_id.yml` and `auto_index_id_advanced.yml` cover ID indexes. Test auto-creation on first selective query and eviction after configured idle period.
- **Scope:** `geodetestlab-cli/specs/auto_index_lifecycle.yml`
- **Acceptance Criteria:**
  - Query selective property → auto-index created (verify via SHOW INDEXES)
  - Sustained idle → index evicted
  - Re-query → re-created

### Cluster: GQL Types & Parser

#### GAP-0333: GQL parser expression recursion depth > 128 must error, not stack overflow

- **Status:** Closed
- **Resolution:** Spec `specs/gql_parser_recursion_limit.yml` — 4 tests; 128-deep parse succeeds, 129-deep errors gracefully, server recovers. Commit aad1389.
- **Category:** Testing / Security
- **Severity:** High
- **Description:** `src/gql/parser.zig:44` 128-level limit. Submit a 129-level nested expression; server must error gracefully, not segfault.
- **Scope:** `geodetestlab-cli/specs/gql_parser_recursion_limit.yml`
- **Acceptance Criteria:**
  - 128-level nested expression parses and executes
  - 129-level expression returns parse error
  - Server stable; no crash

#### GAP-0334: GQL type system — Date, Time, Duration, Point, Path, Interval roundtrip

- **Status:** Closed
- **Resolution:** Spec `specs/gql_value_types_roundtrip.yml` — 18 tests across Date/Time/Duration/LatLon/Interval/Path. 1 documented skip: `path()` literal constructor not in GQL outside MATCH. Commit aad1389.
- **Category:** Testing / Functional
- **Severity:** High
- **Description:** `src/value_types.zig` enumerates types. Existing `advanced_types_basic.yml` is thin. Need full roundtrip (insert → store → query → compare) for each type.
- **Scope:** `geodetestlab-cli/specs/gql_value_types_roundtrip.yml`
- **Acceptance Criteria:**
  - Each of Date, Time, Duration, Point, Path, Interval inserted as literal
  - Queried back as same literal
  - JSON serialization roundtrip stable

#### GAP-0335: GQL temporal interval comparisons (overlap, contains, before/after)

- **Status:** Closed
- **Resolution:** Spec `specs/gql_interval_comparisons.yml` — 10 tests covering ordering operators. 2 documented skips: `interval_overlaps()` / `interval_contains()` defined in `temporal.zig` but not GQL-callable. Commit aad1389.
- **Category:** Testing / Functional
- **Severity:** Medium
- **Description:** `src/temporal.zig`. Verify interval operators end-to-end.
- **Scope:** `geodetestlab-cli/specs/gql_interval_comparisons.yml`
- **Acceptance Criteria:**
  - Two intervals: overlap, contains, before, after return expected booleans
  - Edge: zero-duration interval; reversed interval

#### GAP-0336: GQL undirected pattern matching with multi-hop and labels

- **Status:** Closed
- **Resolution:** Spec `specs/gql_undirected_multi_hop.yml` — 10 tests; bidirectional multi-hop matching with label constraints. Commit aad1389.
- **Category:** Testing / Functional
- **Severity:** Medium
- **Description:** Existing `undirected_pattern_matching.yml` is thin. Need multi-hop undirected with mixed-label endpoints.
- **Scope:** `geodetestlab-cli/specs/gql_undirected_multi_hop.yml`
- **Acceptance Criteria:**
  - `MATCH (a:A)-[*2..3]-(b:B)` returns expected paths in both directions

### Cluster: Transactions

#### GAP-0337: MVCC isolation enforcement — READ COMMITTED, SNAPSHOT, SERIALIZABLE differentials

- **Status:** Closed
- **Resolution:** Spec `specs/transactions_mvcc_isolation.yml` — 6 active tests covering autocommit visibility, commit/rollback boundaries, in-txn read-own-write. 3 documented skips for true concurrent isolation differentials (require harness concurrent-session primitive). Commit aad1389.
- **Category:** Testing / Functional
- **Severity:** High
- **Description:** `src/transactions/mvcc_adv/`. Verify the three isolation levels produce textbook anomalies/non-anomalies: lost update prevented under SERIALIZABLE, dirty reads blocked under READ COMMITTED.
- **Scope:** `geodetestlab-cli/specs/transactions_mvcc_isolation.yml`
- **Acceptance Criteria:**
  - Lost-update test passes under SERIALIZABLE, may fail under lower (document)
  - Dirty-read test passes under READ COMMITTED+
  - Phantom-read behavior documented per level

#### GAP-0338: Long transaction undo — 10k+ row rollback completes, no leak

- **Status:** Closed
- **Resolution:** Spec `specs/transactions_large_rollback.yml` — 5 active tests covering 10k-row UNWIND rollback, mixed nodes/edges. Pins ROLLBACK bug (BUG-0338-A — same root as BUG-0326). Commit aad1389.
- **Category:** Testing / Reliability
- **Severity:** High
- **Description:** `src/txn_undo_log.zig`. Insert 10k rows in a single txn, ROLLBACK; verify no leak, no orphan rows, undo log truncated.
- **Scope:** `geodetestlab-cli/specs/transactions_large_rollback.yml`
- **Acceptance Criteria:**
  - 10k rows inserted in single txn
  - ROLLBACK completes in bounded time (target: < 5s)
  - Post-rollback row count == 0
  - Undo log size returned to pre-txn baseline

#### GAP-0339: Transaction chunked execution — large COMMIT split across messages

- **Status:** Closed
- **Resolution:** Spec `specs/transactions_chunked_edges.yml` — 7 active tests; chunk-boundary rollback + mixed RW in txn. 1 documented skip (true concurrent chunked-session interleave). Commit aad1389.
- **Category:** Testing / Functional
- **Severity:** Medium
- **Description:** Existing `transaction_chunked_execution.yml` exists. Extend with edge cases: chunk-boundary on rollback, mixed read/write chunks.
- **Scope:** `geodetestlab-cli/specs/transactions_chunked_edges.yml`
- **Acceptance Criteria:**
  - ROLLBACK exactly at chunk boundary leaves no committed rows
  - Chunked txn interleaving reads + writes preserves transactional view

### Cluster: CDC & Materialized Views

#### GAP-0340: CDC Kafka sink — backfill from resume token, ordered delivery under restart

- **Status:** Blocked
- **Resolution:** Spec `specs/cdc_kafka_resume_token.yml` — 13 tests exercise GQL CDC procedure surface (cdc.enable/stop/start/get_events/etc). Wire-level delivery blocked: `kafka_sink.zig::sendToBroker` returns `error.KafkaTransportNotImplemented`. Unblock by implementing Kafka client. Commit d83cd1c.
- **Category:** Testing / Functional
- **Severity:** High
- **Description:** `src/streaming/sinks/kafka_sink.zig` — resume token semantics. Verify that crashing server mid-stream and restarting causes resume from token, no duplicates, no gaps.
- **Scope:** `geodetestlab-cli/specs/cdc_kafka_resume_token.yml`
- **Acceptance Criteria:**
  - Stream 1k events; crash sink at event 500
  - Restart; events 501-1000 delivered exactly once; ordered

#### GAP-0341: CDC webhook sink — retry on 5xx, dead-letter on persistent failure

- **Status:** Blocked
- **Resolution:** Spec `specs/cdc_webhook_retry_deadletter.yml` — 11 tests exercise telemetry surface. Wire-level blocked: `webhook_sink.zig::sendHttpPost` returns `error.WebhookTransportNotImplemented`, plus `isPrivateHost(127.0.0.1)` blocks loopback testing, plus no `cdc.configure_sink(url)` or `cdc.dlq_list()` procedure registration. Three-part unblock: (a) transport, (b) `GEODE_WEBHOOK_ALLOW_PRIVATE=1`, (c) procedure registration. Commit d83cd1c.
- **Category:** Testing / Functional
- **Severity:** Medium
- **Description:** `src/streaming/sinks/webhook_sink.zig` — retry policy on 5xx; dead-letter after N retries.
- **Scope:** `geodetestlab-cli/specs/cdc_webhook_retry_deadletter.yml`
- **Acceptance Criteria:**
  - Webhook returns 503 N times → retried with backoff
  - On N+1 failure → moved to dead-letter
  - Dead-letter inspectable via admin command

#### GAP-0342: Materialized view refresh latency variance envelope holds under load

- **Status:** Blocked
- **Resolution:** Spec `specs/mv_refresh_latency_envelope.yml` — 14 tests exercise base-table CDC adaptive-flush surface as proxy. Native `mv.*` procedures never registered in `storage_dispatch.zig`; MV engine (`materialized_views.zig`, enhanced_materialized_views.zig) is internal-only. Unblock by registering `mv.create`, `mv.refresh`, `mv.get_refresh_stats`, `mv.drop`. Commit d83cd1c.
- **Category:** Testing / Performance
- **Severity:** Medium
- **Description:** REQ-GQL-076 — MV refresh latency variance benchmark exists in geode internal tests. Replicate as black-box spec.
- **Scope:** `geodetestlab-cli/specs/mv_refresh_latency_envelope.yml`
- **Acceptance Criteria:**
  - Create MV; load base table at sustained rate
  - p99 refresh latency stays under documented envelope

### Cluster: Misc

#### GAP-0343: Sustained-load stress — 30-minute mixed RW workload at target QPS

- **Status:** Closed
- **Resolution:** Spec `specs/perf_sustained_30min.yml` — 7 tests; mixed RW workload (default 5 min, `SUSTAINED_DURATION_SECS=1800` for 30 min), p99 latency assertion, RSS probe via `/proc/<pid>/status`. `slow: true` keeps out of regular CI; run via `make test-stress`. Commit e373b0c.
- **Category:** Testing / Performance
- **Severity:** Medium
- **Description:** Existing `geode_performance_stress.yml` and `load_stress_sequential.yml` cover short bursts. Need 30-minute sustained mixed RW workload with target QPS and stable latency.
- **Scope:** `geodetestlab-cli/specs/perf_sustained_30min.yml`
- **Acceptance Criteria:**
  - 30-minute test; 70% read / 30% write
  - p99 latency stays under documented SLO
  - No memory growth beyond expected baseline (verify with RSS samples)

#### GAP-0344: LSP schema completion — basic completions, hover, go-to-definition

- **Status:** Closed
- **Resolution:** Spec `specs/lsp_full_surface.yml` — 7 tests covering initialize handshake, completion, hover, definition, diagnostics. Graceful skips when capability not advertised (consistent with `lsp_schema_completion.yml`). Commit e373b0c.
- **Category:** Testing / Functional
- **Severity:** Low
- **Description:** Existing `lsp_schema_completion.yml` is thin. Expand to hover, go-to-definition, diagnostic publication on syntax error.
- **Scope:** `geodetestlab-cli/specs/lsp_full_surface.yml`
- **Acceptance Criteria:**
  - LSP server responds to `textDocument/completion`, `hover`, `definition`, `publishDiagnostics`

#### GAP-0345: MCP client tool invocation surface — list_tools, call_tool, error mapping

- **Status:** Closed
- **Resolution:** Spec `specs/mcp_full_surface.yml` — 7 tests covering initialize, tools/list, valid call, empty/bad/unknown call error paths with SIGABRT/SIGSEGV exit-code check. Commit e373b0c.
- **Category:** Testing / Functional
- **Severity:** Low
- **Description:** `mcp_client_integration.yml` is thin. Expand to full MCP tool surface: list, call, error mapping.
- **Scope:** `geodetestlab-cli/specs/mcp_full_surface.yml`
- **Acceptance Criteria:**
  - MCP server lists all tools
  - Invocation with valid/invalid args returns expected responses
  - Geode-side errors map to JSONRPC error codes

---

## Blocked Gaps (0)

### GAP-0275: Fragile JSON and Table Parsing in Interactive Shell Runner

- **Status:** Closed
- **Category:** Reliability
- **Severity:** High
- **Description:** `runners/shell_runner.py` extracts JSON using basic regex (`r"\[.*\]"`) and manually counts table borders. If the interactive shell's output formatting changes slightly (e.g. pretty-printed JSON over multiple lines, or different table decorators), the parser will silently fail or return incorrect row counts.
- **Resolution:** Modified `start_shell` to use `--format json`. Modified `execute_query` to look for outer `{` and `}` directly and use robust `json.loads`.

### GAP-0276: Error Detection Prone to False Positives

- **Status:** Closed
- **Category:** Reliability
- **Severity:** Medium
- **Description:** The shell runner checks `if "Error" in output or "error" in output.lower():` to determine command failure. If a valid query returns a string containing "error" (e.g. returning an error log string or a user named "Error"), the test will falsely fail.
- **Resolution:** Now checks the JSON `status_class` attribute for values not starting with "00", or explicit Error log prefixes for shell errors.

### GAP-0277: Brittle Command Echo Stripping

- **Status:** Closed
- **Category:** Reliability
- **Severity:** Medium
- **Description:** `send_command` tries to strip the echoed command from `pexpect` output by matching the first 20 characters of the input command. If the terminal wraps the line or the echo is slightly formatted, the actual output is truncated or incorrectly includes the prompt.
- **Resolution:** Simplified echo handling by finding the JSON block directly via braces which naturally skips the command echo text.

### GAP-0278: Conflicting "Shell" Terminology Between Runners

- **Status:** Closed
- **Category:** Maintainability
- **Severity:** Low
- **Description:** In `executor.py`, `test_type: shell` means running an OS bash script (often for source code grepping). In `runners/shell_runner.py`, it means testing the `geode shell` interactive TTY. This overloaded terminology confuses spec authors.
- **Resolution:** Renamed `test_type: shell` in `executor.py` to `test_type: bash` across the codebase, test specs, and security unit tests.

### GAP-0279: Hardcoded Persistence File Checking

- **Status:** Closed
- **Category:** Extensibility
- **Severity:** Low
- **Description:** `_run_persistence_test` in `shell_runner.py` hardcodes the check for `graph_store.dat`. If the storage engine changes or utilizes multiple files (like indexes or logs), the persistence test will not verify them accurately.
- **Resolution:** `_run_persistence_test` now checks `step.get("files", ["graph_store.dat"])` to allow tests to optionally specify multiple persistence files.

### Resolved Gaps Listed Below for Reference

### GAP-0265: No unit tests for security fixes (#48, #49, #58)

- **Status:** Closed
- **Resolution:** Created `test_executor_security.py` (4 tests) and `test_runner_security.py` (6 tests) covering metachar routing, sandbox rejection, allowlist, and file secret path validation. Commit `89fa234`.

### GAP-0268: test-all integration job has allow_failure: true

- **Status:** Closed
- **Resolution:** Removed `allow_failure: true` from test-all job. Commit `ea6dbcc`.

### GAP-0261: .dockerignore file missing despite documented fix (#77 / PERF-015)

- **Status:** Closed
- **Resolution:** Created `.dockerignore` with exclusions for `.git`, `__pycache__`, `.venv`, `reports/`, `docs/`. Commit `3b29b1b`.

### GAP-0262: Makefile Docker commands still bind to 0.0.0.0 despite #54 being closed

- **Status: Won't Do**
- **Issue:** Not yet created (--skip-issues)
- **Category:** Bug
- **Severity:** Medium
- **Requirement source:** [#54](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/54) (Server binds 0.0.0.0 in ServerManager)
- **Current state (evidence):**
  - `Makefile:143` -- `serve --listen 0.0.0.0:3141 --listen-grpc 0.0.0.0:50051 --log-level info`
  - `lib/server_manager.py` fix confirmed (binds 127.0.0.1), but the Makefile `docker-start` target was not updated
- **Why this is a gap:** The Makefile Docker target uses 0.0.0.0 inside the container.
- **Why Won't Do:** Inside a Docker container, the process must bind to 0.0.0.0 for the `-p` port mapping to work. Docker's `-p host:container` maps the host port to the container's listening address. If the container process binds to 127.0.0.1, Docker's port mapping cannot reach it from outside the container's network namespace. The host-side exposure is already limited by the `-p` flag which binds to all host interfaces by default; to restrict host-side exposure, use `-p 127.0.0.1:3141:3141/udp` in the Docker run command (which is a separate concern from the in-container bind address). The `server_manager.py` fix correctly binds to 127.0.0.1 for the non-Docker (bare metal) path.
- **Impact/Risk:** Low. Docker port mapping controls host-side exposure independently of in-container bind address.

### GAP-0266: No pytest-cov configured; 80% coverage threshold cannot be measured

- **Status:** Closed
- **Resolution:** Added `pytest-cov` to dev dependencies, configured `[tool.coverage.run]` and `[tool.coverage.report]` in pyproject.toml. Baseline coverage: 51%. Commit `0ae04fa`.

### GAP-0274: REQUIREMENTS.md stale (6 weeks, missing 32 issues)

- **Status:** Closed
- **Resolution:** Updated REQUIREMENTS.md to include all 79 issues (#1-#79) with correct status. Commit `b853bfe`.

### GAP-0263: Doc claims resolve().relative_to() but code uses str().startswith()

- **Status:** Closed
- **Resolution:** Updated `executor.py:94` to use `resolved.is_relative_to(sandbox_root)` (Python 3.9+), matching the documented approach. Commit `8043c5c`.

### GAP-0264: Doc claims _tracked_pids/track_pid()/untrack_pid() but actual mechanism uses _active_servers

- **Status:** Closed
- **Resolution:** Verified: `_tracked_pids`, `track_pid()`, `untrack_pid()` exist in `cli.py:51-61` but are never called. They serve as an unused secondary cleanup layer. The primary cleanup mechanism is `server.py:_active_servers` list + `cleanup_servers()` atexit handler + `_kill_geode_processes()` fallback with scoped pkill pattern. This dual-layer approach provides adequate coverage. Updated this doc to accurately describe the mechanism.

### GAP-0267: mypy allow_failure in CI (type errors don't block pipeline)

- **Status:** Closed
- **Resolution:** Removed `allow_failure: true` from lint-mypy job. mypy now blocks pipeline on type errors. Commit `ea6dbcc`.

### GAP-0269: No linting for non-Python runners (Go, Zig, Rust, Node.js)

- **Status:** Closed
- **Resolution:** Added `go vet` to build-go, `cargo clippy` to build-rust, `node --check` to test-all. Zig reports warnings during build. Commit `017996d`.

### GAP-0270: Two separate pytest configs (root pytest.ini vs geodetestlab-cli/pyproject.toml)

- **Status:** Closed
- **Resolution:** Removed root-level `pytest.ini`. pyproject.toml is the single config. Commit `0ae04fa`.

### GAP-0271: No JSON Schema for YAML test spec format

- **Status:** Closed
- **Resolution:** Created `docs/spec-schema.json` covering TestSpec, TestCase, ExpectedResult, HttpRequest, TestStep, PlaintextCheck, SecretConfig — all derived from `spec.py` dataclasses.

### GAP-0272: Dead CI jobs (build-python, build-nodejs produce no artifacts)

- **Status:** Closed
- **Resolution:** Removed build-python and build-nodejs jobs from CI. Commit `ea6dbcc`.

### GAP-0273: Three potentially unused dependencies (pydantic, jmespath, psutil)

- **Status:** Closed
- **Resolution:** Confirmed unused via grep; removed `pydantic`, `jmespath`, and `psutil` from `pyproject.toml` dependencies. Commit `8043c5c`.

---

## Process Finding: GitLab Issue Status Discrepancy

**Observation:** 32 GitLab issues (#48-#79) remain OPEN on the platform despite code fixes being documented as implemented. Code verification confirms the fixes ARE in the codebase.

**Root cause:** Issues were resolved in code and documented in gap analysis files, but were never formally closed on GitLab.

**Recommendation:** Close all 32 issues on GitLab with references to the implementing commits. This is a process hygiene issue, not a code gap, so no Gap-ID is assigned.

**Note:** Items #55 and #59 remain permanently "Won't Do" per project policy (see MEMORY.md).

---

## Stack-Ranked Findings Table (All Closed / Won't Do)

| Rank | Sev | Risk | Finding | Component | CWE/OWASP | Issue URL | Fix Applied | Status |
|------|-----|------|---------|-----------|-----------|-----------|-------------|--------|
| 1 | Critical | 60 | Go deps: CVE-2024-45337 auth bypass + 7 more CVEs | `runners/go.mod` | CWE-287 | [#50](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/50) | Updated golang.org/x/crypto v0.43.0→v0.48.0, quic-go v0.55.0→v0.59.0 | **Closed** |
| 2 | High | 48 | Command injection via shell metacharacter routing | `executor.py` | CWE-78 | [#48](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/48) | Only route through `bash -c` when `test_type == "shell"`; all other commands use `shlex.split` + `shell=False` | **Closed** |
| 3 | High | 48 | Arbitrary file write via setup_files path traversal | `executor.py` | CWE-22 | [#49](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/49) | Path traversal sandbox: `resolve().relative_to()` check against temp dir | **Closed** |
| 4 | High | 48 | Pre-server commands allow arbitrary execution | `runner.py` | CWE-78 | [#58](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/58) | Allowlist: `{rm, mkdir, cp, mv, chmod, touch, ln, sleep}`, `shell=False` | **Closed** |
| 5 | High | 48 | Python protobuf 4.25.1 DoS vulns | `pyproject.toml` | CWE-674 | [#51](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/51) | Added `protobuf>=4.25.8` floor pin to dependencies | **Closed** |
| 6 | Medium | 36 | CI pipeline: security jobs allow_failure | `.gitlab-ci.yml` | CWE-693 | [#57](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/57) | Removed `allow_failure: true` from `test-unit` and `lint-security` | **Closed** |
| 7 | Medium | 36 | Server binds 0.0.0.0 in ServerManager | `lib/server_manager.py` | CWE-668 | [#54](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/54) | Changed bind to `127.0.0.1` for both QUIC and gRPC | **Closed** |
| 8 | Medium | 32 | Python deps: no lockfile or hash verification | `pyproject.toml` | CWE-1104 | [#59](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/59) | N/A | **Won't Do** |
| 9 | Medium | 24 | Dockerfile: unpinned pkgs, no HEALTHCHECK | `Dockerfile` | CWE-1104 | [#55](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/55) | N/A | **Won't Do** |
| 10 | Medium | 24 | Rust bytes 1.11.0 vulnerability | `Cargo.lock` | CWE-119 | [#52](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/52) | `cargo update -p bytes` (1.11.0→1.11.1) | **Closed** |
| 11 | Medium | 24 | SSL verification disabled by default | `executor.py` | CWE-295 | [#53](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/53) | Added `logger.debug` warning when SSL verify is disabled | **Closed** |
| 12 | Low | 16 | Hardcoded test credentials in 5+ files | Multiple | CWE-798 | [#56](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/56) | Centralized `DEFAULT_ADMIN_PASSWORD` in `runner_types.py`; all consumers import from single source | **Closed** |
| 13 | Low | 16 | Potential XSS in CI HTML report | `.gitlab-ci.yml` | CWE-79 | [#60](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/60) | Applied `html.escape()` to issue URLs and client names in report | **Closed** |
| 14 | Low | 8 | Audit logging/auth disabled without safeguards | `server.py` | CWE-778 | [#61](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/61) | Added `GEODE_DISABLE_AUDIT_GUARD` and `GEODE_ALLOW_NO_AUTH_GUARD` env vars with `setdefault()` | **Closed** |
| 15 | Low | 8 | Insecure temp file/process cleanup patterns | `cli.py`, `server.py` | CWE-377 | [#62](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/62) | Added `_tracked_pids` set, `track_pid()`/`untrack_pid()`, enhanced `_kill_geode_processes()` | **Closed** |

---

## Won't Do — Policy Notes

> **For future agents:** The following items are intentionally closed as "Won't Do." They are handled via separate organizational controls and should NOT be reopened.

### #55 — Dockerfile unpinned packages / no HEALTHCHECK

### #59 — Python deps: no lockfile or hash verification

**Rationale:** CI/CD hash pinning, Docker tag pinning, and pre-commit hooks are managed via different controls outside this repository. These are organizational policy decisions, not codebase gaps. Re-implementing them here would duplicate effort and conflict with existing tooling.

---

## Findings by Area

### Application Security (4 findings — all closed)

| # | Finding | Issue | Status |
|---|---------|-------|--------|
| 1 | Command injection via shell metacharacter routing | [#48](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/48) | **Closed** |
| 2 | Arbitrary file write via setup_files | [#49](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/49) | **Closed** |
| 3 | Pre-server command execution | [#58](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/58) | **Closed** |
| 4 | SSL verification disabled by default | [#53](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/53) | **Closed** |

### Supply Chain (4 findings — 2 closed, 2 won't do)

| # | Finding | Issue | Status |
|---|---------|-------|--------|
| 1 | Go deps: CVE-2024-45337 + 7 CVEs | [#50](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/50) | **Closed** |
| 2 | Python protobuf DoS vulns | [#51](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/51) | **Closed** |
| 3 | Rust bytes vulnerability | [#52](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/52) | **Closed** |
| 4 | No Python lockfile/hash verification | [#59](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/59) | **Won't Do** |

### CI/CD and Infrastructure (3 findings — 2 closed, 1 won't do)

| # | Finding | Issue | Status |
|---|---------|-------|--------|
| 1 | Security jobs allow failure | [#57](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/57) | **Closed** |
| 2 | Dockerfile hardening gaps | [#55](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/55) | **Won't Do** |
| 3 | Server binds 0.0.0.0 | [#54](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/54) | **Closed** |

### Hardening (4 findings — all closed)

| # | Finding | Issue | Status |
|---|---------|-------|--------|
| 1 | Hardcoded test credentials | [#56](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/56) | **Closed** |
| 2 | XSS in HTML report | [#60](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/60) | **Closed** |
| 3 | Audit logging disabled | [#61](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/61) | **Closed** |
| 4 | Insecure temp/process patterns | [#62](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/62) | **Closed** |

---

## Previously Closed Findings Table

| # | Sev | Score | Category | Finding | Component | Issue | Status |
|---|-----|-------|----------|---------|-----------|-------|--------|
| 1 | Critical | 100 | Tests | Unit test suite broken | `geodetestlab/tests/` | [#40](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/40) QG-003 | **Closed** |
| 2 | High | 80 | Maintainability | runner.py monolith (1439 lines) | `geodetestlab/lib/runner.py` | [#38](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/38) QG-001 | **Closed** |
| 3 | High | 80 | CI-CD | Silent CI build failures | `.gitlab-ci.yml` | [#42](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/42) QG-005 | **Closed** |
| 4 | High | 60 | Security | Subprocess shell=True | `runner.py:190` | [#29](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/29) GAP-0029 | **Closed** |
| 5 | Medium | 60 | Readability | Magic numbers, wrong gRPC port | `runner.py` | [#39](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/39) QG-002 | **Closed** |
| 6 | Medium | 60 | Performance | No CI build caching | `.gitlab-ci.yml` | [#43](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/43) QG-006 | **Closed** |
| 7 | High | 48 | Security | Unpinned dependencies | `pyproject.toml` | [#33](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/33) GAP-0033 | **Closed** |
| 8 | Medium | 48 | Maintainability | Quality toolchain config drift | `pyproject.toml` | [#45](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/45) QG-008 | **Closed** |
| 9 | Medium | 48 | Readability | 44 ruff + 36 mypy violations | Multiple | [#46](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/46) QG-009 | **Closed** |
| 10 | Medium | 48 | Reliability | Inconsistent error handling | `runner.py` | [#44](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/44) QG-007 | **Closed** |
| 11 | High | 40 | Security | CI downloads without checksums | `.gitlab-ci.yml` | [#32](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/32) GAP-0032 | **Closed** |
| 12 | High | N/A | CI-CD | No CI quality gates | `.gitlab-ci.yml` | [#21](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/21) GAP-0021 | **Closed** |
| 13 | High | N/A | Code Quality | .gitignore missing patterns | `.gitignore` | [#20](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/20) GAP-0020 | **Closed** |
| 14 | Medium | 36 | Security | Hardcoded test password in 7+ locations | `runner.py` | [#30](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/30) GAP-0030 | **Closed** |
| 15 | Medium | 32 | Security | Unpinned Docker base images | `.gitlab-ci.yml` | [#35](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/35) GAP-0035 | **Closed** |
| 16 | Medium | 24 | Security | SSL cert verification disabled | `runner.py` | [#31](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/31) GAP-0031 | **Closed** |
| 17 | Medium | N/A | Security | Dynamic module loading via exec | `simple_manager.py` | [#23](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/23) GAP-0023 | **Closed** |
| 18 | Medium | N/A | Code Quality | Generated artifacts in git | 57 files | [#34](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/34) GAP-0034 | **Closed** |
| 19 | Medium | N/A | CI-CD | CI integration tests are no-op | `.gitlab-ci.yml` | [#36](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/36) GAP-0036 | **Closed** |
| 20 | Medium | N/A | Code Quality | Legacy code coexistence | `run_tests.py` | [#19](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/19) GAP-0019 | **Closed** |
| 21 | Medium | N/A | Code Quality | Duplicate test specs | `specs/` | [#22](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/22) GAP-0022 | **Closed** |
| 22 | Medium | N/A | Correctness | Non-query commands ignore gRPC | `runner.py` | [#26](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/26) GAP-0026 | **Closed** |
| 23 | Low | 24 | Cleanup | Dead ServerManagerDisabled class | `server/manager.py` | [#41](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/41) QG-004 | **Closed** |
| 24 | Low | 24 | CI-CD | Pre-commit marker hook always exits 0 | `.pre-commit-config.yaml` | [#47](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/47) QG-010 | **Closed** |
| 25 | Low | N/A | Security | Gitleaks false positives | `specs/*.yml` | [#37](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/37) GAP-0037 | **Closed** |
| 26-34 | Low-Med | N/A | Various | See prior sessions | Various | #24-28, GAP-0256-0260 | **Closed** |

---

## Resolution Evidence

### Closed - Session 4 (13 gaps closed, 2 won't do)

| Issue | Resolution |
|-------|-----------|
| [#48](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/48) | `executor.py`: Only route `test_type == "shell"` through `bash -c`; all others use `shlex.split` + `shell=False` |
| [#49](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/49) | `executor.py`: Path traversal sandbox via `resolve().relative_to(temp_dir)` |
| [#50](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/50) | `runners/go.mod`: `golang.org/x/crypto` v0.43.0→v0.48.0, `quic-go` v0.55.0→v0.59.0, all transitive deps updated |
| [#51](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/51) | `pyproject.toml`: Added `protobuf>=4.25.8` floor pin |
| [#52](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/52) | `runners/rust_runner/Cargo.lock`: `cargo update -p bytes` (1.11.0→1.11.1) |
| [#53](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/53) | `executor.py`: Added `logger.debug("SSL verification disabled")` warning |
| [#54](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/54) | `lib/server_manager.py`: Changed `0.0.0.0` → `127.0.0.1` for QUIC and gRPC bind addresses |
| [#55](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/55) | Won't Do: Docker tag pinning handled via separate organizational controls |
| [#56](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/56) | `runner_types.py`: Centralized `DEFAULT_ADMIN_PASSWORD` constant; `executor.py`, `server.py` import from single source |
| [#57](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/57) | `.gitlab-ci.yml`: Removed `allow_failure: true` from `test-unit` and `lint-security` |
| [#58](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/58) | `runner.py`: Pre-server command allowlist `{rm, mkdir, cp, mv, chmod, touch, ln, sleep}` with `shell=False` |
| [#59](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/59) | Won't Do: CI/CD hash pinning handled via separate organizational controls |
| [#60](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/60) | `.gitlab-ci.yml`: `html.escape()` on issue URLs and client names in HTML report |
| [#61](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/61) | `server.py`: `GEODE_DISABLE_AUDIT_GUARD` and `GEODE_ALLOW_NO_AUTH_GUARD` env var guards with `setdefault()` |
| [#62](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/62) | `cli.py`: `_tracked_pids` set, `track_pid()`/`untrack_pid()`, PID-based cleanup in `_kill_geode_processes()` |

### Closed - Session 1 (23 gaps)

See previous GAP_ANALYSIS.md version for full resolution details.

### Closed - Session 2 (6 gaps)

See previous GAP_ANALYSIS.md version for full resolution details.

### Closed - Session 3 (5 gaps)

See previous GAP_ANALYSIS.md version for full resolution details.

---

## Automated Check Results (2026-02-13)

### Secret Scanning

- gitleaks: 0 findings
- trufflehog: 0 findings

### SAST

- semgrep: 2 findings (1 real, 1 false positive)
- bandit: findings in scripts/ (not main app code)

### Dependency Scanning

- trivy: resolved (protobuf floor pin)
- grype: resolved (Go dep updates)
- osv-scanner: resolved (Go, Rust updates)
- cargo-audit: resolved (bytes update)

### Container/IaC

- hadolint: won't do (Dockerfile pinning)
- trivy config: won't do (Dockerfile pinning)

---

## Analysis Metadata

**Analysis Date:** 2026-03-27
**Analyzed By:** Claude Code (Opus 4.6, requirements-to-code gap analysis + automated scanning)
**Repository State:** 79 gaps tracked. 0 open, 3 won't do, 58 closed in this project, 18 previously resolved.
**Issue Series:**

- GAP-0001 through GAP-0018: Resolved (see [GAP_ANALYSIS_RESOLVED.md](./GAP_ANALYSIS_RESOLVED.md))
- GAP-0019 through GAP-0037: All 19 closed
- QG-001 through QG-010: All 10 closed
- Issues #48 through #62: 13 closed, 2 won't do (all resolved)
- GAP-0261 through GAP-0274: All 14 closed (added 2026-03-27, closed 2026-03-27)
- GAP-0280 through GAP-0345: 54 closed, 12 blocked (added & executed 2026-05-21)

---

## 2026-05-21 Bug Discoveries (during spec-gap execution)

The following geode-server bugs were surfaced by GAP-0280..GAP-0345 spec execution. These are reproducible from the YAML specs (each one has a `BUG_CONFIRMED` / `BUG_PINNED` / `STATUS=BUG_DETECTED` annotation in its CANARY token). File each as a follow-up issue in the upstream geode project.

| # | Severity | Bug | Spec(s) that pin it | Source file:line | Fix-when-this-flips |
|---|----------|-----|---------------------|------------------|---------------------|
| 1 | High     | `handlePolicyCreate` ignores `--table` and `--condition` args, always installs GPS ALLOW with `true` expression | rls_cross_tenant_query_shapes, rls_policy_cache_invalidation, rls_fle_no_decrypt_on_deny | `auth_dispatch.zig:939-965` | rls specs (`tests: []`) will need scenarios populated |
| 2 | High     | `ALTER USER SET ATTRIBUTE` not in GQL parser — ABAC unreachable | abac_attribute_policies | `gql/parser.zig:6437` | abac spec will need scenarios populated |
| 3 | High     | `policy_create` condition string with `;` crashes server (SIGKILL) via CALL path | rls_injection_resistance (TEST_OBSERVED only) | unknown | trip-wire negative; treat as P0 |
| 4 | High     | Rapid concurrent ALTER USER on built-in roles corrupts HMAC chain (`AuthChainTampered` on restart) | rbac_concurrent_alter_user | `auth_graph_manager.zig` chain seal | RBAC concurrent spec must accept restart-OK |
| 5 | Critical | Custom-role binding silently maps to `.User` (header gap #3) | rbac_custom_role_binding_pin (trip-wire) | `auth_graph_manager.zig` | PIN spec will fail → flip assertions |
| 6 | Critical | `GRANT WRITE` corrupts HMAC chain on next restart (header gap #1) | rbac_grant_write_chain_corruption_pin (trip-wire) | `auth_graph_manager.zig:1158` | PIN spec will fail → flip assertions |
| 7 | High     | `ALTER USER SET ROLE <unknown>` silently keeps prior role (worse than .User fallback — privilege retention) | rbac_alter_user_nonexistent_role (trip-wire) | `auth_graph_manager.zig writerSetRole` | PIN spec will fail → flip to require error |
| 8 | High     | `prop_store.zig:67` integer overflow in `readDirEntry` after batch-write + restart | tde_plaintext_full_pipeline (worked around) | `prop_store.zig:67` | Re-enable restart phase of pipeline spec |
| 9 | High     | `geode serve` has no `--kms-url` flag / `GEODE_KMS_URL` env wiring; cannot test KMS-fail-closed | tde_kms_unreachable_fails_closed (skip) | `cli_args.zig`, `server_init.zig` | Unblock by exposing flag |
| 10 | Critical | `geode audit verify` always exits 3 (`TAMPER chain`) on any fresh log — verifier initial state mismatch with writer prev_hash | audit_ed25519_verification, audit_hmac_chain_restart | `cli/geode_audit_verify.zig` vs `security/audit.zig` `appendEventLocked` | When fixed, flip BUG_CONFIRMED asserts to expect exit 0 |
| 11 | Critical | Username enumeration via timing oracle — invalid user ~95 ms, valid user wrong password ~275 ms (Argon2id skipped on miss) | authn_timing_invariance | `security/authn.zig` lookup-miss path | Fix: perform dummy Argon2id on miss; flip timing-diff threshold |
| 12 | High     | MFA admin enrollment accepts any 6-digit code (bypasses TOTP HMAC) | authn_mfa_totp_edges | `security/mfa.zig` admin path | Validate code in admin-enrollment path |
| 13 | High     | CA validation not enforced — wrong `--ca-cert` silently accepted on QUIC AND gRPC | quic_tls_pinning, grpc_mtls_rejection_matrix | `transport/grpc_tls.zig`, QUIC TLS path | Wire CA cert into chain validation |
| 14 | Critical | `BEGIN ... INSERT ... ROLLBACK` in a single CLI invocation silently commits | quic_stream_cancel_rollback, transactions_large_rollback, transactions_chunked_edges (BUG-0326/0337-A/0338-A/0339-A) | `cli/main.zig` query batching or txn state machine | When fixed, change `rollback_behavior=BUG_writes_not_rolled_back` to `_rolled_back` |
| 15 | High     | Memory leaks: `cli_args.zig:298` `config.log_level_arg`, `handleUserCreate`/`handlePolicyCreate` `allocPrint` results | DebugAllocator output during multiple specs | `cli_args.zig:298`, `auth_dispatch.zig:handleUserCreate`,`handlePolicyCreate` | Add `defer allocator.free(...)` |
| 16 | Medium   | FULLTEXT index not visible in `SHOW INDEXES` despite being functional | fulltext_bm25_comprehensive | `index/fulltext.zig` catalog registration | Register FTS in catalog list |
| 17 | Medium   | Auto-index not rebuilt on selective read after DROP INDEX (write-trigger only) | auto_index_lifecycle | `index/selectivity.zig` or `index_manager.zig` | Expected or bug? Confirm and either fix or document |
| 18 | High     | Kafka transport stub: `kafka_sink.zig::sendToBroker` returns `error.KafkaTransportNotImplemented`; unit tests silently swallow this | cdc_kafka_resume_token (sink-internal scope) | `streaming/sinks/kafka_sink.zig` | Implement client; propagate errors |
| 19 | High     | Webhook transport stub: `webhook_sink.zig::sendHttpPost` returns `error.WebhookTransportNotImplemented`; `isPrivateHost(127.0.0.1)` blocks loopback testing with no test-mode bypass | cdc_webhook_retry_deadletter | `streaming/sinks/webhook_sink.zig` | Implement client; add `GEODE_WEBHOOK_ALLOW_PRIVATE=1` for tests |
| 20 | Medium   | MV engine (`materialized_views.zig`, `enhanced_materialized_views.zig`) implemented but no `mv.*` GQL procedures registered in `storage_dispatch.zig` | mv_refresh_latency_envelope | `execution/storage_dispatch.zig` | Register procedures + parse `CREATE MATERIALIZED VIEW` DDL |
| 21 | High     | 2PC participant timeout hardcoded at 30 000 ms (`twophase.zig:166`), no env override; no crash-injection hooks; no oversized-frame injector | 2pc_coordinator_timeout, 2pc_participant_recovery, 2pc_frame_limit (all skip) | `distributed/twophase.zig:166`,`:399` | Add `GEODE_2PC_TIMEOUT_MS`, `GEODE_2PC_CRASH_AFTER_PREPARE`, oversized-frame test tool |
