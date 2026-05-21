# Spec Gap Closure — Misc (Stress / LSP / MCP) Sub-Plan

> **For agentic workers:** Use `superpowers:subagent-driven-development` or `superpowers:executing-plans`.

**Goal:** Close GAP-0343..GAP-0345.

## File Structure

```text
geodetestlab-cli/specs/
├── perf_sustained_30min.yml          # GAP-0343
├── lsp_full_surface.yml              # GAP-0344
└── mcp_full_surface.yml              # GAP-0345
```

## Task 1: GAP-0343 — Sustained 30-minute stress

**Acceptance:** Mixed RW workload (70% read / 30% write) at target QPS for 30 minutes. p99 latency stays under documented SLO. RSS does not grow beyond baseline + headroom. No transient errors.

This test is slow — gate it behind a `slow: true` flag or a separate make target (`make test-stress`) to keep regular CI fast.

- [ ] **Step 1:** Write, [ ] **Step 2:** Validate, [ ] **Step 3:** Commit `test(perf): close GAP-0343 — 30-min sustained load`, [ ] **Step 4:** Update GAP_ANALYSIS.md.

## Task 2: GAP-0344 — LSP full surface

**Acceptance:** LSP server responds to `textDocument/completion`, `hover`, `definition`, `publishDiagnostics`. Use existing `lsp_schema_completion.yml` as starting point.

- [ ] **Step 1:** Write, [ ] **Step 2:** Validate, [ ] **Step 3:** Commit, [ ] **Step 4:** Update GAP_ANALYSIS.md.

## Task 3: GAP-0345 — MCP full surface

**Acceptance:** MCP server lists tools; tool invocation with valid/invalid args returns expected JSONRPC responses. Use existing `mcp_client_integration.yml` as starting point.

- [ ] **Step 1:** Write, [ ] **Step 2:** Validate, [ ] **Step 3:** Commit, [ ] **Step 4:** Update GAP_ANALYSIS.md.

---

- [ ] Commit `docs(gap): close GAP-0343..GAP-0345 — Misc (stress/LSP/MCP)`.
