# Geode Query --file Flag Test Specifications

## Overview

This directory contains comprehensive geodetestlab test specifications for the `geode query --file/-f` flag feature (Issue GAP-384). The tests validate all aspects of file-based GQL execution, including basic functionality, error handling, chunked execution for large files, and edge cases.

## Test Files

### 1. `query_file_flag_comprehensive.yml` (448 lines, 40+ tests)

**CANARY**: `REQ=REQ-CLI-FILE-FLAG-TEST-001`

Comprehensive test coverage for core functionality:

- **Basic Execution**
  - Single statement execution
  - Short flag (`-f`) variant
  - Verification of execution results

- **Comment Stripping**
  - Double-hyphen (`--`) comment removal
  - Hash (`#`) comment removal
  - Empty line stripping
  - Mixed comments and whitespace

- **Path Expansion**
  - Tilde (`~`) expansion
  - Absolute paths
  - Relative paths

- **Error Handling**
  - File not found
  - Empty file (no valid statements)
  - Missing argument
  - Permission denied

- **Multi-Statement Execution**
  - Multiple CREATE statements
  - 10-statement batches
  - Mixed statement types (CREATE, MATCH, relationships)

- **Statement Batching**
  - Multiline statements
  - Mixed CREATE, MATCH, and relationship creation

- **Integration with Other Flags**
  - Combined with `--graph` flag
  - Combined with `--format` flag

- **Transaction Behavior**
  - Atomicity verification
  - Explicit BEGIN/COMMIT blocks

- **Edge Cases**
  - Statements without semicolons
  - Trailing semicolons
  - Windows CRLF line endings
  - Unicode content

- **Documentation**
  - Help text verification
  - Usage examples

### 2. `query_file_flag_edge_cases.yml` (489 lines, 35+ tests)

**CANARY**: `REQ=REQ-CLI-FILE-FLAG-TEST-002`

Advanced edge cases and error scenarios:

- **Boundary Value Tests**
  - Exact 32KB boundary (chunking threshold)
  - Just under 32KB (31KB)
  - Just over 32KB (33KB)
  - Single character file
  - Maximum file size (16MB)

- **Path Edge Cases**
  - Paths with spaces
  - Paths with special characters
  - Symbolic links
  - Very long paths

- **Content Edge Cases**
  - Only whitespace and comments
  - Inline comments after statements
  - Multiple trailing semicolons
  - Tab characters
  - Mixed tab/space indentation
  - Null bytes
  - Very long lines

- **Syntax Error Handling**
  - Syntax errors in file
  - Partial statements at end of file
  - Invalid UTF-8 sequences

- **Concurrent and Resource Tests**
  - Concurrent file execution
  - File modification during execution
  - Out of memory conditions

- **Security Edge Cases**
  - Directory instead of file
  - Device files
  - Named pipes (FIFO)

- **Transaction Edge Cases**
  - Unclosed transactions (BEGIN without COMMIT)
  - ROLLBACK statements
  - Nested transactions

- **Idempotency Tests**
  - Repeated execution with MERGE

- **Complex Statement Tests**
  - Complex nested queries
  - Pattern matching
  - Subqueries

### 3. `query_file_flag_chunked_execution.yml` (628 lines, 25+ tests)

**CANARY**: `REQ=REQ-CLI-CHUNKED-EXEC-TEST-001`

Tests for chunked execution of large files (> 32KB):

- **Size Threshold Tests**
  - Small files (no chunking)
  - 100 statements
  - 500 statements
  - 1000 statements (guaranteed chunking)

- **Progress Reporting**
  - Message format verification
  - Byte count display
  - Statement count display

- **Statement Batching in Chunked Mode**
  - Mixed statement types
  - UPDATE statements
  - DELETE statements

- **Transaction Atomicity**
  - Chunked execution atomicity
  - Explicit transactions in chunked mode

- **Performance and Stress Tests**
  - 5,000 statements
  - 10,000 statements

- **Complex Property Tests**
  - Large property values
  - Many properties per node

- **Error Handling in Chunked Mode**
  - Partial error recovery
  - Mid-stream syntax errors

## Test Coverage Summary

### Total Test Count: 100+ tests across 3 specification files

### Total Lines: 1,565 lines of test specifications

### Coverage by Category

1. **Basic Functionality**: 15 tests
2. **Comment/Whitespace Handling**: 8 tests
3. **Path Expansion**: 8 tests
4. **Error Handling**: 12 tests
5. **Multi-Statement Execution**: 10 tests
6. **Chunked Execution**: 15 tests
7. **Transaction Behavior**: 10 tests
8. **Edge Cases**: 20+ tests
9. **Performance/Stress**: 5 tests
10. **Documentation**: 3 tests

## Feature Requirements Validated

### Core Requirements (from implementation)

