#!/usr/bin/env python3
"""
Python client test runner.

Executes test specifications using the Geode Python client library.
"""

import argparse
import asyncio
import json
import os
import statistics
import sys
import time
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, Optional

import yaml

# Try to import geode_client - it may be installed as a package or in a sibling directory
_GEODE_CLIENT_AVAILABLE = False
try:
    # First try the installed package
    from geode_client import Client, Connection

    _GEODE_CLIENT_AVAILABLE = True
except ImportError:
    # Try adding Python client from external repo sibling directory
    sys.path.insert(0, str(Path(__file__).parent.parent.parent / "geode-client-python"))
    try:
        from geode_client import Client, Connection

        _GEODE_CLIENT_AVAILABLE = True
    except ImportError:
        # Client not available - will report error at runtime
        Client = None
        Connection = None


class DecimalEncoder(json.JSONEncoder):
    """Custom JSON encoder that handles Decimal objects."""

    def default(self, obj):
        if isinstance(obj, Decimal):
            # Convert Decimal to float for JSON serialization
            return float(obj)
        return super().default(obj)


class PythonTestRunner:
    """Test runner for Python client."""

    # Default admin credentials for testing
    DEFAULT_USERNAME = "geode"
    DEFAULT_PASSWORD = "GeodeTestPassword123!"

    def __init__(
        self,
        server: str,
        verbose: bool = False,
        transport: str = "quic",
        username: Optional[str] = None,
        password: Optional[str] = None,
    ):
        host, port = server.split(":")

        # Get credentials from environment or use defaults
        self.username = username or os.environ.get(
            "GEODE_USERNAME", self.DEFAULT_USERNAME
        )
        self.password = (
            password
            or os.environ.get("GEODE_DEFAULT_PASSWORD")
            or os.environ.get("GEODE_ADMIN_PASSWORD", self.DEFAULT_PASSWORD)
        )

        # Determine transport type
        from geode_client import TransportType

        transport_type = (
            TransportType.GRPC if transport.lower() == "grpc" else TransportType.QUIC
        )

        # TLS Configuration:
        # - skip_verify=True: Required for test harness since Geode server uses
        #   self-signed certificates that may lack proper SAN (Subject Alternative Name)
        # - No ca_cert needed when skipping verification
        self.client = Client(
            host=host,
            port=int(port),
            skip_verify=True,
            transport_type=transport_type,
            username=self.username,
            password=self.password,
        )
        self.verbose = verbose
        self.transport = transport
        self.connection: Optional[Connection] = None
        self.connections: Dict[
            str, Connection
        ] = {}  # Connection registry for multi-connection tests

    async def setup(self):
        """Setup runner."""
        pass

    async def teardown(self):
        """Cleanup runner."""
        if self.connection:
            try:
                await self.connection.close()
            except Exception:
                pass  # Ignore connection close errors during teardown
        # Close all pooled connections
        for conn_id, conn in list(self.connections.items()):
            try:
                await conn.close()
            except Exception:
                pass  # Ignore connection close errors during teardown
        self.connections.clear()

    def _get_connection(
        self, connection_id: Optional[str] = None
    ) -> Optional[Connection]:
        """Get connection by ID or return default connection."""
        if connection_id and connection_id in self.connections:
            return self.connections[connection_id]
        return self.connection

    async def pool_acquire(self, connection_id: str):
        """Acquire a pooled connection."""
        conn = await self.client.connect()
        self.connections[connection_id] = conn

    async def pool_release(self, connection_id: str):
        """Release a pooled connection."""
        if connection_id in self.connections:
            try:
                await self.connections[connection_id].close()
            except Exception:
                pass  # Ignore connection close errors during pool release
            del self.connections[connection_id]

    async def connect(self):
        """Establish connection."""
        if not self.connection:
            self.connection = await self.client.connect()

    async def disconnect(self):
        """Close connection."""
        if self.connection:
            await self.connection.close()
            self.connection = None

    async def run_query(
        self,
        query: str,
        params: Optional[Dict[str, Any]] = None,
        connection_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Execute a query on specified or default connection."""
        conn = self._get_connection(connection_id)
        if not conn:
            if connection_id:
                raise Exception(f"Connection '{connection_id}' not found")
            await self.connect()
            conn = self.connection

        page, pager = await conn.query(query, params)

        # Collect all pages if there are more
        all_rows = list(page.rows)
        if not page.final:
            async for next_page in pager():
                all_rows.extend(next_page.rows)

        return {
            "rows": len(all_rows),
            "columns": [col.name for col in page.columns],
            "data": [
                {col.name: row[col.name].raw_value for col in page.columns}
                for row in all_rows
            ],
        }

    async def begin_transaction(self, connection_id: Optional[str] = None):
        """Begin transaction on specified or default connection."""
        conn = self._get_connection(connection_id)
        if not conn:
            if connection_id:
                raise Exception(f"Connection '{connection_id}' not found")
            await self.connect()
            conn = self.connection
        await conn.begin()

    async def commit_transaction(self, connection_id: Optional[str] = None):
        """Commit transaction on specified or default connection."""
        conn = self._get_connection(connection_id)
        if not conn:
            raise Exception(
                f"No active connection{' for ' + connection_id if connection_id else ''}"
            )
        await conn.commit()

    async def rollback_transaction(self, connection_id: Optional[str] = None):
        """Rollback transaction on specified or default connection."""
        conn = self._get_connection(connection_id)
        if not conn:
            raise Exception(
                f"No active connection{' for ' + connection_id if connection_id else ''}"
            )
        await conn.rollback()

    async def run_test(self, test: Dict[str, Any]) -> Dict[str, Any]:
        """Run a single test."""
        # Check if this is a benchmark test
        benchmark = test.get("benchmark")
        if benchmark:
            return await self._run_benchmark_test(test, benchmark)

        return await self._run_single_test(test)

    async def _run_benchmark_test(
        self, test: Dict[str, Any], benchmark: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Run a benchmark test with multiple iterations."""
        iterations = benchmark.get("iterations", 10)
        max_avg_latency_ms = benchmark.get("max_avg_latency_ms")
        max_p95_latency_ms = benchmark.get("max_p95_latency_ms")
        max_total_time_ms = benchmark.get("max_total_time_ms")

        latencies = []
        errors = []
        start_total = time.time()

        for i in range(iterations):
            start = time.time()
            try:
                result = await self._run_single_test(test)
                latency_ms = (time.time() - start) * 1000
                latencies.append(latency_ms)

                if result.get("status") != "passed":
                    errors.append(
                        f"Iteration {i+1}: {result.get('error', 'Unknown error')}"
                    )
            except Exception as e:
                latencies.append((time.time() - start) * 1000)
                errors.append(f"Iteration {i+1}: {str(e)}")

        total_time_ms = (time.time() - start_total) * 1000

        if not latencies:
            return {"status": "error", "error": "No benchmark iterations completed"}

        # Calculate statistics
        avg_latency = statistics.mean(latencies)
        sorted_latencies = sorted(latencies)
        p95_index = int(len(sorted_latencies) * 0.95)
        p95_latency = sorted_latencies[min(p95_index, len(sorted_latencies) - 1)]

        benchmark_result = {
            "iterations": iterations,
            "avg_latency_ms": round(avg_latency, 2),
            "p95_latency_ms": round(p95_latency, 2),
            "min_latency_ms": round(min(latencies), 2),
            "max_latency_ms": round(max(latencies), 2),
            "total_time_ms": round(total_time_ms, 2),
            "errors": len(errors),
        }

        # Check thresholds
        failures = []
        if max_avg_latency_ms and avg_latency > max_avg_latency_ms:
            failures.append(
                f"Average latency {avg_latency:.2f}ms exceeds max {max_avg_latency_ms}ms"
            )
        if max_p95_latency_ms and p95_latency > max_p95_latency_ms:
            failures.append(
                f"P95 latency {p95_latency:.2f}ms exceeds max {max_p95_latency_ms}ms"
            )
        if max_total_time_ms and total_time_ms > max_total_time_ms:
            failures.append(
                f"Total time {total_time_ms:.2f}ms exceeds max {max_total_time_ms}ms"
            )

        if failures:
            return {
                "status": "failed",
                "error": "; ".join(failures),
                "benchmark": benchmark_result,
            }

        if errors:
            return {
                "status": "passed",
                "warning": f"{len(errors)} iterations had errors",
                "benchmark": benchmark_result,
            }

        return {"status": "passed", "benchmark": benchmark_result}

    async def _run_single_test(self, test: Dict[str, Any]) -> Dict[str, Any]:
        """Run a single test iteration."""
        try:
            # Simple query test
            if "query" in test:
                result = await self.run_query(test["query"], test.get("params", {}))

                # Validate expectations
                expect = test.get("expect", {})

                if "rows" in expect and result["rows"] != expect["rows"]:
                    return {
                        "status": "failed",
                        "error": f"Expected {expect['rows']} rows, got {result['rows']}",
                        "result": result,
                    }

                if "columns" in expect:
                    if set(result["columns"]) != set(expect["columns"]):
                        return {
                            "status": "failed",
                            "error": f"Expected columns {expect['columns']}, got {result['columns']}",
                            "result": result,
                        }

                if "values" in expect and len(expect["values"]) > 0:
                    for i, expected_row in enumerate(expect["values"]):
                        if i >= len(result["data"]):
                            return {
                                "status": "failed",
                                "error": f"Expected row {i} missing",
                                "result": result,
                            }

                        actual_row = result["data"][i]
                        for key, expected_value in expected_row.items():
                            if key not in actual_row:
                                return {
                                    "status": "failed",
                                    "error": f"Expected column '{key}' missing in row {i}",
                                    "result": result,
                                }

                            actual_value = actual_row[key]
                            if actual_value != expected_value:
                                return {
                                    "status": "failed",
                                    "error": f"Expected {key}={expected_value}, got {actual_value}",
                                    "result": result,
                                }

                return {"status": "passed", "result": result}

            # Step-based test
            elif "steps" in test:
                results = []
                for step in test["steps"]:
                    step_type = step.get("type")
                    connection_id = step.get("connection_id")

                    if step_type == "connect":
                        if connection_id:
                            # Multi-connection: create named connection
                            await self.pool_acquire(connection_id)
                        else:
                            await self.connect()
                    elif step_type == "disconnect":
                        if connection_id:
                            await self.pool_release(connection_id)
                        else:
                            await self.disconnect()
                    elif step_type == "pool_acquire":
                        conn_id = connection_id or step.get("id", "default")
                        await self.pool_acquire(conn_id)
                    elif step_type == "pool_release":
                        conn_id = connection_id or step.get("id", "default")
                        await self.pool_release(conn_id)
                    elif step_type == "query":
                        result = await self.run_query(
                            step["text"], step.get("params", {}), connection_id
                        )
                        results.append(result)

                        # Check expectations
                        expect = step.get("expect", {})
                        if "rows" in expect and result["rows"] != expect["rows"]:
                            if not step.get("expect_error", False):
                                return {
                                    "status": "failed",
                                    "error": f"Step query: Expected {expect['rows']} rows, got {result['rows']}",
                                    "results": results,
                                }
                    elif step_type == "begin":
                        await self.begin_transaction(connection_id)
                    elif step_type == "commit":
                        await self.commit_transaction(connection_id)
                    elif step_type == "rollback":
                        await self.rollback_transaction(connection_id)
                    else:
                        if self.verbose:
                            print(f"Unknown step type: {step_type}", file=sys.stderr)

                return {"status": "passed", "results": results}

            else:
                return {
                    "status": "error",
                    "error": "Test must have 'query' or 'steps'",
                }

        except Exception as e:
            # Check if error was expected
            if test.get("expect_error", False) or any(
                step.get("expect_error", False) for step in test.get("steps", [])
            ):
                return {"status": "passed", "error_expected": str(e)}

            return {"status": "error", "error": str(e)}

    async def run_spec(self, spec: Dict[str, Any]) -> Dict[str, Any]:
        """Run entire test specification."""
        results = []

        # Run setup
        for setup_step in spec.get("setup", []):
            try:
                if setup_step["type"] == "query":
                    await self.run_query(setup_step["text"])
            except Exception as e:
                print(f"Setup failed: {e}", file=sys.stderr)
                return {"status": "error", "error": f"Setup failed: {e}"}

        # Run tests
        for test in spec.get("tests", []):
            if test.get("skip", False):
                result = {"test": test["name"], "status": "skipped"}
                if "skip_reason" in test:
                    result["skip_reason"] = test["skip_reason"]
                results.append(result)
                continue

            result = await self.run_test(test)
            result["test"] = test["name"]
            results.append(result)

        # Run cleanup
        for cleanup_step in spec.get("cleanup", []):
            try:
                if cleanup_step["type"] == "query":
                    await self.run_query(cleanup_step["text"])
            except Exception as e:
                print(f"Cleanup warning: {e}", file=sys.stderr)

        # Calculate summary
        passed = sum(1 for r in results if r["status"] == "passed")
        failed = sum(1 for r in results if r["status"] == "failed")
        errors = sum(1 for r in results if r["status"] == "error")
        skipped = sum(1 for r in results if r["status"] == "skipped")

        return {
            "summary": {
                "total": len(results),
                "passed": passed,
                "failed": failed,
                "errors": errors,
                "skipped": skipped,
            },
            "results": results,
        }


async def main():
    parser = argparse.ArgumentParser(description="Python client test runner")
    parser.add_argument("--spec", required=True, type=Path, help="Test specification")
    parser.add_argument(
        "--server",
        default="localhost:3141",
        help="Server address (default: localhost:3141)",
    )
    parser.add_argument(
        "--transport",
        default="quic",
        choices=["quic", "grpc"],
        help="Transport protocol (default: quic)",
    )
    parser.add_argument("--json", action="store_true", help="Output JSON")
    parser.add_argument("--verbose", action="store_true", help="Verbose output")

    args = parser.parse_args()

    # Check if Python client is available
    if not _GEODE_CLIENT_AVAILABLE:
        error_msg = (
            "Python client (geode_client) is not installed.\n"
            "Install it from: pip install geode-client\n"
            "Or clone from: git@gitlab.com:devnw/geode/geode-client-python.git"
        )
        if args.json:
            print(
                json.dumps(
                    {
                        "error": error_msg,
                        "summary": {
                            "total": 0,
                            "passed": 0,
                            "failed": 0,
                            "skipped": 0,
                            "errors": 1,
                        },
                    }
                )
            )
        else:
            print(f"Error: {error_msg}", file=sys.stderr)
        sys.exit(1)

    # Load spec
    with open(args.spec) as f:
        spec = yaml.safe_load(f)

    # Run tests
    runner = PythonTestRunner(args.server, args.verbose, transport=args.transport)
    try:
        await runner.setup()
        result = await runner.run_spec(spec)

        if args.json:
            print(json.dumps(result, indent=2, cls=DecimalEncoder))
        else:
            print(f"Tests: {result['summary']['total']}")
            print(f"Passed: {result['summary']['passed']}")
            print(f"Failed: {result['summary']['failed']}")
            print(f"Errors: {result['summary']['errors']}")

        sys.exit(0)

    except Exception as e:
        # Ensure we always output valid JSON even when runner crashes
        error_result = {
            "summary": {
                "total": 0,
                "passed": 0,
                "failed": 0,
                "errors": 1,
                "skipped": 0,
            },
            "results": [],
        }
        if args.json:
            print(json.dumps(error_result, indent=2))
        else:
            print(f"Runner error: {e}", file=sys.stderr)
        sys.exit(1)

    finally:
        await runner.teardown()


if __name__ == "__main__":
    asyncio.run(main())
