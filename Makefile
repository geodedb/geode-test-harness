# Geode Test Harness
# Cross-language test framework for validating Geode client implementations
#
# Uses Docker container for Geode server management

.PHONY: all help setup test test-all test-comprehensive clean build-all report-html test-all-html
.PHONY: test-zig test-go test-python test-rust test-nodejs
.PHONY: build-zig build-go build-python build-rust build-nodejs
.PHONY: docker-start docker-stop docker-logs docker-status docker-clean
.PHONY: test-transactions test-connections test-auth test-perf
.PHONY: analyze-perf analyze-coverage test-with-coverage
.PHONY: migrate migrate-status migrate-create test-graph
.PHONY: route-failures route-failures-dry-run
.PHONY: test-cli test-cli-comprehensive geodetestlab-setup geodetestlab-run
.PHONY: test-full test-full-parallel test-everything
.PHONY: test-unit test-unit-verbose
.PHONY: test-quic test-grpc test-all-transports
.PHONY: test-cluster-1 test-cluster-3 test-cluster-5 test-cluster-10 test-cluster-matrix
.PHONY: lint format type-check security-check quality
.PHONY: lint-go
.PHONY: loadtest loadtest-go loadtest-python loadtest-cli loadtest-build loadtest-scenario loadtest-scenarios

# Default target: run full test suite with Docker
all: clean docker-start test-all docker-stop
	@echo ""
	@echo "Full test suite completed."

# Docker settings (matching client repos)
DOCKER ?= docker
GEODE_IMAGE ?= geodedb/geode:latest
GEODE_CONTAINER ?= geode-test-harness
GEODE_HOST ?= 127.0.0.1
GEODE_PORT ?= 3141
GEODE_GRPC_PORT ?= 50051

# Authentication settings. The default must satisfy geode's passphrase policy
# (25+ characters, 4+ words, mixed case) or the server forces a reset on first login.
GEODE_ADMIN_PASSWORD ?= Geode Test Admin Passphrase
null :=
space := $(null) $(null)
GEODE_DEFAULT_PASSWORD ?= $(GEODE_ADMIN_PASSWORD)
GEODE_USERNAME ?= geode

# Transport selection (quic or grpc)
TRANSPORT ?= quic

# Python virtual environment settings
VENV_DIR := .venv
PYTHON := python3
VENV_PYTHON := $(VENV_DIR)/bin/python3
VENV_PIP := $(VENV_DIR)/bin/pip
ACTIVATE := . $(VENV_DIR)/bin/activate

# External client repo paths (sibling directories, used for local development)
GO_CLIENT_PATH := ../geode-client-go
PYTHON_CLIENT_PATH := ../geode-client-python
RUST_CLIENT_PATH := ../geode-client-rust
ZIG_CLIENT_PATH := ../geode-client-zig
ZIG_BUILD_FLAGS ?= -j2
NODEJS_CLIENT_PATH := ../geode-client-nodejs

# Check if we're in a venv or nix environment
IN_VENV := $(shell python3 -c "import sys; print(1 if hasattr(sys, 'real_prefix') or (hasattr(sys, 'base_prefix') and sys.base_prefix != sys.prefix) else 0)" 2>/dev/null || echo 0)
IN_NIX := $(shell [ -n "$$NIX_BUILD_TOP" ] || [ -n "$$GEODE_NIX_BUILD" ] && echo 1 || echo 0)

# Always use venv Python if it exists
ifneq (,$(wildcard $(VENV_PYTHON)))
    RUN_PYTHON := $(VENV_PYTHON)
else ifeq ($(IN_VENV),1)
    RUN_PYTHON := $(PYTHON)
else
    RUN_PYTHON := $(PYTHON)
endif

