import os
import tempfile
from typing import Any, Dict


def run_source_test(runner, test: Dict[str, Any]) -> Dict[str, Any]:
    """Run a /source file test."""
    result = {
        "test_name": test.get("name", "unnamed"),
        "status": "passed",
        "error": None,
        "details": {},
    }

    # Create the source file if content is provided
    source_content = test.get("source_content")
    source_file = test.get("source_file")

    if source_content:
        # Write content to a temporary file
        with tempfile.NamedTemporaryFile(mode="w", suffix=".gql", delete=False) as f:
            f.write(source_content)
            source_file = f.name
        result["details"]["temp_file"] = source_file

    if not source_file:
        result["status"] = "error"
        result["error"] = "No source_file or source_content provided"
        return result

    # Execute /source
    source_result = runner.source_file(
        source_file, test.get("timeout_ms", 300000) // 1000
    )
    result["details"]["source_result"] = source_result

    # Check expectations
    expect = test.get("expect", {})

    if expect.get("success", True) and source_result.get("has_errors"):
        result["status"] = "failed"
        result["error"] = (
            f"Expected success but got errors: {source_result.get('output', '')[:500]}"
        )

    if "statements" in expect:
        actual = source_result.get("statements_executed", 0)
        expected = expect["statements"]
        if actual != expected:
            result["status"] = "failed"
            result["error"] = f"Expected {expected} statements, got {actual}"

    # Clean up temp file if created
    if source_content and source_file:
        try:
            os.unlink(source_file)
        except OSError:
            pass

    return result


def run_persistence_test(runner, test: Dict[str, Any]) -> Dict[str, Any]:
    """Run a persistence test - verifies data survives server restart."""
    import time

    result = {
        "test_name": test.get("name", "unnamed"),
        "status": "passed",
        "error": None,
        "details": {},
    }

    steps = test.get("steps", [])

    for i, step in enumerate(steps):
        step_type = step.get("type")

        if step_type == "create_data":
            # Create data via shell
            source_content = step.get("content")
            if source_content:
                with tempfile.NamedTemporaryFile(
                    mode="w", suffix=".gql", delete=False
                ) as f:
                    f.write(source_content)
                    temp_file = f.name

                source_result = runner.source_file(temp_file)
                result["details"][f"step_{i}_source"] = source_result

                os.unlink(temp_file)

                if source_result.get("has_errors"):
                    result["status"] = "failed"
                    result["error"] = (
                        f"Step {i} failed: {source_result.get('output', '')[:500]}"
                    )
                    return result

        elif step_type == "check_persistence_file":
            # Check that the persistence file exists and has data
            persistence_files = step.get("files", ["graph_store.dat"])
            total_size = 0

            for filename in persistence_files:
                persistence_file = os.path.join(runner.data_dir, filename)

                if not runner.check_file_exists(persistence_file):
                    result["status"] = "failed"
                    result["error"] = f"Persistence file not found: {persistence_file}"
                    return result

                file_size = runner.get_file_size(persistence_file)
                result["details"][f"persistence_file_size_{filename}"] = file_size
                total_size += file_size

            min_size = step.get("min_size", 0)
            if total_size < min_size:
                result["status"] = "failed"
                result["error"] = (
                    f"Persistence files total size too small: {total_size} < {min_size}"
                )
                return result

        elif step_type == "restart_server":
            # Restart the server to test persistence
            runner.stop_shell()
            runner.stop_server()

            time.sleep(1)

            if not runner.start_server():
                result["status"] = "failed"
                result["error"] = "Failed to restart server"
                return result

            if not runner.start_shell():
                result["status"] = "failed"
                result["error"] = "Failed to reconnect shell after restart"
                return result

        elif step_type == "verify_data":
            # Verify data exists after restart
            query = step.get("query")
            if query:
                query_result = runner.execute_query(query)
                result["details"][f"step_{i}_verify"] = query_result

                expect = step.get("expect", {})
                if "min_rows" in expect:
                    if query_result.get("rows", 0) < expect["min_rows"]:
                        result["status"] = "failed"
                        result["error"] = (
                            f"Expected at least {expect['min_rows']} rows, got {query_result.get('rows', 0)}"
                        )
                        return result

    return result


def run_query_test(runner, test: Dict[str, Any]) -> Dict[str, Any]:
    """Run a simple query test through the shell."""
    result = {
        "test_name": test.get("name", "unnamed"),
        "status": "passed",
        "error": None,
        "details": {},
    }

    query = test.get("query")
    if not query:
        result["status"] = "error"
        result["error"] = "No query provided"
        return result

    query_result = runner.execute_query(query)
    result["details"]["query_result"] = query_result

    expect = test.get("expect", {})

    if query_result.get("status") == "error":
        if not expect.get("error"):
            result["status"] = "failed"
            result["error"] = f"Query failed: {query_result.get('error')}"

    if "rows" in expect:
        actual = query_result.get("rows", 0)
        expected = expect["rows"]
        if actual != expected:
            result["status"] = "failed"
            result["error"] = f"Expected {expected} rows, got {actual}"

    return result


def run_steps_test(runner, test: Dict[str, Any]) -> Dict[str, Any]:
    """Run a multi-step shell test."""
    result = {
        "test_name": test.get("name", "unnamed"),
        "status": "passed",
        "error": None,
        "details": {},
    }

    steps = test.get("steps", [])

    for i, step in enumerate(steps):
        step_type = step.get("type")

        if step_type == "command":
            cmd = step.get("text")
            success, output = runner.send_command(
                cmd, step.get("timeout_ms", 30000) // 1000
            )
            result["details"][f"step_{i}"] = {
                "command": cmd,
                "success": success,
                "output": output[:500],
            }

            if not success:
                result["status"] = "failed"
                result["error"] = f"Step {i} failed: {output}"
                return result

            # Check expectations
            expect = step.get("expect", {})
            if "contains" in expect:
                for expected_text in expect["contains"]:
                    if expected_text not in output:
                        result["status"] = "failed"
                        result["error"] = (
                            f"Step {i}: Expected output to contain '{expected_text}'"
                        )
                        return result

        elif step_type == "query":
            query = step.get("text")
            query_result = runner.execute_query(query)
            result["details"][f"step_{i}"] = query_result

            if query_result.get("status") == "error":
                result["status"] = "failed"
                result["error"] = f"Step {i} query failed: {query_result.get('error')}"
                return result

    return result
