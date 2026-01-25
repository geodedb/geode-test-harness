# Requirements Mirror

> **Last Updated:** 2026-01-24
> **GitLab Project:** [devnw/codepros/geode/geode-test-harness](https://gitlab.com/devnw/codepros/geode/geode-test-harness)
> **Source of Truth:** GitLab Issues

This document is a **flatfile mirror** of requirements tracked in GitLab. GitLab is the authoritative source of truth.

## Open Issues by Priority

### High Priority

| Issue | Type | Title |
|-------|------|-------|
| [#5](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/5) | Feature | GAP-0005: Missing CI/CD Pipeline Configuration |

### Medium Priority

| Issue | Type | Title |
|-------|------|-------|
| [#1](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/1) | Bug | GAP-0001: Missing TLS Certificate Directory |
| [#2](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/2) | Feature | GAP-0002: Incomplete Connection Pool Step Type Support |
| [#4](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/4) | Feature | GAP-0004: Missing Multi-Connection Test Support |
| [#6](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/6) | Enhancement | GAP-0006: Missing README Documentation |

### Low Priority

| Issue | Type | Title |
|-------|------|-------|
| [#3](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/3) | Feature | GAP-0003: Missing Benchmark Execution Support |
| [#7](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/7) | Bug | GAP-0007: Outdated Git Remote URL After Project Move |
| [#8](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/8) | Enhancement | GAP-0008: Undocumented Skipped Tests |

## Requirements by Category

### Test Harness Core

- Test specification format (YAML-based)
- Multi-language runner support (Python, Go, Rust, Zig, Node.js)
- Docker-based server management
- JSON/HTML report generation
- Parallel and sequential test execution

### Connection Management

- Basic connection lifecycle (connect/disconnect)
- Connection pooling ([#2](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/2) - OPEN)
- Multi-connection support ([#4](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/4) - OPEN)
- TLS certificate handling ([#1](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/1) - OPEN)

### Transaction Support

- BEGIN/COMMIT/ROLLBACK operations
- Nested transaction handling
- Rollback on error
- Auto-commit mode

### Query Operations

- Simple RETURN statements
- Parameterized queries
- Multi-column results
- NULL handling
- Array and object literals

### Performance Testing

- Latency benchmarks ([#3](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/3) - OPEN)
- Concurrent query testing
- Connection reuse efficiency

### CI/CD

- Pipeline configuration ([#5](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/5) - OPEN)
- Automated test execution
- Report artifact storage

### Documentation

- README ([#6](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/6) - OPEN)
- Skip reason documentation ([#8](https://gitlab.com/devnw/codepros/geode/geode-test-harness/-/issues/8) - OPEN)

---

*This file is auto-generated. Edit GitLab issues to update requirements.*
