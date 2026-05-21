# Spec Gap Closure — GQL Types & Parser Sub-Plan

> **For agentic workers:** Use `superpowers:subagent-driven-development` or `superpowers:executing-plans`.

**Goal:** Close GAP-0333..GAP-0336.

**Source references:**

- `../geode/src/gql/parser.zig:44` — recursion limit 128
- `../geode/src/gql/ast.zig`, `lexer.zig`
- `../geode/src/value_types.zig` — full type system
- `../geode/src/temporal.zig` — interval ops
- Existing: `advanced_types_basic.yml`, `undirected_pattern_matching.yml`, `recursive_and_cte.yml`

## File Structure

```text
geodetestlab-cli/specs/
├── gql_parser_recursion_limit.yml     # GAP-0333
├── gql_value_types_roundtrip.yml      # GAP-0334
├── gql_interval_comparisons.yml       # GAP-0335
└── gql_undirected_multi_hop.yml       # GAP-0336
```

## Task 1: GAP-0333 — Parser recursion limit

**Acceptance:** Build expression at exactly 128 nested levels (e.g. `(((...x...)))`) — parse succeeds. Build at 129 — parse fails with explicit error (not segfault). Server remains stable for subsequent queries.

- [ ] **Step 1:** Write, [ ] **Step 2:** Validate, [ ] **Step 3:** Commit, [ ] **Step 4:** Update GAP_ANALYSIS.md.

## Task 2: GAP-0334 — Value types roundtrip

**Acceptance:** For each of Date, Time, Duration, Point, Path, Interval:

- Insert as literal
- Query back; JSON output preserves type and value
- Equality predicate works (`WHERE n.d = date('2026-05-21')`)

- [ ] **Step 1:** Write, [ ] **Step 2:** Validate, [ ] **Step 3:** Commit, [ ] **Step 4:** Update GAP_ANALYSIS.md.

## Task 3: GAP-0335 — Interval comparisons

**Acceptance:** Two intervals — verify overlap, contains, before, after return expected booleans for normal, edge (touching), and degenerate (zero-duration) cases.

- [ ] **Step 1:** Write, [ ] **Step 2:** Validate, [ ] **Step 3:** Commit, [ ] **Step 4:** Update GAP_ANALYSIS.md.

## Task 4: GAP-0336 — Undirected multi-hop

**Acceptance:** `MATCH (a:A)-[*2..3]-(b:B)` returns expected paths in both directions; label combinations covered: (A→B), (B→A), (A→A→B), etc.

- [ ] **Step 1:** Write, [ ] **Step 2:** Validate, [ ] **Step 3:** Commit, [ ] **Step 4:** Update GAP_ANALYSIS.md.

---

## Final Steps

- [ ] `python -m geodetestlab run --specs specs --filter gql -v` all green for new specs.
- [ ] Commit `docs(gap): close GAP-0333..GAP-0336 — GQL types & parser`.
