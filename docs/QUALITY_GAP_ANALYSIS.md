# Quality Gap Analysis

> **Last Updated:** 2026-03-27
> **Project:** [devnw/codepros/geode/geode-test-harness](https://gitlab.com/devnw/codepros/geode/geode-test-harness)
> **Analysis Method:** Manual code review (Phase 3), static analysis (ruff, mypy), complexity measurement, duplication detection
> **Mode:** `--skip-issues` (platform issue creation skipped; doc-only tracking)

This document tracks **code quality findings** for the Geode Test Harness. Security findings are tracked separately in [GAP_ANALYSIS.md](./GAP_ANALYSIS.md). Performance findings are tracked in [PERF_GAP_ANALYSIS.md](./PERF_GAP_ANALYSIS.md).

---

## Summary

| Severity | Deferred | Closed | Deferred | Total |
|----------|------|--------|----------|-------|
| Critical | 0 | 2 | 0 | 2 |
| High     | 0 | 3 | 0 | 3 |
| Medium   | 0 | 5 | 6 | 11 |
| Low      | 0 | 5 | 11 | 16 |
| **Total** | **0** | **15** | **17** | **32** |

### Top 5 Risks

1. **QG-001 (Critical, 80)** -- CLOSED. Fixed by extracting `_restart_server()` helper.
2. **QG-002 (Critical, 60)** -- CLOSED. Guard `_shared_http.close()` with None check.
3. **QG-003 (High, 60)** -- CLOSED. Extracted `_restart_server()` eliminating 3x duplication.
4. **QG-004 (High, 48)** -- CLOSED. Deprecated assertions.py with clear docstring.
5. **QG-005 (High, 48)** -- CLOSED. Added 33 unit tests for checks.py and server.py. Tests now 102.

---

## Stack-Ranked Findings Table

| Rank | Severity | PriorityScore | Category | Finding | Component | Evidence | Issue URL | Fix Summary | Owner | ETA/SLA | Status |
|------|----------|---------------|----------|---------|-----------|----------|-----------|-------------|-------|---------|--------|
| 1 | Critical | 80 | maintainability | QG-001: `for/else` bug -- `_replay_setup()` skipped after successful restart | `runner.py` | Fixed: extracted `_restart_server()` helper eliminating for/else pattern | -- | Commit `8043c5c` | -- | -- | **Closed** |
| 2 | Critical | 60 | maintainability | QG-002: `UnboundLocalError` on `_shared_http.close()` in finally block | `runner.py` | Fixed: `_shared_http = None` before try; guarded close | -- | Commit `8043c5c` | -- | -- | **Closed** |
| 3 | High | 60 | maintainability | QG-003: Server restart logic duplicated 3 times | `runner.py` | Fixed: extracted `_restart_server()` helper, all 3 blocks now call it | -- | Commit `8043c5c` | -- | -- | **Closed** |
| 4 | High | 48 | architecture | QG-004: Dual assertion systems diverging silently | `assertions.py` | Fixed: deprecated assertions.py with docstring clarifying checks.py is authoritative | -- | Commit `0ae04fa` | -- | -- | **Closed** |
| 5 | High | 48 | tests | QG-005: Zero unit tests on 4 most complex modules | tests/ | Fixed: added test_checks.py (27 tests), test_server.py (6 tests), test_executor_security.py (4), test_runner_security.py (6). Total: 69->102 | -- | Commits `89fa234`, `0ae04fa` | -- | -- | **Closed** |
| 6 | Medium | 36 | readability | QG-006: `run_cli_test()` is 258 lines, nesting depth 8 | `executor.py:71-328` | Single function handles: setup files, auth, transport resolution, GQL detection, command building, DSN, sequential tests, process execution, timeout handling, output checking. | -- | Extract helpers: `_build_cli_command()`, `_resolve_transport_address()`, `_execute_and_check()` | git blame executor.py | M (2-3 days) | Deferred |
| 7 | Medium | 36 | readability | QG-007: Duplicated GQL keyword lists | `executor.py` | Fixed: uses `is_valid_gql()` from utils.py | -- | Commit `8043c5c` | -- | -- | **Closed** |
| 8 | Medium | 36 | readability | QG-008: Duplicated transport-aware address resolution | `executor.py` | Fixed: extracted `_resolve_server_address()` helper | -- | Commit `8043c5c` | -- | -- | **Closed** |
| 9 | Medium | 36 | readability | QG-009: Duplicated port constants | `runner_types.py` | Fixed: centralized in runner_types.py | -- | Commit `8043c5c` | -- | -- | **Closed** |
| 10 | Medium | 32 | api-contract | QG-010: `stdout_contains` silently falls back to stderr | `checks.py:107-111` | `combined = output + error` concatenates stdout and stderr, then checks `stdout_contains` against the combined string. A test asserting `stdout_contains: ["error"]` would pass if the string appears only in stderr. This masks bugs where output goes to the wrong stream. | -- | Check stdout only; add separate `stderr_contains` or `output_contains` field if needed | git blame checks.py | S (< 1 day) | Deferred |
| 11 | Medium | 32 | api-contract | QG-011: Exit codes are undocumented magic numbers | `cli.py` | Fixed: EXIT_SUCCESS/TEST_FAILURE/SPEC_ERROR/RUNNER_ERROR/SECRET_ERROR/INTERRUPTED constants | -- | Commit `0ae04fa` | -- | -- | **Closed** |
| 12 | Medium | 32 | api-contract | QG-012: JSON report schema differs between single-spec and multi-spec modes | `runner.py` / `cli.py` | Single-spec returns a flat `RunSummary` dict. Multi-spec wraps results in an outer envelope. Consumers must handle both shapes. | -- | Unify report schema: always use envelope format, single-spec wraps one entry | git blame cli.py | M (1-2 days) | Deferred |
| 13 | Medium | 28 | reliability | QG-013: `kill_stale_servers()` overly broad pkill pattern | `server.py` | Fixed: scoped to "geode serve.*geode-test-" | -- | Commit `8043c5c` | -- | -- | **Closed** |
| 14 | Medium | 28 | reliability | QG-014: `assert` used for control flow | `runner.py` | Fixed: `raise RuntimeError` in `_restart_server()` | -- | Commit `8043c5c` | -- | -- | **Closed** |
| 15 | Medium | 24 | reliability | QG-015: Swallowed exceptions in plaintext scanning | `plaintext_scanner.py` | Fixed: exceptions logged at WARNING level | -- | Commit `8043c5c` | -- | -- | **Closed** |
| 16 | Medium | 24 | readability | QG-016: Hardcoded developer path | `executor.py` | Fixed: uses GEODE_SOURCE_DIR env var with sibling dir fallback | -- | Commit `8043c5c` | -- | -- | **Closed** |
| 17 | Low | 20 | complexity | QG-017: `run_tests()` is 572 lines, nesting depth 10 | `runner.py:141-712` | Largest function in the codebase. Contains server lifecycle, test execution, result recording, retries, crash recovery, plaintext scanning, and reporting. | -- | Extract: `_run_single_spec()`, `_restart_server()`, `_run_plaintext_checks()`, `_generate_report()` | git blame runner.py | L (3-5 days) | Deferred |
| 18 | Low | 20 | complexity | QG-018: `run()` CLI handler is 431 lines, depth 7 | `cli.py:175-605` | Single Typer command handler with spec discovery, parallel orchestration, reporting, and error handling all inline. | -- | Extract: `_discover_specs()`, `_run_parallel()`, `_generate_reports()` | git blame cli.py | M (2-3 days) | Deferred |
| 19 | Low | 20 | complexity | QG-019: `evaluate_assertions()` is 243 lines, depth 6 | `assertions.py:114-356` | Long function with many assertion type branches. Each branch is independent and could be a separate method. | -- | Extract per-assertion-type methods; use dispatch dict | git blame assertions.py | M (1-2 days) | Deferred |
| 20 | Low | 20 | complexity | QG-020: `_execute_one_test()` is 222 lines, depth 9 | `runner.py:382-603` | Contains pre-test server health check, restart logic, test execution, retry loop, post-test crash detection, and hung-server recovery all in one function. | -- | Will be addressed by QG-003 (extract restart logic) and QG-017 (decompose `run_tests()`) | git blame runner.py | -- | Deferred |
| 21 | Low | 20 | complexity | QG-021: `check_expectations()` is 170 lines, depth 7 | `checks.py:16-186` | Linear chain of if-blocks for each expectation field. Readable but long. Lower priority than the dual-system issue (QG-004). | -- | Extract per-field checkers; or deprecate in favor of assertions.py | git blame checks.py | -- | Deferred |
| 22 | Low | 16 | readability | QG-022: `re` module imported inside function body | `executor.py` | Fixed: `import re` at module level | -- | Commit `8043c5c` | -- | -- | **Closed** |
| 23 | Low | 16 | ci-cd | QG-023: Dead CI jobs (`build-python`, `build-nodejs`) | `.gitlab-ci.yml` | Fixed: jobs removed | -- | Commit `ea6dbcc` | -- | -- | **Closed** |
| 24 | Low | 16 | reliability | QG-024: Fragile cwd discovery in shell test | `executor.py` | Fixed: uses GEODE_SOURCE_DIR env var with .resolve() | -- | Commit `8043c5c` | -- | -- | **Closed** |
| 25 | Low | 16 | deps | QG-025: Three unused declared dependencies | `pyproject.toml` | Fixed: pydantic, jmespath, psutil removed | -- | Commit `8043c5c` | -- | -- | **Closed** |
| 26 | Low | 12 | tests | QG-026: No pytest coverage configuration | `pyproject.toml` | Fixed: pytest-cov added with coverage config | -- | Commit `0ae04fa` | -- | -- | **Closed** |
| 27 | Low | 12 | docs | QG-027: No exit code documentation | `cli.py` | Related to QG-011. No `--help` text, docstring, or external doc explaining what exit codes 0, 1, 2, etc. mean. | -- | Document in CLI help text and CLAUDE.md | git blame cli.py | S (< 1 day) | Deferred |
| 28 | Low | 12 | cleanup | QG-028: Dead code `_scan_pattern()` method | `plaintext_scanner.py` | Fixed: method deleted | -- | Commit `8043c5c` | -- | -- | **Closed** |
| 29 | Low | 12 | docs | QG-029: `assertions.py` module purpose unclear | `assertions.py` | Fixed: deprecation docstring added explaining relationship to checks.py | -- | Commit `0ae04fa` | -- | -- | **Closed** |
| 30 | Low | 12 | docs | QG-030: No ADR for dual plaintext verification | `plaintext_scanner.py` | Two scan methods exist (`_scan_file` and `_scan_pattern`) with no documented rationale for why both exist or which should be used. | -- | Write ADR or inline doc explaining the design; delete dead code per QG-028 | git blame plaintext_scanner.py | S (< 1 day) | Deferred |
| 31 | Low | 8 | readability | QG-031: Files exceeding 800-line guideline | `cli.py` (803), `shell_runner.py` (833), `main.rs` (883), `zig_runner_new.zig` (1386) | Four files exceed the 800-line soft limit. `cli.py` and `shell_runner.py` are Python and decomposable. The Rust and Zig runners are self-contained binaries where this is less impactful. | -- | Decompose `cli.py` (QG-018) and `shell_runner.py`; runners are lower priority | git blame respective files | M-L | Deferred |
| 32 | Low | 8 | architecture | QG-032: Cross-runner code duplication (~3,850 lines across 5 languages) | `runners/` (Go, Python, Rust, Zig, Node.js) | Each runner independently implements: YAML parsing, CLI arg handling, server connection, query execution, result formatting. Shared logic is re-implemented per language. | -- | Long-term: define a runner protocol/spec and generate boilerplate; short-term: document the contract in a shared `runners/PROTOCOL.md` | git blame runners/ | L (strategic) | Deferred |

---

## Findings by Category

### Maintainability (3 findings)

- **QG-001** (Critical, 80): `for/else` bug skipping `_replay_setup()` after restart
- **QG-002** (Critical, 60): `UnboundLocalError` on `_shared_http.close()`
- **QG-003** (High, 60): Server restart logic duplicated 3 times

### Architecture (2 findings)

- **QG-004** (High, 48): Dual assertion systems diverging
- **QG-032** (Low, 8): Cross-runner code duplication

### Tests (2 findings)

- **QG-005** (High, 48): Zero unit tests on 4 most complex modules
- **QG-026** (Low, 12): No pytest coverage configuration

### Readability (6 findings)

- **QG-006** (Medium, 36): `run_cli_test()` 258 lines depth 8
- **QG-007** (Medium, 36): Duplicated GQL keyword lists
- **QG-008** (Medium, 36): Duplicated transport-aware address resolution
- **QG-009** (Medium, 36): Duplicated port constants
- **QG-016** (Medium, 24): Hardcoded developer path
- **QG-022** (Low, 16): `re` imported inside function body

### API/Contract (3 findings)

- **QG-010** (Medium, 32): `stdout_contains` silently falls back to stderr
- **QG-011** (Medium, 32): Exit codes undocumented magic numbers
- **QG-012** (Medium, 32): JSON report schema differs between modes

### Reliability (4 findings)

- **QG-013** (Medium, 28): Overly broad `pkill` pattern
- **QG-014** (Medium, 28): `assert` used for control flow
- **QG-015** (Medium, 24): Swallowed exceptions in plaintext scanning
- **QG-024** (Low, 16): Fragile cwd discovery

### Complexity (5 findings)

- **QG-017** (Low, 20): `run_tests()` 572 lines depth 10
- **QG-018** (Low, 20): `run()` CLI 431 lines depth 7
- **QG-019** (Low, 20): `evaluate_assertions()` 243 lines depth 6
- **QG-020** (Low, 20): `_execute_one_test()` 222 lines depth 9
- **QG-021** (Low, 20): `check_expectations()` 170 lines depth 7

### CI/CD (1 finding)

- **QG-023** (Low, 16): Dead CI jobs

### Dependencies (1 finding)

- **QG-025** (Low, 16): Three unused declared dependencies

### Cleanup (1 finding)

- **QG-028** (Low, 12): Dead code `_scan_pattern()`

### Documentation (3 findings)

- **QG-027** (Low, 12): No exit code documentation
- **QG-029** (Low, 12): `assertions.py` purpose unclear
- **QG-030** (Low, 12): No ADR for dual plaintext verification

### Files Over Size Limit (1 finding)

- **QG-031** (Low, 8): 4 files exceeding 800 lines

---

## Roadmap

### Quick Wins (< 1 day each)

| ID | Finding | Effort |
|----|---------|--------|
| QG-001 | Fix `for/else` bug: replace with `restarted` flag in both post-test and hung-server restart paths | S |
| QG-002 | Initialize `_shared_http = None` before `try`; guard `.close()` | S |
| QG-007 | Delete inline GQL keyword list in executor.py; import from utils.py | S |
| QG-008 | Extract `_resolve_server_address(env)` helper | S |
| QG-009 | Centralize port constants in `runner_types.py` | S |
| QG-014 | Replace `assert data_dir is not None` with explicit `RuntimeError` | S |
| QG-016 | Remove hardcoded `/home/benji/...` path; use env var | S |
| QG-022 | Move `import re` to module level | S |
| QG-023 | Delete dead `build-python` and `build-nodejs` CI jobs | S |
| QG-025 | Remove unused `pydantic`, `jmespath`, `psutil` from dependencies | S |
| QG-026 | Add `pytest-cov` and coverage threshold configuration | S |
| QG-028 | Delete dead `_scan_pattern()` method | S |

### Medium (1-5 days each)

| ID | Finding | Effort |
|----|---------|--------|
| QG-003 | Extract `_restart_server()` helper (eliminates 3x duplication and root cause of QG-001) | M |
| QG-004 | Resolve dual assertion systems -- decide ownership, deprecate or merge | M |
| QG-006 | Decompose `run_cli_test()` into focused helpers | M |
| QG-010 | Fix `stdout_contains` to check stdout only; add `output_contains` field | M |
| QG-011 | Define and document exit code constants | M |
| QG-012 | Unify JSON report schema | M |
| QG-013 | Replace `pkill` with PID-based cleanup | M |
| QG-015 | Log exceptions in plaintext scanner instead of swallowing | M |
| QG-018 | Decompose `cli.py` `run()` handler | M |

### Strategic (> 5 days)

| ID | Finding | Effort |
|----|---------|--------|
| QG-005 | Add comprehensive unit tests for runner.py, executor.py, checks.py, server.py | L |
| QG-017 | Decompose `run_tests()` into focused functions | L |
| QG-032 | Define cross-runner protocol and reduce duplication | L |

---

## Scoring Methodology

**PriorityScore = Impact(1-5) x Likelihood(1-5) x 4** (range 0-100)

| Finding | Impact | Likelihood | PriorityScore | Confidence |
|---------|--------|------------|---------------|------------|
| QG-001 | 5 (false test results, data integrity) | 4 (any mid-test crash triggers it) | 80 | confirmed |
| QG-002 | 5 (masks original error, crashes cleanup) | 3 (requires exception before L377) | 60 | confirmed |
| QG-003 | 5 (root cause of QG-001) | 3 (maintenance risk) | 60 | confirmed |
| QG-004 | 4 (silent behavioral drift) | 3 (each system evolves independently) | 48 | confirmed |
| QG-005 | 4 (regressions go undetected) | 3 (complex code changes regularly) | 48 | confirmed |
| QG-006 | 3 (hard to modify safely) | 3 (frequently touched) | 36 | confirmed |
| QG-007 | 3 (misclassified queries) | 3 (diverged keyword sets) | 36 | confirmed |
| QG-008 | 3 (inconsistency risk) | 3 (two copies) | 36 | confirmed |
| QG-009 | 3 (inconsistency risk) | 3 (two copies) | 36 | confirmed |
| QG-010 | 4 (masks output stream bugs) | 2 (only when output lands in wrong stream) | 32 | confirmed |
| QG-011 | 2 (poor DX) | 4 (every CI integration) | 32 | confirmed |
| QG-012 | 4 (breaks downstream consumers) | 2 (rare mode switch) | 32 | confirmed |
| QG-013 | 4 (kills wrong processes) | 2 (requires name collision) | 28 | suspected |
| QG-014 | 4 (crash under -O) | 2 (rare to use -O in test harness) | 28 | confirmed |
| QG-015 | 3 (silent scan failure) | 2 (requires file system error) | 24 | confirmed |
| QG-016 | 3 (breaks for other devs) | 2 (only shell tests) | 24 | confirmed |
| QG-017 | 2 (hard to maintain) | 2 (large function) | 20 | confirmed |
| QG-018 | 2 (hard to maintain) | 2 (large function) | 20 | confirmed |
| QG-019 | 2 (hard to maintain) | 2 (large function) | 20 | confirmed |
| QG-020 | 2 (hard to maintain) | 2 (large function) | 20 | confirmed |
| QG-021 | 2 (hard to maintain) | 2 (large function) | 20 | confirmed |
| QG-022 | 1 (minor style) | 4 (every call) | 16 | confirmed |
| QG-023 | 2 (wasted CI time) | 2 (every pipeline) | 16 | confirmed |
| QG-024 | 2 (breaks in new env) | 2 (only shell tests) | 16 | confirmed |
| QG-025 | 2 (install bloat) | 2 (every install) | 16 | confirmed |
| QG-026 | 2 (no coverage enforcement) | 3 (ongoing) | 12 | confirmed |
| QG-027 | 2 (poor DX) | 3 (ongoing) | 12 | confirmed |
| QG-028 | 1 (dead code) | 3 (confuses readers) | 12 | confirmed |
| QG-029 | 1 (confusing docs) | 3 (ongoing) | 12 | confirmed |
| QG-030 | 1 (missing rationale) | 3 (ongoing) | 12 | confirmed |
| QG-031 | 1 (style guideline) | 2 (infrequent edits) | 8 | confirmed |
| QG-032 | 2 (maintenance burden) | 1 (runners rarely change) | 8 | confirmed |

---

## Unknowns / Suspected Items

| Finding | What Would Confirm |
|---------|--------------------|
| QG-013 (pkill pattern too broad) | Run `pgrep -f "geode serve"` on a dev machine to check for unrelated process matches |
| QG-012 (JSON schema differs) | Compare JSON output of `--spec single.yml --json` vs `--specs dir/ --json` and diff top-level keys |
