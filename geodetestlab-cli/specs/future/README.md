# Future Test Specs

This directory contains test specifications that depend on features not yet implemented in Geode.

## Files

### chained_operations.yml

- **Depends on**: `reduce()` function, `CREATE SCHEMA`, typed `CREATE NODE`
- **Status**: Parser does not support `reduce()` function syntax
- **When to move back**: After implementing `reduce()` in the GQL parser

### complex_multi_level_nesting.yml

- **Depends on**: `reduce()` function, complex nested subqueries
- **Status**: Parser does not support `reduce()` function syntax
- **When to move back**: After implementing `reduce()` in the GQL parser

## How to re-enable

Once the required features are implemented:

1. Move the spec file back to `geodetestlab/specs/`
2. Run the tests: `python3 scripts/test/extended_test_runner.py geodetestlab/specs/<filename>.yml`
3. Fix any remaining issues
