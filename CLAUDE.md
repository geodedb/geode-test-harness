# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is the **Geode Test Harness** (`geodetestlab-cli`) — a CLI-based integration test framework for the Geode graph database. It executes YAML test specifications against a Geode server binary, validating CLI commands, GQL queries, HTTP endpoints, and shell operations. It also supports cross-language client runners (Zig, Go, Python, Rust, Node.js) in the `runners/` directory.

## External Dependencies

Client libraries are located in sibling directories:

- `../geode-client-go/` - Go client (module: geodedb.com/geode)
- `../geode-client-python/` - Python client (package: geode_client)
- `../geode-client-rust/` - Rust client (crate: geode-client)
- `../geode-client-zig/` - Zig client (module: geode_client)
- `../geode-client-nodejs/` - Node.js client (package: @geode/client)

Geode server binary: `../geode/zig-out/bin/geode`
Docker image: `geodedb/geode:latest`

## Build & Test Commands

```bash
# Docker server management
make docker-start      # Start Geode container on port 3141
make docker-stop       # Stop Geode container
make docker-logs       # View container logs
make docker-status     # Check container status
make docker-pull       # Pull latest Geode image

# Initial setup
make setup             # Install dependencies and build runners
make geodetestlab-setup # Setup geodetestlab-cli venv

# Run tests (all use geodetestlab-cli)
make test-everything   # Run ALL tests with a unified script (unit, integration, shell, load)
make test              # Run client/integration tests
make test-all          # Run all tests with JSON report
make test-docker       # Start Docker, run tests, stop Docker
make test-unit         # Run unit tests (57 tests)
make test-shell        # Run interactive shell session stability tests

# Transport-specific tests
make test-quic         # Run tests using QUIC transport (default)
make test-grpc         # Run tests using gRPC transport
make test-all-transports # Run tests with both QUIC and gRPC

# Code quality
make lint              # Run ruff linter
make format            # Format with ruff
make type-check        # Run mypy
make security-check    # Run bandit
make quality           # All quality checks

# Direct geodetestlab-cli invocation
cd geodetestlab-cli
source .venv/bin/activate
python -m geodetestlab run --spec specs/filename.yml -v
python -m geodetestlab run --specs specs --parallel 4 -v
python -m geodetestlab run --specs specs --transport grpc -v
```

## OTel Monitoring (debugging via spans/metrics)

When investigating slow queries, transaction failures, or connection issues,
run the suite with OTel monitoring enabled to capture every span/metric
geode emits during the test. This is the recommended path whenever a bug
report includes phrases like "hung for N minutes", "connection died",
"chunk failed", or any cross-layer behavior that's hard to bisect from logs
alone.

### Quick start

```bash
# One-shot: start collector → run full suite → verify → stop collector
make test-everything-otel GEODE_BINARY=/path/to/geode

# Manual control (useful when debugging a specific spec)
make otel-start                      # spin up docker collector on :44318
make otel-tail                       # docker logs -f (live span/metric stream)
GEODE_OTEL=1 make test-spec SPEC=specs/foo.yml
make otel-verify                     # assert spans with service.name=geode arrived
make otel-stop                       # tear down
```

### What gets captured

The collector runs with two exporters — `debug` (stdout, visible via
`make otel-tail`) and `file` (`reports/spans.jsonl`, OTLP/JSON one record
per line, rotates at 64 MB × 3). After a run:

- `reports/spans.jsonl` — every span and metric in OTLP/JSON format. Filter
  by `instrumentationScope.name` or any attribute to focus on a layer.
  Example:
  `jq '.resourceSpans[].scopeSpans[] | select(.scope.name=="wal")' reports/spans.jsonl`
- `reports/otel-collector.log` — collector stdout drained on stop.
- `reports/.otel-env` — exact env vars sourced into the test run (so you
  can reproduce a single failing test interactively against the same
  collector).

### InstrumentationScopes

| Scope | Origin | Useful for |
|---|---|---|
| `com.geodedb.geode` | geode itself | `geode.transport.request`, `geode.query.execute`, `geode.graph_store.{create_node,get_nodes_by_label}`, `gql.execute.PARSE`, `wal.{create,update,delete}_*` |
| `wal` | DevNW wal lib | `wal.replay`, `wal.append` (×2 paths), `wal.append_batch` (×2), `wal.commit`, `wal.checkpoint`, `wal.truncate` |
| `gql` | DevNW gql lib | parser entry (`gql.execute.query`) |
| `dns` | DevNW dns lib | client/recursive/stub query lookups |
| `vulkan` | DevNW vulkan lib | GPU compute ops |
| `thread_pool` | DevNW thread-pool lib | task lifecycle |
| `repl` | DevNW repl lib | REPL command execution |
| `protobuf` / `slog` | DevNW libs | bound but no internal spans yet |

### When to use

- **Pipeline failure cascades** (`make test-shell`, parallel-seed bugs) —
  see which `wal.*` or `geode.graph_store.*` span throws first; the parent
  `geode.transport.request` carries `network.peer.address` for connection
  attribution.
- **"driver: bad connection" / "expected BEGIN response"** — correlate
  `geode.transport.request` start times with QUIC handshake metrics
  (`quic_active_connections`, `quic_min_smoothed_rtt_ns`); the
  `proto_reader_*` counter family shows whether bytes ever reached the
  server.
- **Slow queries** — `gql.execute.PARSE` + `geode.query.execute` durations
  side by side; the lib-emitted `gql.execute.query` parses too, giving a
  parser-vs-execute split.
