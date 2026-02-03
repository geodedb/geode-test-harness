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
.PHONY: test-shell test-shell-all test-shell-comprehensive
.PHONY: test-full test-full-parallel
.PHONY: test-unit test-unit-verbose

# Default target: run full test suite with Docker
all: clean docker-start test-all docker-stop
	@echo ""
	@echo "Full test suite completed."

# Docker settings (matching client repos)
DOCKER ?= docker
GEODE_IMAGE ?= registry.gitlab.com/devnw/geode/geode:latest
GEODE_CONTAINER ?= geode-test-harness
GEODE_HOST ?= 127.0.0.1
GEODE_PORT ?= 3141

# Python virtual environment settings
VENV_DIR := .venv
PYTHON := python3
VENV_PYTHON := $(VENV_DIR)/bin/python3
VENV_PIP := $(VENV_DIR)/bin/pip
ACTIVATE := . $(VENV_DIR)/bin/activate

# External client repo paths (sibling directories)
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
	@echo "  test             - Run basic tests on all clients"
	@echo "  test-all         - Run all test suites (JSON report)"
	@echo "  test-all-html    - Run all tests and generate HTML report"
	@echo "  test-docker      - Start Docker, run all tests, stop Docker"
	@echo ""
	@echo "  test-zig         - Run tests on Zig client only"
	@echo "  test-go          - Run tests on Go client only"
	@echo "  test-python      - Run tests on Python client only"
	@echo "  test-rust        - Run tests on Rust client only"
	@echo "  test-nodejs      - Run tests on Node.js client only"
	@echo ""
	@echo "  test-transactions - Run transaction tests"
	@echo "  test-connections  - Run connection tests"
	@echo "  test-auth        - Run authentication tests"
	@echo "  test-perf        - Run performance benchmarks"
	@echo "  test-graph       - Run graph query tests (requires migrations)"
	@echo ""
	@echo "CLI Tests (geodetestlab-cli):"
	@echo "  geodetestlab-setup      - Setup geodetestlab-cli environment"
	@echo "  test-cli                - Run CLI tests"
	@echo "  test-cli-comprehensive  - Run comprehensive CLI tests"
	@echo "  geodetestlab-run SPEC=  - Run specific CLI spec file"
	@echo ""
	@echo "Shell Tests (shell_runner.py):"
	@echo "  test-shell              - Run all shell tests (each manages own server)"
	@echo "  test-shell-spec SPEC=   - Run single shell spec"
	@echo "  test-shell-all          - Run all shell tests with JSON output"
	@echo ""
	@echo "Combined Tests:"
	@echo "  test-full               - Run geodetestlab + shell tests sequentially"
	@echo "  test-full-parallel      - Run geodetestlab + shell tests in parallel"
	@echo ""
	@echo "Unit Tests (test harness internals):"
	@echo "  test-unit               - Run unit tests for shared lib modules"
	@echo "  test-unit-verbose       - Run unit tests with verbose output"
	@echo ""
	@echo "Analysis:"
	@echo "  test-with-coverage - Run tests and generate coverage report"
	@echo "  analyze-coverage   - Analyze test coverage"
	@echo "  analyze-perf       - Analyze performance results"
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
	@echo "Configuration:"
	@echo "  GEODE_IMAGE=$(GEODE_IMAGE)"
	@echo "  GEODE_PORT=$(GEODE_PORT)"

# ==============================================================================
# Docker Server Management
# ==============================================================================

