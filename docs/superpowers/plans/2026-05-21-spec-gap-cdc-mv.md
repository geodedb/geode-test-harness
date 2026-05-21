# Spec Gap Closure — CDC & Materialized Views Sub-Plan

> **For agentic workers:** Use `superpowers:subagent-driven-development` or `superpowers:executing-plans`.

**Goal:** Close GAP-0340..GAP-0342.

**Source references:**

- `../geode/src/streaming/sinks/kafka_sink.zig` — Kafka sink
- `../geode/src/streaming/sinks/webhook_sink.zig` — webhook sink
- `../geode/src/canary.zig` — REQ-GQL-042 (CDC), REQ-GQL-076 (MV)
- Existing: `geode_cdc_comprehensive.yml`

## File Structure

```text
geodetestlab-cli/specs/
├── cdc_kafka_resume_token.yml             # GAP-0340
├── cdc_webhook_retry_deadletter.yml       # GAP-0341
└── mv_refresh_latency_envelope.yml        # GAP-0342
```

## Task 1: GAP-0340 — Kafka resume token

**Acceptance:**

- Bring up a Kafka container (or use embedded test sink if available)
- Stream 1000 events; crash sink mid-stream (kill after ~500)
- Restart sink; events 501-1000 delivered exactly once in order
- Document the test infrastructure (docker-compose Kafka or embedded)

If Kafka container is impractical in CI, mark `skip: true` with rationale and Blocked status pending CI extension.

- [ ] **Step 1:** Write, [ ] **Step 2:** Validate, [ ] **Step 3:** Commit, [ ] **Step 4:** Update GAP_ANALYSIS.md.

## Task 2: GAP-0341 — Webhook retry + dead-letter

**Acceptance:**

- Local HTTP server in `bash` step (Python `http.server` subclass) returns 503 for first N requests, then 200
- Configure CDC webhook sink to point at it
- Generate events; observe retry with backoff
- After N+1 5xx responses, event lands in dead-letter (inspect via `geode admin cdc-dlq-list` or similar)

- [ ] **Step 1:** Write, [ ] **Step 2:** Validate, [ ] **Step 3:** Commit, [ ] **Step 4:** Update GAP_ANALYSIS.md.

## Task 3: GAP-0342 — MV refresh latency envelope

**Acceptance:** Create MV on a base table; load base at sustained rate; sample MV-refresh latency for 60s; assert p99 stays under documented envelope (look up the envelope in `../geode/src/canary.zig` REQ-GQL-076 benchmark or set conservative threshold based on first observation).

- [ ] **Step 1:** Write, [ ] **Step 2:** Validate, [ ] **Step 3:** Commit, [ ] **Step 4:** Update GAP_ANALYSIS.md.

---

- [ ] `python -m geodetestlab run --specs specs --filter cdc --filter mv -v` all green.
- [ ] Commit `docs(gap): close GAP-0340..GAP-0342 — CDC & MV`.
