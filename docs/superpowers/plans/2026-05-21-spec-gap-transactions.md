# Spec Gap Closure — Transactions Sub-Plan

> **For agentic workers:** Use `superpowers:subagent-driven-development` or `superpowers:executing-plans`.

**Goal:** Close GAP-0337..GAP-0339.

**Source references:**

- `../geode/src/transactions/mvcc_adv/`
- `../geode/src/transactions/transaction_manager.zig`
- `../geode/src/txn_undo_log.zig`
- Existing: `transaction_chunked_execution.yml`, `transaction_state_basic.yml`, `transaction_large_commit.yml`, `gql_transaction_management_comprehensive.yml`

## File Structure

```text
geodetestlab-cli/specs/
├── transactions_mvcc_isolation.yml     # GAP-0337
├── transactions_large_rollback.yml     # GAP-0338
└── transactions_chunked_edges.yml      # GAP-0339
```

## Task 1: GAP-0337 — MVCC isolation differentials

**Acceptance:** Three sessions, three isolation levels:

- READ COMMITTED: dirty read blocked, non-repeatable read possible (document)
- SNAPSHOT: dirty read + non-repeatable read blocked, write skew possible
- SERIALIZABLE: lost-update prevented (expect retry / serialization error)

If geode does not yet support multiple isolation levels, document current default and skip differentials.

- [ ] **Step 1:** Write, [ ] **Step 2:** Validate, [ ] **Step 3:** Commit, [ ] **Step 4:** Update GAP_ANALYSIS.md.

## Task 2: GAP-0338 — Large rollback

**Acceptance:** Insert 10k rows in single txn; ROLLBACK; verify row count == 0, undo log size returns to baseline, rollback completes within bounded time (target: < 5s on test hardware).

- [ ] **Step 1:** Write, [ ] **Step 2:** Validate, [ ] **Step 3:** Commit, [ ] **Step 4:** Update GAP_ANALYSIS.md.

## Task 3: GAP-0339 — Chunked execution edges

**Acceptance:** Chunked txn with ROLLBACK at chunk boundary leaves 0 committed rows. Mixed reads + writes preserve transactional view.

- [ ] **Step 1:** Write, [ ] **Step 2:** Validate, [ ] **Step 3:** Commit, [ ] **Step 4:** Update GAP_ANALYSIS.md.

---

- [ ] `python -m geodetestlab run --specs specs --filter transaction -v` all green.
- [ ] Commit `docs(gap): close GAP-0337..GAP-0339 — Transactions`.
