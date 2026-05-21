# Spec Gap Closure — Audit Forensics Sub-Plan

> **For agentic workers:** Use `superpowers:subagent-driven-development` or `superpowers:executing-plans`.

**Goal:** Close GAP-0305..GAP-0309 by producing 5 spec files that verify audit forensic-grade integrity: Ed25519 signing, JSONL atomicity, sink failure recovery, HMAC chain across restart, configuration-change events.

**Source references:**

- `../geode/src/security/audit.zig` (esp. :51 Ed25519, :62-85 export, :88-97 event types)
- `../geode/src/security/audit_formatter.zig`
- `../geode/src/security/audit_sink.zig`
- Existing: `geode_audit_compliance_v2.yml`, `geode_audit_logging_enterprise.yml`, `geode_audit_security_advanced.yml`, `gps_audit_actor_key.yml`, `gps_persistence_policy_audit.yml`

---

## File Structure

```text
geodetestlab-cli/specs/
├── audit_ed25519_verification.yml         # GAP-0305
├── audit_jsonl_atomic_writes.yml          # GAP-0306
├── audit_sink_failure_recovery.yml        # GAP-0307
├── audit_hmac_chain_restart.yml           # GAP-0308
└── audit_config_change_events.yml         # GAP-0309
```

---

## Task 1: GAP-0305 — Ed25519 forensic export verification

**Files:**

- Create: `geodetestlab-cli/specs/audit_ed25519_verification.yml`

**Acceptance:**

- Generate audit events (CREATE USER, GRANT, etc.)
- `geode audit export --output /tmp/audit.pack --sign` produces pack + signature
- External verify (via `geode audit verify` if available, or `openssl pkeyutl -verify`) succeeds
- Flip 1 byte in the pack → verify fails
- Documented audit pubkey matches

- [ ] **Step 1:** Write spec, [ ] **Step 2:** Validate, [ ] **Step 3:** Commit `test(audit): close GAP-0305 — Ed25519 forensic export`, [ ] **Step 4:** Update GAP_ANALYSIS.md.

---

## Task 2: GAP-0306 — JSONL atomic writes

**Files:**

- Create: `geodetestlab-cli/specs/audit_jsonl_atomic_writes.yml`

**Acceptance:**

- 100 parallel CREATE/DROP USER (via background `&` and `wait` in bash step)
- Stop server cleanly (flush)
- `jq -c '.' /tmp/audit.jsonl | wc -l` matches the expected event count
- No `jq` parse errors (every line is valid JSON)

- [ ] **Step 1:** Write spec, [ ] **Step 2:** Validate, [ ] **Step 3:** Commit, [ ] **Step 4:** Update GAP_ANALYSIS.md.

---

## Task 3: GAP-0307 — Sink failure recovery

**Files:**

- Create: `geodetestlab-cli/specs/audit_sink_failure_recovery.yml`

**Acceptance:**

- Configure audit path to `/tmp/audit-test.jsonl`
- Mid-test, `chmod 000 /tmp/audit-test.jsonl`
- Subsequent CREATE USER returns success; server still running
- stderr or server log captures alarm
- Restore `chmod 644`; subsequent operations append to file successfully

- [ ] **Step 1:** Write spec, [ ] **Step 2:** Validate, [ ] **Step 3:** Commit, [ ] **Step 4:** Update GAP_ANALYSIS.md.

---

## Task 4: GAP-0308 — HMAC chain across restart + tamper detection

**Files:**

- Create: `geodetestlab-cli/specs/audit_hmac_chain_restart.yml`

**Acceptance:**

- Seed N audit records; record final seq
- Restart server
- Subsequent record's seq == N+1 (chain continues)
- Delete middle record from JSONL; run `geode audit verify` → fails with chain-break message
- Audit log records chain-break event (in a different sink or via stderr)

- [ ] **Step 1:** Write spec, [ ] **Step 2:** Validate, [ ] **Step 3:** Commit, [ ] **Step 4:** Update GAP_ANALYSIS.md.

---

## Task 5: GAP-0309 — Configuration-change events with old/new values

**Files:**

- Create: `geodetestlab-cli/specs/audit_config_change_events.yml`

**Acceptance:**

- ALTER a server-side setting (session timeout, audit verbosity, similar)
- Audit JSONL contains `configuration_change` event with `setting`, `old_value`, `new_value`
- Multiple changes produce multiple events

- [ ] **Step 1:** Write spec, [ ] **Step 2:** Validate, [ ] **Step 3:** Commit, [ ] **Step 4:** Update GAP_ANALYSIS.md.

---

## Final Steps

- [ ] `python -m geodetestlab run --specs specs --filter audit -v` all green.
- [ ] Commit `docs(gap): close GAP-0305..GAP-0309 — Audit forensics`.
