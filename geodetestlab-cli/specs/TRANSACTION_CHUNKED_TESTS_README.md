# Transaction Chunked Execution Test Suite

## Overview

This test suite provides comprehensive black-box testing for transaction handling in the `geode query --file` command when files exceed the 32KB chunking threshold. These tests verify that transaction state is correctly maintained across multiple RUN_GQL requests on the same QUIC connection.

## Test Files

### 1. transaction_chunked_execution.yml (580 lines, 26KB)

**Focus**: Core transaction semantics across chunk boundaries

**Key Test Scenarios** (26 tests):

- **Transaction within single chunk** (baseline tests)
  - Basic BEGIN/COMMIT within < 32KB file
  - ROLLBACK within single chunk

- **Transaction spanning chunks** (critical tests)
  - BEGIN in chunk 1, work across chunks 2-3, COMMIT in chunk 4
  - Verification that all 1000+ nodes persist correctly
  - Specific node verification from different chunks (first, middle, last)

- **Partial failure handling**
  - Syntax error mid-transaction causes full rollback
  - Constraint violation triggers transaction failure
  - Atomicity verification (all-or-nothing)

- **Multiple transactions in one file**
  - Three separate complete transactions (300 nodes each)
  - Mixed success/failure scenarios with isolation

- **Auto-commit mode**
  - Statements without explicit transactions
  - Partial failure behavior in auto-commit mode

- **Complex operations across chunks**
  - Interleaved CREATE, MATCH, SET, DELETE operations
  - Relationship creation and traversal
  - 300 created - 100 deleted = 200 remaining verification

- **Edge cases**
  - Files exactly at 32KB boundary
  - Empty transactions in chunked files
  - Very large transactions (5000 statements)

**File Generation Pattern**:

```bash
for i in {1..1000}; do
  echo "CREATE (n:Label {id: $i, description: 'Extended data...'});" >> file.gql
done
```

### 2. transaction_chunked_advanced.yml (474 lines, 21KB)

**Focus**: Advanced transaction features and savepoints

**Key Test Scenarios** (14 tests):

- **Savepoints across chunks** (3 tests, currently skipped)
  - Basic SAVEPOINT and ROLLBACK TO
  - Nested savepoints (outer/inner levels)
  - RELEASE SAVEPOINT verification
  - Tests verify batch 1 + batch 3 persist, batch 2 rolled back

- **Transaction isolation edge cases**
  - Concurrent read visibility during chunked transaction
  - Baseline data + in-transaction data verification

- **Resource limits and stress testing**
  - 10,000 statement transaction
  - Very long transaction handling

- **Graph switching within transactions**
  - USE GRAPH mid-transaction behavior
  - Cross-graph transaction semantics

- **Atomicity verification**
  - 2001 nodes all-or-nothing test
  - Rollback after 3000 nodes across many chunks

- **Transaction state recovery**
  - State consistency across 500 CREATE + 500 UPDATE + 100 VERIFY
  - Dependencies maintained across chunk boundaries

- **Mixed execution modes**
  - Auto-commit + explicit transactions in same file
  - 200 auto + 300 explicit + 200 auto = 700 total

- **Error recovery**
  - Failed transaction followed by successful transaction
  - Continuation after partial failure

**Notable Pattern**:

```bash
# Nested savepoint test structure
START TRANSACTION;
CREATE (level 0 data);
SAVEPOINT outer;
CREATE (level 1 data);
SAVEPOINT inner;
CREATE (level 2 data);  # Will be rolled back
ROLLBACK TO SAVEPOINT inner;
CREATE (more level 1 data);
COMMIT;
```

### 3. transaction_chunked_connection_state.yml (448 lines, 20KB)

**Focus**: QUIC connection state persistence and read-your-writes consistency

**Key Test Scenarios** (12 tests):

- **Connection persistence**
  - Verification that same connection handles all chunks
  - 1200 nodes across multiple chunks

- **Transaction ID consistency**
  - Transaction context maintained across chunks
  - 1500 CREATE + 500 UPDATE verification

- **Interleaved operations**
  - Pattern repeated 8 times: CREATE 100, UPDATE 50, DELETE 25
  - Result: 800 created - 200 deleted = 600 nodes

