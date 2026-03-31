# Geode Cross-Runner Protocol

This document defines the standard protocol for all language-specific test runners in the Geode Test Harness. By adhering to this protocol, runners can be implemented in any language (Zig, Go, Python, Rust, Node.js, etc.) while remaining fully compatible with the central `geodetestlab-cli` orchestrator.

## 1. Command-Line Interface (CLI)

All runners MUST accept the following command-line arguments:

- `--spec <path>`: (Required) Path to the YAML test specification file.
- `--server <host:port>`: (Required) Address of the Geode server to connect to.
- `--transport <protocol>`: (Optional) The transport protocol to use. Valid values are `quic` or `grpc`. Defaults to `quic`.
- `--json`: (Optional) If provided, the runner must output its results as a JSON array to `stdout`.
- `--verbose` or `-v`: (Optional) If provided, the runner should output debug/trace information to `stderr`.

Example invocation by the orchestrator:

```bash
./runners/go_runner --spec specs/my_test.yml --server 127.0.0.1:3141 --transport quic --json
```

## 2. Test Specification Handling

Runners must parse the provided YAML specification file. The file structure is defined by the `geodetestlab-cli` schema.

Key fields the runner must handle:

- `tests`: A list of test cases to execute.
  - `name`: The name of the test case.
  - `query`: The GQL query string to execute.
  - `expected`: An object defining the expected outcome.
    - `error`: If true, the query is expected to fail.
    - `rows`: The exact number of rows expected in the result.

Runners should ignore fields they do not understand or that are meant for the orchestrator (e.g., `mode`, `server_args`).

## 3. Server Connection

Runners must connect to the Geode server specified by the `--server` argument.

- The connection must use the transport protocol specified by `--transport` (`quic` or `grpc`).
- If the transport is not supported by the runner, it should immediately exit with an error.
- Authentication (if required) should use the default test credentials unless overridden by environment variables.

## 4. Output Contract

### Standard Output (stdout)

When the `--json` flag is provided, the runner MUST output a single valid JSON array to `stdout`. No other text may be written to `stdout` in this mode.

Each object in the JSON array represents the result of a single test case and must have the following structure:

```json
[
  {
    "test_name": "name-of-the-test",
    "status": "passed", // "passed", "failed", or "error"
    "error": null,      // String describing the failure/error if status != "passed"
    "details": {        // Optional additional information
      "rows_returned": 5,
      "execution_time_ms": 12
    }
  }
]
```

When `--json` is NOT provided, the runner may output human-readable text to `stdout` (e.g., `✓ test-name` or `✗ test-name: error message`).

### Standard Error (stderr)

All logging, debugging, and verbose output MUST be written to `stderr`. This ensures that the JSON output on `stdout` remains parseable by the orchestrator.

### Exit Codes

- `0`: All tests executed successfully and all assertions passed.
- `1`: One or more tests failed their assertions, or a general execution error occurred.
- `2`: Invalid arguments provided or spec file could not be parsed.

## 5. Error Handling

- If a query fails but the test expected it to fail (`expected.error: true`), the test should be marked as `passed`.
- If a query fails unexpectedly, the test should be marked as `failed`, and the error message from the server should be included in the `error` field of the JSON output.
- If the runner cannot connect to the server, it should output a JSON array with a single error entry (if `--json` is set) and exit with code `1`.
