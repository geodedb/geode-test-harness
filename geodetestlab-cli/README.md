# geodetestlab-cli

> **Location**: This is the CLI testing component of the geode-test-harness. It is located at `geode-test-harness/geodetestlab-cli/` in the monorepo.

`geodetestlab` is a comprehensive CLI testing system specifically designed for the Geode graph database. It executes and verifies Geode CLI operations against declarative YAML specifications, supports intelligent fuzzing using language models, manages server lifecycle, and generates detailed reports suitable for CI/CD pipelines.

## Overview

The system provides end-to-end testing capabilities for Geode's CLI interface, including:

- **Server Management**: Automatic startup/shutdown of Geode server instances for testing
- **GQL Query Testing**: Specialized assertions for Graph Query Language results  
- **Authentication Testing**: User management, role-based access control, and security validation
- **Intelligent Fuzzing**: LLM-powered test case generation with Geode-specific patterns
- **Secret Management**: Secure handling of credentials and API tokens
- **Rich Reporting**: Detailed JSON reports and structured logging

```
spec ──► resolver ──► server ──► runner ──► asserter ──► reporter
│            │           │          │           └─► JSON summary
│            │           │          └─► JSONL logs  
│            │           └─► managed Geode server
│            └─► resolves secrets from env/keyring
└─► YAML specification with Geode-specific features
```

## Quick Start

### Installation

Requires **Python 3.11+**. Install in development mode:

```bash
cd geodetestlab
python -m venv .venv && source .venv/bin/activate
pip install -U pip
pip install -e .[dev]
```

This installs the `geodetestlab` command and all dependencies.

### Basic Usage

Run basic Geode functionality tests:

```bash
geodetestlab run --spec specs/geode_basic.yml
```

Run with managed server and fuzzing:

```bash
geodetestlab run --spec specs/geode_advanced.yml --max-cases 10
```

Run authentication and security tests:

```bash
export GEODE_ADMIN_PASSWORD=secure_password
geodetestlab run --spec specs/geode_auth.yml
```

## Key Features

### 🗄️ Geode Server Management

Automatically manages Geode server instances during testing:

```yaml
cli:
  binary: "geode"
  server:
    enabled: true
    port: 3141  # or null for auto-allocation
    data_dir: null  # temporary directory
    startup_timeout_ms: 60000
    cleanup: true
    args: ["--log-level", "debug"]
```

### 🔍 GQL-Specific Assertions

Rich assertions tailored for graph database testing:

```yaml
tests:
  - name: "complex-query"
    args: ["query", "MATCH (n:Person) RETURN n"]
    expect:
      exit_code: 0
      geode_query:
        row_count: 5
        columns: ["n"]
        contains_node:
          name: "Alice"
        execution_time_ms: 1000
```

### 🤖 Intelligent Fuzzing

Three LLM providers for sophisticated test generation:

- **`mock`**: Deterministic, offline patterns for CI/CD
- **`openai`**: OpenAI-compatible API integration  
- **`geode-ai`**: Specialized Geode database patterns

```yaml
fuzz:
  enabled: true
  provider: "geode-ai"
  max_cases: 20
  geode_specific: true
  include_gql: true
  include_auth: true
```

### 🔐 Security & Secrets

Secure credential management with multiple sources:

```yaml
secrets:
  admin_token:
    source: "env"
    key: "GEODE_ADMIN_TOKEN"
    required: true
  api_key:
    source: "keyring"
    service: "geodetestlab"
    key: "production_api_key"
    required: false
```

### 📊 Rich Reporting

Comprehensive test reporting and logging:

```bash
# JSON summary for CI
geodetestlab run --spec tests.yml --ci

# Detailed report
geodetestlab run --spec tests.yml --report-json results.json

# Verbose output with server logs
geodetestlab run --spec tests.yml --verbose
```

## Command Reference

### Main Commands

```bash
# Execute test suite
geodetestlab run --spec <path> [options]

# Validate and list secrets
geodetestlab secrets check --spec <path>
geodetestlab secrets list --spec <path> [--show]

# Manage server instances  
geodetestlab server start [--port 3141] [--background]
geodetestlab server stop [--port 3141] [--force]
geodetestlab server status [--port 3141]
```