docker-start:
	@echo "Starting Geode server container..."
	@$(DOCKER) rm -f $(GEODE_CONTAINER) 2>/dev/null || true
	@$(DOCKER) run -d --name $(GEODE_CONTAINER) \
		-p $(GEODE_PORT):3141/udp \
		$(GEODE_IMAGE) \
		serve --listen 0.0.0.0:3141 --log-level info
	@echo "Waiting for server to be ready..."
	@for i in 1 2 3 4 5 6 7 8 9 10; do \
		sleep 1; \
		if $(DOCKER) logs $(GEODE_CONTAINER) 2>&1 | grep -q "Server ready\|accepting QUIC connections"; then \
			echo "Geode server ready on $(GEODE_HOST):$(GEODE_PORT)"; \
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
	@$(VENV_PIP) install -r requirements.txt
	@if [ -d "$(PYTHON_CLIENT_PATH)" ]; then \
		echo "Installing Geode Python client..."; \
		$(VENV_PIP) install -e $(PYTHON_CLIENT_PATH); \
	fi
	@echo "Python dependencies installed"
	@echo "Making scripts executable..."
	@chmod +x run_tests.py 2>/dev/null || true
	@chmod +x generate_html_report.py 2>/dev/null || true
	@chmod +x analyze_performance.py 2>/dev/null || true
	@chmod +x analyze_coverage.py 2>/dev/null || true
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
# Test Commands
# ==============================================================================

test: setup
	@echo "Running basic tests..."
	$(RUN_PYTHON) run_tests.py --spec specs/basic.yaml --verbose

test-docker: setup docker-start
	@echo "Running all tests with Docker..."
	@$(MAKE) test-all || ($(MAKE) docker-stop; exit 1)
	@$(MAKE) docker-stop

test-all: setup
	@echo "Running all test suites..."
	@mkdir -p reports
	$(RUN_PYTHON) run_tests.py --verbose --report-json reports/results.json

test-comprehensive: test-all

# Single client tests
test-zig: setup
	@echo "Running tests on Zig client..."
	$(RUN_PYTHON) run_tests.py --clients zig --verbose

test-go: setup
	@echo "Running tests on Go client..."
	$(RUN_PYTHON) run_tests.py --clients go --verbose

test-python: setup
	@echo "Running tests on Python client..."
	$(RUN_PYTHON) run_tests.py --clients python --verbose

test-rust: setup
	@echo "Running tests on Rust client..."
	$(RUN_PYTHON) run_tests.py --clients rust --verbose

test-nodejs: setup
	@echo "Running tests on Node.js client..."
	$(RUN_PYTHON) run_tests.py --clients nodejs --verbose

# Specific test suites
test-transactions: setup
	@echo "Running transaction tests..."
	$(RUN_PYTHON) run_tests.py --spec specs/transactions.yaml --verbose

test-connections: setup
	@echo "Running connection tests..."
	$(RUN_PYTHON) run_tests.py --spec specs/connections.yaml --verbose

test-auth: setup
	@echo "Running authentication tests..."
	$(RUN_PYTHON) run_tests.py --spec specs/auth.yaml --verbose

test-perf: setup
	@echo "Running performance benchmarks..."
	@mkdir -p reports
	$(RUN_PYTHON) run_tests.py --spec specs/performance.yaml --verbose --report-json reports/perf_results.json

test-graph: setup
	@echo "Running graph query tests (with migrations)..."
	@mkdir -p reports
	$(RUN_PYTHON) run_tests.py --spec specs/graph.yaml --verbose --report-json reports/graph_results.json

# ==============================================================================
# CLI Tests (geodetestlab-cli)
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

# Run geodetestlab CLI tests (requires server)
test-cli: geodetestlab-setup
	@echo "Running CLI tests with geodetestlab..."
	@mkdir -p reports
	$(GEODETESTLAB_PYTHON) -m geodetestlab run --specs $(GEODETESTLAB_CLI)/specs --output reports/cli_results.json

# Run comprehensive CLI tests
test-cli-comprehensive: geodetestlab-setup
	@echo "Running comprehensive CLI tests with geodetestlab..."
	@mkdir -p reports
	$(GEODETESTLAB_PYTHON) -m geodetestlab run --specs $(GEODETESTLAB_CLI)/specs --output reports/cli_comprehensive.json --verbose

