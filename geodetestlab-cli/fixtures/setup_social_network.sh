#!/usr/bin/env bash
# Test Fixture Setup: Social Network Database
# This script loads the social network migration data to create a test database
# with pre-populated data for integration testing.

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
MIGRATIONS_DIR="$PROJECT_ROOT/migrations/mg0"
GEODE_BIN="${GEODE_BIN:-$PROJECT_ROOT/zig-out/bin/geode}"
GEODE_SERVER="${GEODE_SERVER:-127.0.0.1:3141}"

echo "=== Social Network Test Fixture Setup ==="
echo "Project Root: $PROJECT_ROOT"
echo "Migrations Dir: $MIGRATIONS_DIR"
echo "Geode Binary: $GEODE_BIN"
echo "Geode Server: $GEODE_SERVER"
echo

# Check if geode binary exists
if [ ! -f "$GEODE_BIN" ]; then
    echo "ERROR: Geode binary not found at $GEODE_BIN"
    echo "Please build geode first: make build"
    exit 1
fi

# Check if migrations directory exists
if [ ! -d "$MIGRATIONS_DIR" ]; then
    echo "ERROR: Migrations directory not found at $MIGRATIONS_DIR"
    exit 1
fi

echo "Loading migration files..."
echo

# Function to execute a migration file
execute_migration() {
    local migration_file=$1
    local migration_name=$(basename "$migration_file")

    echo ">>> Executing: $migration_name"

    # Read the migration file and execute it line by line
    # Skip comment lines and empty lines
    local current_statement=""
    local line_count=0

    while IFS= read -r line || [ -n "$line" ]; do
        line_count=$((line_count + 1))

        # Skip pure comment lines (starting with --)
        if [[ "$line" =~ ^[[:space:]]*--.*$ ]] || [[ -z "${line// }" ]]; then
            continue
        fi

        # Accumulate statement
        current_statement="$current_statement $line"

        # Check if statement is complete (ends with semicolon)
        if [[ "$line" =~ \;[[:space:]]*$ ]]; then
            # Remove leading/trailing whitespace and semicolon
            current_statement=$(echo "$current_statement" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//' | sed 's/;[[:space:]]*$//')

            if [ -n "$current_statement" ]; then
                # Execute the statement
                if ! echo "$current_statement" | "$GEODE_BIN" query --server "$GEODE_SERVER" --insecure - 2>&1 | grep -q "status_class\":\"00000"; then
                    echo "WARNING: Statement may have failed (line ~$line_count): ${current_statement:0:80}..."
                fi
            fi

            current_statement=""
        fi
    done < "$migration_file"

    # Execute remaining statement if exists (no semicolon at end)
    if [ -n "${current_statement// }" ]; then
        current_statement=$(echo "$current_statement" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')
        if ! echo "$current_statement" | "$GEODE_BIN" query --server "$GEODE_SERVER" --insecure - 2>&1 | grep -q "status_class\":\"00000"; then
            echo "WARNING: Final statement may have failed: ${current_statement:0:80}..."
        fi
    fi

    echo "    ✓ Completed: $migration_name"
    echo
}

# Execute migrations in order
for migration_file in "$MIGRATIONS_DIR"/*.gql; do
    if [ -f "$migration_file" ]; then
        execute_migration "$migration_file"
    fi
done

echo
echo "=== Verifying Loaded Data ==="
echo

# Verify data was loaded
echo ">>> Checking node counts..."
NODE_COUNT=$("$GEODE_BIN" query --server "$GEODE_SERVER" --insecure "MATCH (n) RETURN count(n) AS total" 2>/dev/null | grep -o '"rows":\[\[[0-9]*\]\]' | grep -o '[0-9]*' || echo "0")
echo "    Total nodes: $NODE_COUNT"

echo ">>> Checking relationship counts..."
REL_COUNT=$("$GEODE_BIN" query --server "$GEODE_SERVER" --insecure "MATCH ()-[r]->() RETURN count(r) AS total" 2>/dev/null | grep -o '"rows":\[\[[0-9]*\]\]' | grep -o '[0-9]*' || echo "0")
echo "    Total relationships: $REL_COUNT"

echo
if [ "$NODE_COUNT" -gt 0 ]; then
    echo "✓ Test fixture setup completed successfully!"
    echo "  - $NODE_COUNT nodes created"
    echo "  - $REL_COUNT relationships created"
    echo
    echo "The database is now populated with social network test data."
    echo "You can run tests that depend on this data."
    exit 0
else
    echo "⚠ WARNING: No nodes were created. Check migration execution above."
    exit 1
fi