### Run Options

| Option | Description | Default |
|--------|-------------|---------|
| `--llm-provider` | Fuzzing provider: mock, openai, geode-ai | mock |
| `--model` | LLM model (for openai/geode-ai) | gpt-3.5-turbo |
| `--max-cases` | Maximum fuzz cases to generate | 0 |
| `--timeout-ms` | Per-test timeout | 30000 |
| `--server-timeout-ms` | Server startup timeout | 60000 |
| `--dry-run` | Enumerate tests without execution | false |
| `--ci` | Non-interactive mode for CI/CD | false |
| `--verbose` | Show detailed output and server logs | false |

## Specification Format

### Basic Structure

```yaml
version: "1.0"
name: "Test Suite Name"
description: "Optional description"

cli:
  binary: "geode"
  server:
    enabled: true
    # Server configuration...
  client:
    server_address: "127.0.0.1:3141"
    timeout_ms: 30000
    format: "json"

tests:
  - name: "test-name"
    description: "Test description"
    args: ["query", "RETURN 1"]
    expect:
      exit_code: 0
      # Assertions...
```

### Scenarios (server mode)

Add a top-level `scenarios` list to define how each suite runs. When omitted, the runner uses the default server scenario which starts a managed QUIC server for testing.

```yaml
scenarios:
  - name: "server"
    roles:
      server:
        enabled: true
        default_flags: ["--log-level", "info"]  # appended to geode serve
      client:
        mode: "server"
        default_flags: ["--server", "${server_address}", "--insecure"]
```

All tests now run against a real QUIC server. The test runner manages server lifecycle (start/stop) and ensures proper isolation between test suites using separate data directories and port allocation.

### Test Case Features

```yaml
tests:
  - name: "comprehensive-test"
    description: "Multi-faceted test with setup/cleanup"
    args: ["query", "MATCH (n) RETURN count(n)"]

    # Pre-test setup
    setup:
      - "query \"CREATE (n:Test)\""

    # Post-test cleanup  
    cleanup:
      - "query \"MATCH (n:Test) DELETE n\""

    # Custom timeout
    timeout_ms: 60000

    # Test categorization
    tags: ["query", "performance"]

    expect:
      exit_code: 0
      stdout_json_assert:
        - expression: "results[0].count"
          matches_regex: "\\d+"
      geode_query:
        min_rows: 1
        execution_time_ms: 5000
```

### Advanced Assertions

```yaml
expect:
  # Basic assertions
  exit_code: 0
  stdout_exact: "Expected exact output"
  stdout_contains: ["substring1", "substring2"]
  stdout_regex: ["pattern1", "pattern2"]
  stderr_contains: ["error_text"]

  # JSON path assertions
  stdout_json_assert:
    - expression: "results[0].name"
      equals: "Alice"
    - expression: "status"
      not_equals: "error"
    - expression: "message"
      matches_regex: "completed in \\d+ms"

  # Geode-specific assertions
  geode_query:
    row_count: 5               # Exact row count
    min_rows: 1                # Minimum rows
    max_rows: 100              # Maximum rows
    columns: ["id", "name"]    # Expected columns
    execution_time_ms: 1000    # Max execution time

    # Content validation
    contains_node:
      name: "Alice"
      age: 30
    contains_edge:
      type: "KNOWS"
      since: 2020

  # Server health
  server_responsive: true
```

## Example Specifications

The project includes comprehensive example specifications:

- **`specs/geode_basic.yml`**: Core functionality and smoke tests
- **`specs/geode_advanced.yml`**: Complex queries and performance testing
- **`specs/geode_auth.yml`**: Authentication, authorization, and security
- **`specs/geode_fuzz.yml`**: Fuzzing and edge case testing

### Sample: Basic Tests

```yaml
version: "1.0"
name: "Geode Basic Tests"

cli:
  binary: "geode"
  server:
    enabled: true
    cleanup: true

tests:
  - name: "simple-return"
    args: ["query", "RETURN 1 AS result"]
    expect:
      exit_code: 0
      geode_query:
        row_count: 1
        columns: ["result"]

  - name: "create-node"
    args: ["query", "CREATE (n:Person {name: 'Alice'}) RETURN n"]
    expect:
      exit_code: 0
      geode_query:
        contains_node:
          name: "Alice"
```

