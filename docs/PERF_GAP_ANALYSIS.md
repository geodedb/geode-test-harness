# Performance Gap Analysis

> **Last Updated:** 2026-03-27
> **GitLab Project:** [devnw/codepros/geode/geode-test-harness](https://gitlab.com/devnw/codepros/geode/geode-test-harness)
> **Commit:** 183a95d (main)
> **Analysis Method:** Full codebase read (all Python, Go, Rust runners, CI/CD, Dockerfile, Makefile), automated pattern scanning (subprocess spawn sites, sleep calls, env copies, string allocation patterns, regex compilation, connection reuse), manual adversarial performance review, Phase 3 deep review (restart logic, CI job analysis, dependency audit)
> **Scoring:** PerfScore = Impact (1-5) x Likelihood (1-5) x 4

This document tracks all performance and scalability findings for the Geode Test Harness project.

## Summary

| Severity | Closed | Accepted | Open | Total |
|----------|--------|----------|------|-------|
| P0 (Critical) | 0 | 1 | 0 | 1 |
| P1 (High) | 5 | 0 | 0 | 5 |
| P2 (Medium) | 4 | 0 | 3 | 7 |
| P3 (Low/Info) | 3 | 4 | 3 | 10 |
| **Total** | **12** | **5** | **6** | **23** |

### Top 5 Performance Bottlenecks

1. **subprocess per CLI test case** (PerfScore: 40) - 1000+ fork/exec per suite run -- **Accepted** (requires Python client integration, separate project)
2. **No performance regression tests in CI** (PerfScore: 36) - Regressions go undetected -- **Open**
3. **Parallel worker cap at 4** (PerfScore: 28) - Underutilizes multi-core machines -- **Closed** (transport-aware cap)
4. **Server readiness polling via subprocess** (PerfScore: 28) - 100 ss spawns per server start -- **Closed** (socket bind probe)
5. **Server restart logic duplicated 3x with for...else bug** (PerfScore: 24) - Dead `_replay_setup()` in 2 of 3 copies -- **Open**

---

## Stack-Ranked Findings

| # | Issue | PerfScore | Severity | Area | File:Line | Status |
|---|-------|-----------|----------|------|-----------|--------|
| 1 | [subprocess per CLI test](#perf-001) | 40 | P0 | app | executor.py:207 | **Accepted** |
| 2 | [No perf regression tests in CI](#perf-023) | 36 | P2 | ci | .gitlab-ci.yml | **Open** |
| 3 | [Server readiness polling via subprocess](#perf-002) | 28 | P1 | app | server.py:142 | **Closed** |
| 4 | [Parallel worker cap at 4](#perf-003) | 28 | P1 | app | Makefile:326 | **Closed** |
| 5 | [Server restart logic 3x duplication + for...else bug](#perf-018) | 24 | P2 | app | runner.py:413-601 | **Open** |
| 6 | [Unconditional 0.5s sleep in server_manager](#perf-019) | 24 | P2 | app | server_manager.py:190 | **Open** |
| 7 | [Sequential tests within spec](#perf-004) | 24 | P1 | app | runner.py:229 | **Closed** |
| 8 | [Plaintext grep per pattern](#perf-005) | 24 | P1 | app | executor.py:594 | **Closed** |
| 9 | [CI pip install in 4+ jobs](#perf-006) | 20 | P1 | ci | .gitlab-ci.yml | **Closed** |
| 10 | [httpx.Client per test case](#perf-007) | 16 | P2 | app | executor.py:284 | **Closed** |
| 11 | [Redundant pip install pyyaml in 2 CI jobs](#perf-020) | 16 | P3 | ci | .gitlab-ci.yml:399,465 | **Open** |
| 12 | [build-python CI job is a no-op](#perf-021) | 16 | P3 | ci | .gitlab-ci.yml:196-203 | **Open** |
| 13 | [O(n*m) variable substitution](#perf-008) | 12 | P2 | app | executor.py:136 | **Closed** |
| 14 | [Shell runner 0.3s sleep per command](#perf-009) | 12 | P2 | app | shell_runner.py:206 | **Closed** |
| 15 | [CI Zig download duplication](#perf-010) | 12 | P2 | ci | .gitlab-ci.yml:260 | **Closed** |
| 16 | [YAML re-parsed in workers](#perf-low) | 8 | P3 | app | cli.py:117 | **Accepted** |
| 17 | [Rust runner serde_yaml 0.9 deprecated](#perf-022) | 8 | P3 | app | Cargo.toml:16 | **Open** |
| 18 | [os.environ.copy per test](#perf-low) | 4 | P3 | app | runner.py:127 | **Accepted** |
| 19 | [find_geode_binary per worker](#perf-low) | 4 | P3 | app | lib/utils.py:82 | **Closed** |
| 20 | [Go runner deprecated ioutil + code dup](#perf-low) | 4 | P3 | app | go_runner.go:112 | **Closed** |
| 21 | [Dockerfile COPY . . context bloat](#perf-low) | 4 | P3 | infra | Dockerfile:34 | **Closed** |
| 22 | [HTML report string concatenation](#perf-low) | 4 | P3 | ci | .gitlab-ci.yml:510 | **Accepted** |
| 23 | [Docker readiness shell polling](#perf-low) | 4 | P3 | infra | Makefile:156 | **Accepted** |

---

## Detailed Findings

### PERF-001: subprocess spawned per CLI test case {#perf-001}

**PerfScore:** 40 | **Severity:** P0 | **Area:** app | **Confidence:** confirmed | **Status: Accepted — Separate Project**

Every CLI test case in the harness spawns a new subprocess via `subprocess.run()`, which forks the Python process, execs the `geode` binary, establishes a QUIC/gRPC connection, runs one query, and exits. With ~197 spec files and multiple tests per spec, this results in **1,000+ process spawns** per full suite run.

```text
executor.py:207  subprocess.run(cmd, env=test_env, capture_output=True, ...)
executor.py:394  subprocess.run(["bash", "-c", command], ...)  # shell tests
executor.py:521  subprocess.run(cmd, ...)                      # sequential GQL steps
```

**Per-spawn cost:** fork/exec ~1-5ms + binary startup + QUIC handshake ~10-50ms = **20-100ms waste per test**.

**Accepted because:** Requires integrating the Geode Python client library (`geode-client-python`) as a direct dependency — an async-only library. Only 19.8% of tests (CLI query tests) could benefit; HTTP, shell, and sequential tests still require subprocess. This is an architectural decision beyond test harness scope that belongs in a separate project effort.

**GitLab:** [#63](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/63)

---

### PERF-002: Server readiness polling via subprocess {#perf-002}

**PerfScore:** 28 | **Severity:** P1 | **Area:** app | **Confidence:** confirmed | **Status: Closed**

`start_server()` previously polled for server readiness by spawning `ss -uln` and `ss -tln` as subprocesses every 100ms.

**Fix applied:** Replaced subprocess-based `ss`/`netstat` polling with `_port_is_bound()` — a zero-cost socket bind probe that attempts to bind to the port and checks for `EADDRINUSE`. Handles both UDP (QUIC) and TCP (gRPC) port types.

**File:** `geodetestlab-cli/geodetestlab/lib/server.py` — new `_port_is_bound(port, sock_type)` helper

**GitLab:** [#64](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/64)

---

### PERF-003: Parallel worker cap at 4 {#perf-003}

**PerfScore:** 28 | **Severity:** P1 | **Area:** app | **Confidence:** confirmed | **Status: Closed**

PARALLEL_WORKERS was capped at 4 in Makefile due to QUIC memory bugs.

**Fix applied:** Made the cap transport-aware. gRPC transport uses `nproc` (no cap). QUIC retains the cap at 4 until the upstream bug is resolved.

**File:** `Makefile` — `NPROC` detection + conditional `PARALLEL_WORKERS` based on `$(TRANSPORT)`

**GitLab:** [#67](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/67)

---

### PERF-004: Tests within a spec execute strictly sequentially {#perf-004}

**PerfScore:** 24 | **Severity:** P1 | **Area:** app | **Confidence:** confirmed | **Status: Closed**

All tests within a single spec previously executed in a sequential for loop. Independent query/http tests could not overlap.

**Fix applied:** Added opt-in `parallel_tests: true` field to `TestSpec`. When enabled, tests within a spec execute via `ThreadPoolExecutor` (capped at `min(cpu_count, len(tests), 8)` threads). Server health checks and crash recovery are serialized via `threading.Lock`. The shared `httpx.Client` is already thread-safe. No existing specs are changed; the feature requires explicit opt-in.

**Files:** `geodetestlab-cli/geodetestlab/lib/spec.py` (field), `geodetestlab-cli/geodetestlab/lib/runner.py` (executor), `geodetestlab-cli/geodetestlab/tests/test_spec_validation.py` (tests)

**GitLab:** [#68](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/68)

---

### PERF-005: Plaintext verification spawns separate grep per pattern {#perf-005}

**PerfScore:** 24 | **Severity:** P1 | **Area:** app | **Confidence:** confirmed | **Status: Closed**

`run_plaintext_verification()` previously spawned a separate `grep -r` subprocess for EACH search pattern.

**Fix applied:** Combined patterns into a single `grep -rE 'pat1|pat2|pat3'` invocation in both `executor.py` and `plaintext_scanner.py`. Added `_scan_combined()` method to `PlaintextScanner`.

**Files:** `geodetestlab-cli/geodetestlab/lib/executor.py`, `geodetestlab-cli/geodetestlab/lib/plaintext_scanner.py`

**GitLab:** [#65](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/65)

---

### PERF-006: CI installs Python deps independently in 4+ jobs {#perf-006}

**PerfScore:** 20 | **Severity:** P1 | **Area:** ci | **Confidence:** confirmed | **Status: Closed**

lint-python, lint-mypy, and test-unit each independently duplicated `tags`, `image`, `cache`, and `before_script` blocks.

**Fix applied:** Extracted a `.python-setup` hidden job template with the shared configuration. Each job now uses `extends: .python-setup` and only defines its `stage`, `script`, `rules`, and job-specific settings (`allow_failure` for mypy). lint-security remains separate as it only needs `bandit`, not the full `.[dev]` install.

**File:** `.gitlab-ci.yml`

**GitLab:** [#73](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/73)

---

### PERF-007: httpx.Client created per HTTP test case {#perf-007}

**PerfScore:** 16 | **Severity:** P2 | **Area:** app | **Confidence:** confirmed | **Status: Closed**

Each `_run_http_test()` and `_run_sequential_test()` previously created a new `httpx.Client`.

**Fix applied:** Created a shared `httpx.Client` at the spec level in `runner.py` and passed it through to `run_single_test()`, `_run_http_test()`, and `_run_sequential_test()`. Client is closed in a `finally` block after all tests complete.

**Files:** `geodetestlab-cli/geodetestlab/lib/runner.py`, `geodetestlab-cli/geodetestlab/lib/executor.py`

**GitLab:** [#69](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/69)

---

### PERF-008: O(n*m) variable substitution on every command string {#perf-008}

**PerfScore:** 12 | **Severity:** P2 | **Area:** app | **Confidence:** confirmed | **Status: Closed**

Every CLI test iterated over ALL env vars and secrets, calling `.replace()` per variable.

**Fix applied:** New `_substitute_one()` function using a single `re.sub()` pass with a lookup callback. Replaces all `${VAR}` and `${env:VAR}` patterns in one pass.

**File:** `geodetestlab-cli/geodetestlab/lib/executor.py`

**GitLab:** [#66](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/66)

---

### PERF-009: Shell runner hardcoded 0.3s sleep before every command {#perf-009}

**PerfScore:** 12 | **Severity:** P2 | **Area:** app | **Confidence:** confirmed | **Status: Closed**

`time.sleep(0.3)` was called before every `sendline()` in the shell runner.

**Fix applied:** Replaced with a prompt-ready check using `self.shell_process.expect(self.prompt_pattern, timeout=0.5)`. Falls back to the original sleep if the prompt check fails.

**File:** `runners/shell_runner.py`

**GitLab:** [#74](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/74)

---

### PERF-010: CI Zig toolchain downloaded twice on cache miss {#perf-010}

**PerfScore:** 12 | **Severity:** P2 | **Area:** ci | **Confidence:** confirmed | **Status: Closed**

build-zig and test-all both download/extract Zig (~200MB) independently.

**Fix applied:** build-zig now includes the Zig toolchain directory (`zig-linux-x86_64-${ZIG_VERSION}/`) in its artifacts. test-all declares `needs: [{job: build-zig, artifacts: true, optional: true}]` to consume the artifact when available. The existing `if [ ! -d ... ]` guard in test-all acts as the fallback when build-zig is skipped or fails.

**File:** `.gitlab-ci.yml`

**GitLab:** [#75](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/75)

---

### PERF-018: Server restart logic duplicated 3x with for...else bug {#perf-018}

**PerfScore:** 24 | **Severity:** P2 | **Area:** app | **Confidence:** confirmed | **Status: Open**

The server restart loop is copy-pasted three times in `runner.py`:

1. **Copy 1** (lines 413-452): Crash-during-iteration handler. Uses a `restarted` flag. Correctly calls `_replay_setup()` when restart succeeds.
2. **Copy 2** (lines 512-534): Post-test "server died" handler. Uses Python `for...else` pattern, but `break` is called on BOTH success (line 525) AND final failure (line 534). The `else` block (line 535-537 calling `_replay_setup()`) only executes when the loop completes without `break` -- which never happens. `_replay_setup()` is dead code here.
3. **Copy 3** (lines 576-601): Post-test "server hung" handler. Same `for...else` bug as Copy 2. `_replay_setup()` on line 600-601 is dead code.

**Perf Impact:** The runtime cost of the duplication itself is negligible. The real impact is correctness: after a successful restart in copies 2 and 3, setup queries are never replayed, so subsequent tests may fail due to missing data (graphs, users, schemas created in setup). This can cause cascading false failures in CI.

**Root Cause:** Copy-paste of restart logic without extracting a shared helper. The `for...else` semantics were misunderstood -- `else` runs only when the loop exits without `break`, but both exit paths use `break`.

**Fix Guidance:** Extract a `_restart_server()` helper that returns the new process (or raises). Call `_replay_setup()` unconditionally after a successful restart in all three sites. Alternatively, refactor into a single restart-with-replay function.

**Validation Plan:**

```bash
# Verify _replay_setup is called after restart:
cd geodetestlab-cli
python -c "
import ast, sys
with open('geodetestlab/lib/runner.py') as f:
    tree = ast.parse(f.read())
# Count for...else blocks and verify no dead _replay_setup calls
for node in ast.walk(tree):
    if isinstance(node, ast.For) and node.orelse:
        print(f'for...else at line {node.lineno}')
"
# After fix: run a spec that crashes the server mid-suite
python -m geodetestlab run --spec specs/server-crash-recovery.yml -v
```

**Affected Paths:** `geodetestlab-cli/geodetestlab/lib/runner.py`

**Rollout Risk:** Low. Extracting a helper is a refactor with no behavioral change for the success path. The bug fix (calling `_replay_setup()` correctly) can only improve test reliability.

---

### PERF-019: Unconditional 0.5s sleep in server_manager.py {#perf-019}

**PerfScore:** 24 | **Severity:** P2 | **Area:** app | **Confidence:** confirmed | **Status: Open**

After the socket bind probe detects the server port is bound, `lib/server_manager.py:190` unconditionally sleeps 500ms "to let the server fully initialize."

```python
# lib/server_manager.py:190
time.sleep(0.5)
```

This affects every `shell_runner` server start. The geodetestlab `server.py` does NOT have this sleep -- it uses the bind probe result directly.

**Perf Impact:** 500ms wasted per shell_runner spec execution. With N shell_runner specs, this adds 0.5*N seconds to CI. Currently a moderate number of shell specs exist, but this scales linearly.

**Root Cause:** Conservative safety margin added during initial implementation. The bind probe already confirms the port is in use, so the server is listening. A health-check query would be more precise than a blind sleep.

**Fix Guidance:** Replace the unconditional `time.sleep(0.5)` with a health-check loop similar to `server.py`'s approach: attempt a simple query or HTTP health endpoint with a short timeout and exponential backoff. Fall back to a brief sleep (50ms) only if the health check is not feasible for the transport.

**Validation Plan:**

```bash
# Measure current shell_runner startup time:
time python -m geodetestlab run --spec specs/shell-basic.yml -v 2>&1 | grep "Server ready"
# After fix: same command should show ~500ms improvement
```

**Affected Paths:** `lib/server_manager.py`

**Rollout Risk:** Low. The sleep is purely a delay; removing or shortening it may cause rare startup races on very slow machines. A health-check loop is strictly better.

---

### PERF-020: Redundant pip install pyyaml in 2 CI jobs {#perf-020}

**PerfScore:** 16 | **Severity:** P3 | **Area:** ci | **Confidence:** confirmed | **Status: Open**

Two CI jobs install `pyyaml` but never use it:

1. `analyze-coverage` (`.gitlab-ci.yml:399`): Script uses only `json` and `os` modules.
2. `generate-html-report` (`.gitlab-ci.yml:465`): Script uses only `json`, `os`, and `html` string operations.

Neither job imports or references `yaml` anywhere in their inline scripts.

**Perf Impact:** ~5s CI waste per pipeline (2 x ~2.5s pip install). Negligible but unnecessary.

**Root Cause:** Likely copied from a template that included pyyaml for YAML-parsing jobs.

**Fix Guidance:** Remove `pip install pyyaml` from both jobs. Verify with `grep -n 'yaml' .gitlab-ci.yml` that no other references exist in those job blocks.

**Validation Plan:**

```bash
# Verify neither job uses yaml:
grep -A 50 'analyze-coverage:' .gitlab-ci.yml | grep -i yaml
grep -A 50 'generate-html-report:' .gitlab-ci.yml | grep -i yaml
# After fix: pipeline runs successfully without pyyaml in those jobs
```

**Affected Paths:** `.gitlab-ci.yml`

**Rollout Risk:** None. These jobs do not use pyyaml.

---

### PERF-021: build-python CI job is a no-op {#perf-021}

**PerfScore:** 16 | **Severity:** P3 | **Area:** ci | **Confidence:** confirmed | **Status: Open**

The `build-python` job (`.gitlab-ci.yml:196-203`) installs `pyyaml`, prints a confirmation message, and produces empty artifacts (`paths: []`). It does not build, compile, or validate anything meaningful.

```yaml
build-python:
  extends: .build-template
  image: python:3.13-slim
  script:
    - pip install pyyaml
    - python3 -c "import yaml; print('Python dependencies installed')"
  artifacts:
    paths: []
```

**Perf Impact:** ~30s CI waste per pipeline (job startup + image pull + pip install + teardown). Empty artifacts declaration wastes GitLab CI scheduler time.

**Root Cause:** Placeholder job that was never fleshed out. The Python runner does not require a build step (it is interpreted).

**Fix Guidance:** Remove the `build-python` job entirely unless there is a plan to add real validation (e.g., `pip install -e . && python -m pytest`). If downstream jobs `need` it, update their `needs` list.

**Validation Plan:**

```bash
# Check if any job depends on build-python:
grep -n 'build-python' .gitlab-ci.yml
# After removal: pipeline graph should be simpler with one fewer job
```

**Affected Paths:** `.gitlab-ci.yml`

**Rollout Risk:** Low. Verify no other job declares `needs: [{job: build-python}]` before removing.

---

### PERF-022: Rust runner serde_yaml 0.9 deprecated {#perf-022}

**PerfScore:** 8 | **Severity:** P3 | **Area:** app | **Confidence:** confirmed | **Status: Open**

`runners/rust_runner/Cargo.toml:16` depends on `serde_yaml = "0.9"`, which is officially deprecated and unmaintained. The crate's README states: "This crate is no longer maintained. Please use a maintained YAML library such as `serde_yml`."

```toml
serde_yaml = "0.9"
```

**Perf Impact:** No runtime performance impact. Risk is supply-chain: unmaintained dependencies may accumulate CVEs and will not receive bug fixes.

**Root Cause:** Dependency was added before `serde_yaml` was deprecated (pre-2024).

**Fix Guidance:** Replace `serde_yaml = "0.9"` with `serde_yml = "0.0.12"` (or latest). The API is nearly identical -- update import paths from `serde_yaml::` to `serde_yml::` in `src/main.rs`.

**Validation Plan:**

```bash
cd runners/rust_runner
cargo update
cargo build --release
cargo test
```

**Affected Paths:** `runners/rust_runner/Cargo.toml`, `runners/rust_runner/src/main.rs`

**Rollout Risk:** Low. API surface is compatible. Run the Rust runner integration tests to confirm.

---

### PERF-023: No performance regression tests in CI {#perf-023}

**PerfScore:** 36 | **Severity:** P2 | **Area:** ci | **Confidence:** suspected | **Status: Open**

The CI pipeline has no benchmark or performance regression detection. Changes that degrade test harness throughput (e.g., adding sleeps, removing parallelism, breaking connection reuse) will not be caught until a human notices slower CI runs.

**Perf Impact:** Regressions can accumulate silently. The 12 closed PERF findings demonstrate that significant optimizations were needed -- without regression tests, any of these could regress without detection.

**Root Cause:** Performance testing was not part of the initial CI design. The test harness focuses on correctness validation of the Geode server, not its own performance.

**Fix Guidance:** Add a lightweight benchmark CI job that:

1. Runs a fixed set of representative specs (e.g., 10 specs covering CLI, HTTP, shell, sequential modes)
2. Records wall-clock time and per-spec duration
3. Compares against a baseline stored in `reports/perf-baseline.json`
4. Fails the pipeline if total time exceeds baseline by more than 20%

This does NOT require a dedicated benchmark framework -- a simple shell script with `time` and `jq` comparison is sufficient.

**Validation Plan:**

```bash
# Proposed benchmark job (example):
time python -m geodetestlab run \
  --spec specs/basic-queries.yml \
  --spec specs/http-health.yml \
  --spec specs/shell-basic.yml \
  -v --json-report reports/perf-run.json

# Compare against baseline:
python3 -c "
import json
baseline = json.load(open('reports/perf-baseline.json'))
current = json.load(open('reports/perf-run.json'))
ratio = current['summary']['duration_ms'] / baseline['summary']['duration_ms']
print(f'Performance ratio: {ratio:.2f}x')
assert ratio < 1.2, f'Performance regression detected: {ratio:.2f}x slower'
"
```

**Affected Paths:** `.gitlab-ci.yml`, `reports/perf-baseline.json` (new)

**Rollout Risk:** Low. A non-blocking (allow_failure) benchmark job adds visibility without breaking pipelines. Can be made blocking once the baseline is stable.

**What would confirm this finding:** Introduce a deliberate 1s sleep in a hot path, push to CI, and observe that no job detects the regression.

---

### PERF-011 through PERF-017: Low-severity findings {#perf-low}

| # | Finding | PerfScore | Status | Notes |
|---|---------|-----------|--------|-------|
| 11 | YAML re-parsed in each parallel worker | 8 | **Accepted** | Inherent to ProcessPoolExecutor (can't share parsed objects across processes). Pickle cost ≈ re-parse cost. ~1ms. |
| 12 | os.environ.copy() per spec + env.copy() per test | 4 | **Accepted** | Negligible cost (~0.1ms per call). |
| 13 | find_geode_binary spawns subprocess per worker | 4 | **Closed** | Resolved once in `cli.py` before workers start (PERF-013) |
| 14 | Go runner: deprecated ioutil.ReadFile | 4 | **Closed** | Replaced `ioutil.ReadFile` with `os.ReadFile` in `go_runner.go` |
| 15 | Dockerfile COPY . . copies entire context | 4 | **Closed** | Created `.dockerignore` excluding `.git`, `__pycache__`, `*.pyc`, etc. |
| 16 | HTML report via string concatenation | 4 | **Accepted** | Negligible impact; report generated once at end of CI (~0.5ms). |
| 17 | Docker readiness check polls with shell loop | 4 | **Accepted** | Negligible impact; Docker polling runs once during `make docker-start`, not per test. |

---

## Positive Findings

- **ProcessPoolExecutor** used correctly for inter-spec parallelism with proper signal handling
- **httpx** (not requests) used for HTTP tests — now with shared client connection pooling
- **yaml.safe_load()** used consistently — safe and reasonably efficient
- **Go runner** uses `database/sql` connection pooling — efficient connection reuse
- **Python runner** uses async connection with pager — streams results instead of buffering all
- **Server started with `start_new_session=True`** — clean process group management
- **Graceful shutdown** with signal handlers and atexit cleanup
- **Rich console** output uses lazy formatting (not evaluated unless displayed)
- **Subprocess timeouts** set on all calls — prevents hangs
- **Socket bind probe** for server readiness — zero-cost vs subprocess polling
- **Single re.sub pass** for variable substitution — O(n) vs O(n*m)
- **Combined grep patterns** — single invocation vs N recursive scans

## Remediation Roadmap

### Open (6) -- Prioritized

#### Quick Wins (< 1 day)

| Finding | Effort | Expected Impact |
|---------|--------|-----------------|
| PERF-020: Remove redundant `pip install pyyaml` | 5 min | ~5s CI savings/pipeline |
| PERF-021: Remove no-op `build-python` job | 10 min | ~30s CI savings/pipeline |
| PERF-022: Replace deprecated `serde_yaml` | 30 min | Supply-chain hygiene |

#### Medium (1-5 days)

| Finding | Effort | Expected Impact |
|---------|--------|-----------------|
| PERF-018: Extract `_restart_server()` helper, fix `for...else` | 2 hours | Correctness fix: `_replay_setup()` runs after restart |
| PERF-019: Replace 0.5s sleep with health check | 1 hour | 500ms savings per shell_runner spec |

#### Strategic (> 5 days)

| Finding | Effort | Expected Impact |
|---------|--------|-----------------|
| PERF-023: Add performance regression CI job | 2-3 days | Prevents silent regressions |

### Closed (12)

| Issue | Resolution |
|-------|-----------|
| [#64](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/64) Server polling | Replaced `ss` with socket bind probe |
| [#65](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/65) Grep per pattern | Combined into single `grep -E` |
| [#67](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/67) Worker cap | Transport-aware parallelism |
| [#69](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/69) httpx reuse | Shared client across spec |
| [#66](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/66) Variable substitution | Single `re.sub` pass with callback |
| [#74](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/74) Shell sleep | Prompt-ready check |
| [#72](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/72) Binary resolution | Resolved once before workers |
| [#76](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/76) Go ioutil | Replaced with os.ReadFile |
| [#77](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/77) Dockerfile bloat | Created .dockerignore |
| [#68](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/68) Intra-spec parallel | Opt-in `parallel_tests` flag + ThreadPoolExecutor |
| [#73](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/73) CI pip duplication | `.python-setup` hidden job template |
| [#75](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/75) CI Zig duplication | build-zig artifact passed to test-all |

### Accepted (5)

| Issue | Rationale |
|-------|-----------|
| [#63](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/63) subprocess/test | Requires `geode-client-python` integration (async-only). Only 19.8% of tests benefit. Separate project scope. |
| [#70](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/70) YAML re-parse | Architectural limitation -- ProcessPoolExecutor can't share parsed objects. Pickle cost = re-parse cost. ~1ms. |
| [#71](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/71) os.environ.copy | Negligible -- ~0.1ms per call. |
| [#78](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/78) HTML report concat | Negligible -- generated once at end of CI. ~0.5ms. |
| [#79](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/79) Docker polling | Setup only -- runs once during `make docker-start`, not per test. |

## Methodology

### Files Reviewed

| File | Lines | Findings |
|------|-------|----------|
| geodetestlab-cli/geodetestlab/lib/executor.py | 628 | 4 |
| geodetestlab-cli/geodetestlab/lib/runner.py | 610+ | 3 |
| geodetestlab-cli/geodetestlab/lib/server.py | 243 | 1 |
| geodetestlab-cli/geodetestlab/cli.py | 715 | 1 |
| geodetestlab-cli/geodetestlab/lib/spec.py | 514 | 0 |
| geodetestlab-cli/geodetestlab/lib/utils.py | 337 | 0 |
| geodetestlab-cli/geodetestlab/lib/checks.py | 242 | 0 |
| geodetestlab-cli/geodetestlab/lib/plaintext_scanner.py | 311 | 1 |
| geodetestlab-cli/geodetestlab/lib/assertions.py | 356 | 0 |
| geodetestlab-cli/geodetestlab/providers/openai_compat.py | 185 | 0 |
| lib/server_manager.py | 247 | 1 |
| lib/utils.py | 155 | 1 |
| runners/go_runner.go | 770 | 1 |
| runners/python_runner.py | 513 | 0 |
| runners/shell_runner.py | 757 | 1 |
| runners/rust_runner/Cargo.toml | 27 | 1 |
| .gitlab-ci.yml | 674+ | 5 |
| Makefile | 503 | 2 |
| geodetestlab-cli/Dockerfile | 42 | 1 |

### Pattern Scans Performed

- subprocess.run / subprocess.Popen call sites
- time.sleep calls
- os.environ.copy / dict.copy / dict.update chains
- Nested for-loop iterations over .items()
- re.search / re.compile usage (pre-compiled vs inline)
- httpx.Client / httpx.AsyncClient instantiation sites
- yaml.safe_load invocations
- ProcessPoolExecutor / ThreadPoolExecutor usage
- ioutil.ReadFile (deprecated Go API)
- String .replace() chains in hot paths
- for...else control flow patterns (Phase 3)
- Duplicated code blocks via structural comparison (Phase 3)
- CI job dependency graph and artifact flow (Phase 3)
- Deprecated/unmaintained Cargo dependencies (Phase 3)
