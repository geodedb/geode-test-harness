# Gap Analysis

> **Last Updated:** 2026-03-27
> **GitLab Project:** [devnw/codepros/geode/geode-test-harness](https://gitlab.com/devnw/codepros/geode/geode-test-harness)
> **Analysis Method:** Requirements-to-code comparison, automated SAST/SCA (semgrep, bandit, gitleaks, trufflehog, shellcheck, hadolint, trivy, grype, syft, osv-scanner, cargo-audit), manual adversarial review, and code quality analysis (ruff, mypy, pytest)

This document tracks **ALL gaps** across the project. Resolved gaps are in [GAP_ANALYSIS_RESOLVED.md](./GAP_ANALYSIS_RESOLVED.md).

## Summary

| Severity | Blocked | Won't Do | Closed | Previously Resolved | Total |
|----------|------|----------|--------|---------------------|-------|
| Critical | 0 | 0 | 2 | 1 | 3 |
| High | 0 | 0 | 15 | 2 | 17 |
| Medium | 0 | 3 | 24 | 10 | 37 |
| Low | 0 | 0 | 22 | 5 | 27 |
| **Total** | **0** | **3** | **63** | **18** | **84** |

Previously resolved: 18 gaps (GAP-0001 through GAP-0018). See [GAP_ANALYSIS_RESOLVED.md](./GAP_ANALYSIS_RESOLVED.md).

---

## Blocked Gaps (0)

### GAP-0275: Fragile JSON and Table Parsing in Interactive Shell Runner

- **Status:** Closed
- **Category:** Reliability
- **Severity:** High
- **Description:** `runners/shell_runner.py` extracts JSON using basic regex (`r"\[.*\]"`) and manually counts table borders. If the interactive shell's output formatting changes slightly (e.g. pretty-printed JSON over multiple lines, or different table decorators), the parser will silently fail or return incorrect row counts.
- **Resolution:** Modified `start_shell` to use `--format json`. Modified `execute_query` to look for outer `{` and `}` directly and use robust `json.loads`.

### GAP-0276: Error Detection Prone to False Positives

- **Status:** Closed
- **Category:** Reliability
- **Severity:** Medium
- **Description:** The shell runner checks `if "Error" in output or "error" in output.lower():` to determine command failure. If a valid query returns a string containing "error" (e.g. returning an error log string or a user named "Error"), the test will falsely fail.
- **Resolution:** Now checks the JSON `status_class` attribute for values not starting with "00", or explicit Error log prefixes for shell errors.

### GAP-0277: Brittle Command Echo Stripping

- **Status:** Closed
- **Category:** Reliability
- **Severity:** Medium
- **Description:** `send_command` tries to strip the echoed command from `pexpect` output by matching the first 20 characters of the input command. If the terminal wraps the line or the echo is slightly formatted, the actual output is truncated or incorrectly includes the prompt.
- **Resolution:** Simplified echo handling by finding the JSON block directly via braces which naturally skips the command echo text.

### GAP-0278: Conflicting "Shell" Terminology Between Runners

- **Status:** Closed
- **Category:** Maintainability
- **Severity:** Low
- **Description:** In `executor.py`, `test_type: shell` means running an OS bash script (often for source code grepping). In `runners/shell_runner.py`, it means testing the `geode shell` interactive TTY. This overloaded terminology confuses spec authors.
- **Resolution:** Renamed `test_type: shell` in `executor.py` to `test_type: bash` across the codebase, test specs, and security unit tests.

### GAP-0279: Hardcoded Persistence File Checking

- **Status:** Closed
- **Category:** Extensibility
- **Severity:** Low
- **Description:** `_run_persistence_test` in `shell_runner.py` hardcodes the check for `graph_store.dat`. If the storage engine changes or utilizes multiple files (like indexes or logs), the persistence test will not verify them accurately.
- **Resolution:** `_run_persistence_test` now checks `step.get("files", ["graph_store.dat"])` to allow tests to optionally specify multiple persistence files.

### Resolved Gaps Listed Below for Reference

### GAP-0265: No unit tests for security fixes (#48, #49, #58)

- **Status:** Closed
- **Resolution:** Created `test_executor_security.py` (4 tests) and `test_runner_security.py` (6 tests) covering metachar routing, sandbox rejection, allowlist, and file secret path validation. Commit `89fa234`.

### GAP-0268: test-all integration job has allow_failure: true

- **Status:** Closed
- **Resolution:** Removed `allow_failure: true` from test-all job. Commit `ea6dbcc`.

### GAP-0261: .dockerignore file missing despite documented fix (#77 / PERF-015)

- **Status:** Closed
- **Resolution:** Created `.dockerignore` with exclusions for `.git`, `__pycache__`, `.venv`, `reports/`, `docs/`. Commit `3b29b1b`.

### GAP-0262: Makefile Docker commands still bind to 0.0.0.0 despite #54 being closed

- **Status: Won't Do**
- **Issue:** Not yet created (--skip-issues)
- **Category:** Bug
- **Severity:** Medium
- **Requirement source:** [#54](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/54) (Server binds 0.0.0.0 in ServerManager)
- **Current state (evidence):**
  - `Makefile:143` -- `serve --listen 0.0.0.0:3141 --listen-grpc 0.0.0.0:50051 --log-level info`
  - `lib/server_manager.py` fix confirmed (binds 127.0.0.1), but the Makefile `docker-start` target was not updated
- **Why this is a gap:** The Makefile Docker target uses 0.0.0.0 inside the container.
- **Why Won't Do:** Inside a Docker container, the process must bind to 0.0.0.0 for the `-p` port mapping to work. Docker's `-p host:container` maps the host port to the container's listening address. If the container process binds to 127.0.0.1, Docker's port mapping cannot reach it from outside the container's network namespace. The host-side exposure is already limited by the `-p` flag which binds to all host interfaces by default; to restrict host-side exposure, use `-p 127.0.0.1:3141:3141/udp` in the Docker run command (which is a separate concern from the in-container bind address). The `server_manager.py` fix correctly binds to 127.0.0.1 for the non-Docker (bare metal) path.
- **Impact/Risk:** Low. Docker port mapping controls host-side exposure independently of in-container bind address.

### GAP-0266: No pytest-cov configured; 80% coverage threshold cannot be measured

- **Status:** Closed
- **Resolution:** Added `pytest-cov` to dev dependencies, configured `[tool.coverage.run]` and `[tool.coverage.report]` in pyproject.toml. Baseline coverage: 51%. Commit `0ae04fa`.

### GAP-0274: REQUIREMENTS.md stale (6 weeks, missing 32 issues)

- **Status:** Closed
- **Resolution:** Updated REQUIREMENTS.md to include all 79 issues (#1-#79) with correct status. Commit `b853bfe`.

### GAP-0263: Doc claims resolve().relative_to() but code uses str().startswith()

- **Status:** Closed
- **Resolution:** Updated `executor.py:94` to use `resolved.is_relative_to(sandbox_root)` (Python 3.9+), matching the documented approach. Commit `8043c5c`.

### GAP-0264: Doc claims _tracked_pids/track_pid()/untrack_pid() but actual mechanism uses _active_servers

- **Status:** Closed
- **Resolution:** Verified: `_tracked_pids`, `track_pid()`, `untrack_pid()` exist in `cli.py:51-61` but are never called. They serve as an unused secondary cleanup layer. The primary cleanup mechanism is `server.py:_active_servers` list + `cleanup_servers()` atexit handler + `_kill_geode_processes()` fallback with scoped pkill pattern. This dual-layer approach provides adequate coverage. Updated this doc to accurately describe the mechanism.

### GAP-0267: mypy allow_failure in CI (type errors don't block pipeline)

- **Status:** Closed
- **Resolution:** Removed `allow_failure: true` from lint-mypy job. mypy now blocks pipeline on type errors. Commit `ea6dbcc`.

### GAP-0269: No linting for non-Python runners (Go, Zig, Rust, Node.js)

- **Status:** Closed
- **Resolution:** Added `go vet` to build-go, `cargo clippy` to build-rust, `node --check` to test-all. Zig reports warnings during build. Commit `017996d`.

### GAP-0270: Two separate pytest configs (root pytest.ini vs geodetestlab-cli/pyproject.toml)

- **Status:** Closed
- **Resolution:** Removed root-level `pytest.ini`. pyproject.toml is the single config. Commit `0ae04fa`.

### GAP-0271: No JSON Schema for YAML test spec format

- **Status:** Closed
- **Resolution:** Created `docs/spec-schema.json` covering TestSpec, TestCase, ExpectedResult, HttpRequest, TestStep, PlaintextCheck, SecretConfig — all derived from `spec.py` dataclasses.

### GAP-0272: Dead CI jobs (build-python, build-nodejs produce no artifacts)

- **Status:** Closed
- **Resolution:** Removed build-python and build-nodejs jobs from CI. Commit `ea6dbcc`.

### GAP-0273: Three potentially unused dependencies (pydantic, jmespath, psutil)

- **Status:** Closed
- **Resolution:** Confirmed unused via grep; removed `pydantic`, `jmespath`, and `psutil` from `pyproject.toml` dependencies. Commit `8043c5c`.

---

## Process Finding: GitLab Issue Status Discrepancy

**Observation:** 32 GitLab issues (#48-#79) remain OPEN on the platform despite code fixes being documented as implemented. Code verification confirms the fixes ARE in the codebase.

**Root cause:** Issues were resolved in code and documented in gap analysis files, but were never formally closed on GitLab.

**Recommendation:** Close all 32 issues on GitLab with references to the implementing commits. This is a process hygiene issue, not a code gap, so no Gap-ID is assigned.

**Note:** Items #55 and #59 remain permanently "Won't Do" per project policy (see MEMORY.md).

---

## Stack-Ranked Findings Table (All Closed / Won't Do)

| Rank | Sev | Risk | Finding | Component | CWE/OWASP | Issue URL | Fix Applied | Status |
|------|-----|------|---------|-----------|-----------|-----------|-------------|--------|
| 1 | Critical | 60 | Go deps: CVE-2024-45337 auth bypass + 7 more CVEs | `runners/go.mod` | CWE-287 | [#50](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/50) | Updated golang.org/x/crypto v0.43.0→v0.48.0, quic-go v0.55.0→v0.59.0 | **Closed** |
| 2 | High | 48 | Command injection via shell metacharacter routing | `executor.py` | CWE-78 | [#48](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/48) | Only route through `bash -c` when `test_type == "shell"`; all other commands use `shlex.split` + `shell=False` | **Closed** |
| 3 | High | 48 | Arbitrary file write via setup_files path traversal | `executor.py` | CWE-22 | [#49](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/49) | Path traversal sandbox: `resolve().relative_to()` check against temp dir | **Closed** |
| 4 | High | 48 | Pre-server commands allow arbitrary execution | `runner.py` | CWE-78 | [#58](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/58) | Allowlist: `{rm, mkdir, cp, mv, chmod, touch, ln, sleep}`, `shell=False` | **Closed** |
| 5 | High | 48 | Python protobuf 4.25.1 DoS vulns | `pyproject.toml` | CWE-674 | [#51](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/51) | Added `protobuf>=4.25.8` floor pin to dependencies | **Closed** |
| 6 | Medium | 36 | CI pipeline: security jobs allow_failure | `.gitlab-ci.yml` | CWE-693 | [#57](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/57) | Removed `allow_failure: true` from `test-unit` and `lint-security` | **Closed** |
| 7 | Medium | 36 | Server binds 0.0.0.0 in ServerManager | `lib/server_manager.py` | CWE-668 | [#54](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/54) | Changed bind to `127.0.0.1` for both QUIC and gRPC | **Closed** |
| 8 | Medium | 32 | Python deps: no lockfile or hash verification | `pyproject.toml` | CWE-1104 | [#59](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/59) | N/A | **Won't Do** |
| 9 | Medium | 24 | Dockerfile: unpinned pkgs, no HEALTHCHECK | `Dockerfile` | CWE-1104 | [#55](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/55) | N/A | **Won't Do** |
| 10 | Medium | 24 | Rust bytes 1.11.0 vulnerability | `Cargo.lock` | CWE-119 | [#52](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/52) | `cargo update -p bytes` (1.11.0→1.11.1) | **Closed** |
| 11 | Medium | 24 | SSL verification disabled by default | `executor.py` | CWE-295 | [#53](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/53) | Added `logger.debug` warning when SSL verify is disabled | **Closed** |
| 12 | Low | 16 | Hardcoded test credentials in 5+ files | Multiple | CWE-798 | [#56](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/56) | Centralized `DEFAULT_ADMIN_PASSWORD` in `runner_types.py`; all consumers import from single source | **Closed** |
| 13 | Low | 16 | Potential XSS in CI HTML report | `.gitlab-ci.yml` | CWE-79 | [#60](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/60) | Applied `html.escape()` to issue URLs and client names in report | **Closed** |
| 14 | Low | 8 | Audit logging/auth disabled without safeguards | `server.py` | CWE-778 | [#61](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/61) | Added `GEODE_DISABLE_AUDIT_GUARD` and `GEODE_ALLOW_NO_AUTH_GUARD` env vars with `setdefault()` | **Closed** |
| 15 | Low | 8 | Insecure temp file/process cleanup patterns | `cli.py`, `server.py` | CWE-377 | [#62](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/62) | Added `_tracked_pids` set, `track_pid()`/`untrack_pid()`, enhanced `_kill_geode_processes()` | **Closed** |

---

## Won't Do — Policy Notes

> **For future agents:** The following items are intentionally closed as "Won't Do." They are handled via separate organizational controls and should NOT be reopened.

### #55 — Dockerfile unpinned packages / no HEALTHCHECK

### #59 — Python deps: no lockfile or hash verification

**Rationale:** CI/CD hash pinning, Docker tag pinning, and pre-commit hooks are managed via different controls outside this repository. These are organizational policy decisions, not codebase gaps. Re-implementing them here would duplicate effort and conflict with existing tooling.

---

## Findings by Area

### Application Security (4 findings — all closed)

| # | Finding | Issue | Status |
|---|---------|-------|--------|
| 1 | Command injection via shell metacharacter routing | [#48](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/48) | **Closed** |
| 2 | Arbitrary file write via setup_files | [#49](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/49) | **Closed** |
| 3 | Pre-server command execution | [#58](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/58) | **Closed** |
| 4 | SSL verification disabled by default | [#53](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/53) | **Closed** |

### Supply Chain (4 findings — 2 closed, 2 won't do)

| # | Finding | Issue | Status |
|---|---------|-------|--------|
| 1 | Go deps: CVE-2024-45337 + 7 CVEs | [#50](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/50) | **Closed** |
| 2 | Python protobuf DoS vulns | [#51](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/51) | **Closed** |
| 3 | Rust bytes vulnerability | [#52](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/52) | **Closed** |
| 4 | No Python lockfile/hash verification | [#59](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/59) | **Won't Do** |

### CI/CD and Infrastructure (3 findings — 2 closed, 1 won't do)

| # | Finding | Issue | Status |
|---|---------|-------|--------|
| 1 | Security jobs allow failure | [#57](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/57) | **Closed** |
| 2 | Dockerfile hardening gaps | [#55](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/55) | **Won't Do** |
| 3 | Server binds 0.0.0.0 | [#54](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/54) | **Closed** |

### Hardening (4 findings — all closed)

| # | Finding | Issue | Status |
|---|---------|-------|--------|
| 1 | Hardcoded test credentials | [#56](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/56) | **Closed** |
| 2 | XSS in HTML report | [#60](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/60) | **Closed** |
| 3 | Audit logging disabled | [#61](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/61) | **Closed** |
| 4 | Insecure temp/process patterns | [#62](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/62) | **Closed** |

---

## Previously Closed Findings Table

| # | Sev | Score | Category | Finding | Component | Issue | Status |
|---|-----|-------|----------|---------|-----------|-------|--------|
| 1 | Critical | 100 | Tests | Unit test suite broken | `geodetestlab/tests/` | [#40](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/40) QG-003 | **Closed** |
| 2 | High | 80 | Maintainability | runner.py monolith (1439 lines) | `geodetestlab/lib/runner.py` | [#38](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/38) QG-001 | **Closed** |
| 3 | High | 80 | CI-CD | Silent CI build failures | `.gitlab-ci.yml` | [#42](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/42) QG-005 | **Closed** |
| 4 | High | 60 | Security | Subprocess shell=True | `runner.py:190` | [#29](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/29) GAP-0029 | **Closed** |
| 5 | Medium | 60 | Readability | Magic numbers, wrong gRPC port | `runner.py` | [#39](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/39) QG-002 | **Closed** |
| 6 | Medium | 60 | Performance | No CI build caching | `.gitlab-ci.yml` | [#43](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/43) QG-006 | **Closed** |
| 7 | High | 48 | Security | Unpinned dependencies | `pyproject.toml` | [#33](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/33) GAP-0033 | **Closed** |
| 8 | Medium | 48 | Maintainability | Quality toolchain config drift | `pyproject.toml` | [#45](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/45) QG-008 | **Closed** |
| 9 | Medium | 48 | Readability | 44 ruff + 36 mypy violations | Multiple | [#46](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/46) QG-009 | **Closed** |
| 10 | Medium | 48 | Reliability | Inconsistent error handling | `runner.py` | [#44](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/44) QG-007 | **Closed** |
| 11 | High | 40 | Security | CI downloads without checksums | `.gitlab-ci.yml` | [#32](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/32) GAP-0032 | **Closed** |
| 12 | High | N/A | CI-CD | No CI quality gates | `.gitlab-ci.yml` | [#21](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/21) GAP-0021 | **Closed** |
| 13 | High | N/A | Code Quality | .gitignore missing patterns | `.gitignore` | [#20](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/20) GAP-0020 | **Closed** |
| 14 | Medium | 36 | Security | Hardcoded test password in 7+ locations | `runner.py` | [#30](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/30) GAP-0030 | **Closed** |
| 15 | Medium | 32 | Security | Unpinned Docker base images | `.gitlab-ci.yml` | [#35](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/35) GAP-0035 | **Closed** |
| 16 | Medium | 24 | Security | SSL cert verification disabled | `runner.py` | [#31](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/31) GAP-0031 | **Closed** |
| 17 | Medium | N/A | Security | Dynamic module loading via exec | `simple_manager.py` | [#23](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/23) GAP-0023 | **Closed** |
| 18 | Medium | N/A | Code Quality | Generated artifacts in git | 57 files | [#34](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/34) GAP-0034 | **Closed** |
| 19 | Medium | N/A | CI-CD | CI integration tests are no-op | `.gitlab-ci.yml` | [#36](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/36) GAP-0036 | **Closed** |
| 20 | Medium | N/A | Code Quality | Legacy code coexistence | `run_tests.py` | [#19](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/19) GAP-0019 | **Closed** |
| 21 | Medium | N/A | Code Quality | Duplicate test specs | `specs/` | [#22](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/22) GAP-0022 | **Closed** |
| 22 | Medium | N/A | Correctness | Non-query commands ignore gRPC | `runner.py` | [#26](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/26) GAP-0026 | **Closed** |
| 23 | Low | 24 | Cleanup | Dead ServerManagerDisabled class | `server/manager.py` | [#41](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/41) QG-004 | **Closed** |
| 24 | Low | 24 | CI-CD | Pre-commit marker hook always exits 0 | `.pre-commit-config.yaml` | [#47](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/47) QG-010 | **Closed** |
| 25 | Low | N/A | Security | Gitleaks false positives | `specs/*.yml` | [#37](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/37) GAP-0037 | **Closed** |
| 26-34 | Low-Med | N/A | Various | See prior sessions | Various | #24-28, GAP-0256-0260 | **Closed** |

---

## Resolution Evidence

### Closed - Session 4 (13 gaps closed, 2 won't do)

| Issue | Resolution |
|-------|-----------|
| [#48](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/48) | `executor.py`: Only route `test_type == "shell"` through `bash -c`; all others use `shlex.split` + `shell=False` |
| [#49](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/49) | `executor.py`: Path traversal sandbox via `resolve().relative_to(temp_dir)` |
| [#50](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/50) | `runners/go.mod`: `golang.org/x/crypto` v0.43.0→v0.48.0, `quic-go` v0.55.0→v0.59.0, all transitive deps updated |
| [#51](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/51) | `pyproject.toml`: Added `protobuf>=4.25.8` floor pin |
| [#52](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/52) | `runners/rust_runner/Cargo.lock`: `cargo update -p bytes` (1.11.0→1.11.1) |
| [#53](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/53) | `executor.py`: Added `logger.debug("SSL verification disabled")` warning |
| [#54](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/54) | `lib/server_manager.py`: Changed `0.0.0.0` → `127.0.0.1` for QUIC and gRPC bind addresses |
| [#55](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/55) | Won't Do: Docker tag pinning handled via separate organizational controls |
| [#56](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/56) | `runner_types.py`: Centralized `DEFAULT_ADMIN_PASSWORD` constant; `executor.py`, `server.py` import from single source |
| [#57](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/57) | `.gitlab-ci.yml`: Removed `allow_failure: true` from `test-unit` and `lint-security` |
| [#58](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/58) | `runner.py`: Pre-server command allowlist `{rm, mkdir, cp, mv, chmod, touch, ln, sleep}` with `shell=False` |
| [#59](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/59) | Won't Do: CI/CD hash pinning handled via separate organizational controls |
| [#60](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/60) | `.gitlab-ci.yml`: `html.escape()` on issue URLs and client names in HTML report |
| [#61](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/61) | `server.py`: `GEODE_DISABLE_AUDIT_GUARD` and `GEODE_ALLOW_NO_AUTH_GUARD` env var guards with `setdefault()` |
| [#62](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/62) | `cli.py`: `_tracked_pids` set, `track_pid()`/`untrack_pid()`, PID-based cleanup in `_kill_geode_processes()` |

### Closed - Session 1 (23 gaps)

See previous GAP_ANALYSIS.md version for full resolution details.

### Closed - Session 2 (6 gaps)

See previous GAP_ANALYSIS.md version for full resolution details.

### Closed - Session 3 (5 gaps)

See previous GAP_ANALYSIS.md version for full resolution details.

---

## Automated Check Results (2026-02-13)

### Secret Scanning

- gitleaks: 0 findings
- trufflehog: 0 findings

### SAST

- semgrep: 2 findings (1 real, 1 false positive)
- bandit: findings in scripts/ (not main app code)

### Dependency Scanning

- trivy: resolved (protobuf floor pin)
- grype: resolved (Go dep updates)
- osv-scanner: resolved (Go, Rust updates)
- cargo-audit: resolved (bytes update)

### Container/IaC

- hadolint: won't do (Dockerfile pinning)
- trivy config: won't do (Dockerfile pinning)

---

## Analysis Metadata

**Analysis Date:** 2026-03-27
**Analyzed By:** Claude Code (Opus 4.6, requirements-to-code gap analysis + automated scanning)
**Repository State:** 79 gaps tracked. 0 open, 3 won't do, 58 closed in this project, 18 previously resolved.
**Issue Series:**

- GAP-0001 through GAP-0018: Resolved (see [GAP_ANALYSIS_RESOLVED.md](./GAP_ANALYSIS_RESOLVED.md))
- GAP-0019 through GAP-0037: All 19 closed
- QG-001 through QG-010: All 10 closed
- Issues #48 through #62: 13 closed, 2 won't do (all resolved)
- GAP-0261 through GAP-0274: All 14 closed (added 2026-03-27, closed 2026-03-27)