- **Read-your-writes consistency** (critical test)
  - Chunk 1: CREATE nodes with phase='created'
  - Chunk 2: MATCH and update to phase='updated'
  - Chunk 3: MATCH updated nodes and SET verified=true
  - Verifies all 400 nodes have phase='updated' AND verified=true

- **Relationship visibility**
  - 600 nodes created
  - 299 relationships created between adjacent nodes
  - 149 relationships verified (property added)

- **Path query validation**
  - 500 node chain with NEXT relationships
  - Path query verification: node 1 to node 10 (length 9)

- **Session parameter interaction** (skipped if not supported)
  - SESSION SET VALUE $batch_id = 42
  - All 800 nodes should have batch_id: 42

- **Transaction abort cleanup**
  - 1500 nodes created then ROLLBACK
  - Verify zero AbortCleanup nodes
  - New transaction with 300 AfterAbort nodes succeeds

- **Aggregation queries**
  - 1000 nodes with sequential values
  - COUNT, SUM (500500), MIN (1), MAX (1000) verification

- **Deterministic execution**
  - Sequential ID assignment
  - Verification of IDs 1, 500, 1000 exist

**Critical Test Pattern**:

```bash
# Read-your-writes across chunks
START TRANSACTION;
# Chunk 1
CREATE (n:Test {id: i, phase: 'created'});
# Chunk 2
MATCH (n:Test {id: i, phase: 'created'}) SET n.phase = 'updated';
# Chunk 3
MATCH (n:Test {id: i, phase: 'updated'}) SET n.verified = true;
COMMIT;
```

## Test Coverage Summary

### Total Test Count: 52 tests across 3 files

**By Category**:

- Baseline/Single-chunk: 4 tests
- Spanning chunks: 12 tests
- Partial failure: 6 tests
- Multiple transactions: 4 tests
- Auto-commit: 3 tests
- Complex operations: 5 tests
- Edge cases: 6 tests
- Savepoints: 3 tests (skipped)
- Connection state: 9 tests

**By Status**:

- Active tests: 49
- Skipped tests: 3 (savepoints not implemented, session params)
- Long-running tests: 0 (all enabled for comprehensive testing)

## Chunking Mechanism

**Threshold**: 32KB (32,768 bytes)

**How Chunking is Triggered**:
Files are generated with extended property values to exceed 32KB:

```bash
# ~160 bytes per statement
for i in {1..200}; do
  echo "CREATE (n:Test {id: $i, description: 'Extended property data to ensure chunking occurs...'});"
done
# ~200 statements × 160 bytes = ~32KB
```

**Verification**:
Tests check for chunking messages in stdout:

```yaml
expect:
  stdout_contains: ["Large file detected", "chunked execution"]
```

## Black-Box Testing Principles

These tests follow strict black-box methodology:

1. **No implementation assumptions** - Tests verify observable behavior only
2. **Data persistence verification** - All tests verify via subsequent MATCH queries
3. **No internal state inspection** - Tests use COUNT, properties, relationships
4. **Isolation through cleanup** - Each test has dedicated cleanup steps
5. **Deterministic assertions** - Exact counts, specific values, no ranges

**Verification Pattern**:

```yaml
verify:
  - args: ["query", "--insecure", "MATCH (n:Label) RETURN count(n) AS cnt"]
    expect:
      stdout_contains: ["1000"]
```

## Test Execution

### Running Individual Test Files

```bash
# Run specific test file
python3 scripts/test/extended_test_runner.py geodetestlab/specs/transaction_chunked_execution.yml

# Run with specific tags
python3 scripts/test/extended_test_runner.py geodetestlab/specs/transaction_chunked_execution.yml --tags chunked,transaction
```

### Running All Transaction Chunked Tests

```bash
# Run all three files
for file in geodetestlab/specs/transaction_chunked*.yml; do
  python3 scripts/test/extended_test_runner.py "$file"
done
```

### Prerequisites

- Geode server must support `--disable-auth --insecure` flags
- QUIC transport must be enabled (standard configuration)
- Server auto-started by test framework (no manual setup needed)

## Expected Behavior

### Successful Transaction Spanning Chunks