help:
	@echo "Geode Test Harness"
	@echo ""
	@echo "Quick Start (local development):"
	@echo "  make geodetestlab-install  - Install geodetestlab CLI"
	@echo "  make test                  - Run full spec suite (~193 specs)"
	@echo "  make test-spec SPEC=name   - Run a single spec file"
	@echo ""
	@echo "Quick Start (Docker/CI):"
	@echo "  make geodetestlab-setup    - Setup geodetestlab in venv"
	@echo "  make test-docker           - Start Docker, run tests, stop"
	@echo ""
	@echo "Test Commands:"
	@echo "  test                 - Run full spec suite (JSON report in reports/)"
	@echo "  test-verbose         - Run full suite with verbose output"
	@echo "  test-spec SPEC=      - Run a single spec (e.g. SPEC=per_graph_storage.yml)"
	@echo "  test-grep PATTERN=   - Run specs matching a pattern"
	@echo "  test-shell           - Run shell/REPL stability tests"
	@echo "  test-per-graph       - Run per-graph storage tests"
	@echo "  test-regression      - Run regression tests only"
	@echo "  test-unit            - Run geodetestlab unit tests (pytest)"
	@echo ""
	@echo "Transport-Specific:"
	@echo "  test-quic            - Run with QUIC transport (default)"
	@echo "  test-grpc            - Run with gRPC transport"
	@echo "  test-all-transports  - Run with both transports"
	@echo ""
	@echo "OTel Monitoring (full suite with span/metric capture):"
	@echo "  test-everything-otel - Run test-everything with a docker OTel collector"
	@echo "  otel-start           - Start the harness's OTel collector container"
	@echo "  otel-stop            - Stop the collector"
	@echo "  otel-tail            - docker logs -f the running collector"
	@echo "  otel-logs            - Cat captured collector log"
	@echo "  otel-verify          - Assert spans with service.name=geode arrived"
	@echo ""
	@echo "Docker Server:"
	@echo "  docker-start         - Start Geode server container"
	@echo "  docker-stop          - Stop container"
	@echo "  docker-logs          - View container logs"
	@echo "  docker-status        - Check container status"
	@echo ""
	@echo "Setup & Build:"
	@echo "  geodetestlab-install - Install geodetestlab to user env (pipx)"
	@echo "  geodetestlab-setup   - Install geodetestlab in venv (CI)"
	@echo "  setup                - Full setup (venv + all runners)"
	@echo "  build-all            - Build multi-language runners"
	@echo ""
	@echo "Load Testing:"
	@echo "  loadtest             - Run all load tests (Go + CLI)"
	@echo "  loadtest-go          - Go client concurrent connections (1-64)"
	@echo "  loadtest-python      - Python CLI concurrent processes"
	@echo "  loadtest-cli         - Geodetestlab sequential stress spec"
	@echo "  loadtest-build       - Build Go load test binary"
	@echo "  loadtest-scenario SCENARIO=<name> - Run a specific load test scenario"
	@echo "  loadtest-scenarios   - Run all 5 load test scenarios"
	@echo ""
	@echo "Code Quality:"
	@echo "  lint / format / type-check / security-check / quality"
	@echo ""
	@echo "Reports:"
	@echo "  report               - Show last test results summary"
	@echo ""
	@echo "Cleanup:"
	@echo "  clean                - Remove build artifacts and containers"
	@echo "  clean-all            - Clean everything including Docker image"
	@echo ""
	@echo "Configuration:"
	@echo "  GEODE_BINARY=$(GEODE_BINARY)"
	@echo "  GEODE_IMAGE=$(GEODE_IMAGE)"
	@echo "  GEODE_PORT=$(GEODE_PORT) (QUIC)  GEODE_GRPC_PORT=$(GEODE_GRPC_PORT) (gRPC)"
	@echo "  TRANSPORT=$(TRANSPORT)  PARALLEL_WORKERS=$(PARALLEL_WORKERS)"

# ==============================================================================
# Docker Server Management
# ==============================================================================

docker-start:
	@echo "Starting Geode server container..."
	@$(DOCKER) rm -f $(GEODE_CONTAINER) 2>/dev/null || true
	@$(DOCKER) run -d --name $(GEODE_CONTAINER) \
		-p $(GEODE_PORT):3141/udp \
		-p $(GEODE_GRPC_PORT):50051/tcp \
		-e "GEODE_ADMIN_PASSWORD=$(GEODE_ADMIN_PASSWORD)" \
		-e "GEODE_DEFAULT_PASSWORD=$(GEODE_DEFAULT_PASSWORD)" \
		-e GEODE_DISABLE_AUDIT=1 \
		$(GEODE_IMAGE) \
		serve --listen 0.0.0.0:3141 --listen-grpc 0.0.0.0:50051 --log-level info
	@echo "Waiting for server to be ready..."
	@for i in 1 2 3 4 5 6 7 8 9 10; do \
		sleep 1; \
		if $(DOCKER) logs $(GEODE_CONTAINER) 2>&1 | grep -q "Server ready\|accepting QUIC connections\|gRPC server"; then \
			echo "Geode server ready:"; \
			echo "  QUIC: $(GEODE_HOST):$(GEODE_PORT) (UDP)"; \
			echo "  gRPC: $(GEODE_HOST):$(GEODE_GRPC_PORT) (TCP)"; \
			exit 0; \
		fi; \
		echo "  Waiting... ($$i/10)"; \
	done; \
	echo "Warning: Server may not be fully ready"; \
	$(DOCKER) logs $(GEODE_CONTAINER)

