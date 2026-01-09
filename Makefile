# Note: Go, Python, Rust clients have moved to separate repositories
# This test harness now only supports the Zig client
.PHONY: help setup test test-zig test-all test-comprehensive clean build-all build-zig report-html test-all-html test-auth test-perf analyze-perf analyze-coverage test-with-coverage

# Python virtual environment settings
VENV_DIR := .venv
PYTHON := python3
VENV_PYTHON := $(VENV_DIR)/bin/python3
VENV_PIP := $(VENV_DIR)/bin/pip
ACTIVATE := . $(VENV_DIR)/bin/activate

# Check if we're in a venv or nix environment
IN_VENV := $(shell python3 -c "import sys; print(1 if hasattr(sys, 'real_prefix') or (hasattr(sys, 'base_prefix') and sys.base_prefix != sys.prefix) else 0)" 2>/dev/null || echo 0)
IN_NIX := $(shell [ -n "$$NIX_BUILD_TOP" ] || [ -n "$$GEODE_NIX_BUILD" ] && echo 1 || echo 0)

# Always use venv Python if it exists, to ensure Python dependencies are available
ifneq (,$(wildcard $(VENV_PYTHON)))
    RUN_PYTHON := $(VENV_PYTHON)
else ifeq ($(IN_VENV),1)
    RUN_PYTHON := $(PYTHON)
else
    RUN_PYTHON := $(PYTHON)
endif

help:
	@echo "Client Library Test Harness (Zig only)"
	@echo ""
	@echo "Note: Go, Python, Rust clients have moved to separate repositories"
	@echo ""
	@echo "Available targets:"
	@echo "  setup            - Install dependencies and build Zig runner"
	@echo "  build-all        - Build Zig runner"
	@echo "  build-zig        - Build Zig runner"
	@echo "  test             - Run basic tests on Zig client"
	@echo "  test-zig         - Run tests on Zig client"
	@echo "  test-all         - Run all test suites (JSON report)"
	@echo "  test-comprehensive - Alias for test-all (full suite)"
	@echo "  test-all-html    - Run all tests and generate HTML report"
	@echo "  test-auth        - Run authentication tests"
	@echo "  test-perf        - Run performance benchmarks"
	@echo "  test-with-coverage - Run tests and generate coverage report"
	@echo "  report-html      - Generate HTML report from existing JSON results"
	@echo "  analyze-perf     - Analyze performance results"
	@echo "  analyze-coverage - Analyze test coverage"
	@echo "  clean            - Remove build artifacts"
	@echo ""
	@echo "Usage:"
	@echo "  make setup"
	@echo "  make test SERVER=localhost:8443"
	@echo "  make test-all-html"
	@echo "  make test-with-coverage"
	@echo "  make analyze-coverage REPORT=reports/results.json"

$(VENV_DIR):
	@echo "Creating Python virtual environment..."
	@$(PYTHON) -m venv $(VENV_DIR)
	@echo "✓ Virtual environment created at $(VENV_DIR)"

setup: $(VENV_DIR)
	@echo "Setting up client test harness..."
	@echo "Installing Python dependencies in virtual environment..."
	@$(VENV_PIP) install --upgrade pip
	@echo "Installing test harness dependencies..."
	@$(VENV_PIP) install -r requirements.txt
	@echo "✓ Python dependencies installed in $(VENV_DIR)"
	@echo "Making scripts executable..."
	@chmod +x run_tests.py 2>/dev/null || true
	@chmod +x generate_html_report.py 2>/dev/null || true
	@chmod +x analyze_performance.py 2>/dev/null || true
	@chmod +x analyze_coverage.py 2>/dev/null || true
	@echo "Building Zig runner..."
	@$(MAKE) build-zig || echo "⚠ Zig runner build failed"
	@echo "✓ Setup complete!"
	@if [ "$(IN_VENV)" = "0" ] && [ "$(IN_NIX)" = "0" ]; then \
		echo ""; \
		echo "To use the test harness, activate the virtual environment:"; \
		echo "  source $(VENV_DIR)/bin/activate"; \
		echo ""; \
		echo "Or run make targets which will use the venv automatically."; \
	fi

build-all: build-zig
	@echo "✓ Build complete"

build-zig:
	@echo "Building Zig runner..."
	@command -v zig >/dev/null 2>&1 || { echo "Zig not found, skipping"; exit 1; }
	@cd runners && zig build && cp zig-out/bin/zig_runner ./zig_runner

test: setup
	@echo "Running basic tests on Zig client..."
	$(RUN_PYTHON) run_tests.py --spec specs/basic.yaml --clients zig --verbose

test-zig: setup
	@echo "Running tests on Zig client..."
	$(RUN_PYTHON) run_tests.py --clients zig --verbose

test-all: setup
	@echo "Running all test suites on Zig client..."
	$(RUN_PYTHON) run_tests.py --clients zig --verbose --report-json reports/results.json

test-comprehensive: test-all

test-transactions: setup
	@echo "Running transaction tests..."
	$(RUN_PYTHON) run_tests.py --spec specs/transactions.yaml --verbose

test-connections: setup
	@echo "Running connection tests..."
	$(RUN_PYTHON) run_tests.py --spec specs/connections.yaml --verbose

clean:
	@echo "Cleaning build artifacts..."
	rm -f runners/go_runner
	rm -f runners/zig_runner
	rm -rf runners/rust_runner/target
	rm -rf runners/zig-out
	rm -rf runners/.zig-cache
	rm -rf reports/*.json
	rm -rf reports/*.html
	rm -rf $(VENV_DIR)
	@echo "Clean complete!"

# Server management
start-server:
	@echo "Starting Geode server..."
	@cd ../../.. && ./zig-out/bin/geode serve --listen 0.0.0.0:8443 &
	@sleep 3
	@echo "Server started on port 8443"

stop-server:
	@echo "Stopping Geode server..."
	@pkill -f "geode serve" || true
	@echo "Server stopped"

# Reporting
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

# Authentication tests
test-auth: setup
	@echo "Running authentication tests..."
	$(RUN_PYTHON) run_tests.py --spec specs/auth.yaml --verbose

# Performance benchmarking
test-perf: setup
	@echo "Running performance benchmarks..."
	@mkdir -p reports
	$(RUN_PYTHON) run_tests.py --spec specs/performance.yaml --verbose --report-json reports/perf_results.json

analyze-perf:
	@echo "Analyzing performance results..."
	$(RUN_PYTHON) analyze_performance.py reports/perf_results.json --verbose --markdown reports/perf_report.md
	@echo "Performance analysis complete!"
	@echo "  Report: reports/perf_report.md"

# Coverage analysis
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
