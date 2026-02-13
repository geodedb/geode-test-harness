# Gap Analysis

> **Last Updated:** 2026-02-13
> **GitLab Project:** [devnw/codepros/geode/geode-test-harness](https://gitlab.com/devnw/codepros/geode/geode-test-harness)
> **Analysis Method:** Requirements-to-code comparison, automated SAST/SCA (semgrep, bandit, gitleaks, trufflehog, shellcheck, hadolint, trivy, grype, syft, osv-scanner, cargo-audit), manual adversarial review, and code quality analysis (ruff, mypy, pytest)

This document tracks **ALL gaps** across the project. Resolved gaps are in [GAP_ANALYSIS_RESOLVED.md](./GAP_ANALYSIS_RESOLVED.md).

## Summary

| Severity | Open | Won't Do | Closed | Previously Resolved | Total |
|----------|------|----------|--------|---------------------|-------|
| Critical | 0 | 0 | 2 | 1 | 3 |
| High | 0 | 0 | 12 | 2 | 14 |
| Medium | 0 | 2 | 19 | 10 | 31 |
| Low | 0 | 0 | 12 | 5 | 17 |
| **Total** | **0** | **2** | **45** | **18** | **65** |

Previously resolved: 18 gaps (GAP-0001 through GAP-0018). See [GAP_ANALYSIS_RESOLVED.md](./GAP_ANALYSIS_RESOLVED.md).

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

**Analysis Date:** 2026-02-13
**Analyzed By:** Claude Code (adversarial security review + automated scanning)
**Repository State:** 65 gaps tracked. 0 open, 2 won't do, 45 closed in this project, 18 previously resolved.
**Issue Series:**

- GAP-0001 through GAP-0018: Resolved (see [GAP_ANALYSIS_RESOLVED.md](./GAP_ANALYSIS_RESOLVED.md))
- GAP-0019 through GAP-0037: All 19 closed
- QG-001 through QG-010: All 10 closed
- Issues #48 through #62: 13 closed, 2 won't do (all resolved)