```
1. BEGIN TRANSACTION (chunk 1, statements 1-X)
2. CREATE nodes (chunk 2, statements X-Y)
3. UPDATE nodes (chunk 3, statements Y-Z)
4. COMMIT (chunk N, final statements)

Result: All operations committed atomically
Verification: All nodes exist with updates applied
```

### Failed Transaction Mid-Stream

```
1. BEGIN TRANSACTION (chunk 1)
2. CREATE 400 valid nodes (chunk 2)
3. Syntax error (chunk 3)
4. More statements (chunk 4)

Result: Transaction rolled back completely
Verification: Zero nodes exist
```

### Auto-Commit Mode

```
1. CREATE statements (no BEGIN) (chunk 1)
2. More CREATE statements (chunk 2)
3. Error occurs (chunk 3)

Result: Chunks 1-2 may be committed (implementation dependent)
Verification: Tests check for 0 or 400 nodes (both valid)
```

## Known Limitations & Future Work

### Not Yet Tested (Awaiting Implementation)

1. **Savepoints**: Tests exist but are skipped (skip: true)
   - SAVEPOINT/ROLLBACK TO across chunks
   - Nested savepoints
   - RELEASE SAVEPOINT

2. **Session Parameters in Transactions**: Test skipped
   - SESSION SET VALUE interaction with transactions
   - Parameter visibility across chunks

3. **Isolation Levels**: Not tested
   - READ UNCOMMITTED, READ COMMITTED, REPEATABLE READ, SERIALIZABLE
   - Phantom read prevention across chunks

### Edge Cases Not Covered

1. **Network failures mid-chunk**: QUIC reconnection behavior
2. **Server restart during transaction**: Durability guarantees
3. **Concurrent transactions**: Multi-client chunk interference
4. **Resource exhaustion**: Memory limits during large transactions

## CANARY Governance Tracking

Each test file includes CANARY markers:

- `transaction_chunked_execution.yml`: REQ=REQ-TXN-CHUNKED-EXEC-001
- `transaction_chunked_advanced.yml`: REQ=REQ-TXN-CHUNKED-ADVANCED-001
- `transaction_chunked_connection_state.yml`: REQ=REQ-TXN-CHUNKED-CONN-001

These markers track transaction chunking requirements in the governance system.

## Success Criteria

A test is considered **PASSING** if:

1. Exit code matches expected (0 for success, 1 for failures)
2. Stdout contains expected messages (chunking indicators, etc.)
3. All verification queries return expected results
4. Cleanup successfully removes test data

A test suite is **PRODUCTION READY** if:

- All non-skipped tests pass (currently 49/49 expected)
- Skipped tests have documented reasons and tickets
- Coverage includes all major transaction scenarios
- Edge cases are identified and documented

## GQL Compliance

These tests verify ISO/IEC 39075:2024 compliance for:

- **Section 19.1**: START TRANSACTION statement
- **Section 19.2**: COMMIT statement
- **Section 19.3**: ROLLBACK statement
- **Transaction Atomicity**: All-or-nothing semantics
- **Transaction Isolation**: Read-your-writes consistency

## Troubleshooting

### Test Failures

**Symptom**: Nodes not persisting after COMMIT

- Check: Transaction state maintained across chunks
- Verify: QUIC connection not being reset between chunks
- Debug: Add logging to connection handler

**Symptom**: "Transaction already active" errors

- Check: Transaction state cleanup after COMMIT/ROLLBACK
- Verify: State files cleared in /tmp/geode-session-*
- Debug: Review txn_session.zig state management

**Symptom**: Incorrect node counts

- Check: Auto-commit vs explicit transaction semantics
- Verify: Error handling in chunked execution
- Debug: Review statement batching logic

### Common Issues

1. **File not large enough**: Increase loop iterations or property sizes
2. **Cleanup failures**: Ensure DETACH DELETE for nodes with relationships
3. **Timing issues**: Increase server startup timeout if needed

---

**Created**: 2026-02-02
**Author**: Claude Code (Test Specification)
**Status**: Ready for execution
**Coverage**: 52 comprehensive black-box integration tests
**Purpose**: Verify transaction handling across 32KB chunk boundaries in `geode query --file`
