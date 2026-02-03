"""Tests for assertion evaluation."""

from geodetestlab.core.assertions import _extract_rows_from_geode_output, evaluate_assertions
from geodetestlab.core.spec import GeodeQueryAssert, StdoutJsonAssert, TestExpectations


def test_exit_code_assertion():
    """Test exit code assertion."""
    expect = TestExpectations(exit_code=0)
    results = evaluate_assertions(expect, 0, "", "")

    assert len(results) == 1
    assert results[0]["type"] == "exit_code"
    assert results[0]["ok"] is True
    assert results[0]["expected"] == 0
    assert results[0]["actual"] == 0

    # Test failure
    results = evaluate_assertions(expect, 1, "", "")
    assert results[0]["ok"] is False


def test_stdout_exact_assertion():
    """Test exact stdout matching."""
    expect = TestExpectations(stdout_exact="Hello, World!")
    results = evaluate_assertions(expect, 0, "Hello, World!", "")

    assert len(results) == 1
    assert results[0]["type"] == "stdout_exact"
    assert results[0]["ok"] is True

    # Test failure
    results = evaluate_assertions(expect, 0, "Hello, Universe!", "")
    assert results[0]["ok"] is False


def test_stdout_contains_assertion():
    """Test stdout contains assertion."""
    expect = TestExpectations(stdout_contains=["Hello", "World"])
    results = evaluate_assertions(expect, 0, "Hello, beautiful World!", "")

    assert len(results) == 2
    assert all(r["ok"] for r in results)
    assert all(r["type"] == "stdout_contains" for r in results)

    # Test partial failure
    results = evaluate_assertions(expect, 0, "Hello, Universe!", "")
    assert results[0]["ok"] is True  # "Hello" found
    assert results[1]["ok"] is False  # "World" not found


def test_stdout_regex_assertion():
    """Test stdout regex assertion."""
    expect = TestExpectations(stdout_regex=[r"\d+", r"result:\s*\w+"])
    results = evaluate_assertions(expect, 0, "Found 42 items, result: success", "")

    assert len(results) == 2
    assert all(r["ok"] for r in results)
    assert all(r["type"] == "stdout_regex" for r in results)

    # Test invalid regex
    expect = TestExpectations(stdout_regex=["[invalid regex"])
    results = evaluate_assertions(expect, 0, "test", "")
    assert results[0]["ok"] is False
    assert "error" in results[0]


def test_stderr_assertions():
    """Test stderr contains and regex assertions."""
    expect = TestExpectations(stderr_contains=["Error", "failed"], stderr_regex=[r"Error \d+", r"failed.*execution"])

    stderr = "Error 404: Operation failed during execution"
    results = evaluate_assertions(expect, 1, "", stderr)

    # Should have 4 results: 2 contains + 2 regex
    assert len(results) == 4
    assert all(r["ok"] for r in results)


def test_json_assert_equals():
    """Test JSON assertion with equals."""
    json_assert = StdoutJsonAssert(expression="result.count", equals=42)
    expect = TestExpectations(stdout_json_assert=[json_assert])

    stdout = '{"result": {"count": 42, "status": "ok"}}'
    results = evaluate_assertions(expect, 0, stdout, "")

    assert len(results) == 1
    assert results[0]["type"] == "stdout_json_assert"
    assert results[0]["ok"] is True
    assert results[0]["extracted_value"] == 42


def test_json_assert_not_equals():
    """Test JSON assertion with not_equals."""
    json_assert = StdoutJsonAssert(expression="status", not_equals="error")
    expect = TestExpectations(stdout_json_assert=[json_assert])

    stdout = '{"status": "success", "data": []}'
    results = evaluate_assertions(expect, 0, stdout, "")

    assert len(results) == 1
    assert results[0]["ok"] is True
    assert results[0]["extracted_value"] == "success"


def test_json_assert_regex():
    """Test JSON assertion with regex matching."""
    json_assert = StdoutJsonAssert(expression="message", matches_regex=r"completed in \d+ms")
    expect = TestExpectations(stdout_json_assert=[json_assert])

    stdout = '{"message": "Query completed in 123ms", "rows": 5}'
    results = evaluate_assertions(expect, 0, stdout, "")

    assert len(results) == 1
    assert results[0]["ok"] is True


def test_json_assert_invalid_json():
    """Test JSON assertion with invalid JSON."""
    json_assert = StdoutJsonAssert(expression="result", equals=42)
    expect = TestExpectations(stdout_json_assert=[json_assert])

    stdout = "This is not JSON"
    results = evaluate_assertions(expect, 0, stdout, "")

    assert len(results) == 1
    assert results[0]["ok"] is False
    assert "error" in results[0]