# Run specific CLI spec
geodetestlab-run: geodetestlab-setup
	@if [ -z "$(SPEC)" ]; then \
		echo "Usage: make geodetestlab-run SPEC=spec_name.yml"; \
		exit 1; \
	fi
	@echo "Running $(SPEC)..."
	$(GEODETESTLAB_PYTHON) -m geodetestlab run --specs $(GEODETESTLAB_CLI)/specs/$(SPEC) --verbose

# ==============================================================================
# Shell Tests (shell_runner.py - manages own server)
# ==============================================================================

# Shell test configuration
SHELL_RUNNER := runners/shell_runner.py
SHELL_SPECS := $(wildcard specs/shell*.yaml)
GEODE_BINARY ?= ../geode/zig-out/bin/geode

# Run all shell tests (each spec manages its own server)
test-shell: setup
	@echo "Running shell tests..."
	@mkdir -p reports
	@PASSED=0; FAILED=0; \
	for spec in $(SHELL_SPECS); do \
		echo "Running: $$spec"; \
		if $(RUN_PYTHON) $(SHELL_RUNNER) --spec $$spec --geode-binary $(GEODE_BINARY) --verbose; then \
			PASSED=$$((PASSED + 1)); \
		else \
			FAILED=$$((FAILED + 1)); \
		fi; \
	done; \
	echo ""; \
	echo "Shell Tests: $$PASSED passed, $$FAILED failed"; \
	[ $$FAILED -eq 0 ]

# Run a single shell spec
test-shell-spec: setup
	@if [ -z "$(SPEC)" ]; then \
		echo "Usage: make test-shell-spec SPEC=shell_basic.yaml"; \
		exit 1; \
	fi
	@echo "Running shell spec: $(SPEC)"
	$(RUN_PYTHON) $(SHELL_RUNNER) --spec specs/$(SPEC) --geode-binary $(GEODE_BINARY) --verbose --json

# Run shell tests with JSON output
test-shell-all: setup
	@echo "Running all shell tests with JSON reports..."
	@mkdir -p reports
	@for spec in $(SHELL_SPECS); do \
		name=$$(basename $$spec .yaml); \
		echo "Running: $$name"; \
		$(RUN_PYTHON) $(SHELL_RUNNER) --spec $$spec --geode-binary $(GEODE_BINARY) --json > reports/$${name}_results.json 2>&1 || true; \
	done
	@echo "Shell test reports written to reports/"

# ==============================================================================
# Combined Tests (geodetestlab + shell tests in parallel)
# ==============================================================================

# Run both geodetestlab and shell tests sequentially
test-full: geodetestlab-setup setup
	@echo "Running full test suite (geodetestlab + shell tests)..."
	@mkdir -p reports
	@echo ""
	@echo "=== Running geodetestlab CLI tests ==="
	-$(GEODETESTLAB_PYTHON) -m geodetestlab run --specs $(GEODETESTLAB_CLI)/specs --output reports/cli_results.json --verbose
	@echo ""
	@echo "=== Running shell tests ==="
	-$(MAKE) test-shell
	@echo ""
	@echo "Full test suite complete. Reports in reports/"

