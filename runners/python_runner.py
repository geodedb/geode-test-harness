#!/usr/bin/env python3
"""
Python client test runner.

Executes test specifications using the Geode Python client library.
"""

import argparse
import asyncio
import json
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

# Try to import geode_client - it may be installed as a package or in a sibling directory
_GEODE_CLIENT_AVAILABLE = False
try:
    # First try the installed package
    from geode_client import Client, Connection
    _GEODE_CLIENT_AVAILABLE = True
except ImportError:
    # Try adding Python client sibling directory to path
    sys.path.insert(0, str(Path(__file__).parent.parent.parent / "python"))
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

    def __init__(self, server: str, verbose: bool = False):
        host, port = server.split(":")

        # Use CA certificate for TLS verification
        ca_cert_path = Path(__file__).parent.parent / "certs" / "ca.crt"

        self.client = Client(
            host=host,
            port=int(port),
            ca_cert=str(ca_cert_path),
            skip_verify=True  # MSQUIC migration: self-signed cert without proper SAN validation
        )
        self.verbose = verbose
        self.connection: Optional[Connection] = None

    async def setup(self):
        """Setup runner."""
        pass

    async def teardown(self):
        """Cleanup runner."""
        if self.connection:
            try:
                await self.connection.close()
            except:
                pass

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
        self, query: str, params: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Execute a query."""
        if not self.connection:
            await self.connect()

        page, pager = await self.connection.query(query, params)

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

    async def begin_transaction(self):
        """Begin transaction."""
        if not self.connection:
            await self.connect()
        await self.connection.begin()

    async def commit_transaction(self):
        """Commit transaction."""
        if not self.connection:
            raise Exception("No active connection")
        await self.connection.commit()

    async def rollback_transaction(self):
        """Rollback transaction."""
        if not self.connection:
            raise Exception("No active connection")
        await self.connection.rollback()

    async def run_test(self, test: Dict[str, Any]) -> Dict[str, Any]:
        """Run a single test."""
        try:
            # Simple query test
            if "query" in test:
                result = await self.run_query(
                    test["query"], test.get("params", {})
                )

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

                    if step_type == "connect":
                        await self.connect()
                    elif step_type == "disconnect":
                        await self.disconnect()
                    elif step_type == "query":
                        result = await self.run_query(
                            step["text"], step.get("params", {})
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
                        await self.begin_transaction()
                    elif step_type == "commit":
                        await self.commit_transaction()
                    elif step_type == "rollback":
                        await self.rollback_transaction()
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
                results.append({"test": test["name"], "status": "skipped"})
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
        "--server", default="localhost:8443", help="Server address"
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
            print(json.dumps({
                "error": error_msg,
                "summary": {"total": 0, "passed": 0, "failed": 0, "skipped": 0, "errors": 1}
            }))
        else:
            print(f"Error: {error_msg}", file=sys.stderr)
        sys.exit(1)

    # Load spec
    with open(args.spec) as f:
        spec = yaml.safe_load(f)

    # Run tests
    runner = PythonTestRunner(args.server, args.verbose)
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
            "summary": {"total": 0, "passed": 0, "failed": 0, "errors": 1, "skipped": 0},
            "results": []
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