- **Connection drops** — `quic_active_connections` gauge over time.

### Defaults (override via env)

- `OTEL_COLLECTOR_HTTP_PORT=44318`, `OTEL_COLLECTOR_GRPC_PORT=44317` —
  uncommon ports so a host-resident collector on `:4317`/`:4318` keeps
  running.
- `OTEL_TRACES_SAMPLER=always_on`, `OTEL_BSP_SCHEDULE_DELAY=2000`,
  `OTEL_METRIC_EXPORT_INTERVAL=3000` — tight enough that a 30 s
  `make loadtest` produces visible exports.
- `service.name=geode` resource attribute (used by `make otel-verify`).
- `OTEL_COLLECTOR_IMAGE=otel/opentelemetry-collector-contrib:0.96.0` —
  pinned for reproducibility.

### Files

- `scripts/otel-collector.sh` — collector lifecycle (`start|stop|logs|tail|verify`)
- `scripts/run_all_tests.sh` — sources `reports/.otel-env` when `GEODE_OTEL=1`
- `Makefile` — `otel-*` + `test-everything-otel` targets
- `reports/.otel-env`, `reports/.otel-collector.yaml`, `reports/spans.jsonl`,
  `reports/otel-collector.log` — generated, all under `reports/` (gitignored)

## Architecture

### Test Flow

1. `geodetestlab-cli/geodetestlab/cli.py` — Typer CLI entry point
2. `geodetestlab-cli/geodetestlab/lib/runner.py` — Test orchestration
   - Imports from sub-modules: `server.py`, `executor.py`, `checks.py`, `runner_types.py`
3. `geodetestlab-cli/geodetestlab/lib/spec.py` — YAML spec parsing
4. `geodetestlab-cli/specs/` — 243 YAML test specifications

### Key Files

```text
geodetestlab-cli/
├── geodetestlab/
│   ├── cli.py                 # Typer CLI (run, secrets, server commands)
│   ├── lib/
│   │   ├── runner.py          # Test orchestration (396 lines)
│   │   ├── runner_types.py    # Shared data classes (TestResult, RunSummary)
│   │   ├── server.py          # Server lifecycle (start/stop/cleanup)
│   │   ├── executor.py        # Test execution (CLI/HTTP/shell/sequential)
│   │   ├── checks.py          # Expectation checking
│   │   ├── spec.py            # YAML spec parser
│   │   ├── assertions.py      # Test assertion functions
│   │   ├── utils.py           # Utilities (binary finder, port allocator)
│   │   └── plaintext_scanner.py # FLE plaintext verification
│   ├── providers/             # LLM fuzz testing providers
│   ├── server/                # Server manager (importlib-based)
│   └── tests/                 # Unit tests (57 tests)
├── specs/                     # 243 YAML test specifications
└── pyproject.toml             # Python package config (ruff, mypy, pytest)
```

### Test Spec Format

```yaml
name: "Test Suite Name"
mode: server           # auto-manages a Geode server per spec
server_args: []        # extra args for the server
tests:
  - name: "query-test"
    query: "RETURN 1 AS x"
    expected:
      exit_code: 0
      stdout_contains: ["x"]

  - name: "command-test"
    command: "zig-out/bin/geode query 'RETURN 1' --server ${GEODE_SERVER_ADDRESS}"
    expected:
      exit_code: 0
      stdout_contains: ["1"]

  - name: "http-test"
    test_type: http
    http_requests:
      - method: GET
        url: "http://${GEODE_HOST}:${PORT}/health"
        expected:
          status_code: 200
```

### Cross-Language Runners

The `runners/` directory contains language-specific test runners for cross-client validation:

- `runners/zig_runner` / `zig_runner_new.zig` - Zig client runner
- `runners/go_runner` / `go_runner.go` - Go client runner
- `runners/python_runner.py` - Python client runner
- `runners/rust_runner/` - Rust client runner
- `runners/nodejs_runner.js` - Node.js client runner
- `runners/shell_runner.py` - Shell test runner

Runners accept `--spec <yaml> --server host:port --transport quic|grpc --json` flags.

## Docker Server Configuration

```bash
# Default settings
GEODE_IMAGE=geodedb/geode:latest
GEODE_CONTAINER=geode-test-harness
GEODE_PORT=3141        # QUIC (UDP)
GEODE_GRPC_PORT=50051  # gRPC (TCP)

# Override via environment or make variables
GEODE_PORT=8443 make docker-start
```

## Environment Variables

- `GEODE_IMAGE` - Docker image to use
- `GEODE_HOST` - Server host (default: 127.0.0.1)
- `GEODE_PORT` - QUIC server port (default: 3141, UDP)
- `GEODE_GRPC_PORT` - gRPC server port (default: 50051, TCP)
- `GEODE_ADMIN_PASSWORD` - Admin password (default: GeodeTestPassword123!)
- `GEODE_USERNAME` - Username (default: geode)
- `GEODE_VERIFY_SSL` - Enable SSL verification (default: 0)

## Requirements

### Required

- Python 3.11+ (for geodetestlab-cli)
- Geode binary (`../geode/zig-out/bin/geode`)

### Optional

- Docker (for containerized server management)
- **Zig**: 0.15.1+ for Zig runner
- **Go**: 1.24+ for Go runner
- **Rust**: 1.70+ for Rust runner
- **Node.js**: 20+ for Node.js runner