docker-stop:
	@echo "Stopping Geode server container..."
	@$(DOCKER) stop $(GEODE_CONTAINER) 2>/dev/null || true
	@$(DOCKER) rm $(GEODE_CONTAINER) 2>/dev/null || true
	@echo "Container stopped"

docker-logs:
	@$(DOCKER) logs -f $(GEODE_CONTAINER)

docker-status:
	@$(DOCKER) ps -a --filter "name=$(GEODE_CONTAINER)" --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"

# ==============================================================================
# Migration Management
# ==============================================================================

# Path to Geode CLI (auto-detected)
GEODE_CLI ?= $(shell which geode 2>/dev/null || echo "../geode/zig-out/bin/geode")
MIGRATIONS_DIR ?= migrations

migrate: docker-start
	@echo "Running migrations from $(MIGRATIONS_DIR)..."
	@if [ -x "$(GEODE_CLI)" ]; then \
		$(GEODE_CLI) migrate run --dir $(MIGRATIONS_DIR) --server $(GEODE_HOST):$(GEODE_PORT) --insecure; \
	else \
		echo "Geode CLI not found at $(GEODE_CLI)"; \
		echo "Build it with: cd ../geode && make build"; \
		exit 1; \
	fi

migrate-status:
	@echo "Migration status for $(MIGRATIONS_DIR):"
	@if [ -x "$(GEODE_CLI)" ]; then \
		$(GEODE_CLI) migrate status --dir $(MIGRATIONS_DIR); \
	else \
		echo "Geode CLI not found at $(GEODE_CLI)"; \
		exit 1; \
	fi

migrate-create:
	@if [ -z "$(NAME)" ]; then \
		echo "Usage: make migrate-create NAME=migration_name"; \
		exit 1; \
	fi
	@echo "Creating migration: $(NAME)"
	@if [ -x "$(GEODE_CLI)" ]; then \
		$(GEODE_CLI) migrate create $(NAME) --dir $(MIGRATIONS_DIR); \
	else \
		echo "Geode CLI not found at $(GEODE_CLI)"; \
		exit 1; \
	fi

docker-pull:
	@echo "Pulling latest Geode image..."
	@$(DOCKER) pull $(GEODE_IMAGE)

# ==============================================================================
# Setup & Build
# ==============================================================================

$(VENV_DIR):
	@echo "Creating Python virtual environment..."
	@$(PYTHON) -m venv $(VENV_DIR)
	@echo "Virtual environment created at $(VENV_DIR)"

setup: $(VENV_DIR)
	@echo "Setting up test harness..."
	@echo "Installing Python dependencies..."
	@$(VENV_PIP) install --upgrade pip
	@if [ -f requirements.txt ]; then $(VENV_PIP) install -r requirements.txt; fi
	@if [ -d "$(PYTHON_CLIENT_PATH)" ]; then \
		echo "Installing Geode Python client..."; \
		$(VENV_PIP) install -e $(PYTHON_CLIENT_PATH); \
	fi
	@echo "Python dependencies installed"
	@$(MAKE) build-all
	@echo "Setup complete!"
	@if [ "$(IN_VENV)" = "0" ] && [ "$(IN_NIX)" = "0" ]; then \
		echo ""; \
		echo "To use the test harness, activate the virtual environment:"; \
		echo "  source $(VENV_DIR)/bin/activate"; \
		echo ""; \
		echo "Or run make targets which will use the venv automatically."; \
	fi

build-all: build-zig build-go build-python build-rust build-nodejs
	@echo "Build complete"

build-zig:
	@echo "Building Zig runner..."
	@command -v zig >/dev/null 2>&1 || { echo "Zig is required to build the runner" >&2; exit 1; }
	@cd runners && zig build $(ZIG_BUILD_FLAGS)
	@cp runners/zig-out/bin/zig_runner runners/zig_runner

lint-go:
	@test -d "$(GO_CLIENT_PATH)" || { echo "Go client not found at $(GO_CLIENT_PATH)" >&2; exit 1; }
	@cd runners && go list -mod=readonly ./... >/dev/null
	@cd runners && $(PYTHON) ../scripts/golangci-lint.py run --no-config --default none --enable govet --timeout 5m ./...

build-go: lint-go
	@echo "Building Go runner..."
	@cd runners && go build -o go_runner go_runner.go

