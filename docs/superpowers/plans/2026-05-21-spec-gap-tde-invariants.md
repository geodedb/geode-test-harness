# Spec Gap Closure — TDE Invariants Sub-Plan

> **For agentic workers:** Use `superpowers:subagent-driven-development` or `superpowers:executing-plans`.

**Goal:** Close GAP-0293..GAP-0298 by producing 6 spec files that pin the core TDE invariants: plaintext-on-disk forbidden across the whole pipeline, nonce uniqueness, key rotation atomicity, KMS fail-closed, envelope unwrap auth tag, bit-flip detection.

**Architecture:** Template: `geodetestlab-cli/specs/tde_plaintext_verification_*.yml`. Each new spec exercises one TDE invariant end-to-end via the CLI, then uses `bash` steps with `grep -r`, file inspection, and hex-dump tools to verify on-disk state.

**Source references:**

- `../geode/src/security/tde.zig:54,78-103,93-97` — AES-256-GCM, nonce, auth tag
- `../geode/src/security/key_rotation.zig` — rotation lifecycle
- `../geode/src/security/external_kms_client.zig`, `kms_remote.zig`, `vault_kms_provider.zig`
- `../geode/src/security/backup_key_envelope.zig`
- `../geode/src/storage/tde_file_encryption.zig`
- Existing specs: `tde_plaintext_verification_wal.yml`, `tde_plaintext_verification_key_rotation.yml`, `tde_plaintext_verification_backup.yml`, `tde_plaintext_verification_combined.yml`

---

## File Structure

```text
geodetestlab-cli/specs/
├── tde_plaintext_full_pipeline.yml          # GAP-0293
├── tde_nonce_uniqueness.yml                  # GAP-0294
├── tde_key_rotation_crash_safety.yml         # GAP-0295
├── tde_kms_unreachable_fails_closed.yml      # GAP-0296
├── tde_backup_envelope_wrong_kek.yml         # GAP-0297
└── tde_bitflip_detection.yml                 # GAP-0298
```

---

## Task 1: GAP-0293 — Plaintext-on-disk full pipeline

**Files:**

- Create: `geodetestlab-cli/specs/tde_plaintext_full_pipeline.yml`

Single-secret walkthrough proving no plaintext anywhere.

- [ ] **Step 1: Write spec**

```yaml
version: '1.0'
name: TDE — plaintext never on disk across WAL → checkpoint → snapshot → backup → restart
description: |
  End-to-end pipeline verification. One secret string is written, the
  database is forced through every persistence transition, and grep
  asserts the plaintext is absent from every on-disk artifact at every
  stage.
  CANARY: REQ=REQ-TDE-PIPELINE-001; FEATURE="TDE full-pipeline plaintext absence"; ASPECT=DiskGrepInvariant; STATUS=TESTED; OWNER=security; UPDATED=2026-05-21
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
      GEODE_TDE_ENABLED: '1'
  client:
    timeout_ms: 30000
    format: json
secrets:
  admin_password: { source: env, key: GEODE_ADMIN_PASSWORD, required: false, default: GeodeTestPassword123! }
invariants:
- type: server_running
tests:
- name: tde-pipeline-seed
  description: Insert secret string TDE_PIPELINE_SECRET_VALUE_42.
  args: [query, -U, geode, -P, '${secret:admin_password}', '-']
  stdin: |
    CREATE (n:TdePipeNode {marker: 'TDE_PIPELINE_SECRET_VALUE_42'}) RETURN n
  expect: { exit_code: 0, stdout_contains: [TdePipeNode] }
  tags: [tde, setup]

- name: tde-pipeline-grep-after-insert
  description: After insert, no plaintext on disk.
  type: bash
  command: |
    ! grep -r 'TDE_PIPELINE_SECRET_VALUE_42' "${GEODE_DATA_DIR}" 2>/dev/null
  expect: { exit_code: 0 }
  tags: [tde, invariant, grep]

- name: tde-pipeline-force-checkpoint
  args: [admin, checkpoint]
  expect: { exit_code: 0 }
  tags: [tde, checkpoint]

- name: tde-pipeline-grep-after-checkpoint
  type: bash
  command: |
    ! grep -r 'TDE_PIPELINE_SECRET_VALUE_42' "${GEODE_DATA_DIR}" 2>/dev/null
  expect: { exit_code: 0 }
  tags: [tde, invariant, grep]

- name: tde-pipeline-backup
  args: [backup, create, --output, /tmp/tde-pipe-backup.tar]
  expect: { exit_code: 0 }
  tags: [tde, backup]

- name: tde-pipeline-grep-after-backup
  type: bash
  command: |
    ! grep -a 'TDE_PIPELINE_SECRET_VALUE_42' /tmp/tde-pipe-backup.tar
  expect: { exit_code: 0 }
  tags: [tde, invariant, grep]

- name: tde-pipeline-restart-checkpoint
  type: bash
  command: echo 'restart now'
  restart_server: true
  expect: { exit_code: 0 }
  tags: [tde, restart]

- name: tde-pipeline-grep-after-restart
  type: bash
  command: |
    ! grep -r 'TDE_PIPELINE_SECRET_VALUE_42' "${GEODE_DATA_DIR}" 2>/dev/null
  expect: { exit_code: 0 }
  tags: [tde, invariant, grep]

- name: tde-pipeline-decrypted-roundtrip
  description: Authorized read recovers plaintext.
  args: [query, -U, geode, -P, '${secret:admin_password}', '-']
  stdin: "MATCH (n:TdePipeNode) RETURN n.marker AS marker"
  expect:
    exit_code: 0
    stdout_contains: ['TDE_PIPELINE_SECRET_VALUE_42']
  tags: [tde, roundtrip, positive]

- name: tde-pipeline-cleanup
  args: [query, -U, geode, -P, '${secret:admin_password}', '-']
  stdin: |
    MATCH (n:TdePipeNode) DETACH DELETE n;
  expect: { exit_code: 0 }
  tags: [tde, teardown]

tags: [tde, plaintext_verification, pipeline, security, comprehensive]
```

