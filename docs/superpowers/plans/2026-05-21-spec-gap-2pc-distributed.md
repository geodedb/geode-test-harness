# Spec Gap Closure — 2PC Distributed Safety Sub-Plan

> **For agentic workers:** Use `superpowers:subagent-driven-development` or `superpowers:executing-plans`.

**Goal:** Close GAP-0317..GAP-0322 by producing 6 spec files that pin 2PC safety invariants: coordinator-timeout rollback, participant-crash recovery, nonce replay rejection, 16 MiB frame limit, cluster-token enforcement, principal envelope across shards.

**Source references:**

- `../geode/src/transactions/two_phase_commit.zig`
- `../geode/src/distributed/twophase.zig` (esp. :52 nonce, :60 16MiB frame, :66-70 cluster token)
- `../geode/src/distributed/twophase_participant.zig`
- `../geode/src/distributed/principal_envelope.zig`
- `../geode/src/distributed/cluster_auth.zig`
- `../geode/src/txn_undo_log.zig`
- Existing: `distributed_2pc_undo.yml`, `distributed_snapshot_serialization.yml`, `distributed_tenant_isolation.yml`, `distributed_federation_merge.yml`

---

## File Structure

```text
geodetestlab-cli/specs/
├── 2pc_coordinator_timeout.yml           # GAP-0317
├── 2pc_participant_recovery.yml          # GAP-0318
├── 2pc_nonce_replay_protection.yml       # GAP-0319
├── 2pc_frame_limit.yml                   # GAP-0320
├── 2pc_cluster_token_required.yml        # GAP-0321
└── 2pc_principal_propagation.yml         # GAP-0322
```

**Test infrastructure caveat:** These tests require a multi-node deployment. The harness currently runs single-node by default. Each spec must either:

- Set up multiple `geode serve` processes on different ports (via `bash` steps with `&` and explicit port assignment), or
- Mark the spec with `skip: true` and `skip_reason: "requires distributed harness extension"` if multi-node bring-up via this harness is impractical, and close the gap as `Blocked` with rationale to add a distributed-harness skill.

For each spec below, attempt the multi-node `bash` bring-up first; fall back to `Blocked` only if there's no path.

---

## Task 1: GAP-0317 — Coordinator timeout rolls back participants

**Acceptance:** Bring up coordinator + 2 participants. Begin distributed txn writing 10 rows on each participant. SIGSTOP the coordinator post-PREPARE. Participants timeout (default 30s — make configurable to 5s for test) and rollback. Resume coordinator (SIGCONT); txn observed-aborted. Final state: 0 rows on each participant.

- [ ] **Step 1:** Write, [ ] **Step 2:** Validate, [ ] **Step 3:** Commit, [ ] **Step 4:** Update GAP_ANALYSIS.md.

---

## Task 2: GAP-0318 — Participant crash post-prepare → replay decision

**Acceptance:** Participant crashes after writing PREPARE to WAL; coordinator commits successfully on other participants; crashed participant restarts; coordinator's recovery thread or participant's recovery query learns COMMIT; data applied.

- [ ] **Step 1:** Write, [ ] **Step 2:** Validate, [ ] **Step 3:** Commit, [ ] **Step 4:** Update GAP_ANALYSIS.md.

---

## Task 3: GAP-0319 — Nonce replay rejection

**Acceptance:** Capture a 2PC PREPARE wire-message (via tcpdump or via injecting a packet-capture-replay tool — likely a separate Go binary as a runner). Replay the same nonce; coordinator rejects with `NONCE_REUSED` or equivalent. Original txn proceeds normally.

If wire-level replay tooling isn't available, simulate via repeated submission of the same `geode admin 2pc-test-replay <nonce>` if such command exists; otherwise mark Blocked with rationale to add a test-only replay tool.

- [ ] **Step 1:** Write, [ ] **Step 2:** Validate, [ ] **Step 3:** Commit, [ ] **Step 4:** Update GAP_ANALYSIS.md.

---

## Task 4: GAP-0320 — Frame size limit

**Acceptance:** Submit 2PC message with 17 MiB payload (via crafted wire-level injection or via a query producing >16 MiB of output). Server rejects with `FRAME_TOO_LARGE`. Subsequent normal queries succeed (server stable, no allocator spike).

- [ ] **Step 1:** Write, [ ] **Step 2:** Validate, [ ] **Step 3:** Commit, [ ] **Step 4:** Update GAP_ANALYSIS.md.

---

## Task 5: GAP-0321 — Cluster token required

**Acceptance:**

- Coordinator with `GEODE_CLUSTER_TOKEN=abc`
- Participant with `GEODE_CLUSTER_TOKEN=xyz` (wrong) → coordinator-participant handshake fails; data not replicated
- Restart participant with `GEODE_CLUSTER_TOKEN=abc` → handshake succeeds; replication proceeds
- Participant without `GEODE_CLUSTER_TOKEN` → handshake fails

- [ ] **Step 1:** Write, [ ] **Step 2:** Validate, [ ] **Step 3:** Commit, [ ] **Step 4:** Update GAP_ANALYSIS.md.

---

## Task 6: GAP-0322 — Principal envelope propagation

**Acceptance:**

- Tenant_a user issues cross-shard query (via federation or sharding)
- Remote shard's RLS filter receives `tenant_a` identity, not `geode` (coordinator user)
- Cross-shard rows obey tenant_a's RLS scope

Reference `distributed_federation_merge.yml` for federation setup pattern.

- [ ] **Step 1:** Write, [ ] **Step 2:** Validate, [ ] **Step 3:** Commit, [ ] **Step 4:** Update GAP_ANALYSIS.md.

---

## Final Steps

- [ ] `python -m geodetestlab run --specs specs --filter 2pc -v` all green (or documented Blocked).
- [ ] Commit `docs(gap): close GAP-0317..GAP-0322 — 2PC distributed safety`.
