#!/bin/bash
set -e

# Unified test runner for Geode Test Harness
# Usage: ./scripts/run_all_tests.sh --geode-binary /path/to/geode

GEODE_BINARY=""
PORT=3141

while [[ "$#" -gt 0 ]]; do
    case $1 in
        --geode-binary) GEODE_BINARY="$2"; shift ;;
        -h|--help)
            echo "Usage: $0 [--geode-binary /path/to/geode]"
            exit 0
            ;;
        *) echo "Unknown parameter passed: $1"; exit 1 ;;
    esac
    shift
done

if [ -n "$GEODE_BINARY" ]; then
    export GEODE_BINARY="$GEODE_BINARY"
    echo "Using Geode binary: $GEODE_BINARY"
else
    echo "Warning: No --geode-binary specified. Will use the default from Makefile."
    GEODE_BINARY=$(make -s -f <(echo "include Makefile" && echo "print_binary: ; @echo \$(GEODE_BINARY)") print_binary)
    export GEODE_BINARY="$GEODE_BINARY"
fi

if [ ! -x "$GEODE_BINARY" ]; then
    echo "Error: GEODE_BINARY ($GEODE_BINARY) is not executable or not found."
    exit 1
fi

echo "============================================================"
echo "Running Geode Test Harness Unified Suite"
echo "============================================================"

# 1. Run the geodetestlab-cli unit tests
echo ""
echo "=== 1. Running geodetestlab-cli Unit Tests ==="
make test-unit

# 2. Run the geodetestlab-cli integration and client tests
echo ""
echo "=== 2. Running geodetestlab-cli Tests (Client Tests) ==="
make test

# 3. Run shell stability tests
echo ""
echo "=== 3. Running Shell Tests ==="
make test-shell

# 4. Run load tests
echo ""
echo "=== 4. Running Load Tests ==="
# loadtest-go and loadtest-python expect a running server
DATA_DIR=$(mktemp -d)
echo "Starting Geode server on port $PORT for load tests..."
GEODE_DEFAULT_PASSWORD="${GEODE_DEFAULT_PASSWORD:-${GEODE_ADMIN_PASSWORD:-GeodeTestPassword123!}}" \
GEODE_ADMIN_PASSWORD="${GEODE_ADMIN_PASSWORD:-${GEODE_DEFAULT_PASSWORD:-GeodeTestPassword123!}}" \
GEODE_DISABLE_AUDIT=1 \
"$GEODE_BINARY" serve --data-dir "$DATA_DIR" --listen "127.0.0.1:$PORT" --log-level info &
SERVER_PID=$!

# Wait for server to start
sleep 2

# Check if server is running
if ! kill -0 $SERVER_PID 2>/dev/null; then
    echo "Error: Geode server failed to start for load tests."
    exit 1
fi

# Run the load tests
# Disable set -e temporarily so we ensure we clean up the server even if tests fail
set +e
make loadtest
LOADTEST_EXIT_CODE=$?
set -e

# Stop the server
echo "Stopping Geode server (PID: $SERVER_PID)..."
kill $SERVER_PID || true
wait $SERVER_PID 2>/dev/null || true
rm -rf "$DATA_DIR"

if [ $LOADTEST_EXIT_CODE -ne 0 ]; then
    echo "Load tests failed with exit code $LOADTEST_EXIT_CODE"
    exit $LOADTEST_EXIT_CODE
fi

echo ""
echo "============================================================"
echo "All tests completed successfully!"
echo "============================================================"
