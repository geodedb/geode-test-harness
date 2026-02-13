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
.PHONY: test-full test-full-parallel
.PHONY: test-unit test-unit-verbose
.PHONY: test-quic test-grpc test-all-transports
.PHONY: lint format type-check security-check quality

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

# Authentication settings
GEODE_ADMIN_PASSWORD ?= GeodeTestPassword123!
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
	@echo "Geode Test Harness - Cross-Language Client Testing"
	@echo ""
	@echo "Quick Start:"
	@echo "  make             - Run full test suite (clean, start Docker, test, stop)"
	@echo "  make clean && make - Clean everything and run full suite"
	@echo ""
	@echo "Docker Server Management:"
	@echo "  docker-start     - Start Geode server container"
	@echo "  docker-stop      - Stop Geode server container"
	@echo "  docker-logs      - View container logs"
	@echo "  docker-status    - Check container status"
	@echo "  docker-clean     - Stop and remove test container"
	@echo ""
	@echo "Migration Commands:"
	@echo "  migrate          - Run database migrations"
	@echo "  migrate-status   - Show migration status"
	@echo "  migrate-create   - Create a new migration (NAME=name)"
	@echo ""
	@echo "Build Commands:"
	@echo "  setup            - Install dependencies and build all runners"
	@echo "  build-all        - Build all client runners"
	@echo "  build-zig        - Build Zig runner"
	@echo "  build-go         - Build Go runner"
	@echo "  build-python     - Setup Python runner"
	@echo "  build-rust       - Build Rust runner"
	@echo "  build-nodejs     - Setup Node.js runner"
	@echo ""
	@echo "Test Commands:"
	@echo "  test             - Run basic tests (geodetestlab-cli)"
	@echo "  test-all         - Run all test suites (JSON report)"
	@echo "  test-all-html    - Run all tests and generate HTML report"
	@echo "  test-docker      - Start Docker, run all tests, stop Docker"
	@echo ""
	@echo "CLI Tests (geodetestlab-cli):"
	@echo "  geodetestlab-setup      - Setup geodetestlab-cli environment"
	@echo "  test-cli                - Run CLI tests (parallel by default)"
	@echo "  test-cli-comprehensive  - Run comprehensive CLI tests (parallel by default)"
	@echo "  geodetestlab-run SPEC=  - Run specific CLI spec file"
	@echo ""
	@echo "Unit Tests (test harness internals):"
	@echo "  test-unit               - Run unit tests for shared lib modules"
	@echo "  test-unit-verbose       - Run unit tests with verbose output"
	@echo ""
	@echo "Analysis:"
	@echo "  report-html        - Generate HTML report from JSON results"
	@echo ""
	@echo "Failure Routing (CI/CD):"
	@echo "  route-failures        - Route failures to appropriate GitLab repos"
	@echo "  route-failures-dry-run - Preview failure routing without creating issues"
	@echo ""
	@echo "Cleanup:"
	@echo "  clean            - Stop containers and remove build artifacts"
	@echo "  clean-all        - Clean everything including Docker image"
	@echo ""
	@echo "Transport-Specific Tests:"
	@echo "  test-quic          - Run tests using QUIC transport (default)"
	@echo "  test-grpc          - Run tests using gRPC transport"
	@echo "  test-all-transports - Run tests with both QUIC and gRPC"
	@echo ""
	@echo "Code Quality:"
	@echo "  lint              - Run ruff linter"
	@echo "  format            - Format with ruff"
	@echo "  type-check        - Run mypy"
	@echo "  security-check    - Run bandit"
	@echo "  quality           - All quality checks"
	@echo ""
	@echo "Configuration:"
	@echo "  GEODE_IMAGE=$(GEODE_IMAGE)"
	@echo "  GEODE_PORT=$(GEODE_PORT) (QUIC/UDP)"
	@echo "  GEODE_GRPC_PORT=$(GEODE_GRPC_PORT) (gRPC/TCP)"
	@echo "  TRANSPORT=$(TRANSPORT) (quic or grpc)"
	@echo "  GEODE_ADMIN_PASSWORD=<set> (authentication)"

