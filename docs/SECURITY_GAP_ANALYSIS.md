# Security Gap Analysis

> **Last Updated:** 2026-03-27
> **Review Phase:** Phase 3 (adversarial security review) + post-closure verification + gap closure
> **Reviewer:** Claude Code (security scoring agent)
> **Repository:** [devnw/codepros/geode/geode-test-harness](https://gitlab.com/devnw/codepros/geode/geode-test-harness)
> **Commit:** 979f487 (main)
> **Previous Review:** 2026-02-13 (see [SECURITY_REVIEW_NOTES.md](./SECURITY_REVIEW_NOTES.md))
> **Mode:** --skip-issues (documentation only, no platform issue creation)

This document tracks security findings from Phase 3 of the adversarial security review. For general gap tracking (quality, CI/CD, requirements), see [GAP_ANALYSIS.md](./GAP_ANALYSIS.md).

---

## Summary

| Severity | Total | Closed | Blocked | Blocked | SLA |
|----------|-------|--------|----------|------|-----|
| Critical | 1 | 1 | 0 | 0 | 7 days |
| High | 3 | 3 | 0 | 0 | 30 days |
| Medium | 5 | 3 | 2 | 0 | 90 days |
| Low | 8 | 7 | 1 | 0 | 180 days |
| Info | 2 | 2 | 0 | 0 | Backlog |
| **Total** | **19** | **16** | **3** | **0** | -- |

### Remaining Blocked Risks

None. All actionable findings are closed.

### Blocked Risks

- **SEC-008** (Medium): CI_JOB_TOKEN scope -- requires GitLab admin, not a code change.
- **SEC-009** (Medium): Admin password in /proc -- accepted for test harness context.
- **SEC-014** (Low): SSL verification disabled -- by design for test harness with debug warning.

---

## Stack-Ranked Findings Table

| Rank | Severity | Risk | SEC-ID | Finding | Status |
|------|----------|------|--------|---------|--------|
| 1 | Critical | 100 | SEC-001 | CVE-2026-33186 gRPC auth bypass | **Closed** -- grpc v1.79.3 (commit `97bde40`) |
| 2 | High | 80 | SEC-002 | Arbitrary file read via source:file | **Closed** -- path allowlist in utils.py (commit `8043c5c`) |
| 3 | High | 64 | SEC-003 | sanitize_args() never called | **Closed** -- wired into executor.py (commit `979f487`) |
| 4 | High | 60 | SEC-004 | Go stdlib vulns in go 1.24.12 | **Closed** -- go 1.25.0 (commit `97bde40`) |
| 5 | Medium | 48 | SEC-007 | Rust aws-lc-sys advisories | **Closed** -- aws-lc-sys 0.39.0 (commit `8a7282e`) |
| 6 | Medium | 36 | SEC-005 | Overly broad pkill pattern | **Closed** -- scoped to "geode serve.*geode-test-" (commit `8043c5c`) |
| 7 | Medium | 36 | SEC-009 | Admin password in /proc | **Blocked** -- test harness context |
| 8 | Medium | 32 | SEC-006 | Unpinned pip in Dockerfile | **Closed** -- pinned pip==24.3.1 (commit `979f487`) |
| 9 | Medium | 24 | SEC-008 | CI_JOB_TOKEN scope | **Blocked** -- requires GitLab admin |
| 10 | Low | 16 | SEC-010 | Dockerfile missing --no-install-recommends | **Closed** -- flag added (commit `4b2a72d`) |
| 11 | Low | 16 | SEC-011 | No Docker HEALTHCHECK | **Closed** -- added (commit `4b2a72d`) |
| 12 | Low | 12 | SEC-013 | Hardcoded developer path | **Closed** -- removed, uses GEODE_SOURCE_DIR (commit `8043c5c`) |
| 13 | Low | 12 | SEC-012 | pre-commit check-yaml --unsafe | **Closed** -- flag removed (commit `e6c5b6c`) |
| 14 | Low | 8 | SEC-014 | SSL verification disabled | **Blocked** -- debug warning exists |
| 15 | Low | 8 | SEC-015 | Temp directories default permissions | **Closed** -- mkdtemp with 0o700 (commit `979f487`) |
| 16 | Low | 8 | SEC-016 | Report JSON output path not validated | **Blocked** -- user already has CLI access |
| 17 | Low | 8 | SEC-017 | setup_files sandbox string prefix bypass | **Closed** -- uses is_relative_to() (commit `8043c5c`) |
| 18 | Info | 4 | SEC-018 | YAML SafeLoader correctly used | **Closed** |
| 19 | Info | 4 | SEC-019 | Test credential design is intentional | **Closed** |

---

## Closed Findings (Gap Closure Session)

### SEC-003: sanitize_args() wired into executor (High, Risk 64) -- Closed

- **Component:** `executor.py`
- **Resolution:** Added `sanitize_args()` call after command building for non-shell test types. ValueError returns a failed TestResult with descriptive error. Commit `979f487`.

### SEC-006: Pip pinned in Dockerfile (Medium, Risk 32) -- Closed

- **Component:** `geodetestlab-cli/Dockerfile:15`
- **Resolution:** Pinned `pip==24.3.1`. Commit `979f487`.

### SEC-015: Temp directories use mkdtemp (Low, Risk 8) -- Closed

- **Component:** `executor.py:101`
- **Resolution:** Replaced `gettempdir()` with `mkdtemp(prefix="geodetestlab_")` + `os.chmod(0o700)` for per-test sandboxes. Commit `979f487`.

---

## Risk Score Methodology

```text
Risk Score = Impact (1-5) x Likelihood (1-5) x 4
```

SLA Policy: Critical 7d, High 30d, Medium 90d, Low 180d, Info Backlog.

---

## Analysis Metadata

**Analysis Date:** 2026-03-27
**Analyzed By:** Claude Code (Phase 3 adversarial security review + scoring agent)
**Repository State:** 979f487 (main). 0 open, 3 accepted, 16 closed.
**Scoring Framework:** Impact(1-5) x Likelihood(1-5) x 4 = Risk Score (0-100)
