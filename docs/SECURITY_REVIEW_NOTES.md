# Security Review Notes

> **Review Date:** 2026-02-13
> **Reviewer:** Claude Code (adversarial security review agent)
> **Repository:** devnw/codepros/geode/geode-test-harness
> **Commit:** 7c94957 (main)
> **Previous Review:** 2026-02-09 (d45ba18)

## Scanner Versions

| Tool | Version | Available | Ran | Notes |
|------|---------|-----------|-----|-------|
| gitleaks | 8.30.0 | Yes | Yes | 0 leaks (allowlist effective) |
| trufflehog | 3.92.5 | Yes | Yes | Clean |
| semgrep | 1.150.0 | Yes | Yes | 2 findings (1 injection, 1 false-positive token) |
| bandit | 1.9.3 | Yes | Yes | Multiple findings in scripts/ |
| shellcheck | 0.10.0 | Yes | Yes | 20 findings (info/warning/error) |
| hadolint | 2.14.0 | Yes | Yes | 5 findings (DL3008, DL3013, DL3015) |
| trivy | 0.69.0 | Yes | Yes | protobuf CVEs, Dockerfile misconfigs |
| osv-scanner | 2.3.2 | Yes | Yes | Go/Rust dep vulnerabilities |
| grype | 0.107.0 | Yes | Yes | protobuf, quic-go, x/crypto, x/net |
| syft | 1.41.1 | Yes | Yes | SBOM generated at /tmp/sbom.cdx.json |
| checkov | 3.2.499 | Yes | Yes | JSON output malformed, trivy-config used instead |
| safety | 3.7.0 | Yes | Yes | Exit 2 (older CLI format) |
| cargo-audit | 0.22.0 | Yes | Yes | Exit 1 (findings) |
| govulncheck | go1.25.6 | Yes | Attempted | Requires runners/ as Go module root |
| snyk | 1.1302.1 | Yes | Not run | Requires auth; documented as blocker |

## Scan Results Summary

### Gitleaks: CLEAN

0 findings. `.gitleaks.toml` allowlist rules working correctly.

### Semgrep: 2 Findings

| Rule | Severity | File | Description |
|------|----------|------|-------------|
| dangerous-subprocess-use-tainted-env-args | ERROR | executor.py:208 | subprocess.run with user-controlled data |
| detected-google-oauth-access-token | ERROR | fle_large_data_stress_verification.yml:148 | False positive: test fixture data |

### Bandit: Key Findings

| ID | Severity | File | Description |
|----|----------|------|-------------|
| B602 | HIGH | scripts/fuzz_go.py:10,31 | shell=True subprocess |
| B602 | HIGH | scripts/tag.py:9 | shell=True subprocess |
| B602 | HIGH | scripts/test/debug_subprocess.py:12 | shell=True subprocess |
| B602 | HIGH | scripts/test/extended_test_runner.py:338 | shell=True subprocess |
| B105 | LOW | scripts/test/extended_test_runner.py:1165,1167 | Hardcoded test password |
| B108 | MEDIUM | scripts/test/extended_test_runner.py:155,1173,1211 | Insecure temp usage |

### Trivy: Vulnerability Findings

| Severity | CVE | Package | Version | Fixed |
|----------|-----|---------|---------|-------|
| HIGH | CVE-2025-4565 | protobuf | 4.25.1 | 4.25.8+ |
| HIGH | CVE-2026-0994 | protobuf | 4.25.1 | 5.29.6+ |

### Trivy Config: Dockerfile Misconfigs

| Severity | ID | Description |
|----------|-----|-------------|
| HIGH | DS-0029 | apt-get missing --no-install-recommends (2x) |
| LOW | DS-0026 | No HEALTHCHECK defined |

### Grype (via SBOM): Vulnerability Findings

| Severity | CVE | Package | Fixed |
|----------|-----|---------|-------|
| CRITICAL | CVE-2024-45337 | golang.org/x/crypto v0.26.0 | v0.31.0+ |
| HIGH | CVE-2025-22869 | golang.org/x/crypto v0.26.0 | v0.35.0+ |
| HIGH | CVE-2025-59530 | quic-go v0.54.0 | v0.54.1+ |
| MEDIUM | CVE-2025-47914 | golang.org/x/crypto v0.26.0 | v0.45.0+ |
| MEDIUM | CVE-2025-58181 | golang.org/x/crypto v0.26.0 | v0.45.0+ |
| MEDIUM | CVE-2025-22870 | golang.org/x/net v0.28.0 | v0.36.0+ |
| MEDIUM | CVE-2025-22872 | golang.org/x/net v0.28.0 | v0.38.0+ |
| MEDIUM | CVE-2025-64702 | quic-go v0.54.0 | v0.57.0+ |

### OSV-Scanner: Additional Findings

| ID | Package | Version | Fixed |
|----|---------|---------|-------|
| GHSA-434x-w66g-qw3r | bytes (Rust) | 1.11.0 | 1.11.1+ |
| GHSA-j5w8-q4qc-rx2x | golang.org/x/crypto | v0.43.0 | v0.45.0+ |
| GHSA-g754-hx8w-x2g6 | quic-go | v0.55.0 | v0.57.0+ |
| GHSA-f6x5-jh6r-wrfv | golang.org/x/crypto | v0.43.0 | v0.45.0+ |

## Threat Model Snapshot

### Assets

- Test infrastructure (CI runners, Docker containers)
- CI/CD secrets (GITLAB_TOKEN, CI_JOB_TOKEN, CI_REGISTRY_AUTH)
- Source code and test specifications (YAML)
- Build artifacts (compiled runners for Zig, Go, Rust)
- OpenAI API key (if LLM fuzzing enabled)

### Trust Boundaries

1. YAML specs to executor: Specs are user-authored, executed by runner with system privileges
2. CI pipeline to build env: Downloaded tools run with CI runner privileges
3. Package managers to deps: Dependencies fetched without hash verification
4. Docker Hub to base images: Container images with pinned tags (good)
5. LLM provider to test generation: API responses parsed and potentially executed

### Attacker Types

- Spec author (insider): Can inject commands via command, pre_server, setup_files fields
- Supply chain: Can compromise deps, Docker images, or CI tools
- Network (MITM): Can intercept unverified HTTP/SSL connections
- CI pipeline attacker: Can leverage allow_failure to bypass security gates

## Positive Findings

- All YAML loading uses yaml.safe_load() (no unsafe deserialization)
- No dangerous dynamic code patterns in main codebase
- No SQL injection vectors (parameterized client libraries)
- Most subprocess calls use list form (shell=False)
- Port validation has min/max ranges in Typer CLI
- Subprocess calls have timeouts
- TLS/crypto deferred to client libraries
- Dockerfile runs as non-root user (USER geodetest)
- Pre-commit hooks configured with version pinning
- No .env files tracked in git
- Gitleaks allowlist properly configured for test data
- CI download checksums verified (Zig, glab)
- Docker base images pinned to specific tags
- shlex.split() used for pre_server commands (mitigates shell injection)

## Blockers and Unknowns

1. Snyk not run (requires authentication)
2. govulncheck (requires cd runners context)
3. No DAST (network-facing services not tested)
4. npm audit not run for Node.js runner dependencies