build-python:
	@echo "Setting up Python runner..."
	@if [ ! -d "$(PYTHON_CLIENT_PATH)" ]; then \
		echo "Warning: Python client not found at $(PYTHON_CLIENT_PATH)"; \
		exit 0; \
	fi
	@echo "Python runner ready (uses installed geode_client package)"

build-rust:
	@echo "Building Rust runner..."
	@if [ ! -d "$(RUST_CLIENT_PATH)" ]; then \
		echo "Warning: Rust client not found at $(RUST_CLIENT_PATH)"; \
		exit 0; \
	fi
	@command -v cargo >/dev/null 2>&1 || { echo "Cargo not found, skipping"; exit 0; }
	@cd runners/rust_runner && cargo build --release 2>/dev/null || echo "Rust build skipped"

build-nodejs:
	@echo "Setting up Node.js runner..."
	@if [ ! -d "$(NODEJS_CLIENT_PATH)" ]; then \
		echo "Warning: Node.js client not found at $(NODEJS_CLIENT_PATH)"; \
		exit 0; \
	fi
	@command -v node >/dev/null 2>&1 || { echo "Node not found, skipping"; exit 0; }
	@command -v npm >/dev/null 2>&1 || { echo "npm not found, skipping"; exit 0; }
	@cd runners && npm install 2>/dev/null || echo "Node.js setup skipped"
	@echo "Node.js runner ready"

# ==============================================================================
# geodetestlab-cli setup
# ==============================================================================

# Path to geodetestlab-cli specs and package
GEODETESTLAB_CLI := geodetestlab-cli
SPECS_DIR := $(GEODETESTLAB_CLI)/specs
GEODETESTLAB_VENV := $(GEODETESTLAB_CLI)/.venv
GEODETESTLAB_PIP := $(GEODETESTLAB_VENV)/bin/pip
GEODETESTLAB_PYTHON := $(GEODETESTLAB_VENV)/bin/python3

# Auto-detect geodetestlab: prefer system-installed, fall back to venv
# Uses = (recursive) so it re-evaluates after auto-install
GEODETESTLAB = $(or $(shell command -v geodetestlab 2>/dev/null),$(wildcard $(GEODETESTLAB_VENV)/bin/geodetestlab))

# Geode binary: prefer ../geode/zig-out/bin/geode, then system
GEODE_BINARY ?= $(shell \
	if [ -x "../geode/zig-out/bin/geode" ]; then echo "../geode/zig-out/bin/geode"; \
	elif command -v geode >/dev/null 2>&1; then command -v geode; \
	else echo ""; fi)

# Number of parallel workers for CLI tests.
# Each spec spawns a full Geode server and some suites leave background flush /
# persistence work in flight long enough that parallel spec execution can cause
# nondeterministic crashes and false failures. Default to serial execution for
# trustworthy local verification; callers can still opt in explicitly.
PARALLEL_WORKERS ?= 1

# Setup geodetestlab-cli in a venv (for CI or first-time setup)
geodetestlab-setup:
	@echo "Setting up geodetestlab-cli..."
	@if [ ! -d "$(GEODETESTLAB_VENV)" ]; then \
		$(PYTHON) -m venv $(GEODETESTLAB_VENV); \
	fi
	@$(GEODETESTLAB_PIP) install --upgrade pip
	@$(GEODETESTLAB_PIP) install -e $(GEODETESTLAB_CLI)
	@$(GEODETESTLAB_PIP) install pytest
	@echo "geodetestlab-cli setup complete"

# Install geodetestlab-cli to user environment via pipx (for local development)
geodetestlab-install:
	@echo "Installing geodetestlab-cli to user environment..."
	@if command -v pipx >/dev/null 2>&1; then \
		pipx install --editable ./$(GEODETESTLAB_CLI) --force; \
	else \
		echo "Error: pipx not found. Install it with: apt install pipx"; \
		exit 1; \
	fi
	@echo "Installed. Run 'geodetestlab --help' to verify."

# Verify prerequisites before running tests; auto-install via pipx if missing
.check-geodetestlab:
	@if [ -z "$(GEODETESTLAB)" ]; then \
		echo "geodetestlab not found, installing via pipx..."; \
		$(MAKE) geodetestlab-install; \
	fi

.check-geode-binary:
	@if [ -z "$(GEODE_BINARY)" ]; then \
		echo "Error: geode binary not found."; \
		echo "  Build it: cd ../geode && make build"; \
		echo "  Or install: sudo cp ../geode/zig-out/bin/geode /usr/bin/geode"; \
		exit 1; \
	fi
	@echo "Using geode binary: $(GEODE_BINARY)"