# ==============================================================================
# Docker Server Management
# ==============================================================================

docker-start:
	@echo "Starting Geode server container..."
	@$(DOCKER) rm -f $(GEODE_CONTAINER) 2>/dev/null || true
	@$(DOCKER) run -d --name $(GEODE_CONTAINER) \
		-p $(GEODE_PORT):3141/udp \
		-p $(GEODE_GRPC_PORT):50051/tcp \
		-e GEODE_ADMIN_PASSWORD=$(GEODE_ADMIN_PASSWORD) \
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
	@if [ ! -d "$(ZIG_CLIENT_PATH)" ]; then \
		echo "Warning: Zig client not found at $(ZIG_CLIENT_PATH)"; \
		exit 0; \
	fi
	@command -v zig >/dev/null 2>&1 || { echo "Zig not found, skipping"; exit 0; }
	@cd runners && zig build && cp zig-out/bin/zig_runner ./zig_runner 2>/dev/null || echo "Zig build skipped"

build-go:
	@echo "Building Go runner..."
	@if [ ! -d "$(GO_CLIENT_PATH)" ]; then \
		echo "Warning: Go client not found at $(GO_CLIENT_PATH)"; \
		exit 0; \
	fi
	@command -v go >/dev/null 2>&1 || { echo "Go not found, skipping"; exit 0; }
	@cd runners && go build -o go_runner go_runner.go 2>/dev/null || echo "Go build skipped"

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

# Path to geodetestlab-cli
GEODETESTLAB_CLI := geodetestlab-cli
GEODETESTLAB_VENV := $(GEODETESTLAB_CLI)/.venv
GEODETESTLAB_PYTHON := $(GEODETESTLAB_VENV)/bin/python3
GEODETESTLAB_PIP := $(GEODETESTLAB_VENV)/bin/pip

# Setup geodetestlab-cli environment
geodetestlab-setup:
	@echo "Setting up geodetestlab-cli..."
	@if [ ! -d "$(GEODETESTLAB_VENV)" ]; then \
		$(PYTHON) -m venv $(GEODETESTLAB_VENV); \
	fi
	@$(GEODETESTLAB_PIP) install --upgrade pip
	@$(GEODETESTLAB_PIP) install -e $(GEODETESTLAB_CLI)
	@echo "geodetestlab-cli setup complete"

# Number of parallel workers for CLI tests.
# QUIC transport: cap at 4 (QUIC memory bugs cause double-free under high load).
# gRPC transport: no cap needed — use full core count (PERF-003).
NPROC := $(shell nproc 2>/dev/null || sysctl -n hw.ncpu 2>/dev/null || echo 4)
ifeq ($(TRANSPORT),grpc)
  PARALLEL_WORKERS ?= $(NPROC)
else
  PARALLEL_WORKERS ?= $(shell echo $$(( $(NPROC) > 4 ? 4 : $(NPROC) )))
endif

# ==============================================================================
# Test Commands (all use geodetestlab-cli)
# ==============================================================================

test: geodetestlab-setup
	@echo "Running tests (transport: $(TRANSPORT))..."
	@mkdir -p reports
	$(GEODETESTLAB_PYTHON) -m geodetestlab run --specs $(GEODETESTLAB_CLI)/specs --output reports/results.json --verbose --parallel $(PARALLEL_WORKERS) --transport $(TRANSPORT)

test-docker: geodetestlab-setup docker-start
	@echo "Running all tests with Docker..."
	@$(MAKE) test-all || ($(MAKE) docker-stop; exit 1)
	@$(MAKE) docker-stop

test-all: geodetestlab-setup
	@echo "Running all test suites (transport: $(TRANSPORT))..."
	@mkdir -p reports
	$(GEODETESTLAB_PYTHON) -m geodetestlab run --specs $(GEODETESTLAB_CLI)/specs --output reports/results.json --verbose --parallel $(PARALLEL_WORKERS) --transport $(TRANSPORT)

