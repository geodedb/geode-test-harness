import os

filepath = "geodetestlab-cli/geodetestlab/lib/assertions.py"

with open(filepath, "r") as f:
    content = f.read()

import re

# We will replace the evaluate_assertions function
new_func = """def _eval_exit_code(expect: TestExpectations, exit_code: int) -> list[dict[str, Any]]:
    if expect.exit_code is None:
        return []
    return [{
        "type": "exit_code",
        "ok": exit_code == expect.exit_code,
        "expected": expect.exit_code,
        "actual": exit_code,
    }]

def _eval_stdout_exact(expect: TestExpectations, stdout: str) -> list[dict[str, Any]]:
    if expect.stdout_exact is None:
        return []
    return [{
        "type": "stdout_exact",
        "ok": stdout.strip() == expect.stdout_exact.strip(),
        "expected": expect.stdout_exact,
        "actual": stdout,
    }]

def _eval_stdout_contains(expect: TestExpectations, stdout: str) -> list[dict[str, Any]]:
    if not expect.stdout_contains:
        return []
    return [{
        "type": "stdout_contains",
        "ok": item in stdout,
        "expected": item,
        "actual": stdout,
    } for item in expect.stdout_contains]

def _eval_stdout_regex(expect: TestExpectations, stdout: str) -> list[dict[str, Any]]:
    if not expect.stdout_regex:
        return []
    results = []
    for pattern in expect.stdout_regex:
        try:
            matched = bool(re.search(pattern, stdout))
            results.append({
                "type": "stdout_regex",
                "ok": matched,
                "pattern": pattern,
                "actual": stdout,
            })
        except re.error as e:
            results.append({
                "type": "stdout_regex",
                "ok": False,
                "pattern": pattern,
                "error": f"Invalid regex: {e}",
            })
    return results

def _eval_stderr_contains(expect: TestExpectations, stderr: str) -> list[dict[str, Any]]:
    if not expect.stderr_contains:
        return []
    return [{
        "type": "stderr_contains",
        "ok": item in stderr,
        "expected": item,
        "actual": stderr,
    } for item in expect.stderr_contains]

def _eval_stderr_regex(expect: TestExpectations, stderr: str) -> list[dict[str, Any]]:
    if not expect.stderr_regex:
        return []
    results = []
    for pattern in expect.stderr_regex:
        try:
            matched = bool(re.search(pattern, stderr))
            results.append({
                "type": "stderr_regex",
                "ok": matched,
                "pattern": pattern,
                "actual": stderr,
            })
        except re.error as e:
            results.append({
                "type": "stderr_regex",
                "ok": False,
                "pattern": pattern,
                "error": f"Invalid regex: {e}",
            })
    return results

def _eval_stdout_json_assert(expect: TestExpectations, stdout: str) -> list[dict[str, Any]]:
    if not expect.stdout_json_assert:
        return []
    results = []
    import json
    for json_assert in expect.stdout_json_assert:
        result: dict[str, Any] = {"type": "stdout_json_assert"}
        try:
            parsed = json.loads(stdout)
            value = _resolve_json_expression(parsed, json_assert.expression)
            result["extracted_value"] = value

            if json_assert.equals is not None:
                result["ok"] = value == json_assert.equals
                result["expected"] = json_assert.equals
            elif json_assert.not_equals is not None:
                result["ok"] = value != json_assert.not_equals
                result["not_expected"] = json_assert.not_equals
            elif json_assert.matches_regex is not None:
                result["ok"] = bool(re.search(json_assert.matches_regex, str(value)))
                result["pattern"] = json_assert.matches_regex
            else:
                result["ok"] = True
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            result["ok"] = False
            result["error"] = str(e)
        results.append(result)
    return results

def _eval_geode_query(expect: TestExpectations, stdout: str) -> list[dict[str, Any]]:
    if not expect.geode_query:
        return []
    gq = expect.geode_query
    results = []
    import json
    try:
        parsed = json.loads(stdout)
    except (json.JSONDecodeError, TypeError):
        parsed = {}

    rows = _extract_rows_from_geode_output(parsed)
    row_count = len(rows) if rows is not None else 0

    if gq.row_count is not None:
        results.append({
            "type": "geode_row_count",
            "ok": row_count == gq.row_count,
            "expected": gq.row_count,
            "actual": row_count,
        })

    if gq.min_rows is not None:
        results.append({
            "type": "geode_min_rows",
            "ok": row_count >= gq.min_rows,
            "minimum": gq.min_rows,
            "actual": row_count,
        })

    if gq.max_rows is not None:
        results.append({
            "type": "geode_max_rows",
            "ok": row_count <= gq.max_rows,
            "maximum": gq.max_rows,
            "actual": row_count,
        })

    if gq.columns is not None:
        actual_columns = list(parsed.get("columns", []))
        if not actual_columns and rows:
            actual_columns = list(rows[0].keys())
        results.append({
            "type": "geode_columns",
            "ok": set(gq.columns) <= set(actual_columns),
            "expected": gq.columns,
            "actual": actual_columns,
        })

    if gq.contains_node is not None:
        found = False
        if rows:
            for row in rows:
                values_to_check = [row]
                values_to_check.extend(v for v in row.values() if isinstance(v, dict))
                for obj in values_to_check:
                    if all(str(obj.get(k)) == str(v) for k, v in gq.contains_node.items()):
                        found = True
                        break
                if found:
                    break
        results.append({
            "type": "geode_contains_node",
            "ok": found,
            "expected_node": gq.contains_node,
        })

    if gq.execution_time_ms is not None:
        metadata = parsed.get("metadata", {})
        actual_time = metadata.get("execution_time_ms", 0)
        results.append({
            "type": "geode_execution_time",
            "ok": actual_time <= gq.execution_time_ms,
            "max_time_ms": gq.execution_time_ms,
            "actual_time_ms": actual_time,
        })

    return results

def _eval_server_responsive(expect: TestExpectations, exit_code: int) -> list[dict[str, Any]]:
    if expect.server_responsive is None:
        return []
    return [{
        "type": "server_responsive",
        "ok": (exit_code == 0) == expect.server_responsive,
        "expected_responsive": expect.server_responsive,
        "exit_code": exit_code,
    }]

def evaluate_assertions(
    expect: TestExpectations,
    exit_code: int,
    stdout: str,
    stderr: str,
) -> list[dict[str, Any]]:
    \"\"\"Evaluate all assertions and return detailed results.

    Parameters
    ----------
    expect : TestExpectations
        The expected results to check against.
    exit_code : int
        The actual exit code of the command.
    stdout : str
        The captured stdout.
    stderr : str
        The captured stderr.

    Returns
    -------
    list[dict[str, Any]]
        A list of assertion result dicts, each containing at minimum
        'type' (str) and 'ok' (bool).
    \"\"\"
    results: list[dict[str, Any]] = []

    results.extend(_eval_exit_code(expect, exit_code))
    results.extend(_eval_stdout_exact(expect, stdout))
    results.extend(_eval_stdout_contains(expect, stdout))
    results.extend(_eval_stdout_regex(expect, stdout))
    results.extend(_eval_stderr_contains(expect, stderr))
    results.extend(_eval_stderr_regex(expect, stderr))
    results.extend(_eval_stdout_json_assert(expect, stdout))
    results.extend(_eval_geode_query(expect, stdout))
    results.extend(_eval_server_responsive(expect, exit_code))

    return results
"""

# Find the start of evaluate_assertions
start_idx = content.find("def evaluate_assertions(")
if start_idx != -1:
    content = content[:start_idx] + new_func
    with open(filepath, "w") as f:
        f.write(content)
    print("Successfully replaced evaluate_assertions")
else:
    print("Could not find evaluate_assertions")