# Run both geodetestlab and shell tests in parallel (background jobs)
test-full-parallel: geodetestlab-setup setup
	@echo "Running full test suite in PARALLEL (geodetestlab + shell tests)..."
	@mkdir -p reports
	@echo ""
	@echo "Starting geodetestlab CLI tests in background..."
	$(GEODETESTLAB_PYTHON) -m geodetestlab run --specs $(GEODETESTLAB_CLI)/specs --output reports/cli_results.json --verbose > reports/geodetestlab.log 2>&1 &
	@CLI_PID=$$!; \
	echo "geodetestlab PID: $$CLI_PID"; \
	echo ""; \
	echo "Starting shell tests in background..."; \
	$(MAKE) test-shell > reports/shell_tests.log 2>&1 & \
	SHELL_PID=$$!; \
	echo "shell tests PID: $$SHELL_PID"; \
	echo ""; \
	echo "Waiting for both test suites to complete..."; \
	CLI_EXIT=0; SHELL_EXIT=0; \
	wait $$CLI_PID || CLI_EXIT=$$?; \
	wait $$SHELL_PID || SHELL_EXIT=$$?; \
	echo ""; \
	echo "=== Test Results ==="; \
	if [ $$CLI_EXIT -eq 0 ]; then \
		echo "geodetestlab: PASSED"; \
	else \
		echo "geodetestlab: FAILED (see reports/geodetestlab.log)"; \
	fi; \
	if [ $$SHELL_EXIT -eq 0 ]; then \
		echo "shell tests:  PASSED"; \
	else \
		echo "shell tests:  FAILED (see reports/shell_tests.log)"; \
	fi; \
	echo ""; \
	echo "Full test logs: reports/geodetestlab.log, reports/shell_tests.log"; \
	[ $$CLI_EXIT -eq 0 ] && [ $$SHELL_EXIT -eq 0 ]

# ==============================================================================
# Unit Tests (for test harness internals)
# ==============================================================================

# Run unit tests for shared lib modules
test-unit: setup
	@echo "Running unit tests..."
	$(VENV_PYTHON) -m pytest tests/ -v

# Run unit tests with verbose output
test-unit-verbose: setup
	@echo "Running unit tests (verbose)..."
	$(VENV_PYTHON) -m pytest tests/ -v --tb=long

# ==============================================================================
# Reporting & Analysis
# ==============================================================================

test-all-html: setup
	@echo "Running all tests and generating HTML report..."
	@mkdir -p reports
	$(RUN_PYTHON) run_tests.py --verbose --report-json reports/results.json --report-html reports/test_report.html
	@echo ""
	@echo "Reports generated:"
	@echo "  JSON: reports/results.json"
	@echo "  HTML: reports/test_report.html"

report-html:
	@echo "Generating HTML report from JSON results..."
	@mkdir -p reports
	$(RUN_PYTHON) generate_html_report.py ${REPORT:-reports/results.json} --output reports/test_report.html
	@echo "HTML report generated: reports/test_report.html"

analyze-perf:
	@echo "Analyzing performance results..."
	$(RUN_PYTHON) analyze_performance.py reports/perf_results.json --verbose --markdown reports/perf_report.md
	@echo "Performance analysis complete!"
	@echo "  Report: reports/perf_report.md"

analyze-coverage:
	@echo "Analyzing test coverage..."
	$(RUN_PYTHON) analyze_coverage.py ${REPORT:-reports/results.json} --verbose --markdown reports/coverage_report.md
	@echo "Coverage analysis complete!"
	@echo "  Report: reports/coverage_report.md"

test-with-coverage: setup
	@echo "Running all tests with coverage analysis..."
	@mkdir -p reports
	@$(RUN_PYTHON) run_tests.py --verbose --report-json reports/results.json
	@$(RUN_PYTHON) analyze_coverage.py reports/results.json --verbose --markdown reports/coverage_report.md
	@echo ""
	@echo "Coverage report generated: reports/coverage_report.md"

# ==============================================================================
# Failure Routing (for CI/CD integration)
# ==============================================================================

route-failures:
	@echo "Routing failures to appropriate repositories..."
	@if [ ! -f reports/results.json ]; then \
		echo "No results file found. Run 'make test-all' first."; \
		exit 1; \
	fi
	$(RUN_PYTHON) route_failures.py reports/results.json --verbose --output reports/created_issues.json
	@echo ""
	@if [ -f reports/created_issues.json ]; then \
		echo "Created issues saved to: reports/created_issues.json"; \
	fi

route-failures-dry-run:
	@echo "Dry run: Analyzing failures for routing..."
	@if [ ! -f reports/results.json ]; then \
		echo "No results file found. Run 'make test-all' first."; \
		exit 1; \
	fi
	$(RUN_PYTHON) route_failures.py reports/results.json --dry-run --verbose

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
