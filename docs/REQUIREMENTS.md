# Requirements Mirror

> **Last Updated:** 2026-03-27
> **GitLab Project:** [devnw/codepros/geode/geode-test-harness](https://gitlab.com/devnw/codepros/geode/geode-test-harness)
> **Source of Truth:** GitLab Issues

This document is a **flatfile mirror** of requirements tracked in GitLab. GitLab is the authoritative source of truth.

## Summary

79 total issues tracked. 47 original gap issues (all resolved). 15 security/hardening issues (#48-#62, all resolved). 17 performance issues (#63-#79, 12 resolved, 5 accepted by design).

See [GAP_ANALYSIS.md](./GAP_ANALYSIS.md), [QUALITY_GAP_ANALYSIS.md](./QUALITY_GAP_ANALYSIS.md), [PERF_GAP_ANALYSIS.md](./PERF_GAP_ANALYSIS.md), and [SECURITY_GAP_ANALYSIS.md](./SECURITY_GAP_ANALYSIS.md) for detailed tracking.

## Resolved Issues (Issues #1-#47)

All 47 original gap issues are closed. See [GAP_ANALYSIS_RESOLVED.md](./GAP_ANALYSIS_RESOLVED.md) for detailed resolution evidence.

### Critical / High Priority (Resolved)

| Issue | Type | Title | Status |
|-------|------|-------|--------|
| [#40](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/40) | Bug | QG-003: Unit test suite broken — 3/5 files import non-existent module | **Closed** |
| [#38](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/38) | Enhancement | QG-001: runner.py monolith (1439 lines) | **Closed** |
| [#42](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/42) | Bug | QG-005: Silent CI build failures via `\|\| echo` error suppression | **Closed** |
| [#29](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/29) | Security | GAP-0029: Subprocess shell=True with spec-controlled input | **Closed** |
| [#33](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/33) | Security | GAP-0033: Unpinned dependencies across all package managers | **Closed** |
| [#32](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/32) | Security | GAP-0032: CI downloads without checksum verification | **Closed** |
| [#21](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/21) | Feature | GAP-0021: No CI quality gates (linting/security scanning) | **Closed** |
| [#20](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/20) | Bug | GAP-0020: .gitignore missing patterns for generated artifacts | **Closed** |
| [#5](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/5) | Feature | GAP-0005: Missing CI/CD Pipeline Configuration | **Closed** |
| [#9](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/9) | Bug | GAP-0009: Inconsistent Default Server Port Configuration | **Closed** |

### Medium Priority (Resolved)

| Issue | Type | Title | Status |
|-------|------|-------|--------|
| [#39](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/39) | Enhancement | QG-002: 30+ magic numbers including wrong gRPC port | **Closed** |
| [#43](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/43) | Enhancement | QG-006: No CI build caching | **Closed** |
| [#45](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/45) | Enhancement | QG-008: Quality toolchain config drift (black/isort vs ruff) | **Closed** |
| [#46](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/46) | Enhancement | QG-009: 44 ruff + 36 mypy violations | **Closed** |
| [#44](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/44) | Enhancement | QG-007: Inconsistent error handling | **Closed** |
| [#30](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/30) | Security | GAP-0030: Hardcoded test password in 7+ source locations | **Closed** |
| [#35](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/35) | Security | GAP-0035: Unpinned Docker base images in CI | **Closed** |
| [#31](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/31) | Security | GAP-0031: SSL certificate verification disabled in HTTP client | **Closed** |
| [#23](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/23) | Security | GAP-0023: Dynamic module loading via exec() | **Closed** |
| [#34](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/34) | Bug | GAP-0034: Generated artifacts committed to git history | **Closed** |
| [#36](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/36) | Enhancement | GAP-0036: CI integration tests are no-op placeholders | **Closed** |
| [#19](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/19) | Enhancement | GAP-0019: Legacy code coexistence with new architecture | **Closed** |
| [#22](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/22) | Enhancement | GAP-0022: Duplicate test specifications across two locations | **Closed** |
| [#26](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/26) | Bug | GAP-0026: Non-query commands silently ignore gRPC transport | **Closed** |
| [#18](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/18) | Bug | GAP-0018: Stale REQUIREMENTS.md shows closed issues as open | **Closed** |
| [#1](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/1) | Bug | GAP-0001: Missing TLS Certificate Directory | **Closed** |
| [#2](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/2) | Feature | GAP-0002: Incomplete Connection Pool Step Type Support | **Closed** |
| [#4](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/4) | Feature | GAP-0004: Missing Multi-Connection Test Support | **Closed** |
| [#6](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/6) | Enhancement | GAP-0006: Missing README Documentation | **Closed** |
| [#11](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/11) | Bug | GAP-0011: Zig YAML Dependency Path Outside Repository | **Closed** |
| [#13](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/13) | Enhancement | GAP-0013: Missing Docker Availability Validation | **Closed** |
| [#14](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/14) | Enhancement | GAP-0014: Missing Test Specification Schema Validation | **Closed** |
| [#15](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/15) | Enhancement | GAP-0015: Missing Harness-Level Timeout Enforcement | **Closed** |
| [#16](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/16) | Bug | GAP-0016: TestResult Field Name Mismatch | **Closed** |

### Low Priority (Resolved)

| Issue | Type | Title | Status |
|-------|------|-------|--------|
| [#41](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/41) | Cleanup | QG-004: 488-line dead ServerManagerDisabled class | **Closed** |
| [#47](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/47) | Bug | QG-010: Pre-commit check-todos hook always exits 0 | **Closed** |
| [#37](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/37) | Enhancement | GAP-0037: Gitleaks false positives from test encryption keys | **Closed** |
| [#24](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/24) | Bug | GAP-0024: Duplicate sys.path.insert in manager.py | **Closed** |
| [#25](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/25) | Enhancement | GAP-0025: Temp directory accumulation from disabled cleanup | **Closed** |
| [#27](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/27) | Enhancement | GAP-0027: Inconsistent gap label usage | **Closed** |
| [#28](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/28) | Enhancement | GAP-0028: Missing Makefile quality targets | **Closed** |
| [#3](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/3) | Feature | GAP-0003: Missing Benchmark Execution Support | **Closed** |
| [#7](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/7) | Bug | GAP-0007: Outdated Git Remote URL After Project Move | **Closed** |
| [#8](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/8) | Enhancement | GAP-0008: Undocumented Skipped Tests | **Closed** |
| [#10](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/10) | Enhancement | GAP-0010: Unused Imports in run_tests.py | **Closed** |
| [#12](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/12) | Bug | GAP-0012: Bare except Clauses in Python Runner Teardown | **Closed** |
| [#17](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/17) | Enhancement | GAP-0017: Missed Bare Except Clause in pool_release() | **Closed** |

## Requirements by Category

### Test Harness Core

- Test specification format (YAML-based) - RESOLVED
- Multi-language runner support (Python, Go, Rust, Zig, Node.js) - RESOLVED
- Docker-based server management - RESOLVED
- JSON/HTML report generation - RESOLVED
- Parallel and sequential test execution - RESOLVED
- Legacy code cleanup ([#19](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/19) - RESOLVED)
- Specs consolidation ([#22](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/22) - RESOLVED)

### Connection Management

- Basic connection lifecycle (connect/disconnect) - RESOLVED
- Connection pooling ([#2](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/2) - RESOLVED)
- Multi-connection support ([#4](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/4) - RESOLVED)
- TLS certificate handling ([#1](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/1) - RESOLVED)

### Transport Support

- QUIC transport (default) - RESOLVED
- gRPC transport for query commands - RESOLVED
- gRPC transport for admin commands ([#26](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/26) - RESOLVED, warning emitted on fallback)

### Security

- Subprocess command injection ([#29](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/29) - RESOLVED)
- Hardcoded credentials ([#30](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/30) - RESOLVED)
- SSL certificate validation ([#31](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/31) - RESOLVED)
- Dynamic code execution ([#23](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/23) - RESOLVED)
- Secret scanning false positives ([#37](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/37) - RESOLVED)
- Shell metacharacter routing ([#48](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/48) - RESOLVED)
- Path traversal in setup_files ([#49](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/49) - RESOLVED)
- Pre-server command allowlist ([#58](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/58) - RESOLVED)
- Server bind address ([#54](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/54) - RESOLVED)
- Audit/auth guards ([#61](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/61) - RESOLVED)
- Temp file cleanup ([#62](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/62) - RESOLVED)
- CI HTML report XSS ([#60](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/60) - RESOLVED)
- Centralized test credentials ([#56](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/56) - RESOLVED)
- SSL verification logging ([#53](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/53) - RESOLVED)
- CI security job allow_failure ([#57](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/57) - RESOLVED)
- Dockerfile hardening ([#55](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/55) - WON'T DO, org controls)
- Python lockfile ([#59](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/59) - WON'T DO, org controls)

### Supply Chain

- CI download integrity ([#32](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/32) - RESOLVED)
- Dependency pinning ([#33](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/33) - RESOLVED)
- Docker image pinning ([#35](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/35) - RESOLVED)
- Go deps CVE-2024-45337 ([#50](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/50) - RESOLVED)
- Python protobuf pin ([#51](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/51) - RESOLVED)
- Rust bytes vulnerability ([#52](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/52) - RESOLVED)

### Performance (Issues #63-#79)

- Subprocess per CLI test ([#63](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/63) - ACCEPTED, by design)
- Server readiness polling ([#64](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/64) - RESOLVED)
- Plaintext grep optimization ([#65](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/65) - RESOLVED)
- Variable substitution O(n*m) ([#66](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/66) - RESOLVED)
- Parallel worker cap ([#67](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/67) - RESOLVED)
- Sequential tests within spec ([#68](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/68) - RESOLVED)
- httpx.Client per test ([#69](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/69) - RESOLVED)
- YAML re-parsed in workers ([#70](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/70) - ACCEPTED)
- os.environ.copy per spec ([#71](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/71) - ACCEPTED)
- find_geode_binary per worker ([#72](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/72) - RESOLVED)
- CI pip install duplication ([#73](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/73) - RESOLVED)
- Shell runner sleep ([#74](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/74) - RESOLVED)
- CI Zig toolchain duplication ([#75](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/75) - RESOLVED)
- Go runner deprecated ioutil ([#76](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/76) - RESOLVED)
- Dockerfile COPY context ([#77](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/77) - RESOLVED)
- HTML report string concat ([#78](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/78) - ACCEPTED)
- Docker readiness polling ([#79](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/79) - ACCEPTED)

### CI/CD

- Pipeline configuration ([#5](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/5) - RESOLVED)
- Automated test execution - RESOLVED
- Report artifact storage - RESOLVED
- Quality gates ([#21](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/21) - RESOLVED)
- Integration tests ([#36](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/36) - RESOLVED)

### Code Quality

- Makefile quality targets ([#28](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/28) - RESOLVED)
- Module loading safety ([#23](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/23) - RESOLVED)
- Temp directory cleanup ([#25](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/25) - RESOLVED)
- Duplicate code ([#24](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/24) - RESOLVED)

### Documentation

- README ([#6](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/6) - RESOLVED)
- Skip reason documentation ([#8](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/8) - RESOLVED)
- Requirements mirror accuracy ([#18](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/18) - RESOLVED)

### Repository Hygiene

- .gitignore patterns ([#20](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/20) - RESOLVED)
- Committed artifacts ([#34](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/34) - RESOLVED)
- Label consistency ([#27](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/27) - RESOLVED)

---

*This file is a mirror of GitLab issues. Edit GitLab issues to update requirements.*
