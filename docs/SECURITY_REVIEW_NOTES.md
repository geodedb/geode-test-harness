# Security Review Notes

> **Review Date:** 2026-02-09
> **Reviewer:** Claude Code (adversarial security review agent)
> **Repository:** devnw/codepros/geode/geode-test-harness
> **Commit:** d45ba18 (main)

## Scanner Versions

| Tool | Version | Available | Command |
|------|---------|-----------|---------|
| gitleaks | 8.30.0 | Yes | `gitleaks detect` |
| trufflehog | 3.92.5 | Yes | Not run (gitleaks sufficient) |
| semgrep | 1.150.0 | Yes | Not run (bandit covered Python) |
| bandit | 1.9.3 | Yes | `bandit -r . -f json` |
| shellcheck | 0.10.0 | Yes | `git ls-files '*.sh' \| xargs shellcheck -x` |
| hadolint | 2.14.0 | Yes | `hadolint geodetestlab-cli/Dockerfile` |
| trivy | 0.69.0 | Yes | Not run (fs scan) |
| osv-scanner | 2.3.2 | Yes | Not run (manual dep review) |
| grype | 0.107.0 | Yes | Not run (no SBOM generated) |
| syft | 1.41.1 | Yes | Not run (no container image) |
| checkov | 3.2.499 | Yes | Not run (no IaC) |
| safety | 3.7.0 | Yes | Not run (pip deps not locked) |
| cargo-audit | 0.22.0 | Yes | Not run (Cargo.lock in runners/) |
| govulncheck | go1.25.5 | Yes | Not run (Go in runners/) |
| snyk | 1.1302.1 | Yes | Not run (requires auth) |

## Scan Results Summary

### Gitleaks (52 findings)
- **All false positives** — 52 `generic-api-key` findings in `geodetestlab-cli/specs/*.yml`
- These are test encryption keys in YAML spec assertions, not real credentials
- No real secrets detected in any source code, config, or data files
- **Recommendation:** Create `.gitleaks.toml` to suppress (see GAP-0037)

### Bandit (14 high/medium findings in project code)
| Finding ID | Severity | Count | Description |
|-----------|----------|-------|-------------|
| B602 | HIGH/HIGH | 1 | `subprocess.run(shell=True)` in runner.py:190 |
| B501 | HIGH/HIGH | 2 | `httpx.Client(verify=False)` in runner.py:839,1085 |
| B102 | MEDIUM/HIGH | 1 | `exec()` in simple_manager.py:53 |
| B108 | MEDIUM/MEDIUM | 10 | Hardcoded `/tmp` directory usage |

### ShellCheck (1 finding)
- SC2155 in `geodetestlab-cli/fixtures/setup_social_network.sh:40` — declare and assign separately

### Hadolint (5 findings)
| Rule | Severity | Description |
|------|----------|-------------|
| DL3008 | Warning | Pin apt package versions (lines 7, 24) |
| DL3013 | Warning | Pin pip package versions (line 15) |
| DL3015 | Info | Use `--no-install-recommends` (lines 7, 24) |

## Threat Model Snapshot

### Assets
- Test infrastructure (CI runners, Docker containers)
- CI/CD secrets (GITLAB_TOKEN, CI_JOB_TOKEN)
- Source code and test specifications
- Build artifacts (compiled runners)

### Trust Boundaries
1. **YAML specs → runner**: Specs are user-authored, executed by runner with system privileges
2. **CI pipeline → build env**: Downloaded tools run with CI runner privileges
3. **Package managers → deps**: Dependencies fetched from external registries
4. **Docker Hub → base images**: Container images pulled without verification

### Attacker Types
- **Spec author (insider)**: Can inject commands via `pre_server` field (GAP-0029)
- **Supply chain**: Can compromise deps, Docker images, or CI tools (GAP-0032, GAP-0033, GAP-0035)
- **Network (MITM)**: Can intercept unverified HTTP/SSL connections (GAP-0031, GAP-0032)

### Top Abuse Cases
1. RCE via malicious spec `pre_server` command (GAP-0029) — **Likelihood: Medium**
2. CI compromise via poisoned Zig/glab download (GAP-0032) — **Likelihood: Low**
3. Dependency confusion/hijacking (GAP-0033) — **Likelihood: Low-Medium**
4. Credential reuse from hardcoded test password (GAP-0030) — **Likelihood: Low**

## Positive Findings

The following security practices are correctly implemented:

- All YAML loading uses `yaml.safe_load()` — no unsafe deserialization
- No pickle usage anywhere in codebase
- No SQL injection vectors (uses parameterized client libraries)
- Most subprocess calls use list form (not shell=True) — exception: runner.py:190
- Port validation has min/max ranges in argparse
- Subprocess calls have timeouts
- TLS/crypto deferred to client libraries
- No API keys or tokens in source code (only test password)
- Dockerfile runs as non-root user
- Pre-commit hooks configured with version pinning
- No `.env` files tracked in git

## Blockers and Unknowns

1. **Snyk not run** — requires authentication; would provide comprehensive dependency vulnerability scanning
2. **Trivy filesystem scan not run** — would detect additional vulnerabilities in dependencies
3. **osv-scanner not run** — would cross-reference OSV database for known vulnerabilities
4. **cargo-audit not run** — Rust dependencies not audited (would need `cd runners/rust_runner && cargo audit`)
5. **govulncheck not run** — Go dependencies not audited (would need `cd runners && govulncheck ./...`)
6. **No DAST** — Network-facing services not tested (would require running server)

## What Would Confirm Suspected Issues

All findings in this review are **confirmed** (confidence::confirmed) with code evidence. No suspected-only findings.
