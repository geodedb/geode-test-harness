# Geode Test Harness

A cross-language test framework for validating Geode client library implementations. The harness runs identical YAML test specifications against multiple language-specific runners (Zig, Go, Python, Rust, Node.js) to ensure consistent behavior across all client implementations.

## Overview

The test harness:
- Manages a Geode server via Docker
- Loads YAML test specifications from `specs/`
- Dispatches tests to language-specific runners
- Collects results and generates JSON/HTML reports
- Supports benchmarking, connection pooling, and multi-connection tests

## Prerequisites

### Required
- **Python 3.9+** - Test harness orchestrator
- **Docker** - Geode server management

### Optional (for specific clients)
- **Zig 0.15.1+** - Zig client runner
- **Go 1.24+** - Go client runner
- **Rust 1.70+** - Rust client runner
- **Node.js 20+** - Node.js client runner

## Quick Start

```bash
# Initial setup (creates venv, installs deps, builds runners)
make setup

# Start the Geode server
make docker-start

# Run all tests
make test-all

# Stop the server
make docker-stop
```

## Make Targets

### Docker Management
| Target | Description |
|--------|-------------|
| `docker-start` | Start Geode container on port 3141 |
| `docker-stop` | Stop Geode container |
| `docker-logs` | View container logs |
| `docker-status` | Check container status |
| `docker-pull` | Pull latest Geode image |

### Building
| Target | Description |
|--------|-------------|
| `setup` | Full setup: Python venv, deps, build all runners |
| `build-all` | Build all client runners |
| `build-zig` | Build Zig runner |
| `build-go` | Build Go runner |
| `build-rust` | Build Rust runner |
| `build-python` | Setup Python runner |
| `build-nodejs` | Setup Node.js runner |

### Testing
| Target | Description |
|--------|-------------|
| `test` | Run basic tests |
| `test-all` | Run all tests with JSON report |
| `test-docker` | Start Docker, run tests, stop Docker |
| `test-zig` | Run tests on Zig client only |
| `test-go` | Run tests on Go client only |
| `test-python` | Run tests on Python client only |
| `test-rust` | Run tests on Rust client only |
| `test-nodejs` | Run tests on Node.js client only |
| `test-transactions` | Run transaction tests |
| `test-connections` | Run connection tests |
| `test-auth` | Run authentication tests |
| `test-perf` | Run performance benchmarks |

### Reports
| Target | Description |
|--------|-------------|
| `test-all-html` | Generate HTML report |
| `test-with-coverage` | Tests + coverage report |
| `analyze-coverage` | Analyze results JSON |
| `analyze-perf` | Analyze performance results |

## Test Specification Format

Test specs are YAML files in the `specs/` directory:

```yaml
version: "1.0"
name: "Test Suite Name"
description: "What this suite tests"

setup:
  - type: query
    text: "CREATE (n:TestNode) RETURN n"

tests:
  - name: "simple-query"
    description: "Basic query test"
    query: "RETURN 1 AS x"
    params: {}
    expect:
      rows: 1
      columns: ["x"]
      values:
        - x: 1
    timeout_ms: 5000

  - name: "transaction-test"
    description: "Transaction handling"
    steps:
      - type: connect
      - type: begin
      - type: query
        text: "CREATE (n:Node {id: 1}) RETURN n"
        expect:
          rows: 1
      - type: commit
      - type: disconnect

  - name: "benchmark-test"
    description: "Performance benchmark"
    query: "RETURN 1 AS x"
    benchmark:
      iterations: 100
      max_avg_latency_ms: 10
      max_p95_latency_ms: 20

  - name: "skipped-test"
    description: "Not ready yet"
    query: "SOME QUERY"
    skip: true
    skip_reason: "Requires feature X"

cleanup:
  - type: query
    text: "MATCH (n:TestNode) DELETE n"
```

### Step Types

| Type | Description |
|------|-------------|
| `connect` | Establish connection |
| `disconnect` | Close connection |
| `begin` | Begin transaction |
| `commit` | Commit transaction |
| `rollback` | Rollback transaction |
| `query` | Execute GQL query |
| `pool_acquire` | Acquire pooled connection |
| `pool_release` | Release pooled connection |

### Multi-Connection Tests

For tests requiring multiple concurrent connections:

```yaml
steps:
  - type: connect
    connection_id: "conn1"
  - type: connect
    connection_id: "conn2"
  - type: query
    connection_id: "conn1"
    text: "RETURN 1"
  - type: disconnect
    connection_id: "conn1"
  - type: disconnect
    connection_id: "conn2"
```

## Adding a New Client Runner

1. Create runner file in `runners/` (e.g., `newlang_runner.ext`)

2. Implement CLI interface:
   ```
   --spec <file>       Test specification YAML
   --server <host:port> Server address
   --json              Output JSON format
   --verbose           Verbose output
   ```

3. Output JSON format:
   ```json
   {
     "summary": {
       "total": 10,
       "passed": 8,
       "failed": 1,
       "errors": 0,
       "skipped": 1
     },
     "results": [
       {
         "test": "test-name",
         "status": "passed|failed|error|skipped",
         "error": "error message if any",
         "skip_reason": "reason if skipped",
         "duration_ms": 123.45,
         "benchmark": {
           "iterations": 100,
           "avg_latency_ms": 5.2,
           "p95_latency_ms": 8.1
         }
       }
     ]
   }
   ```

4. Add `NewLangRunner` class to `run_tests.py`

5. Add build target to `Makefile`

## Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `GEODE_IMAGE` | `registry.gitlab.com/devnw/geode/geode:latest` | Docker image |
| `GEODE_CONTAINER` | `geode-test-harness` | Container name |
| `GEODE_HOST` | `127.0.0.1` | Server host |
| `GEODE_PORT` | `3141` | Server port |

### Direct Runner Invocation

```bash
# Run specific spec with specific clients
python3 run_tests.py --spec specs/basic.yaml --clients zig,go --verbose

# Run against external server (skip Docker management)
python3 run_tests.py --server my-server:3141 --no-manage-server --clients all
```

## Client Dependencies

Runners depend on client libraries in sibling directories:

| Client | Location | Module/Package |
|--------|----------|----------------|
| Zig | `../geode-client-zig` | geode_client |
| Go | `../geode-client-go` | go.codepros.org/geode |
| Rust | `../geode-client-rust` | geode-client |
| Python | `../geode-client-python` | geode_client |
| Node.js | `../geode-client-nodejs` | @geode/client |

## Troubleshooting

### Docker Issues
```bash
# Check container status
make docker-status

# View logs
make docker-logs

# Force restart
make docker-stop && make docker-start
```

### Build Issues
```bash
# Clean all artifacts
make clean

# Rebuild specific runner
make build-zig  # or build-go, build-rust, etc.
```

### Client Not Found
Ensure sibling client repositories exist:
```bash
ls ../geode-client-{go,python,rust,zig,nodejs}
```

## CI/CD

The harness includes GitLab CI configuration (`.gitlab-ci.yml`) that:
- Builds all client runners
- Runs integration tests against Geode Docker service
- Generates coverage and performance reports
- Publishes HTML reports to GitLab Pages

## License

Apache License 2.0

## Copyright

2024-2025 CodePros