## Environment Variables

### Required for OpenAI Provider

```bash
export OPENAI_API_KEY=sk-...
export OPENAI_BASE_URL=https://api.openai.com  # optional
export OPENAI_MODEL=gpt-4                      # optional
```

### Geode Configuration

```bash
export GEODE_BINARY=/path/to/geode             # Binary location
export GEODE_ADMIN_PASSWORD=secure_password    # Admin credentials
export GEODE_TEST_TOKEN=test_token              # Test API token
```

### Logging and Debugging

```bash
export GEODE_LOG_LEVEL=debug                   # Server log level
export GEODETESTLAB_VERBOSE=true               # Verbose output
```

## CI/CD Integration

### GitHub Actions Example

```yaml
name: Geode CLI Tests
on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Setup Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.11'

      - name: Install geodetestlab
        run: |
          cd geodetestlab
          pip install -e .

      - name: Build Geode
        run: make build

      - name: Run basic tests
        run: |
          geodetestlab run --spec geodetestlab/specs/geode_basic.yml --ci

      - name: Run fuzzing tests
        env:
          OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
        run: |
          geodetestlab run \
            --spec geodetestlab/specs/geode_fuzz.yml \
            --llm-provider openai \
            --max-cases 10 \
            --ci
```

### Exit Codes

- **0**: All tests passed
- **1**: One or more tests failed
- **2**: Specification validation error
- **3**: Runtime/setup error (binary not found, server startup failure)
- **4**: Secret resolution error

## Security Considerations

### Secret Protection

- All secret values are automatically redacted from logs and reports
- Secrets are never persisted to disk in plaintext
- Geode-specific credential patterns are automatically detected and masked
- Use `--show` flag only in secure environments

### Safe Fuzzing

- Argument sanitization prevents shell injection attacks
- Timeout enforcement prevents resource exhaustion
- Server isolation through temporary data directories
- Automatic cleanup of test artifacts

### Audit Trail

- Complete command execution logging to `.geodetestlab/logs/`
- Structured JSONL format for analysis
- Integration with Geode's audit logging features
- Tamper-evident log formats

## Development

### Running Tests

```bash
cd geodetestlab
pytest -v
```

### Code Quality

```bash
# Format code
black geodetestlab/ tests/
isort geodetestlab/ tests/

# Type checking
mypy geodetestlab/

# Linting
flake8 geodetestlab/ tests/
```

### Adding New Assertions

1. Extend `TestExpect` model in `core/spec.py`
2. Implement evaluation logic in `core/assertions.py`
3. Add tests in `tests/test_assertions.py`
4. Update documentation

### Custom LLM Providers

1. Implement `LLMProvider` protocol in `providers/`
2. Register in `providers/__init__.py:get_provider()`
3. Add provider-specific tests
4. Update CLI help and documentation

## Troubleshooting

### Common Issues

**Server startup failures:**

```bash
# Check Geode binary location
export GEODE_BINARY=/path/to/geode
geodetestlab server status

# Verify port availability
geodetestlab server start --port 9443
```

**Secret resolution errors:**

```bash
# Validate secret configuration
geodetestlab secrets check --spec your_spec.yml

# List configured secrets
geodetestlab secrets list --spec your_spec.yml --show
```

**Test execution timeouts:**

```bash
# Increase timeouts for complex queries
geodetestlab run --spec tests.yml --timeout-ms 60000 --server-timeout-ms 120000
```

### Debug Mode

```bash
# Maximum verbosity
geodetestlab run --spec tests.yml --verbose --dry-run

# Server logs only
geodetestlab server start --port 3141 --verbose

# Detailed error reporting
PYTHONPATH=. python -m geodetestlab.cli run --spec tests.yml --verbose
```

## License

MIT License - see LICENSE file for details.

## Contributing

1. Fork the repository
2. Create a feature branch
3. Add tests for new functionality
4. Ensure all tests pass: `pytest`
5. Submit a pull request

For bugs and feature requests, please use the GitHub issue tracker.