- [ ] **Step 2:** Validate, [ ] **Step 3:** Commit `test(tde): close GAP-0293 — full-pipeline plaintext absence`, [ ] **Step 4:** Update GAP_ANALYSIS.md.

---

## Task 2: GAP-0294 — Nonce uniqueness

**Files:**

- Create: `geodetestlab-cli/specs/tde_nonce_uniqueness.yml`

**Acceptance:** Generate 100k encrypted writes; extract IVs from on-disk ciphertext (via `xxd` or `geode admin tde-inspect` if available); assert all distinct.

Tactic: If no admin inspect tool exists, generate 1k writes (still statistically meaningful for collision detection at 96-bit IV) and use `strings` + a small Python helper in a `bash` step to count distinct IV positions. Document the bound; tag `nonce_uniqueness`.

- [ ] **Step 1:** Write spec, [ ] **Step 2:** Validate, [ ] **Step 3:** Commit, [ ] **Step 4:** Update GAP_ANALYSIS.md.

---

## Task 3: GAP-0295 — Key rotation crash safety

**Files:**

- Create: `geodetestlab-cli/specs/tde_key_rotation_crash_safety.yml`

**Acceptance:** Seed rows; trigger key rotation; kill -9 server (via the harness's `kill_server: true` mechanism or a `bash` step that runs `pkill -9 -f 'geode serve'`); restart; verify all rows readable.

Reference existing `fle_rotation.yml` for rotation invocation pattern and adapt to TDE master key rotation.

- [ ] **Step 1:** Write spec, [ ] **Step 2:** Validate, [ ] **Step 3:** Commit, [ ] **Step 4:** Update GAP_ANALYSIS.md.

---

## Task 4: GAP-0296 — KMS unreachable fails closed

**Files:**

- Create: `geodetestlab-cli/specs/tde_kms_unreachable_fails_closed.yml`

**Acceptance:** Server starts with `GEODE_KMS_URL=https://127.0.0.1:1` (unreachable). Spec invokes `geode serve` directly via `bash` (since the harness's auto-server-start expects success) and asserts:

- Non-zero exit code
- stderr contains `KMS_UNREACHABLE` or similar
- Data directory not initialized with plaintext (no `graph_store.dat` containing test data, or the file is empty)

- [ ] **Step 1:** Write spec, [ ] **Step 2:** Validate, [ ] **Step 3:** Commit, [ ] **Step 4:** Update GAP_ANALYSIS.md.

---

## Task 5: GAP-0297 — Backup envelope wrong KEK

**Files:**

- Create: `geodetestlab-cli/specs/tde_backup_envelope_wrong_kek.yml`

**Acceptance:** Create backup with KEK A; attempt restore with KEK B; assert restore fails with auth tag error; data directory after failed restore is unchanged.

- [ ] **Step 1:** Write spec, [ ] **Step 2:** Validate, [ ] **Step 3:** Commit, [ ] **Step 4:** Update GAP_ANALYSIS.md.

---

## Task 6: GAP-0298 — Bit-flip detection

**Files:**

- Create: `geodetestlab-cli/specs/tde_bitflip_detection.yml`

**Acceptance:** Seed a row; identify the corresponding page on disk (via `geode admin storage-inspect` if available, otherwise via the page that grew when the row was inserted); flip one bit with `dd if=... bs=1 count=1 seek=N`; restart; read row → query fails with `DECRYPT_AUTH_FAILED`.

- [ ] **Step 1:** Write spec, [ ] **Step 2:** Validate, [ ] **Step 3:** Commit, [ ] **Step 4:** Update GAP_ANALYSIS.md.

---

## Final Steps

- [ ] `python -m geodetestlab run --specs specs --filter tde -v` all green.
- [ ] Commit `docs(gap): close GAP-0293..GAP-0298 — TDE invariants`.
