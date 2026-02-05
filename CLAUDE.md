# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is the **Geode Test Harness** - a cross-language test framework for validating Geode client library implementations. It runs identical YAML test specifications against different client runners (Zig, Go, Python, Rust, Node.js) from external repositories.

The harness uses Docker containers for Geode server management, parses test specs, executes tests through language-specific runners, and produces JSON/HTML reports.

## External Dependencies

Client libraries are located in sibling directories:
- `../geode-client-go/` - Go client (module: geodedb.com/geode)
- `../geode-client-python/` - Python client (package: geode_client)
- `../geode-client-rust/` - Rust client (crate: geode-client)
- `../geode-client-zig/` - Zig client (module: geode_client)
- `../geode-client-nodejs/` - Node.js client (package: @geode/client)

Docker image: `registry.gitlab.com/devnw/geode/geode:latest`

## Build & Test Commands

```bash
# Docker server management
make docker-start      # Start Geode container on port 3141
make docker-stop       # Stop Geode container
make docker-logs       # View container logs
make docker-status     # Check container status
make docker-pull       # Pull latest Geode image

# Initial setup (creates venv, installs deps, builds runners)
make setup

# Build specific runners
make build-all         # Build all client runners
make build-zig         # Build Zig runner
make build-go          # Build Go runner
make build-rust        # Build Rust runner (may take time)
make build-python      # Setup Python runner
make build-nodejs      # Setup Node.js runner

# Run tests
make test              # Run basic tests
make test-all          # Run all tests with JSON report
make test-docker       # Start Docker, run tests, stop Docker

# Single-client tests
make test-zig          # Run tests on Zig client only
make test-go           # Run tests on Go client only
make test-python       # Run tests on Python client only
make test-rust         # Run tests on Rust client only
make test-nodejs       # Run tests on Node.js client only

# Specific test suites
make test-transactions
make test-connections
make test-auth
make test-perf

# Transport-specific tests
make test-quic           # Run tests using QUIC transport (default)
make test-grpc           # Run tests using gRPC transport
make test-all-transports # Run tests with both QUIC and gRPC
TRANSPORT=grpc make test # Run any test with specific transport

# Reports and analysis
make test-all-html          # Generate HTML report
make test-with-coverage     # Tests + coverage report
make analyze-coverage REPORT=reports/results.json
make analyze-perf           # Analyze performance results

# Direct runner invocation
python3 run_tests.py --spec specs/basic.yaml --clients zig --verbose
python3 run_tests.py --server localhost:3141 --no-manage-server --clients go,python
python3 run_tests.py --transport grpc --server localhost:50051 --clients python --verbose
```

## Architecture

### Test Flow

1. `run_tests.py` - Main orchestrator that:
   - Starts a managed Geode server (Docker container)
   - Loads YAML specs from `specs/` directory
   - Dispatches tests to language-specific runners
   - Collects results and generates reports

2. **Runners** - Language-specific executables in `runners/`:
   - `runners/zig_runner` - Zig runner (uses geode-client-zig)
   - `runners/go_runner` - Go runner (uses geode-client-go)
   - `runners/python_runner.py` - Python runner (uses geode-client-python)
   - `runners/rust_runner/` - Rust runner (uses geode-client-rust)
   - `runners/nodejs_runner.js` - Node.js runner (uses geode-client-nodejs)
   - Runners accept `--spec <yaml> --server host:port --transport quic|grpc --json` flags
   - Output JSON with `summary` and `results` arrays

3. **Test Specs** - YAML files in `specs/`:
   - `basic.yaml` - Core GQL operations, parameters, data types
   - `transactions.yaml` - BEGIN/COMMIT/ROLLBACK
   - `connections.yaml` - Connection management
   - `auth.yaml` - Authentication tests
   - `performance.yaml` - Benchmarks

### Key Files

- `run_tests.py` - Main test harness coordinator
  - `GeodeServerManager` - Docker container management
  - `*Runner` classes - Language-specific test runners
  - `TestHarness` - Test orchestration