test-comprehensive: test-all

# Run geodetestlab CLI tests (alias for test-all)
test-cli: test-all

# Run comprehensive CLI tests
test-cli-comprehensive: test-all

# Run specific CLI spec
geodetestlab-run: geodetestlab-setup
	@if [ -z "$(SPEC)" ]; then \
		echo "Usage: make geodetestlab-run SPEC=spec_name.yml"; \
		exit 1; \
	fi
	@echo "Running $(SPEC)..."
	$(GEODETESTLAB_PYTHON) -m geodetestlab run --spec $(GEODETESTLAB_CLI)/specs/$(SPEC) --verbose

# Combined tests (alias for test-all since shell tests are now in geodetestlab-cli/specs/)
test-full: test-all

test-full-parallel: test-all

# ==============================================================================
# Transport-Specific Tests
# ==============================================================================

# Run tests using QUIC transport (default)
test-quic: geodetestlab-setup
	@echo "Running tests using QUIC transport..."
	@mkdir -p reports
	$(GEODETESTLAB_PYTHON) -m geodetestlab run --specs $(GEODETESTLAB_CLI)/specs --output reports/results_quic.json --verbose --parallel $(PARALLEL_WORKERS) --transport quic

# Run tests using gRPC transport
test-grpc: geodetestlab-setup
	@echo "Running tests using gRPC transport..."
	@mkdir -p reports
	$(GEODETESTLAB_PYTHON) -m geodetestlab run --specs $(GEODETESTLAB_CLI)/specs --output reports/results_grpc.json --verbose --parallel $(PARALLEL_WORKERS) --transport grpc

# Run tests with both QUIC and gRPC transports
test-all-transports: geodetestlab-setup
	@echo "Running tests with both QUIC and gRPC transports..."
	@mkdir -p reports
	@echo ""
	@echo "=== QUIC Transport Tests ==="
	-$(GEODETESTLAB_PYTHON) -m geodetestlab run --specs $(GEODETESTLAB_CLI)/specs --output reports/results_quic.json --verbose --parallel $(PARALLEL_WORKERS) --transport quic
	@echo ""
	@echo "=== gRPC Transport Tests ==="
	-$(GEODETESTLAB_PYTHON) -m geodetestlab run --specs $(GEODETESTLAB_CLI)/specs --output reports/results_grpc.json --verbose --parallel $(PARALLEL_WORKERS) --transport grpc
	@echo ""
	@echo "Transport test results:"
	@echo "  QUIC: reports/results_quic.json"
	@echo "  gRPC: reports/results_grpc.json"

# ==============================================================================
# Unit Tests (for test harness internals)
# ==============================================================================

# Run unit tests for geodetestlab-cli
test-unit: geodetestlab-setup
	@echo "Running unit tests..."
	$(GEODETESTLAB_PYTHON) -m pytest $(GEODETESTLAB_CLI)/geodetestlab/tests/ -v

# Run unit tests with verbose output
test-unit-verbose: geodetestlab-setup
	@echo "Running unit tests (verbose)..."
	$(GEODETESTLAB_PYTHON) -m pytest $(GEODETESTLAB_CLI)/geodetestlab/tests/ -v --tb=long

# ==============================================================================
# Reporting & Analysis
# ==============================================================================

test-all-html: geodetestlab-setup
	@echo "Running all tests and generating report..."
	@mkdir -p reports
	$(GEODETESTLAB_PYTHON) -m geodetestlab run --specs $(GEODETESTLAB_CLI)/specs --output reports/results.json --verbose --parallel $(PARALLEL_WORKERS) --transport $(TRANSPORT)
	@echo ""
	@echo "Report: reports/results.json"

report-html:
	@echo "JSON reports are in reports/"
	@ls -la reports/*.json 2>/dev/null || echo "No reports found. Run 'make test-all' first."

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
