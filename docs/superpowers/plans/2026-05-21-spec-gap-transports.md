# Spec Gap Closure — Transports (QUIC/gRPC) Sub-Plan

> **For agentic workers:** Use `superpowers:subagent-driven-development` or `superpowers:executing-plans`.

**Goal:** Close GAP-0323..GAP-0327 by producing 5 spec files covering transport hardening: QUIC PollSync stress, TLS pinning, gRPC mTLS parity, stream cancellation rollback, pool exhaustion.

**Source references:**

- `../geode/src/transport/quic.zig:30-79` (vendored QUIC, PollSync)
- `../geode/src/transport/grpc_server.zig`
- `../geode/src/transport/grpc_tls.zig`
- `../geode/src/transport/connection_manager.zig`
- `../geode/src/transport/stream_scheduler.zig`
- `../geode/src/server/active_stream_registry.zig`
- Existing: `geode_quic_transport.yml`, `quic_mutations_january_2026.yml`, `gap_0257_iso_conformance_verification.yml`

---

## File Structure

```text
geodetestlab-cli/specs/
├── quic_pollsync_stress.yml              # GAP-0323
├── quic_tls_pinning.yml                  # GAP-0324
├── grpc_mtls_rejection_matrix.yml        # GAP-0325
├── quic_stream_cancel_rollback.yml       # GAP-0326
└── connection_pool_exhaustion.yml        # GAP-0327
```

---

## Task 1: GAP-0323 — QUIC PollSync stress

**Acceptance:**

- 1000 concurrent stream opens within 10 s (via background `&` from bash step, or via a small Go helper using `runners/go_runner` against parallel queries)
- Server stable (no SIGABRT, no panic in log)
- All streams complete or cancel cleanly within bounded time

- [ ] **Step 1:** Write, [ ] **Step 2:** Validate, [ ] **Step 3:** Commit, [ ] **Step 4:** Update GAP_ANALYSIS.md.

---

## Task 2: GAP-0324 — QUIC TLS pinning

**Acceptance:**

- Client (one of the language runners or geode CLI) configured with pinned server cert thumbprint
- Connect to server with matching cert → success
- Rotate server cert; client still pinned to old → rejects with `CERT_PIN_MISMATCH`
- Update client pin; reconnect succeeds

- [ ] **Step 1:** Write, [ ] **Step 2:** Validate, [ ] **Step 3:** Commit, [ ] **Step 4:** Update GAP_ANALYSIS.md.

---

## Task 3: GAP-0325 — gRPC mTLS rejection parity

**Acceptance:** Identical to GAP-0312 (authn-methods/Task 3) but invoked with `--transport grpc`. Three rejection cases produce equivalent errors.

- [ ] **Step 1:** Write, [ ] **Step 2:** Validate, [ ] **Step 3:** Commit, [ ] **Step 4:** Update GAP_ANALYSIS.md.

---

## Task 4: GAP-0326 — Stream cancel rollback

**Acceptance:**

- Begin transaction; insert 5 rows
- Cancel QUIC stream before COMMIT (via client-side `SIGINT` to the running query process, or via the harness's `timeout: 1` causing kill)
- Subsequent query as admin shows 0 rows from the txn (rolled back)
- Server's txn tracker (via `geode admin txn-list`) shows no orphan

- [ ] **Step 1:** Write, [ ] **Step 2:** Validate, [ ] **Step 3:** Commit, [ ] **Step 4:** Update GAP_ANALYSIS.md.

---

## Task 5: GAP-0327 — Pool exhaustion clean error

**Acceptance:**

- Configure connection pool to small cap (e.g. 4 connections)
- Open 4 long-running streams; 5th `geode query` request returns `POOL_EXHAUSTED` or similar within configured timeout (not a hang)
- Close one stream; 5th attempt succeeds

- [ ] **Step 1:** Write, [ ] **Step 2:** Validate, [ ] **Step 3:** Commit, [ ] **Step 4:** Update GAP_ANALYSIS.md.

---

## Final Steps

- [ ] `python -m geodetestlab run --specs specs --filter quic --filter grpc --filter transport -v` all green.
- [ ] Commit `docs(gap): close GAP-0323..GAP-0327 — Transports`.