def test_geode_query_row_count():
    """Test Geode query row count assertion."""
    geode_assert = GeodeQueryAssert(row_count=2)
    expect = TestExpectations(geode_query=geode_assert)

    stdout = '{"results": [{"id": 1, "name": "Alice"}, {"id": 2, "name": "Bob"}]}'
    results = evaluate_assertions(expect, 0, stdout, "")

    # Find the row count assertion
    row_count_result = next(r for r in results if r["type"] == "geode_row_count")
    assert row_count_result["ok"] is True
    assert row_count_result["expected"] == 2
    assert row_count_result["actual"] == 2


def test_geode_query_min_max_rows():
    """Test Geode query min/max rows assertions."""
    geode_assert = GeodeQueryAssert(min_rows=1, max_rows=5)
    expect = TestExpectations(geode_query=geode_assert)

    stdout = '{"results": [{"id": 1}, {"id": 2}, {"id": 3}]}'
    results = evaluate_assertions(expect, 0, stdout, "")

    # Check min_rows assertion
    min_result = next(r for r in results if r["type"] == "geode_min_rows")
    assert min_result["ok"] is True
    assert min_result["minimum"] == 1
    assert min_result["actual"] == 3

    # Check max_rows assertion
    max_result = next(r for r in results if r["type"] == "geode_max_rows")
    assert max_result["ok"] is True
    assert max_result["maximum"] == 5
    assert max_result["actual"] == 3


def test_geode_query_columns():
    """Test Geode query columns assertion."""
    geode_assert = GeodeQueryAssert(columns=["id", "name"])
    expect = TestExpectations(geode_query=geode_assert)

    stdout = '{"columns": ["id", "name", "age"], "results": [{"id": 1, "name": "Alice", "age": 30}]}'
    results = evaluate_assertions(expect, 0, stdout, "")

    # Find the columns assertion
    columns_result = next(r for r in results if r["type"] == "geode_columns")
    assert columns_result["ok"] is True
    assert set(columns_result["expected"]) <= set(columns_result["actual"])


def test_geode_query_contains_node():
    """Test Geode query contains node assertion."""
    geode_assert = GeodeQueryAssert(contains_node={"name": "Alice", "age": 30})
    expect = TestExpectations(geode_query=geode_assert)

    stdout = '{"results": [{"person": {"name": "Alice", "age": 30, "city": "NYC"}}]}'
    results = evaluate_assertions(expect, 0, stdout, "")

    # Find the contains_node assertion
    node_result = next(r for r in results if r["type"] == "geode_contains_node")
    assert node_result["ok"] is True


def test_geode_query_execution_time():
    """Test Geode query execution time assertion."""
    geode_assert = GeodeQueryAssert(execution_time_ms=1000)
    expect = TestExpectations(geode_query=geode_assert)

    stdout = '{"results": [], "metadata": {"execution_time_ms": 500}}'
    results = evaluate_assertions(expect, 0, stdout, "")

    # Find the execution time assertion
    time_result = next(r for r in results if r["type"] == "geode_execution_time")
    assert time_result["ok"] is True
    assert time_result["max_time_ms"] == 1000
    assert time_result["actual_time_ms"] == 500


def test_extract_rows_from_geode_output():
    """Test extracting rows from different Geode output formats."""
    # Standard results format
    data = {"results": [{"id": 1}, {"id": 2}]}
    rows = _extract_rows_from_geode_output(data)
    assert rows == [{"id": 1}, {"id": 2}]

    # Alternative rows format
    data = {"rows": [{"name": "Alice"}, {"name": "Bob"}]}
    rows = _extract_rows_from_geode_output(data)
    assert rows == [{"name": "Alice"}, {"name": "Bob"}]

    # Data format
    data = {"data": [{"value": 42}]}
    rows = _extract_rows_from_geode_output(data)
    assert rows == [{"value": 42}]

    # Direct array format
    data = [{"id": 1}, {"id": 2}]
    rows = _extract_rows_from_geode_output(data)
    assert rows == [{"id": 1}, {"id": 2}]

    # No recognizable format
    data = {"other": "value"}
    rows = _extract_rows_from_geode_output(data)
    assert rows is None


def test_server_responsive_assertion():
    """Test server responsive assertion."""
    expect = TestExpectations(server_responsive=True)
    results = evaluate_assertions(expect, 0, "", "")

    # Find the server responsive assertion
    server_result = next(r for r in results if r["type"] == "server_responsive")
    assert server_result["ok"] is True  # exit_code 0 implies responsive

    # Test with non-zero exit code
    results = evaluate_assertions(expect, 1, "", "")
    server_result = next(r for r in results if r["type"] == "server_responsive")
    assert server_result["ok"] is False


def test_multiple_assertions():
    """Test evaluation of multiple assertions together."""
    expect = TestExpectations(
        exit_code=0, stdout_contains=["success"], geode_query=GeodeQueryAssert(row_count=1), server_responsive=True
    )

    stdout = '{"status": "success", "results": [{"id": 42}]}'
    results = evaluate_assertions(expect, 0, stdout, "")

    # Should have multiple assertion results
    assert len(results) >= 4  # At least exit_code, stdout_contains, geode_row_count, server_responsive

    # All should pass
    assert all(r["ok"] for r in results)
