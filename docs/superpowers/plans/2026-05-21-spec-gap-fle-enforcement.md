# Spec Gap Closure — FLE Enforcement Sub-Plan

> **For agentic workers:** Use `superpowers:subagent-driven-development` or `superpowers:executing-plans`.

**Goal:** Close GAP-0299..GAP-0304 by producing 6 spec files that prove FLE enforcement across all persistence paths, schema evolution, denial-aware placeholder, blind index, key determinism, and rotation atomicity.

**Source references:**

- `../geode/src/fle_integration.zig`
- `../geode/src/execution/fle_hooks.zig` — execution-time encrypt/decrypt
- `../geode/src/schema/fle_catalog.zig`
- `../geode/src/index/blind_index.zig`
- `../geode/src/security/test_fle_enforcement.zig`
- Existing: `fle_comprehensive_security.yml`, `fle_plaintext_verification_*.yml`, `fle_rotation.yml`, `fle_large_data_stress_verification.yml`

---

## File Structure

```text
geodetestlab-cli/specs/
├── fle_plaintext_full_pipeline.yml             # GAP-0299
├── fle_schema_alter_consistency.yml            # GAP-0300
├── fle_decrypt_denied_placeholder.yml          # GAP-0301
├── fle_blind_index_search.yml                  # GAP-0302
├── fle_key_derivation_restart.yml              # GAP-0303
└── fle_key_rotation_atomic.yml                 # GAP-0304
```

---

## Task 1: GAP-0299 — Full pipeline plaintext absence

**Files:**

- Create: `geodetestlab-cli/specs/fle_plaintext_full_pipeline.yml`

**Acceptance scenarios:**

- FLE-encrypted property on `:Doc` (node) AND `:RELATES` (edge)
- One row with FLE-encrypted indexed property
- Verify: `grep -r '<plaintext>' <data_dir>` returns 0 hits after insert, after checkpoint, after backup, after restart
- Verify: authorized query decrypts to original plaintext

Use `fle_plaintext_verification_basic.yml` as base; extend with edge properties and indexed fields.

- [ ] **Step 1:** Write spec, [ ] **Step 2:** Validate, [ ] **Step 3:** Commit `test(fle): close GAP-0299 — full pipeline plaintext absence`, [ ] **Step 4:** Update GAP_ANALYSIS.md.

---

## Task 2: GAP-0300 — Schema ALTER FIELD consistency

**Files:**

- Create: `geodetestlab-cli/specs/fle_schema_alter_consistency.yml`

**Acceptance:** Seed plaintext rows; ALTER FIELD to add FLE encryption. Expected outcomes (assert whichever the implementation chose; document the path):

- (Preferred) All existing rows re-encrypted; subsequent reads decrypt them.
- (Fallback) ALTER rejected with `MIXED_STATE_NOT_ALLOWED`; rows remain plaintext.
- (Bug-pin) ALTER succeeds, plaintext rows remain — this is a security gap. Tag `known_limitation` and file follow-up.

- [ ] **Step 1:** Write spec, [ ] **Step 2:** Validate, [ ] **Step 3:** Commit, [ ] **Step 4:** Update GAP_ANALYSIS.md.

---

## Task 3: GAP-0301 — Denied placeholder

**Files:**

- Create: `geodetestlab-cli/specs/fle_decrypt_denied_placeholder.yml`

**Acceptance:**

- User `fle_reader` lacks `decrypt_field` GPS action (via GPS policy or attribute restriction).
- Query returning the FLE field returns placeholder (`<ENCRYPTED>`, null, or `""`) — but NOT raw ciphertext base64 and NOT the plaintext.
- Row count matches admin's row count (row visible, field redacted).
- Audit log: `decrypt_field` denied event for `fle_reader`; `decrypt_field` allow for admin.

- [ ] **Step 1:** Write spec, [ ] **Step 2:** Validate, [ ] **Step 3:** Commit, [ ] **Step 4:** Update GAP_ANALYSIS.md.

---

## Task 4: GAP-0302 — Blind index search

**Files:**

- Create: `geodetestlab-cli/specs/fle_blind_index_search.yml`

**Acceptance:**

- Schema: `:Person { email FLE BLIND }`
- Insert 100 persons, distinct emails
- `MATCH WHERE n.email = 'alice@example.com'` returns the one matching row
- EXPLAIN output does NOT contain `alice@example.com`
- `grep -r 'alice@example.com' <data_dir>` returns 0 hits (FLE + blind index masks plaintext on disk)
- Logs (`reports/server.log` if available) do not contain the email

- [ ] **Step 1:** Write spec, [ ] **Step 2:** Validate, [ ] **Step 3:** Commit, [ ] **Step 4:** Update GAP_ANALYSIS.md.

---

## Task 5: GAP-0303 — Key derivation determinism

**Files:**

- Create: `geodetestlab-cli/specs/fle_key_derivation_restart.yml`

**Acceptance:**

- Seed encrypted rows
- Restart server (fresh process, same data dir)
- Same authorized query returns identical plaintext (per-field key re-derived correctly from catalog)

- [ ] **Step 1:** Write spec, [ ] **Step 2:** Validate, [ ] **Step 3:** Commit, [ ] **Step 4:** Update GAP_ANALYSIS.md.

---

## Task 6: GAP-0304 — Atomic key rotation with rollback

**Files:**

- Create: `geodetestlab-cli/specs/fle_key_rotation_atomic.yml`

**Acceptance:**

- Seed N rows under key v1
- Begin FLE per-field rotation to v2
- Inject failure mid-rotation (kill server, or simulated KMS error)
- After restart, either: all rows under v2 (rotation committed) OR all rows under v1 (rolled back). NOT a mix.
- Audit log shows rollback or completion event.

- [ ] **Step 1:** Write spec, [ ] **Step 2:** Validate, [ ] **Step 3:** Commit, [ ] **Step 4:** Update GAP_ANALYSIS.md.

---

## Final Steps

- [ ] `python -m geodetestlab run --specs specs --filter fle -v` all green.
- [ ] Commit `docs(gap): close GAP-0299..GAP-0304 — FLE enforcement`.
