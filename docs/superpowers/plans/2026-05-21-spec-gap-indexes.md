# Spec Gap Closure — Indexes Sub-Plan

> **For agentic workers:** Use `superpowers:subagent-driven-development` or `superpowers:executing-plans`.

**Goal:** Close GAP-0328..GAP-0332 by producing 5 spec files (one shared with FLE plan).

**Source references:**

- `../geode/src/index/vector_index.zig`, `hnsw_persist.zig`
- `../geode/src/index/spatial_index.zig`, `rtree_persist.zig`
- `../geode/src/index/fulltext.zig`, `../geode/src/fts/bm25.zig`
- `../geode/src/index/blind_index.zig`
- `../geode/src/index/index_manager.zig`, `selectivity.zig`
- Existing: `vector_operations_basic.yml`, `spatial_wkb_functions.yml`, `fulltext_search_basic.yml`, `auto_index_id.yml`

---

## File Structure

```text
geodetestlab-cli/specs/
├── vector_hnsw_comprehensive.yml      # GAP-0328
├── spatial_rtree_comprehensive.yml    # GAP-0329
├── fulltext_bm25_comprehensive.yml    # GAP-0330
└── auto_index_lifecycle.yml           # GAP-0332
# GAP-0331 covered by fle_blind_index_search.yml (FLE plan)
```

## Task 1: GAP-0328 — Vector HNSW comprehensive

**Acceptance:**

- Insert 10k vectors of dimension 128
- Build HNSW index with cosine, L2, and dot-product distance metrics (3 indexes or 1 index with metric specified at query)
- Query: known ground-truth nearest neighbor returned in top-10 with recall ≥ 0.9
- Restart; same query returns same results
- Tag: `vector`, `hnsw`, `comprehensive`

- [ ] **Step 1:** Write spec, [ ] **Step 2:** Validate, [ ] **Step 3:** Commit, [ ] **Step 4:** Update GAP_ANALYSIS.md.

## Task 2: GAP-0329 — Spatial R-tree comprehensive

**Acceptance:**

- 1000 geo points across two grids
- Bounding-box query returns expected subset
- Polygon-contains query returns only inner points
- WKB roundtrip: point→WKB→point preserves coordinates
- Restart; queries return same results

- [ ] **Step 1:** Write, [ ] **Step 2:** Validate, [ ] **Step 3:** Commit, [ ] **Step 4:** Update GAP_ANALYSIS.md.

## Task 3: GAP-0330 — Fulltext BM25 comprehensive

**Acceptance:**

- 1000 docs with varied text
- Multi-token query returns ordered by BM25 score
- Phrase query (`"foo bar"`) returns only ordered matches
- Stemming on/off configurable; off returns exact-form-only matches
- Re-index produces same rankings (deterministic)

- [ ] **Step 1:** Write, [ ] **Step 2:** Validate, [ ] **Step 3:** Commit, [ ] **Step 4:** Update GAP_ANALYSIS.md.

## Task 4: GAP-0332 — Auto-index lifecycle

**Acceptance:**

- Selective query on previously-unindexed property → auto-index creation observable via SHOW INDEXES
- Sustained idle (configured threshold, possibly mocked via env) → eviction
- Subsequent selective query → re-creation

- [ ] **Step 1:** Write, [ ] **Step 2:** Validate, [ ] **Step 3:** Commit, [ ] **Step 4:** Update GAP_ANALYSIS.md.

---

## Final Steps

- [ ] `python -m geodetestlab run --specs specs --filter vector --filter spatial --filter fulltext --filter auto_index -v` all green.
- [ ] Commit `docs(gap): close GAP-0328..GAP-0332 — Indexes`.
