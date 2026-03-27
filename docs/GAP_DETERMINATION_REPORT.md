# Gap Determination Report

> **Date:** 2026-03-27
> **Analyst:** Claude Code (gap determination phase)
> **Repository:** /home/benji/src/devnw/codepros/geode/geode-test-harness
> **Branch:** main (commit 183a95d)
> **Prior Gap-ID range:** GAP-0001 through GAP-0260 (all resolved)
> **New Gap-IDs start at:** GAP-0261

## Summary

- **Total requirements analyzed:** 79 GitLab issues + 10 new findings from Phase 2 scan
- **Implemented:** 62 | **Partial:** 4 | **Not Implemented:** 1 | **Won't Do:** 2 | **Accepted:** 5 | **Unknown:** 0
- **New gaps found:** 14
- **Previously open gaps resolved:** 0 (no open gaps existed in GAP_ANALYSIS.md)
- **Total open gaps:** 14

---

## New Gaps

### GAP-0261: .dockerignore file missing despite documented fix (#77 / PERF-015)

- **Category:** Requirement
- **Severity:** Medium
- **Requirement source:** [#77](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/77) (PERF-015: Dockerfile COPY . . context bloat)
- **Current state (evidence):**
  - `test -f .dockerignore` returns "MISSING"
  - `docs/PERF_GAP_ANALYSIS.md:211` documents the fix as "Created `.dockerignore` excluding `.git`, `__pycache__`, `*.pyc`, etc." with status **Closed**
  - The file was either never committed, or was deleted after the issue was closed
- **Why this is a gap:** The documented resolution claims a .dockerignore was created, but the file does not exist on disk at HEAD (183a95d). The Docker build context bloat issue remains unresolved.
- **Impact/Risk:** Every `docker build` copies the entire repository context including `.git/`, `__pycache__/`, test artifacts, and CI reports. This inflates build time and layer cache size.
- **Recommended fix:** Create `.dockerignore` with at minimum: `.git`, `__pycache__`, `*.pyc`, `.venv`, `reports/`, `docs/`, `.gitlab-ci.yml`, `*.md`
- **Acceptance criteria:** `.dockerignore` exists at repo root, contains exclusions for `.git` and `__pycache__`, `docker build` context size is measurably smaller.

---

### GAP-0262: Makefile Docker commands bind to 0.0.0.0 (#54 partial)

- **Category:** Bug
- **Severity:** Medium
- **Requirement source:** [#54](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/54) (Server binds 0.0.0.0 in ServerManager)
- **Current state (evidence):**
  - `Makefile:143` -- `serve --listen 0.0.0.0:3141 --listen-grpc 0.0.0.0:50051 --log-level info`
  - `docs/GAP_ANALYSIS.md:33` documents #54 as **Closed** with fix in `lib/server_manager.py`
  - The `server_manager.py` fix is confirmed (binds 127.0.0.1), but the Makefile `docker-start` target was not updated
- **Why this is a gap:** The Makefile Docker target exposes the Geode server on all network interfaces (0.0.0.0) rather than localhost only. The fix in `server_manager.py` covers the non-Docker path but not the Docker path.
- **Impact/Risk:** When `make docker-start` is run on a machine with a public IP, the test Geode server is accessible from the network. Low real-world risk since this is a test harness, but it contradicts the stated fix for #54.
- **Recommended fix:** Change `Makefile:143` to bind `127.0.0.1:3141` and `127.0.0.1:50051` in the Docker serve command, or use Docker port mapping (`-p 127.0.0.1:3141:3141/udp`) to restrict exposure.
- **Acceptance criteria:** `make docker-start` only exposes ports on 127.0.0.1, verified by `docker inspect` or `ss -uln`/`ss -tln`.

---

### GAP-0263: Path traversal sandbox uses string prefix instead of relative_to() (#49 doc mismatch)

- **Category:** Bug
- **Severity:** Low
- **Requirement source:** [#49](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/49) (Arbitrary file write via setup_files path traversal)
- **Current state (evidence):**
  - `geodetestlab-cli/geodetestlab/lib/executor.py:94` -- `if not str(resolved).startswith(str(sandbox_root)):`
  - `docs/GAP_ANALYSIS.md:29` documents the fix as "Path traversal sandbox via `resolve().relative_to()` check against temp dir"
- **Why this is a gap:** The documentation says `relative_to()` is used, but the actual implementation uses `str().startswith()`. The `startswith()` approach has a known bypass: a sandbox root of `/tmp/test` would allow writes to `/tmp/test-evil/` since the string prefix matches. However, because `Path.resolve()` is called first and sandbox roots are typically unique temp dirs (e.g., `/tmp/tmp_random/`), the practical risk is very low.
- **Impact/Risk:** Theoretical path traversal bypass if the temp directory name is a prefix of another directory. Very low practical risk.
- **Recommended fix:** Either update the code to use `resolved.relative_to(sandbox_root)` inside a try/except ValueError (as documented), OR update the documentation to accurately describe the `startswith()` approach and note why it is sufficient (unique temp dir names).
- **Acceptance criteria:** Code and documentation agree on the mechanism. If `startswith()` is kept, ensure `sandbox_root` always ends with `/` before comparison.

---

### GAP-0264: #62 documentation overstates process cleanup implementation

- **Category:** Docs
- **Severity:** Low
- **Requirement source:** [#62](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/62) (Insecure temp file/process cleanup patterns)
- **Current state (evidence):**
  - `geodetestlab-cli/geodetestlab/cli.py:41-68` -- `_tracked_pids` set, `track_pid()`, `untrack_pid()`, and PID-based cleanup in `_kill_geode_processes()` all exist as documented
  - Documentation is accurate for the PID tracking mechanism
  - However, `track_pid()`/`untrack_pid()` are defined but their actual usage within the codebase needs verification
- **Why this is a gap:** The functions exist but may not be wired into all server lifecycle paths. The documentation claims the fix is complete. This is a minor documentation accuracy issue since the PID tracking infrastructure is in place.
- **Impact/Risk:** Low -- the existing `_kill_geode_processes()` function already has fallback logic to find and kill geode processes by name, so orphaned processes are still cleaned up.
- **Recommended fix:** Verify that `track_pid()` is called wherever server processes are spawned (in `server.py` and `runner.py`). Update docs if wiring is incomplete.
- **Acceptance criteria:** `track_pid()` is called for every `subprocess.Popen` of the geode binary, or documentation is updated to reflect partial coverage.

---

### GAP-0265: No unit tests for security fixes (#48, #49, #58)

- **Category:** Test
- **Severity:** High
- **Requirement source:** [#48](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/48), [#49](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/49), [#58](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/58)
- **Current state (evidence):**
  - `geodetestlab-cli/geodetestlab/tests/` contains 5 test files: `test_assertions.py`, `test_cli.py`, `test_providers.py`, `test_spec_validation.py`, `test_utils.py`
  - `grep -ri "test_.*metachar\|test_.*sandbox\|test_.*allowlist\|test_.*injection\|test_.*traversal\|test_.*pre_server"` in tests/ returns **no matches**
  - No test file for `executor.py` or `runner.py` security behavior
- **Why this is a gap:** Three critical/high security fixes have zero unit test coverage:
  1. Shell metacharacter routing (#48) -- no test verifying that non-shell commands reject metacharacters
  2. Path traversal sandbox (#49) -- no test verifying that `../` paths are rejected
  3. Pre-server command allowlist (#58) -- no test verifying that disallowed commands are blocked
- **Impact/Risk:** Security regressions can be introduced without any test catching them. These are the highest-risk code paths in the harness.
- **Recommended fix:** Create `test_executor_security.py` and `test_runner_security.py` with tests for: (1) metacharacter rejection in non-shell mode, (2) path traversal rejection in setup_files, (3) allowlist enforcement for pre-server commands.
- **Acceptance criteria:** At least one test per security fix verifying the guard logic. Tests fail if the guard is removed.

---

### GAP-0266: No code coverage tool configured (pytest-cov missing)

- **Category:** CI-CD
- **Severity:** Medium
- **Requirement source:** Project CLAUDE.md testing requirements, `~/.claude/rules/common/testing.md` ("Verify 80%+ coverage")
- **Current state (evidence):**
  - `geodetestlab-cli/pyproject.toml` -- no `pytest-cov` in dependencies, no `[tool.coverage]` configuration
  - `.gitlab-ci.yml` test-unit job: `python -m pytest geodetestlab/tests/ -v --tb=short` -- no `--cov` flag
  - No coverage report artifacts in CI
- **Why this is a gap:** The testing requirements mandate 80%+ coverage verification, but no coverage tool is installed or configured. There is no way to measure or enforce coverage thresholds.
- **Impact/Risk:** Coverage regressions are invisible. The 80% threshold from project requirements cannot be verified.
- **Recommended fix:** Add `pytest-cov` to dev dependencies, configure `[tool.coverage.run]` and `[tool.coverage.report]` in `pyproject.toml` with `fail_under = 80`, add `--cov` flags to the CI test-unit job.
- **Acceptance criteria:** `pytest --cov` produces a coverage report, CI fails if coverage drops below 80%.

---

### GAP-0267: mypy allow_failure in CI (type errors do not block merges)

- **Category:** CI-CD
- **Severity:** Medium
- **Requirement source:** `.gitlab-ci.yml:64-65` comment: "mypy can legitimately fail on third-party stubs; allow failure but log"
- **Current state (evidence):**
  - `.gitlab-ci.yml:65` -- `allow_failure: true` on lint-mypy job
  - This means type errors in application code are not blocking
- **Why this is a gap:** While third-party stub issues are a legitimate reason for `allow_failure`, this also suppresses real type errors in the project's own code. The comment acknowledges this is a known trade-off.
- **Impact/Risk:** Type errors can accumulate silently. Medium risk since mypy with `--ignore-missing-imports` should isolate third-party issues.
- **Recommended fix:** Configure mypy with `--follow-imports=silent` or per-module overrides to isolate third-party stub issues, then remove `allow_failure: true`. Alternatively, use `--disallow-any-unimported` to get the best of both worlds.
- **Acceptance criteria:** mypy runs without `allow_failure` and does not fail on third-party stubs alone.

---

### GAP-0268: test-all integration job has allow_failure: true

- **Category:** CI-CD
- **Severity:** High
- **Requirement source:** `.gitlab-ci.yml:299-300`
- **Current state (evidence):**
  - `.gitlab-ci.yml:299-300` -- `# Allow failures while CI integration stabilizes` / `allow_failure: true`
  - This is the main integration test job that runs all spec tests against a real Geode server
- **Why this is a gap:** The integration test suite can fail and merges still proceed. This means regressions in GQL query behavior, HTTP endpoints, or CLI commands are not caught at merge time.
- **Impact/Risk:** High -- integration test failures are the primary quality gate for this test harness project. If the test-all job is allowed to fail, the harness itself may regress without detection.
- **Recommended fix:** Remove `allow_failure: true` from the test-all job. If stability concerns remain, gate it on `$CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH` only (already partially done via rules).
- **Acceptance criteria:** `test-all` job failure blocks the pipeline on the default branch.

---

### GAP-0269: No linting for non-Python runners (Go, Zig, Rust, Node.js)

- **Category:** Code Quality
- **Severity:** Low
- **Requirement source:** General code quality standards
- **Current state (evidence):**
  - `.gitlab-ci.yml` -- lint-python and lint-mypy cover Python code only
  - No `go vet`, `golangci-lint`, `clippy`, `eslint`, or Zig compiler warnings in CI
  - Runners in `runners/` directory (go_runner.go, nodejs_runner.js, rust_runner/, zig_runner_new.zig) have no lint jobs
- **Why this is a gap:** Non-Python runners have no automated quality checks in CI. Issues like the deprecated `ioutil.ReadFile` (PERF-014) were only caught during manual review.
- **Impact/Risk:** Low -- runners are supplementary components, not the core harness. But quality issues can accumulate.
- **Recommended fix:** Add `go vet ./...` to the build-go job. Add `cargo clippy` to the build-rust job. Add `npx eslint` to the build-nodejs job. Zig compiler warnings are surfaced during build.
- **Acceptance criteria:** Each runner language has at least basic lint/vet checks in its CI build job.

---

### GAP-0270: Two separate pytest configurations causing potential confusion

- **Category:** Code Quality
- **Severity:** Low
- **Requirement source:** General code quality standards
- **Current state (evidence):**
  - `/home/benji/src/devnw/codepros/geode/geode-test-harness/pytest.ini` -- root-level config with `testpaths = tests`
  - `/home/benji/src/devnw/codepros/geode/geode-test-harness/geodetestlab-cli/pyproject.toml:89-91` -- `[tool.pytest.ini_options]` with `testpaths = ["geodetestlab/tests"]`
  - The root `pytest.ini` points to `tests` (does not exist at root) while pyproject.toml points to `geodetestlab/tests`
- **Why this is a gap:** Running `pytest` from the repo root uses `pytest.ini` and looks for a non-existent `tests/` directory. Running from `geodetestlab-cli/` uses pyproject.toml correctly. This can cause confusion during local development.
- **Impact/Risk:** Low -- CI runs from the correct directory. Only affects developer experience.
- **Recommended fix:** Remove the root-level `pytest.ini` (it appears to be a legacy artifact), or update it to point to the correct test directory.
- **Acceptance criteria:** Only one pytest configuration exists, or both are consistent and documented.

---

### GAP-0271: No JSON Schema for YAML test spec format

- **Category:** Docs
- **Severity:** Low
- **Requirement source:** General documentation standards
- **Current state (evidence):**
  - `geodetestlab-cli/geodetestlab/lib/spec.py` -- validates specs programmatically but no formal schema file
  - 243 YAML spec files in `specs/` with no schema reference
  - CLAUDE.md documents the spec format informally
- **Why this is a gap:** No machine-readable schema for the YAML test spec format. Contributors must read `spec.py` source code to understand valid fields. IDE autocompletion/validation is not available.
- **Impact/Risk:** Low -- the programmatic validation in `spec.py` catches invalid specs at runtime. This is a developer experience improvement.
- **Recommended fix:** Create a JSON Schema file (`specs/schema.json` or `docs/spec-schema.json`) and reference it from CLAUDE.md. Optionally add `$schema` references to spec files for IDE support.
- **Acceptance criteria:** A JSON Schema file exists that validates the YAML spec format.

---

### GAP-0272: build-python and build-nodejs CI jobs produce no useful artifacts

- **Category:** CI-CD
- **Severity:** Low
- **Requirement source:** `.gitlab-ci.yml:196-216`
- **Current state (evidence):**
  - `.gitlab-ci.yml:196-203` -- `build-python` runs `python3 -c "import yaml; print('Python dependencies installed')"` with `artifacts: paths: []`
  - `.gitlab-ci.yml:205-216` -- `build-nodejs` installs `yaml` package and caches `node_modules/`
  - Both extend `.build-template` which has `allow_failure: true`
  - Neither produces artifacts consumed by downstream jobs
- **Why this is a gap:** These jobs consume CI minutes but produce no meaningful output. They verify that a single import/install works but do not build anything.
- **Impact/Risk:** Low -- wasted CI time (~30-60s per job per pipeline run).
- **Recommended fix:** Either remove these jobs or make them useful (e.g., `build-python` could validate the Python package installs correctly, `build-nodejs` could run `node --check runners/nodejs_runner.js`).
- **Acceptance criteria:** Jobs either produce artifacts consumed by downstream stages or are removed.

---

### GAP-0273: Potentially unused dependencies in pyproject.toml

- **Category:** Code Quality
- **Severity:** Low
- **Requirement source:** `geodetestlab-cli/pyproject.toml:31,34,36`
- **Current state (evidence):**
  - `pyproject.toml:31` -- `pydantic>=2.5.0`
  - `pyproject.toml:34` -- `jmespath>=1.0.1`
  - `pyproject.toml:36` -- `psutil>=5.9.0`
  - `grep -r "import pydantic\|from pydantic\|import jmespath\|import psutil\|from psutil"` in `geodetestlab-cli/**/*.py` returns **no matches**
- **Why this is a gap:** Three dependencies are declared but never imported in application code. They inflate the install footprint and attack surface.
- **Impact/Risk:** Low -- unnecessary dependencies, minor supply chain risk.
- **Recommended fix:** Verify these are truly unused (check dynamic imports, CLI plugins, or test-only usage), then remove from dependencies if confirmed unused.
- **Acceptance criteria:** All declared dependencies are imported somewhere in the codebase, or unused ones are removed.

---

### GAP-0274: REQUIREMENTS.md stale -- does not cover issues #48-#79

- **Category:** Docs
- **Severity:** Medium
- **Requirement source:** `docs/REQUIREMENTS.md:3` -- "Last Updated: 2026-02-09"
- **Current state (evidence):**
  - `docs/REQUIREMENTS.md:11` -- "No open issues. All 47 gap issues are resolved."
  - Does not mention issues #48 through #79 (32 issues created after 2026-02-09)
  - Issues #48-#62 are security/hardening findings; #63-#79 are performance findings
  - All these issues have been implemented but REQUIREMENTS.md was never updated
- **Why this is a gap:** The requirements mirror document is stale by 6 weeks and 32 issues. Anyone using this document as a requirements reference will miss a third of the project's tracked work.
- **Impact/Risk:** Medium -- documentation drift reduces trust in project tracking. New team members or auditors will get an incomplete picture.
- **Recommended fix:** Update REQUIREMENTS.md to include issues #48-#79 with their current status (closed/accepted/won't do).
- **Acceptance criteria:** REQUIREMENTS.md lists all 79 issues with correct status, and the "Last Updated" date is current.

---

## Updated Gaps (evidence changed)

| Gap-ID | Change | Updated Evidence |
|--------|--------|-----------------|
| (none) | N/A | All prior gaps were marked Closed in GAP_ANALYSIS.md; no previously-open gaps existed to update |

## Resolved Gaps (ready to close)

| Gap-ID | Resolution Evidence |
|--------|-------------------|
| (none) | No previously-open gaps existed in GAP_ANALYSIS.md |

## Gap Priority Matrix

| Severity | Count | Gap-IDs |
|----------|-------|---------|
| Critical | 0 | -- |
| High | 2 | GAP-0265, GAP-0268 |
| Medium | 4 | GAP-0261, GAP-0262, GAP-0266, GAP-0274 |
| Low | 8 | GAP-0263, GAP-0264, GAP-0269, GAP-0270, GAP-0271, GAP-0272, GAP-0273, GAP-0274 |

**Correction:** GAP-0274 is Medium, not Low. Updated matrix:

| Severity | Count | Gap-IDs |
|----------|-------|---------|
| Critical | 0 | -- |
| High | 2 | GAP-0265, GAP-0268 |
| Medium | 4 | GAP-0261, GAP-0262, GAP-0266, GAP-0274 |
| Low | 8 | GAP-0263, GAP-0264, GAP-0269, GAP-0270, GAP-0271, GAP-0272, GAP-0273 |

---

## Process Finding: GitLab Issue Status Discrepancy

**Observation:** 32 GitLab issues (#48-#79) were reported as OPEN on GitLab during Phase 1 scanning, while `docs/GAP_ANALYSIS.md` and `docs/PERF_GAP_ANALYSIS.md` document them as "Closed" or "Accepted". Code verification confirms the fixes ARE implemented in the codebase.

**Root cause:** The issues were resolved in code and documented in the gap analysis files, but were never formally closed on GitLab.

**Recommendation:** Close all 32 issues on GitLab with references to the implementing commits. This is a process hygiene issue, not a code gap, so no Gap-ID is assigned.

---

## Notes on Won't Do Items

The following remain unchanged from prior analysis:

- **#55** (Dockerfile unpinned packages / no HEALTHCHECK) -- Won't Do (organizational controls)
- **#59** (Python deps: no lockfile or hash verification) -- Won't Do (organizational controls)

Per MEMORY.md policy: "Items #55 and #59 in GAP_ANALYSIS.md are permanently 'Won't Do.'"

---

## Analysis Metadata

**Analysis Date:** 2026-03-27
**Analyzed By:** Claude Code (Opus 4.6, gap determination phase)
**Prior State:** 65 gaps tracked (GAP-0001 through GAP-0037, QG-001 through QG-010, #48-#62), plus GAP-0256 through GAP-0260. All marked resolved/closed/won't do.
**New Gaps:** 14 (GAP-0261 through GAP-0274)
**Highest Gap-ID:** GAP-0274