- `Makefile` - Build and test commands
- `runners/build.zig` - Zig runner build config
- `runners/go.mod` - Go runner module config
- `runners/rust_runner/Cargo.toml` - Rust runner config
- `runners/package.json` - Node.js runner dependencies

### Test Spec Format

```yaml
version: "1.0"
name: "Test Suite Name"
tests:
  - name: "test-name"
    description: "What this tests"
    query: "RETURN $param AS result"
    params:
      param: "value"
    expect:
      rows: 1
      columns: ["result"]
      values:
        - result: "value"
    timeout_ms: 5000
    skip: false
    expect_error: false

  # Multi-step tests
  - name: "multi-step-test"
    steps:
      - type: connect
      - type: begin
      - type: query
        text: "CREATE (n:Node {id: 1})"
      - type: commit
      - type: disconnect
```

Step types: `connect`, `disconnect`, `begin`, `commit`, `rollback`, `query`

## Docker Server Configuration

The test harness uses Docker for server management:

```bash
# Default settings
GEODE_IMAGE=registry.gitlab.com/devnw/geode/geode:latest
GEODE_CONTAINER=geode-test-harness
GEODE_PORT=3141

# Override via environment or make variables
GEODE_PORT=8443 make docker-start
GEODE_IMAGE=my-registry/geode:custom make docker-start
```

The server listens on UDP port 3141 for QUIC connections.

## Development Notes

### Adding a New Client Runner

1. Create runner file in `runners/` (e.g., `newlang_runner.ext`)
2. Implement CLI interface: `--spec <file> --server <host:port> --json`
3. Output JSON format:
   ```json
   {
     "summary": {"total": N, "passed": N, "failed": N, "errors": N, "skipped": N},
     "results": [{"test": "name", "status": "passed|failed|error|skipped", ...}]
   }
   ```
4. Add `NewLangRunner` class to `run_tests.py`
5. Add build target to `Makefile`
6. Update `--clients` default in `run_tests.py`

### Client Dependencies

- **Zig**: Uses `build.zig.zon` to reference `../../geode-client-zig`
- **Go**: Uses `go.mod` replace directive to `../../geode-client-go`
- **Rust**: Uses Cargo path dependency to `../../../geode-client-rust`
- **Python**: Imports from installed package or `../geode-client-python`
- **Node.js**: Uses npm file dependency to `../../geode-client-nodejs`

### Testing Against External Server

```bash
# Skip Docker management (QUIC transport)
python3 run_tests.py --server my-server:3141 --no-manage-server --clients zig

# Test with gRPC transport
python3 run_tests.py --server my-server:50051 --transport grpc --no-manage-server --clients go
```

### Environment Variables

- `GEODE_IMAGE` - Docker image to use
- `GEODE_CONTAINER` - Container name
- `GEODE_HOST` - Server host (default: 127.0.0.1)
- `GEODE_PORT` - QUIC server port (default: 3141, UDP)
- `GEODE_GRPC_PORT` - gRPC server port (default: 50051, TCP)
- `GEODE_ADMIN_PASSWORD` - Admin password for authentication (default: GeodeTestPassword123!)
- `GEODE_USERNAME` - Username for authentication (default: geode)

## Requirements

### Required

- Python 3.9+ (for test harness)
- Docker (for server management)

### Optional (for specific clients)

- **Zig**: Zig 0.15.1+ for Zig runner
- **Go**: Go 1.24+ for Go runner
- **Rust**: Rust 1.70+ for Rust runner
- **Node.js**: Node.js 20+ for Node.js runner

## Troubleshooting

### Docker Issues

```bash
# Check if container is running
make docker-status

# View logs for debugging
make docker-logs

# Force restart
make docker-stop && make docker-start
```

### Build Issues

```bash
# Clean all build artifacts
make clean

# Rebuild specific runner
make build-zig  # or build-go, build-rust, etc.
```

### Client Not Found

Ensure sibling client repositories exist:
```bash
ls ../geode-client-{go,python,rust,zig,nodejs}
```

If missing, clone from GitLab:
```bash
git clone git@gitlab.com:devnw/geode/geode-client-go.git ../geode-client-go
# etc.
```
