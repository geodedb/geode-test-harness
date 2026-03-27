# Security Gap Analysis

> **Last Updated:** 2026-03-27
> **Review Phase:** Phase 3 (adversarial security review)
> **Reviewer:** Claude Code (security scoring agent)
> **Repository:** [devnw/codepros/geode/geode-test-harness](https://gitlab.com/devnw/codepros/geode/geode-test-harness)
> **Commit:** 183a95d (main)
> **Previous Review:** 2026-02-13 (see [SECURITY_REVIEW_NOTES.md](./SECURITY_REVIEW_NOTES.md))
> **Mode:** --skip-issues (documentation only, no platform issue creation)

This document tracks security findings from Phase 3 of the adversarial security review. For general gap tracking (quality, CI/CD, requirements), see [GAP_ANALYSIS.md](./GAP_ANALYSIS.md).

---

## Summary

| Severity | Count | Open | SLA |
|----------|-------|------|-----|
| Critical | 1 | 1 | 7 days |
| High | 3 | 3 | 30 days |
| Medium | 5 | 5 | 90 days |
| Low | 8 | 8 | 180 days |
| Info | 2 | 0 | Backlog |
| **Total** | **19** | **17** | -- |

### Top 5 Risks

1. **SEC-001** (Critical, Risk 100): CVE-2026-33186 gRPC auth bypass in `google.golang.org/grpc v1.75.1` -- remote pre-auth bypass.
2. **SEC-002** (High, Risk 80): Arbitrary file read via `source:file` secret resolution -- no path validation, can read `/etc/shadow`.
3. **SEC-003** (High, Risk 64): `sanitize_args()` defined but never called in execution pipeline -- LLM fuzz args unsanitized.
4. **SEC-004** (High, Risk 60): Go stdlib vulnerabilities in `go 1.24.12` -- multiple CVEs fixed in 1.24.14+.
5. **SEC-007** (Medium, Risk 48): Rust `aws-lc-sys 0.37.0` with 5 advisories including X.509 certificate bypass.

### Immediate Actions Required

- **SEC-001**: Update `google.golang.org/grpc` to >= 1.79.3 in both `runners/go.mod` and `loadtest/go/go.mod`. This is a known CVE with public exploit details.
- **SEC-002**: Add path validation to `utils.py:325-330` before reading secret files. Restrict to a configurable allowlist of directories.

---

## Stack-Ranked Findings Table

| Rank | Severity | Risk Score | SEC-ID | Finding | Component | CWE / OWASP | Evidence | Issue URL | Fix | Owner | Due | Status |
|------|----------|------------|--------|---------|-----------|-------------|----------|-----------|-----|-------|-----|--------|
| 1 | Critical | 100 | SEC-001 | CVE-2026-33186 gRPC auth bypass | `runners/go.mod:20`, `loadtest/go/go.mod:17` | CWE-287 / A07:2021 | `google.golang.org/grpc v1.75.1` in both go.mod files; fixed in >= 1.79.3 | Skipped | Upgrade grpc to >= 1.79.3 | -- | 2026-04-03 | **Open** |
| 2 | High | 80 | SEC-002 | Arbitrary file read via source:file secret resolution | `utils.py:325-330` | CWE-22 / A01:2021 | `Path(config.key).expanduser()` with no path validation; reads any readable file | Skipped | Add path allowlist or restrict to project-relative paths | -- | 2026-04-26 | **Open** |
| 3 | High | 64 | SEC-003 | sanitize_args() defined but never called | `utils.py:63` | CWE-88 / A03:2021 | Function exported in `__init__.py` but grep confirms zero calls in `executor.py` or `runner.py`; LLM fuzz provider args pass unsanitized to subprocess | Skipped | Wire sanitize_args() into executor command-building path | -- | 2026-04-26 | **Open** |
| 4 | High | 60 | SEC-004 | Go stdlib vulns in go 1.24.12 | `runners/go.mod:3`, `loadtest/go/go.mod:3` | CWE-1395 / A06:2021 | Both modules declare `go 1.24.12`; multiple CVEs fixed in 1.24.14+ | Skipped | Update go directive to >= 1.24.14 and rebuild | -- | 2026-04-26 | **Open** |
| 5 | Medium | 48 | SEC-007 | Rust aws-lc-sys 0.37.0 -- 5 advisories | `runners/rust_runner/Cargo.lock:152` | CWE-295 / A06:2021 | `aws-lc-sys 0.37.0` with advisories including X.509 certificate validation bypass | Skipped | `cargo update -p aws-lc-sys` | -- | 2026-06-25 | **Open** |
| 6 | Medium | 36 | SEC-005 | Overly broad pkill pattern | `server.py:60` | CWE-400 / A05:2021 | `subprocess.run(["pkill", "-f", "geode serve"])` can kill unrelated processes matching the pattern | Skipped | Use PID-based cleanup from `_tracked_pids` set instead of pattern match | -- | 2026-06-25 | **Open** |
| 7 | Medium | 36 | SEC-009 | Admin password visible in /proc | `server.py:128` | CWE-214 / A04:2021 | Password set via `env.setdefault("GEODE_ADMIN_PASSWORD", ...)` -- visible in `/proc/PID/environ` on Linux; also potentially in command-line args | Skipped | Pass password via file descriptor, stdin pipe, or temp file with restricted permissions | -- | 2026-06-25 | **Open** |
| 8 | Medium | 32 | SEC-006 | Unpinned pip in Dockerfile | `geodetestlab-cli/Dockerfile:15-16` | CWE-1395 / A06:2021 | `pip install --no-cache-dir --upgrade pip` without version pin; supply chain risk | Skipped | Pin pip version: `pip==24.x` | -- | 2026-06-25 | **Open** |
| 9 | Medium | 24 | SEC-008 | CI_JOB_TOKEN cross-repo cloning without scope restriction | `.gitlab-ci.yml:165,185,259` | CWE-522 / A04:2021 | `CI_JOB_TOKEN` used to clone 3 sibling repos; token scope not restricted in CI config | Skipped | Use scoped project access tokens or restrict CI_JOB_TOKEN allowlist in GitLab project settings | -- | 2026-06-25 | **Open** |
| 10 | Low | 16 | SEC-010 | Dockerfile missing --no-install-recommends | `geodetestlab-cli/Dockerfile:7,24` | CWE-1104 / A06:2021 | Two `apt-get install -y` without `--no-install-recommends`; installs unnecessary packages | Skipped | Add `--no-install-recommends` to both apt-get calls | -- | 2026-09-23 | **Open** |
| 11 | Low | 16 | SEC-011 | No Docker HEALTHCHECK | `geodetestlab-cli/Dockerfile` | CWE-1188 / A05:2021 | No HEALTHCHECK instruction in Dockerfile | Skipped | Add `HEALTHCHECK CMD curl -f http://localhost:PORT/health \|\| exit 1` | -- | 2026-09-23 | **Open** |
| 12 | Low | 12 | SEC-013 | Hardcoded developer path in executor.py | `executor.py:443` | CWE-200 / A01:2021 | Hardcoded path `/home/benji/src/gl/devnw/codepros/geode/geode` as fallback binary location | Skipped | Remove hardcoded path; use GEODE_BINARY env var or error if not found | -- | 2026-09-23 | **Open** |
| 13 | Low | 12 | SEC-012 | pre-commit check-yaml --unsafe flag | `.pre-commit-config.yaml:17` | CWE-502 / A08:2021 | `args: [--unsafe]` allows YAML tags that could be exploited if specs are parsed with unsafe loaders elsewhere | Skipped | Remove `--unsafe` flag; fix any YAML files that rely on custom tags | -- | 2026-09-23 | **Open** |
| 14 | Low | 8 | SEC-014 | SSL verification disabled by default | `executor.py` | CWE-295 / A07:2021 | `GEODE_VERIFY_SSL` defaults to `0`; acceptable for test harness but noted for awareness | Skipped | Already mitigated with debug-level log warning (see #53) | -- | 2026-09-23 | **Open** |
| 15 | Low | 8 | SEC-015 | Temporary directories use default permissions | `executor.py:88` | CWE-732 / A01:2021 | `tempfile.gettempdir()` returns world-readable `/tmp`; setup_files written with default umask | Skipped | Use `tempfile.mkdtemp()` for per-test sandboxes with 0o700 permissions | -- | 2026-09-23 | **Open** |
| 16 | Low | 8 | SEC-016 | Report JSON output path not validated | `cli.py:594` | CWE-22 / A01:2021 | `report_json.parent.mkdir(parents=True)` creates arbitrary directories; `report_json.write_text()` writes to user-specified path without validation | Skipped | Validate output path is within project directory or use `--output-dir` with allowlist | -- | 2026-09-23 | **Open** |
| 17 | Low | 8 | SEC-017 | setup_files sandbox uses string prefix matching | `executor.py:94` | CWE-367 / A01:2021 | `str(resolved).startswith(str(sandbox_root))` is bypassable via symlinks; e.g., `/tmp -> /etc/tmp` prefix match | Skipped | Use `resolved.relative_to(sandbox_root)` (raises ValueError on escape) instead of string prefix | -- | 2026-09-23 | **Open** |
| 18 | Info | 4 | SEC-018 | YAML SafeLoader correctly used | Multiple | -- | All YAML loading uses `yaml.safe_load()` | N/A | No action needed | -- | Backlog | **Closed** |
| 19 | Info | 4 | SEC-019 | Test credential design is intentional | `runner_types.py` | -- | `DEFAULT_ADMIN_PASSWORD` centralized; intentional for test harness | N/A | No action needed | -- | Backlog | **Closed** |

---

## Findings by Area

### Supply Chain (4 findings)

| SEC-ID | Finding | Severity | Risk | Status |
|--------|---------|----------|------|--------|
| SEC-001 | CVE-2026-33186 gRPC auth bypass in grpc v1.75.1 | Critical | 100 | **Open** |
| SEC-004 | Go stdlib vulnerabilities in go 1.24.12 | High | 60 | **Open** |
| SEC-006 | Unpinned pip in Dockerfile | Medium | 32 | **Open** |
| SEC-007 | Rust aws-lc-sys 0.37.0 -- 5 advisories | Medium | 48 | **Open** |

### Application Security (3 findings)

| SEC-ID | Finding | Severity | Risk | Status |
|--------|---------|----------|------|--------|
| SEC-002 | Arbitrary file read via source:file secret resolution | High | 80 | **Open** |
| SEC-003 | sanitize_args() defined but never called | High | 64 | **Open** |
| SEC-017 | setup_files sandbox string prefix bypass | Low | 8 | **Open** |

### CI/CD and Infrastructure (2 findings)

| SEC-ID | Finding | Severity | Risk | Status |
|--------|---------|----------|------|--------|
| SEC-008 | CI_JOB_TOKEN cross-repo cloning without scope restriction | Medium | 24 | **Open** |
| SEC-009 | Admin password visible in /proc | Medium | 36 | **Open** |

### Container Hardening (3 findings)

| SEC-ID | Finding | Severity | Risk | Status |
|--------|---------|----------|------|--------|
| SEC-010 | Dockerfile missing --no-install-recommends | Low | 16 | **Open** |
| SEC-011 | No Docker HEALTHCHECK | Low | 16 | **Open** |
| SEC-013 | Hardcoded developer path | Low | 12 | **Open** |

### Operational Hardening (5 findings)

| SEC-ID | Finding | Severity | Risk | Status |
|--------|---------|----------|------|--------|
| SEC-005 | Overly broad pkill pattern | Medium | 36 | **Open** |
| SEC-012 | pre-commit check-yaml --unsafe | Low | 12 | **Open** |
| SEC-014 | SSL verification disabled by default | Low | 8 | **Open** |
| SEC-015 | Temp directories default permissions | Low | 8 | **Open** |
| SEC-016 | Report JSON output path not validated | Low | 8 | **Open** |

### Positive Findings (2 info items)

| SEC-ID | Finding | Status |
|--------|---------|--------|
| SEC-018 | YAML SafeLoader correctly used throughout | **Closed** |
| SEC-019 | Test credential design is intentional and documented | **Closed** |

---

## Risk Score Methodology

```text
Risk Score = Impact (1-5) x Likelihood (1-5) x 4
```

### Score Breakdown

| SEC-ID | Impact | Likelihood | Score | Reasoning |
|--------|--------|------------|-------|-----------|
| SEC-001 | 5 (auth bypass) | 5 (pre-auth, remote, public CVE) | 100 | Known CVE with public details; grpc is internet-facing protocol |
| SEC-002 | 4 (credential/file read) | 4 (remote, requires spec authoring) | 80 | Attacker with spec write access reads arbitrary files including /etc/shadow |
| SEC-003 | 4 (command injection) | 4 (requires LLM fuzz mode) | 64 | LLM-generated args bypass sanitization; constrained by fuzz mode activation |
| SEC-004 | 4 (multiple CVEs) | 3 (requires Go runner usage) | 60 | Multiple stdlib CVEs; exploitation requires running Go-based tests |
| SEC-007 | 3 (X.509 bypass) | 4 (remote, constrained) | 48 | Certificate validation bypass in Rust TLS; constrained to Rust runner |
| SEC-005 | 2 (DoS/disruption) | 4 (trivially triggerable) | 36 | pkill pattern match could kill unrelated processes on shared hosts |
| SEC-009 | 4 (credential exposure) | 2 (requires /proc access) | 36 | Password in environment; requires local access to read /proc |
| SEC-006 | 3 (supply chain) | 2 (rare, requires MITM) | 32 | Unpinned pip could be hijacked but requires active MITM or registry compromise |
| SEC-008 | 3 (scope escalation) | 2 (CI-only, internal) | 24 | Token scoping is a GitLab project setting, not code-level |
| SEC-010 | 1 (hardening) | 4 (always present) | 16 | Unnecessary packages increase attack surface |
| SEC-011 | 1 (hardening) | 4 (always present) | 16 | Missing healthcheck delays failure detection |
| SEC-012 | 2 (YAML exploit) | 1 (theoretical) | 12 | --unsafe flag only matters if unsafe loaders used elsewhere (they are not) |
| SEC-013 | 2 (info disclosure) | 1 (requires source access) | 12 | Leaks developer username/path structure in source |
| SEC-014 | 2 (MITM) | 1 (test harness only) | 8 | Acceptable for test infrastructure; already has debug warning |
| SEC-015 | 2 (file access) | 1 (multi-tenant only) | 8 | Only exploitable on shared systems with malicious local users |
| SEC-016 | 2 (path traversal) | 1 (requires CLI access) | 8 | User already has CLI access; low additional risk |
| SEC-017 | 2 (sandbox escape) | 1 (requires symlink setup) | 8 | Requires pre-existing symlink at /tmp; theoretical |
| SEC-018 | 0 (positive) | 0 | 4 | No action needed |
| SEC-019 | 0 (positive) | 0 | 4 | No action needed |

---

## Remediation Roadmap

### Quick Wins (< 1 day effort)

| SEC-ID | Task | Estimated Effort |
|--------|------|------------------|
| SEC-001 | `go get google.golang.org/grpc@v1.79.3` in both go.mod files, then `go mod tidy` | 15 min |
| SEC-004 | Update `go 1.24.12` directive to `go 1.24.14` in both go.mod files | 15 min |
| SEC-007 | `cargo update -p aws-lc-sys` in runners/rust_runner | 15 min |
| SEC-010 | Add `--no-install-recommends` to Dockerfile apt-get lines | 5 min |
| SEC-011 | Add HEALTHCHECK instruction to Dockerfile | 10 min |
| SEC-013 | Remove hardcoded `/home/benji/...` path from executor.py:443 | 5 min |
| SEC-006 | Pin pip version in Dockerfile: `pip==24.3.1` | 5 min |

### Medium Effort (1-5 days)

| SEC-ID | Task | Estimated Effort |
|--------|------|------------------|
| SEC-002 | Add path allowlist to source:file secret resolution in utils.py | 2 hours |
| SEC-003 | Wire `sanitize_args()` into executor command-building pipeline | 4 hours |
| SEC-005 | Replace pkill pattern with PID-based cleanup using _tracked_pids | 2 hours |
| SEC-009 | Pass admin password via file descriptor or stdin pipe instead of env/args | 4 hours |
| SEC-012 | Remove `--unsafe` from pre-commit check-yaml args | 30 min |
| SEC-015 | Use `tempfile.mkdtemp()` with 0o700 instead of gettempdir() | 1 hour |
| SEC-017 | Replace `str.startswith()` with `Path.relative_to()` in setup_files sandbox | 30 min |

### Strategic (> 5 days)

| SEC-ID | Task | Estimated Effort |
|--------|------|------------------|
| SEC-008 | Restrict CI_JOB_TOKEN scope via GitLab project settings; evaluate project access tokens | 1-2 days (cross-project coordination) |
| SEC-016 | Implement output path validation with configurable allowlist | 1 day |

---

## How to Verify Each Finding

| SEC-ID | Verification Method |
|--------|---------------------|
| SEC-001 | Run `govulncheck` against runners/ and loadtest/go/; confirm CVE-2026-33186 no longer reported |
| SEC-002 | Create a test spec with `secrets: {test: {source: file, key: /etc/passwd}}`; confirm path validation rejects it |
| SEC-003 | Grep for `sanitize_args` calls in executor.py/runner.py; confirm it is called before subprocess invocation |
| SEC-004 | Check `go version` in CI output; confirm >= 1.24.14 |
| SEC-005 | Run tests with other processes named "geode serve" running; confirm they are not killed |
| SEC-006 | Check Dockerfile for pinned pip version |
| SEC-007 | Run `cargo audit` in runners/rust_runner; confirm no aws-lc-sys advisories |
| SEC-008 | Review GitLab project CI/CD settings for token scope restrictions |
| SEC-009 | Run a test, then inspect `/proc/<geode_pid>/environ` for GEODE_ADMIN_PASSWORD |
| SEC-010 | Check Dockerfile for --no-install-recommends |
| SEC-011 | Run `docker inspect` on built image; confirm HEALTHCHECK is set |
| SEC-012 | Check `.pre-commit-config.yaml` for `--unsafe` flag removal |
| SEC-013 | Grep executor.py for `/home/benji`; confirm removed |
| SEC-014 | Existing debug log warning sufficient; no further action |
| SEC-015 | Check executor.py for `mkdtemp()` usage with restricted permissions |
| SEC-016 | Attempt to write report JSON to a path outside the project; confirm it is rejected |
| SEC-017 | Create a symlink `/tmp/escape -> /etc` and test setup_files; confirm sandbox catches it |

---

## Relationship to Previous Reviews

This Phase 3 review builds on the Phase 1-2 findings tracked in [GAP_ANALYSIS.md](./GAP_ANALYSIS.md):

- **Previously closed**: 45 gaps across 4 sessions (issues #19-62)
- **Won't Do**: #55 (Dockerfile pinning) and #59 (Python lockfile) -- organizational policy
- **New in Phase 3**: 17 open findings (SEC-001 through SEC-017), 2 info/closed (SEC-018, SEC-019)
- **Overlap**: SEC-010/SEC-011 overlap with #55 (won't do) but are tracked separately here with specific remediation. SEC-014 overlaps with #53 (already mitigated with debug warning).

### Blockers and Unknowns

1. **SEC-001 confirmation**: Need to verify CVE-2026-33186 affects the specific grpc usage patterns in the Go runner. Would confirm with `govulncheck ./...` from runners/ directory.
2. **SEC-008 scope**: CI_JOB_TOKEN scope restriction is a GitLab project setting, not a code change. Requires project maintainer access to verify/configure.
3. **SEC-003 scope**: Need to trace all code paths where LLM fuzz provider outputs feed into subprocess commands to confirm full coverage of sanitize_args integration.
4. **Snyk**: Still not run (requires authentication). Would provide additional SCA coverage.
5. **npm audit**: Not run for Node.js runner dependencies.

---

## Analysis Metadata

**Analysis Date:** 2026-03-27
**Analyzed By:** Claude Code (Phase 3 adversarial security review + scoring agent)
**Repository State:** 183a95d (main). 17 open security findings, 2 info/closed.
**Scoring Framework:** Impact(1-5) x Likelihood(1-5) x 4 = Risk Score (0-100)
**SLA Policy:** Critical: 7d, High: 30d, Medium: 90d, Low: 180d, Info: Backlog