# ==============================================================================
# Test Commands
# ==============================================================================

# Run the full geodetestlab spec suite (managed servers per spec).
# Failures are streamed live to reports/test-failures.md (tail -f it during a
# run; point an agent at it afterward to fix the failures).
test: .check-geodetestlab
	@echo "Running full spec suite ($(shell ls $(SPECS_DIR)/*.yml 2>/dev/null | wc -l) specs)..."
	@mkdir -p reports
	$(GEODETESTLAB) run --specs $(SPECS_DIR) --output reports/results.json \
		--failure-file reports/test-failures.md -j $(PARALLEL_WORKERS)
	@echo "Failure detail (if any): reports/test-failures.md"

# Run full suite with verbose output
test-verbose: .check-geodetestlab
	@mkdir -p reports
	$(GEODETESTLAB) run --specs $(SPECS_DIR) --output reports/results.json \
		--failure-file reports/test-failures.md -v -j $(PARALLEL_WORKERS)
	@echo "Failure detail (if any): reports/test-failures.md"

# Run a single spec by name (e.g. make test-spec SPEC=per_graph_storage.yml)
test-spec: .check-geodetestlab
	@if [ -z "$(SPEC)" ]; then \
		echo "Usage: make test-spec SPEC=spec_name.yml"; \
		echo "Available specs:"; \
		ls $(SPECS_DIR)/*.yml | xargs -n1 basename | head -20; \
		echo "  ... ($(shell ls $(SPECS_DIR)/*.yml | wc -l) total)"; \
		exit 1; \
	fi
	$(GEODETESTLAB) run --spec $(SPECS_DIR)/$(SPEC) -v

# Run specs matching a pattern (e.g. make test-grep PATTERN=per_graph)
test-grep: .check-geodetestlab
	@if [ -z "$(PATTERN)" ]; then \
		echo "Usage: make test-grep PATTERN=search_term"; \
		exit 1; \
	fi
	@echo "Running specs matching '$(PATTERN)'..."
	@for spec in $(SPECS_DIR)/*$(PATTERN)*.yml; do \
		if [ -f "$$spec" ]; then \
			echo "--- $$spec ---"; \
			$(GEODETESTLAB) run --spec "$$spec" -v; \
		fi; \
	done

# Run shell/REPL stability tests
test-shell: .check-geodetestlab
	@echo "Running shell stability tests..."
	$(GEODETESTLAB) run --spec $(SPECS_DIR)/shell_session_stability.yml -v

# --- Cluster matrix testing (Task B4 of 2026-05-25 distributed plan) ---
#
# Runs the full spec suite against 1-, 3-, 5-, and 10-node deployments.
# `--force-cluster-size N` promotes specs without a `cluster:` block to
# N-node clusters; specs that set `single_node_only: true` opt out.
#
# Each size writes its report to reports/cluster-N.json so test-cluster-matrix
# can aggregate them at the end.

test-cluster-1: .check-geodetestlab
	@echo "Running full spec suite against 1-node deployment..."
	@mkdir -p reports
	$(GEODETESTLAB) run --specs $(SPECS_DIR) \
		--force-cluster-size 1 \
		--output reports/cluster-1.json \
		-j $(PARALLEL_WORKERS)

test-cluster-3: .check-geodetestlab
	@echo "Running full spec suite against 3-node deployment..."
	@mkdir -p reports
	$(GEODETESTLAB) run --specs $(SPECS_DIR) \
		--force-cluster-size 3 \
		--output reports/cluster-3.json \
		-j $(PARALLEL_WORKERS)

test-cluster-5: .check-geodetestlab
	@echo "Running full spec suite against 5-node deployment..."
	@mkdir -p reports
	$(GEODETESTLAB) run --specs $(SPECS_DIR) \
		--force-cluster-size 5 \
		--output reports/cluster-5.json \
		-j $(PARALLEL_WORKERS)

test-cluster-10: .check-geodetestlab
	@echo "Running full spec suite against 10-node deployment..."
	@mkdir -p reports
	$(GEODETESTLAB) run --specs $(SPECS_DIR) \
		--force-cluster-size 10 \
		--output reports/cluster-10.json \
		-j $(PARALLEL_WORKERS)

test-cluster-matrix: test-cluster-1 test-cluster-3 test-cluster-5 test-cluster-10
	@echo "--- Cluster matrix summary ---"
	@for n in 1 3 5 10; do \
		if [ -f reports/cluster-$$n.json ]; then \
			echo "Size $$n:"; \
			python3 -c "import json; r=json.load(open('reports/cluster-$$n.json'))['summary']; print('  passed=%s failed=%s skipped=%s total=%s' % (r.get('passed',0), r.get('failed',0), r.get('skipped',0), r.get('total',0)))"; \
		fi; \
	done

# Run per-graph storage tests
test-per-graph: .check-geodetestlab
	@echo "Running per-graph storage tests..."
	$(GEODETESTLAB) run --spec $(SPECS_DIR)/per_graph_storage.yml -v
	$(GEODETESTLAB) run --spec $(SPECS_DIR)/per_graph_storage_resilience.yml -v

# Run regression tests only
test-regression: .check-geodetestlab
	@echo "Running regression tests..."
	@for spec in $(SPECS_DIR)/regression_*.yml; do \
		if [ -f "$$spec" ]; then \
			$(GEODETESTLAB) run --spec "$$spec" -v || true; \
		fi; \
	done

# Docker-managed test run (starts/stops container)
test-docker: geodetestlab-setup docker-start
	@echo "Running all tests with Docker..."
	@$(MAKE) test || ($(MAKE) docker-stop; exit 1)
	@$(MAKE) docker-stop

# Aliases for backward compatibility
test-all: test
test-comprehensive: test
test-cli: test
test-cli-comprehensive: test
test-full: test
test-full-parallel: test
geodetestlab-run: test-spec

# Unified target for running all tests with a specific binary
test-everything: .check-geode-binary
	@echo "Running all tests with geode binary: $(GEODE_BINARY)"
	@bash scripts/run_all_tests.sh --geode-binary "$(GEODE_BINARY)"

# ==============================================================================
# OTel monitoring
# ==============================================================================
# Spin up a local otel/opentelemetry-collector-contrib container, point geode
# at it via env vars, run the test suite, then drain + stop the collector.
# The collector emits to stdout (visible via `make otel-tail`) and writes
# every span/metric to reports/spans.jsonl via the file exporter.

.PHONY: otel-start otel-stop otel-logs otel-tail otel-verify test-everything-otel

otel-start:
	@bash scripts/otel-collector.sh start

otel-stop:
	@bash scripts/otel-collector.sh stop

otel-logs:
	@bash scripts/otel-collector.sh logs

otel-tail:
	@bash scripts/otel-collector.sh tail

otel-verify:
	@bash scripts/otel-collector.sh verify

# Run the full suite with OTel monitoring enabled. Brings the collector up,
# sources its env file inside run_all_tests.sh (gated on GEODE_OTEL=1), then
# verifies + tears the collector down regardless of test outcome.
test-everything-otel: .check-geode-binary
	@bash scripts/otel-collector.sh start
	@trap 'bash scripts/otel-collector.sh stop >/dev/null 2>&1 || true' EXIT; \
	GEODE_OTEL=1 bash scripts/run_all_tests.sh --geode-binary "$(GEODE_BINARY)"; \
	rc=$$?; \
	echo ""; \
	echo "--- post-run OTel verification ---"; \
	bash scripts/otel-collector.sh verify || rc=$$?; \
	bash scripts/otel-collector.sh stop >/dev/null 2>&1 || true; \
	exit $$rc

# ==============================================================================
# Transport-Specific Tests
# ==============================================================================

test-quic: .check-geodetestlab
	@echo "Running tests using QUIC transport..."
	@mkdir -p reports
	$(GEODETESTLAB) run --specs $(SPECS_DIR) --output reports/results_quic.json -v -j $(PARALLEL_WORKERS)

test-grpc: .check-geodetestlab
	@echo "Running tests using gRPC transport..."
	@mkdir -p reports
	$(GEODETESTLAB) run --specs $(SPECS_DIR) --output reports/results_grpc.json -v -j $(PARALLEL_WORKERS) --transport grpc

test-all-transports: .check-geodetestlab
	@echo "=== QUIC Transport Tests ==="
	@mkdir -p reports
	-$(GEODETESTLAB) run --specs $(SPECS_DIR) --output reports/results_quic.json -v -j $(PARALLEL_WORKERS)
	@echo ""
	@echo "=== gRPC Transport Tests ==="
	-$(GEODETESTLAB) run --specs $(SPECS_DIR) --output reports/results_grpc.json -v -j $(PARALLEL_WORKERS) --transport grpc
	@echo ""
	@echo "Results: reports/results_quic.json, reports/results_grpc.json"

# ==============================================================================
# Load Testing — Concurrent Connection Stress
# ==============================================================================

# Geode connection DSN for load tests (override as needed)
LOADTEST_DSN ?= localhost:3141?insecure=true&user=$(GEODE_USERNAME)&pass=$(subst $(space),%20,$(GEODE_ADMIN_PASSWORD))
LOADTEST_LEVELS ?= 1,2,4,8,16,32
LOADTEST_DURATION ?= 5s

# Build Go load test binary
loadtest-build:
	@echo "Building Go load test..."
	cd loadtest/go && go build -o geode-loadtest .
	@echo "Built: loadtest/go/geode-loadtest"

# 2026-04-28 — concurrent BEGIN/EXEC/COMMIT regression test.
# Pins post-fix expectations for the msft-graph parallel-seed failure
# where 4-9 of 9 concurrent BEGINs returned "expected BEGIN response"
# or "sql: connection is already closed" against pinned conns.
.PHONY: test-concurrent-tx test-concurrent-tx-build
test-concurrent-tx-build:
	@echo "Building concurrent-tx regression test..."
	cd tests/concurrent_tx && go build -o concurrent-tx-test .
	@echo "Built: tests/concurrent_tx/concurrent-tx-test"

# Run the concurrent-tx regression.  Override defaults via env vars:
#   CTX_DSN     — override the DSN (default: localhost:3141 with insecure=true)
#   CTX_CONNS   — number of pinned conns running concurrently (default 8)
#   CTX_ITER    — tx iterations per conn (default 25)
#   CTX_TIMEOUT — overall test timeout (default 5m)
CTX_DSN     ?= 127.0.0.1:3141?insecure=true&user=geode&pass=$(subst $(space),%20,$(GEODE_ADMIN_PASSWORD))&graph=concurrent_tx_test
CTX_CONNS   ?= 8
CTX_ITER    ?= 25
CTX_TIMEOUT ?= 5m
test-concurrent-tx: test-concurrent-tx-build
	@echo "Running concurrent-tx regression: conns=$(CTX_CONNS) iter=$(CTX_ITER) timeout=$(CTX_TIMEOUT)"
	cd tests/concurrent_tx && ./concurrent-tx-test \
		-dsn "$(CTX_DSN)" \
		-conns $(CTX_CONNS) \
		-iter $(CTX_ITER) \
		-timeout $(CTX_TIMEOUT)

# Run Go client load test (native QUIC via quic-go, connection pooling)
loadtest-go: loadtest-build
	@mkdir -p reports
	@echo "Running Go concurrent load test..."
	cd loadtest/go && ./geode-loadtest \
		-dsn "$(LOADTEST_DSN)" \
		-levels "$(LOADTEST_LEVELS)" \
		-duration $(LOADTEST_DURATION) \
		-output ../../reports/loadtest_go.json
	@echo ""
	@cat reports/loadtest_go.json | python3 -c "import json,sys; r=json.load(sys.stdin); print(r.get('summary',''))"

# Run a specific load test scenario
# Usage: make loadtest-scenario SCENARIO=one_hop
SCENARIO ?= ping
loadtest-scenario: loadtest-build
	mkdir -p reports
	cd loadtest/go && ./geode-loadtest \
		-dsn "$(LOADTEST_DSN)" \
		-scenario "$(SCENARIO)" \
		-levels "$(LOADTEST_LEVELS)" \
		-duration $(LOADTEST_DURATION) \
		-output ../../reports/loadtest_$(SCENARIO).json

# Run all load test scenarios sequentially.  edge_create and
# edge_create_with_props are the regression vehicles for the MATCH+CREATE
# write-lock contention path (see geode crud_operations.zig executeMerge and
# quic_connection_handler.zig:3387 acquireGraphWriteLockCancelable).
loadtest-scenarios: loadtest-build
	mkdir -p reports
	@for scenario in ping point_read one_hop two_hop fan_out edge_create edge_create_with_props; do \
		echo ""; \
		echo "=== Running scenario: $$scenario ==="; \
		cd loadtest/go && ./geode-loadtest \
			-dsn "$(LOADTEST_DSN)" \
			-scenario "$$scenario" \
			-levels "$(LOADTEST_LEVELS)" \
			-duration $(LOADTEST_DURATION) \
			-output ../../reports/loadtest_$${scenario}.json; \
		cd ../..; \
	done
	@echo ""
	@echo "=== All scenarios complete ==="
	@echo "Reports: reports/loadtest_*.json"

# Run Python CLI-based load test (subprocess per query)
loadtest-python:
	@mkdir -p reports
	@echo "Running Python CLI load test..."
	python3 loadtest/python/loadtest.py \
		--host $(GEODE_HOST) --port $(GEODE_PORT) \
		-U $(GEODE_USERNAME) -P "$(GEODE_ADMIN_PASSWORD)" \
		--levels "$(LOADTEST_LEVELS)" \
		--duration 5 \
		--output reports/loadtest_python.json

# Run geodetestlab load stress specs
loadtest-cli: .check-geodetestlab
	@echo "Running CLI load stress specs..."
	$(GEODETESTLAB) run --spec $(SPECS_DIR)/load_stress_sequential.yml -v

# Run all load tests
loadtest: loadtest-go loadtest-cli
	@echo ""
	@echo "Load test reports:"
	@ls -la reports/loadtest_*.json 2>/dev/null

# ==============================================================================
# Unit Tests (test harness internals)
# ==============================================================================

test-unit:
	@echo "Running geodetestlab unit tests..."
	$(GEODETESTLAB_PYTHON) -m pytest $(GEODETESTLAB_CLI)/geodetestlab/tests/ -v

test-unit-verbose:
	$(GEODETESTLAB_PYTHON) -m pytest $(GEODETESTLAB_CLI)/geodetestlab/tests/ -v --tb=long

# ==============================================================================
# Reporting
# ==============================================================================

report:
	@echo "JSON reports:"
	@ls -la reports/*.json 2>/dev/null || echo "No reports found. Run 'make test' first."
	@if [ -f reports/results.json ]; then \
		python3 -c "import json; r=json.load(open('reports/results.json')); s=r['summary']; print(f\"Total: {s['total']}  Passed: {s['passed']}  Failed: {s['failed']}  Skipped: {s['skipped']}\")"; \
	fi

report-html: report

# ==============================================================================
# Failure Routing (for CI/CD integration)
# ==============================================================================

route-failures:
	@echo "Routing failures to appropriate repositories..."
	@if [ ! -f reports/results.json ]; then \
		echo "No results file found. Run 'make test-all' first."; \
		exit 1; \
	fi
	@if [ -f route_failures.py ]; then \
		$(RUN_PYTHON) route_failures.py reports/results.json --verbose --output reports/created_issues.json; \
	else \
		echo "route_failures.py not found (legacy script removed)"; \
	fi

route-failures-dry-run:
	@echo "Dry run: Analyzing failures for routing..."
	@if [ ! -f reports/results.json ]; then \
		echo "No results file found. Run 'make test-all' first."; \
		exit 1; \
	fi
	@if [ -f route_failures.py ]; then \
		$(RUN_PYTHON) route_failures.py reports/results.json --dry-run --verbose; \
	else \
		echo "route_failures.py not found (legacy script removed)"; \
	fi

# ==============================================================================
# Cleanup
# ==============================================================================

clean: docker-clean
	@echo "Cleaning build artifacts..."
	rm -f runners/go_runner
	rm -f runners/zig_runner
	rm -rf runners/rust_runner/target
	rm -rf runners/zig-out
	rm -rf runners/.zig-cache
	rm -rf runners/node_modules
	rm -rf reports/*.json
	rm -rf reports/*.html
	rm -rf reports/*.md
	rm -rf $(VENV_DIR)
	@echo "Clean complete!"

docker-clean:
	@echo "Stopping any running test containers..."
	@$(DOCKER) stop $(GEODE_CONTAINER) 2>/dev/null || true
	@$(DOCKER) rm $(GEODE_CONTAINER) 2>/dev/null || true

clean-all: clean
	@echo "Removing Docker image..."
	@$(DOCKER) rmi $(GEODE_IMAGE) 2>/dev/null || true
	@echo "Full cleanup complete!"

# =============================================================================
# Code Quality Targets
# =============================================================================

lint: ## Run ruff linter on Python code
	cd geodetestlab-cli && . .venv/bin/activate && ruff check geodetestlab/

format: ## Format Python code with ruff
	cd geodetestlab-cli && . .venv/bin/activate && ruff format geodetestlab/

type-check: ## Run mypy type checker
	cd geodetestlab-cli && . .venv/bin/activate && mypy geodetestlab/ --ignore-missing-imports

security-check: ## Run bandit security scanner
	cd geodetestlab-cli && . .venv/bin/activate && pip install -q bandit && bandit -r geodetestlab/ -s B101

quality: lint type-check security-check ## Run all quality checks
	@echo "All quality checks passed!"
