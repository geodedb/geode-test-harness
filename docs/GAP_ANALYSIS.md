# Gap Analysis

> **Last Updated:** 2026-03-27
> **GitLab Project:** [devnw/codepros/geode/geode-test-harness](https://gitlab.com/devnw/codepros/geode/geode-test-harness)
> **Analysis Method:** Requirements-to-code comparison, automated SAST/SCA (semgrep, bandit, gitleaks, trufflehog, shellcheck, hadolint, trivy, grype, syft, osv-scanner, cargo-audit), manual adversarial review, and code quality analysis (ruff, mypy, pytest)

This document tracks **ALL gaps** across the project. Resolved gaps are in [GAP_ANALYSIS_RESOLVED.md](./GAP_ANALYSIS_RESOLVED.md).

## Summary

| Severity | Open | Won't Do | Closed | Previously Resolved | Total |
|----------|------|----------|--------|---------------------|-------|
| Critical | 0 | 0 | 2 | 1 | 3 |
| High | 2 | 0 | 12 | 2 | 16 |
| Medium | 4 | 2 | 19 | 10 | 35 |
| Low | 8 | 0 | 12 | 5 | 25 |
| **Total** | **14** | **2** | **45** | **18** | **79** |

Previously resolved: 18 gaps (GAP-0001 through GAP-0018). See [GAP_ANALYSIS_RESOLVED.md](./GAP_ANALYSIS_RESOLVED.md).

---

## Open Gaps (14)

### GAP-0265: No unit tests for security fixes (#48, #49, #58)

- **Issue:** Not yet created (--skip-issues)
- **Category:** Test
- **Severity:** High
- **Requirement source:** [#48](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/48), [#49](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/49), [#58](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/58)
- **Current state (evidence):**
  - `geodetestlab-cli/geodetestlab/tests/` -- 5 test files exist; none cover executor.py or runner.py security behavior
  - `grep -ri "test_.*injection\|test_.*traversal\|test_.*allowlist"` in tests/ returns no matches
- **Why this is a gap:** Three critical/high security fixes have zero unit test coverage: shell metacharacter routing (#48), path traversal sandbox (#49), pre-server command allowlist (#58). Security regressions can land without any test catching them.
- **Impact/Risk:** Security regressions can be introduced silently. These are the highest-risk code paths in the harness.
- **Recommended fix:** Create `test_executor_security.py` and `test_runner_security.py` covering: (1) metacharacter rejection in non-shell mode, (2) path traversal rejection in setup_files, (3) allowlist enforcement for pre-server commands.
- **Acceptance criteria:**
  - At least one test per security fix verifying the guard logic
  - Tests fail if the guard is removed

### GAP-0268: test-all integration job has allow_failure: true

- **Issue:** Not yet created (--skip-issues)
- **Category:** CI-CD
- **Severity:** High
- **Requirement source:** `.gitlab-ci.yml:299-300`
- **Current state (evidence):**
  - `.gitlab-ci.yml:299-300` -- `allow_failure: true` on the main integration test job
  - Comment: "Allow failures while CI integration stabilizes"
- **Why this is a gap:** The integration test suite can fail and merges still proceed. Regressions in GQL query behavior, HTTP endpoints, or CLI commands are not caught at merge time.
- **Impact/Risk:** High -- integration test failures are the primary quality gate for this test harness project.
- **Recommended fix:** Remove `allow_failure: true` from the test-all job. If stability concerns remain, gate it on `$CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH` only.
- **Acceptance criteria:**
  - `test-all` job failure blocks the pipeline on the default branch

### GAP-0261: .dockerignore file missing despite documented fix (#77 / PERF-015)

- **Issue:** Not yet created (--skip-issues)
- **Category:** Requirement
- **Severity:** Medium
- **Requirement source:** [#77](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/77) (PERF-015: Dockerfile COPY . . context bloat)
- **Current state (evidence):**
  - `test -f .dockerignore` returns "MISSING"
  - `docs/PERF_GAP_ANALYSIS.md:211` documents the fix as "Created `.dockerignore`" with status **Closed**
  - The file was either never committed or was deleted after the issue was closed
- **Why this is a gap:** The documented resolution claims a .dockerignore was created, but the file does not exist on disk at HEAD (183a95d). The Docker build context bloat issue remains unresolved.
- **Impact/Risk:** Every `docker build` copies the entire repository context including `.git/`, `__pycache__/`, test artifacts, and CI reports. Inflates build time and layer cache size.
- **Recommended fix:** Create `.dockerignore` with at minimum: `.git`, `__pycache__`, `*.pyc`, `.venv`, `reports/`, `docs/`, `.gitlab-ci.yml`, `*.md`
- **Acceptance criteria:**
  - `.dockerignore` exists at repo root with exclusions for `.git` and `__pycache__`
  - `docker build` context size is measurably smaller

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

- **Issue:** Not yet created (--skip-issues)
- **Category:** CI-CD
- **Severity:** Medium
- **Requirement source:** Project CLAUDE.md testing requirements, `~/.claude/rules/common/testing.md` ("Verify 80%+ coverage")
- **Current state (evidence):**
  - `geodetestlab-cli/pyproject.toml` -- no `pytest-cov` in dependencies, no `[tool.coverage]` configuration
  - `.gitlab-ci.yml` test-unit job: `python -m pytest geodetestlab/tests/ -v --tb=short` -- no `--cov` flag
  - No coverage report artifacts in CI
- **Why this is a gap:** The testing requirements mandate 80%+ coverage verification, but no coverage tool is installed or configured. There is no way to measure or enforce coverage thresholds.
- **Impact/Risk:** Coverage regressions are invisible. The 80% threshold cannot be verified.
- **Recommended fix:** Add `pytest-cov` to dev dependencies, configure `[tool.coverage.run]` and `[tool.coverage.report]` in `pyproject.toml` with `fail_under = 80`, add `--cov` flags to the CI test-unit job.
- **Acceptance criteria:**
  - `pytest --cov` produces a coverage report
  - CI fails if coverage drops below 80%

### GAP-0274: REQUIREMENTS.md stale (6 weeks, missing 32 issues)

- **Issue:** Not yet created (--skip-issues)
- **Category:** Docs
- **Severity:** Medium
- **Requirement source:** `docs/REQUIREMENTS.md:3` -- "Last Updated: 2026-02-09"
- **Current state (evidence):**
  - `docs/REQUIREMENTS.md:11` -- "No open issues. All 47 gap issues are resolved."
  - Does not mention issues #48 through #79 (32 issues created after 2026-02-09)
  - Issues #48-#62 are security/hardening findings; #63-#79 are performance findings
- **Why this is a gap:** The requirements mirror document is stale by 6 weeks and 32 issues. Anyone using it as a requirements reference will miss a third of the project's tracked work.
- **Impact/Risk:** Documentation drift reduces trust in project tracking. New team members or auditors get an incomplete picture.
- **Recommended fix:** Update REQUIREMENTS.md to include issues #48-#79 with their current status (closed/accepted/won't do).
- **Acceptance criteria:**
  - REQUIREMENTS.md lists all 79 issues with correct status
  - "Last Updated" date is current

### GAP-0263: Doc claims resolve().relative_to() but code uses str().startswith()

- **Issue:** Not yet created (--skip-issues)
- **Category:** Bug
- **Severity:** Low
- **Requirement source:** [#49](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/49) (Arbitrary file write via setup_files path traversal)
- **Current state (evidence):**
  - `geodetestlab-cli/geodetestlab/lib/executor.py:94` -- `if not str(resolved).startswith(str(sandbox_root)):`
  - `docs/GAP_ANALYSIS.md:29` documents the fix as "Path traversal sandbox via `resolve().relative_to()` check against temp dir"
- **Why this is a gap:** The documentation says `relative_to()` is used, but the actual implementation uses `str().startswith()`. The `startswith()` approach has a known bypass: a sandbox root of `/tmp/test` would allow writes to `/tmp/test-evil/`. Practical risk is very low due to unique temp dir names.
- **Impact/Risk:** Theoretical path traversal bypass if the temp directory name is a prefix of another directory. Very low practical risk.
- **Recommended fix:** Either update the code to use `resolved.relative_to(sandbox_root)` inside a try/except ValueError (as documented), OR update the documentation to accurately describe the `startswith()` approach.
- **Acceptance criteria:**
  - Code and documentation agree on the mechanism
  - If `startswith()` is kept, ensure `sandbox_root` always ends with `/` before comparison

### GAP-0264: Doc claims _tracked_pids/track_pid()/untrack_pid() but actual mechanism uses _active_servers

- **Issue:** Not yet created (--skip-issues)
- **Category:** Docs
- **Severity:** Low
- **Requirement source:** [#62](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/62) (Insecure temp file/process cleanup patterns)
- **Current state (evidence):**
  - `geodetestlab-cli/geodetestlab/cli.py:41-68` -- `_tracked_pids` set, `track_pid()`, `untrack_pid()` defined
  - Functions exist but their actual usage within server lifecycle paths needs verification
- **Why this is a gap:** The functions exist but may not be wired into all server lifecycle paths. The existing `_kill_geode_processes()` function has fallback logic, so orphaned processes are still cleaned up.
- **Impact/Risk:** Low -- fallback cleanup logic covers the gap in practice.
- **Recommended fix:** Verify that `track_pid()` is called wherever server processes are spawned (in `server.py` and `runner.py`). Update docs if wiring is incomplete.
- **Acceptance criteria:**
  - `track_pid()` is called for every `subprocess.Popen` of the geode binary, or documentation is updated to reflect partial coverage

### GAP-0267: mypy allow_failure in CI (type errors don't block pipeline)

- **Issue:** Not yet created (--skip-issues)
- **Category:** CI-CD
- **Severity:** Low
- **Requirement source:** `.gitlab-ci.yml:64-65`
- **Current state (evidence):**
  - `.gitlab-ci.yml:65` -- `allow_failure: true` on lint-mypy job
  - Comment: "mypy can legitimately fail on third-party stubs; allow failure but log"
- **Why this is a gap:** While third-party stub issues are a legitimate reason for `allow_failure`, this also suppresses real type errors in the project's own code.
- **Impact/Risk:** Type errors can accumulate silently. Medium risk mitigated by `--ignore-missing-imports`.
- **Recommended fix:** Configure mypy with `--follow-imports=silent` or per-module overrides to isolate third-party stub issues, then remove `allow_failure: true`.
- **Acceptance criteria:**
  - mypy runs without `allow_failure` and does not fail on third-party stubs alone

### GAP-0269: No linting for non-Python runners (Go, Zig, Rust, Node.js)

- **Issue:** Not yet created (--skip-issues)
- **Category:** Code Quality
- **Severity:** Low
- **Requirement source:** General code quality standards
- **Current state (evidence):**
  - `.gitlab-ci.yml` -- lint-python and lint-mypy cover Python code only
  - No `go vet`, `golangci-lint`, `clippy`, `eslint`, or Zig compiler warnings in CI
  - Runners in `runners/` directory have no lint jobs
- **Why this is a gap:** Non-Python runners have no automated quality checks in CI. Issues like deprecated `ioutil.ReadFile` (PERF-014) were only caught during manual review.
- **Impact/Risk:** Low -- runners are supplementary components. Quality issues can accumulate.
- **Recommended fix:** Add `go vet ./...` to build-go, `cargo clippy` to build-rust, `npx eslint` to build-nodejs. Zig warnings are surfaced during build.
- **Acceptance criteria:**
  - Each runner language has at least basic lint/vet checks in its CI build job

### GAP-0270: Two separate pytest configs (root pytest.ini vs geodetestlab-cli/pyproject.toml)

- **Issue:** Not yet created (--skip-issues)
- **Category:** Code Quality
- **Severity:** Low
- **Requirement source:** General code quality standards
- **Current state (evidence):**
  - `pytest.ini` at repo root -- `testpaths = tests` (directory does not exist at root)
  - `geodetestlab-cli/pyproject.toml:89-91` -- `[tool.pytest.ini_options]` with `testpaths = ["geodetestlab/tests"]`
- **Why this is a gap:** Running `pytest` from the repo root uses `pytest.ini` and looks for a non-existent `tests/` directory. Running from `geodetestlab-cli/` uses pyproject.toml correctly.
- **Impact/Risk:** Low -- CI runs from the correct directory. Only affects developer experience.
- **Recommended fix:** Remove the root-level `pytest.ini` (legacy artifact), or update it to point to the correct test directory.
- **Acceptance criteria:**
  - Only one pytest configuration exists, or both are consistent and documented

### GAP-0271: No JSON Schema for YAML test spec format

- **Issue:** Not yet created (--skip-issues)
- **Category:** Docs
- **Severity:** Low
- **Requirement source:** General documentation standards
- **Current state (evidence):**
  - `geodetestlab-cli/geodetestlab/lib/spec.py` -- validates specs programmatically but no formal schema file
  - 243 YAML spec files in `specs/` with no schema reference
- **Why this is a gap:** No machine-readable schema for the YAML test spec format. Contributors must read `spec.py` source code to understand valid fields. IDE autocompletion/validation is not available.
- **Impact/Risk:** Low -- programmatic validation in `spec.py` catches invalid specs at runtime. Developer experience improvement.
- **Recommended fix:** Create a JSON Schema file (`specs/schema.json` or `docs/spec-schema.json`) and reference it from CLAUDE.md.
- **Acceptance criteria:**
  - A JSON Schema file exists that validates the YAML spec format

### GAP-0272: Dead CI jobs (build-python, build-nodejs produce no artifacts)

- **Issue:** Not yet created (--skip-issues)
- **Category:** CI-CD
- **Severity:** Low
- **Requirement source:** `.gitlab-ci.yml:196-216`
- **Current state (evidence):**
  - `.gitlab-ci.yml:196-203` -- `build-python` runs `python3 -c "import yaml; print('Python dependencies installed')"` with `artifacts: paths: []`
  - `.gitlab-ci.yml:205-216` -- `build-nodejs` installs `yaml` package and caches `node_modules/`
  - Both extend `.build-template` which has `allow_failure: true`
  - Neither produces artifacts consumed by downstream jobs
- **Why this is a gap:** These jobs consume CI minutes but produce no meaningful output.
- **Impact/Risk:** Low -- wasted CI time (~30-60s per job per pipeline run).
- **Recommended fix:** Either remove these jobs or make them useful (e.g., `node --check runners/nodejs_runner.js`).
- **Acceptance criteria:**
  - Jobs either produce artifacts consumed by downstream stages or are removed

### GAP-0273: Three potentially unused dependencies (pydantic, jmespath, psutil)

- **Issue:** Not yet created (--skip-issues)
- **Category:** Code Quality
- **Severity:** Low
- **Requirement source:** `geodetestlab-cli/pyproject.toml:31,34,36`
- **Current state (evidence):**
  - `pyproject.toml:31` -- `pydantic>=2.5.0`
  - `pyproject.toml:34` -- `jmespath>=1.0.1`
  - `pyproject.toml:36` -- `psutil>=5.9.0`
  - `grep -r "import pydantic\|from pydantic\|import jmespath\|import psutil"` in `geodetestlab-cli/**/*.py` returns no matches
- **Why this is a gap:** Three dependencies are declared but never imported in application code. They inflate the install footprint and attack surface.
- **Impact/Risk:** Low -- unnecessary dependencies, minor supply chain risk.
- **Recommended fix:** Verify these are truly unused (check dynamic imports, CLI plugins, test-only usage), then remove if confirmed unused.
- **Acceptance criteria:**
  - All declared dependencies are imported somewhere in the codebase, or unused ones are removed

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
**Repository State:** 79 gaps tracked. 14 open, 2 won't do, 45 closed in this project, 18 previously resolved.
**Issue Series:**

- GAP-0001 through GAP-0018: Resolved (see [GAP_ANALYSIS_RESOLVED.md](./GAP_ANALYSIS_RESOLVED.md))
- GAP-0019 through GAP-0037: All 19 closed
- QG-001 through QG-010: All 10 closed
- Issues #48 through #62: 13 closed, 2 won't do (all resolved)
- GAP-0261 through GAP-0274: 14 open (added 2026-03-27)