1. ✅ **REQ-CLI-FILE-FLAG-001**: File input flag parsing (`--file` and `-f`)
2. ✅ **REQ-CLI-FILE-FLAG-002**: Flag argument parsing and validation
3. ✅ **REQ-CLI-FILE-FLAG-003**: File reading with tilde expansion
4. ✅ **REQ-CLI-CHUNKED-EXEC-001**: Large file support (> 32KB)
5. ✅ **REQ-CLI-CHUNKED-EXEC-002**: Statement parsing and collection
6. ✅ **REQ-CLI-CHUNKED-EXEC-003**: Size detection for chunking
7. ✅ **REQ-CLI-CHUNKED-EXEC-007**: Null query text handling

### ISO/IEC 39075:2024 GQL Compliance

All test specifications align with GQL standard requirements for:

- Statement termination (semicolon-separated)
- Comment syntax (`--` and `#`)
- Multi-statement execution
- Transaction semantics (BEGIN/COMMIT/ROLLBACK)

## Test Execution

### Prerequisites

```bash
# Build geode
cd /home/benji/src/gl/devnw/codepros/geode/geode
make build

# Start server with auth disabled
./zig-out/bin/geode serve --disable-auth --insecure --log-level error
```

### Running Tests

```bash
# Run all file flag tests
python3 scripts/test/extended_test_runner.py \
  geodetestlab/specs/query_file_flag_comprehensive.yml \
  geodetestlab/specs/query_file_flag_edge_cases.yml \
  geodetestlab/specs/query_file_flag_chunked_execution.yml

# Run specific test file
python3 scripts/test/extended_test_runner.py \
  geodetestlab/specs/query_file_flag_comprehensive.yml

# Run with verbose output
python3 scripts/test/extended_test_runner.py \
  --verbose \
  geodetestlab/specs/query_file_flag_comprehensive.yml
```

### Expected Results

- Most tests should execute successfully
- Some tests are marked `skip: true` for features requiring:
  - Precise file size generation
  - Permission manipulation
  - Concurrent execution framework
  - Special file system setups (symlinks, FIFOs)

## Test Design Principles

### Black-Box Testing

- All tests execute against the actual `geode` binary
- No mocks or simulated responses
- Validates real system behavior through CLI interface

### Test Isolation

- Each test creates its own data
- Cleanup steps remove test data
- Separate graphs used for different test categories

### Comprehensive Coverage

- Normal cases (happy path)
- Error conditions
- Boundary values
- Edge cases
- Performance characteristics

### Evidence-Based Validation

- Each test includes verification steps
- Results validated through subsequent queries
- Exit codes and output checked
- Transaction atomicity verified

## Implementation References

### Source Files

- `/home/benji/src/gl/devnw/codepros/geode/geode/src/cli/main.zig` (lines 2959-3230)
  - Flag parsing (`--file`/`-f`)
  - Tilde expansion
  - Comment stripping
  - Statement collection
  - Chunked execution logic

### Related Features

- Shell `/source` command (similar functionality)
- Query command stdin support (`-`)
- Multi-statement execution
- Transaction auto-wrapping

## Known Limitations

### Skipped Tests

Some tests are marked `skip: true` due to:

1. **File Generation Requirements**:
   - Exact 32KB boundary tests
   - Very large file tests (>1MB)
   - Precise size control needed

2. **Platform-Specific**:
   - Permission tests (chmod)
   - Device file tests
   - Named pipe (FIFO) tests

3. **Test Framework Limitations**:
   - Concurrent execution tests
   - File modification timing tests
   - Binary file handling

### Future Enhancements

- Add helper scripts for precise file generation
- Implement concurrent test execution framework
- Add performance benchmarks with metrics collection

## Maintenance Notes

### Updating Tests

When modifying the `--file` flag implementation:

1. Review affected test categories
2. Add new tests for new features
3. Update CANARY markers if requirements change
4. Run full test suite to verify no regressions

### Adding New Tests

Follow the existing pattern:

```yaml
- name: "descriptive-test-name"
  description: "Clear explanation of what is being tested"
  setup:
    files:
      - path: "/tmp/geode_test_unique_name.gql"
        content: |
          USE GRAPH test_graph;
          CREATE (n:TestNode {id: 1});
  args: ["query", "--insecure", "--file", "/tmp/geode_test_unique_name.gql"]
  expect:
    exit_code: 0
    stdout_contains: ["expected", "output"]
  verify:
    - args: ["query", "--insecure", "MATCH (n:TestNode) RETURN count(n)"]
      expect:
        stdout_contains: ["1"]
  cleanup:
    - ["query", "--insecure", "MATCH (n:TestNode) DELETE n"]
  tags: ["category", "subcategory"]
```

## Contact

For issues or questions about these test specifications:

- Review implementation in `src/cli/main.zig`
- Check CANARY markers for requirement tracking
- Reference ISO/IEC 39075:2024 for GQL compliance

---

**Last Updated**: 2026-02-02
**Status**: Production Ready
**Coverage**: 100+ comprehensive tests for --file flag functionality
