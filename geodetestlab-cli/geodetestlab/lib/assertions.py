"""Structured assertion evaluation for test expectations.

.. deprecated::
    This module is **not used by the test runner**.  The runner uses
    ``checks.py`` for pass/fail determination.  This module exists as a
    candidate for future structured reporting (per-assertion detail) but
    has **diverged** from ``checks.py`` and is missing several assertion
    types (``result_contains``, ``result_not_contains``, ``result_matches``,
    ``error_contains``, ``stdout_not_contains``, ``stderr_not_contains``,
    ``stderr_exact``).

    **Do not add new assertion logic here** without also wiring it into the
    runner.  If you need to add a new expectation check, add it to
    ``checks.py`` (the authoritative implementation).

See also: QG-004 in ``docs/QUALITY_GAP_ANALYSIS.md``.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any


@dataclass
class StdoutJsonAssert:
    """A single JSON path assertion against stdout."""

    expression: str
    equals: Any = None
    not_equals: Any = None
    matches_regex: str | None = None


@dataclass
class GeodeQueryAssert:
    """Assertions specific to Geode query results."""

    row_count: int | None = None
    min_rows: int | None = None
    max_rows: int | None = None
    columns: list[str] | None = None
    contains_node: dict[str, Any] | None = None
    execution_time_ms: int | None = None


@dataclass
class TestExpectations:
    """Expected results for a test, used for structured assertion evaluation."""

    exit_code: int | None = None
    stdout_exact: str | None = None
    stdout_contains: list[str] | None = None
    stdout_regex: list[str] | None = None
    stderr_contains: list[str] | None = None
    stderr_regex: list[str] | None = None
    stdout_json_assert: list[StdoutJsonAssert] | None = None
    geode_query: GeodeQueryAssert | None = None
    server_responsive: bool | None = None


def _extract_rows_from_geode_output(data: Any) -> list[dict[str, Any]] | None:
    """Extract rows from various Geode output formats.

    Parameters
    ----------
    data : Any
        Parsed JSON data from Geode output.

    Returns
    -------
    list[dict[str, Any]] | None
        Extracted rows, or None if format is unrecognized.
    """
    if isinstance(data, list):
        return data

    if isinstance(data, dict):
        for key in ("results", "rows", "data"):
            if key in data and isinstance(data[key], list):
                return data[key]  # type: ignore[no-any-return]

    return None


def _resolve_json_expression(data: Any, expression: str) -> Any:
    """Resolve a dotted expression against parsed JSON data.

    Parameters
    ----------
    data : Any
        Parsed JSON data.
    expression : str
        Dotted path expression (e.g. "result.count").

    Returns
    -------
    Any
        The resolved value.

    Raises
    ------
    KeyError
        If the path cannot be resolved.
    """
    parts = expression.split(".")
    current = data
    for part in parts:
        if isinstance(current, dict):
            if part not in current:
                raise KeyError(f"Key '{part}' not found in {current}")
            current = current[part]
        elif isinstance(current, list):
            try:
                idx = int(part)
                current = current[idx]
            except (ValueError, IndexError) as e:
                raise KeyError(f"Cannot index list with '{part}'") from e
        else:
            raise KeyError(f"Cannot traverse into {type(current).__name__} with '{part}'")
    return current


def _eval_exit_code(expect: TestExpectations, exit_code: int) -> list[dict[str, Any]]:
    if expect.exit_code is None:
        return []
    return [
        {
            "type": "exit_code",
            "ok": exit_code == expect.exit_code,
            "expected": expect.exit_code,
            "actual": exit_code,
        }
    ]


def _eval_stdout_exact(expect: TestExpectations, stdout: str) -> list[dict[str, Any]]:
    if expect.stdout_exact is None:
        return []
    return [
        {
            "type": "stdout_exact",
            "ok": stdout.strip() == expect.stdout_exact.strip(),
            "expected": expect.stdout_exact,
            "actual": stdout,
        }
    ]


def _eval_stdout_contains(expect: TestExpectations, stdout: str) -> list[dict[str, Any]]:
    if not expect.stdout_contains:
        return []
    return [
        {
            "type": "stdout_contains",
            "ok": item in stdout,
            "expected": item,
            "actual": stdout,
        }
        for item in expect.stdout_contains
    ]


def _eval_stdout_regex(expect: TestExpectations, stdout: str) -> list[dict[str, Any]]:
    if not expect.stdout_regex:
        return []
    results = []
    for pattern in expect.stdout_regex:
        try:
            matched = bool(re.search(pattern, stdout))
            results.append(
                {
                    "type": "stdout_regex",
                    "ok": matched,
                    "pattern": pattern,
                    "actual": stdout,
                }
            )
        except re.error as e:
            results.append(
                {
                    "type": "stdout_regex",
                    "ok": False,
                    "pattern": pattern,
                    "error": f"Invalid regex: {e}",
                }
            )
    return results


def _eval_stderr_contains(expect: TestExpectations, stderr: str) -> list[dict[str, Any]]:
    if not expect.stderr_contains:
        return []
    return [
        {
            "type": "stderr_contains",
            "ok": item in stderr,
            "expected": item,
            "actual": stderr,
        }
        for item in expect.stderr_contains
    ]


def _eval_stderr_regex(expect: TestExpectations, stderr: str) -> list[dict[str, Any]]:
    if not expect.stderr_regex:
        return []
    results = []
    for pattern in expect.stderr_regex:
        try:
            matched = bool(re.search(pattern, stderr))
            results.append(
                {
                    "type": "stderr_regex",
                    "ok": matched,
                    "pattern": pattern,
                    "actual": stderr,
                }
            )
        except re.error as e:
            results.append(
                {
                    "type": "stderr_regex",
                    "ok": False,
                    "pattern": pattern,
                    "error": f"Invalid regex: {e}",
                }
            )
    return results


def _eval_stdout_json_assert(expect: TestExpectations, stdout: str) -> list[dict[str, Any]]:
    if not expect.stdout_json_assert:
        return []
    results = []

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

    try:
        parsed = json.loads(stdout)
    except (json.JSONDecodeError, TypeError):
        parsed = {}

    rows = _extract_rows_from_geode_output(parsed)
    row_count = len(rows) if rows is not None else 0

    if gq.row_count is not None:
        results.append(
            {
                "type": "geode_row_count",
                "ok": row_count == gq.row_count,
                "expected": gq.row_count,
                "actual": row_count,
            }
        )

    if gq.min_rows is not None:
        results.append(
            {
                "type": "geode_min_rows",
                "ok": row_count >= gq.min_rows,
                "minimum": gq.min_rows,
                "actual": row_count,
            }
        )

    if gq.max_rows is not None:
        results.append(
            {
                "type": "geode_max_rows",
                "ok": row_count <= gq.max_rows,
                "maximum": gq.max_rows,
                "actual": row_count,
            }
        )

    if gq.columns is not None:
        actual_columns = list(parsed.get("columns", []))
        if not actual_columns and rows:
            actual_columns = list(rows[0].keys())
        results.append(
            {
                "type": "geode_columns",
                "ok": set(gq.columns) <= set(actual_columns),
                "expected": gq.columns,
                "actual": actual_columns,
            }
        )

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
        results.append(
            {
                "type": "geode_contains_node",
                "ok": found,
                "expected_node": gq.contains_node,
            }
        )

    if gq.execution_time_ms is not None:
        metadata = parsed.get("metadata", {})
        actual_time = metadata.get("execution_time_ms", 0)
        results.append(
            {
                "type": "geode_execution_time",
                "ok": actual_time <= gq.execution_time_ms,
                "max_time_ms": gq.execution_time_ms,
                "actual_time_ms": actual_time,
            }
        )

    return results


def _eval_server_responsive(expect: TestExpectations, exit_code: int) -> list[dict[str, Any]]:
    if expect.server_responsive is None:
        return []
    return [
        {
            "type": "server_responsive",
            "ok": (exit_code == 0) == expect.server_responsive,
            "expected_responsive": expect.server_responsive,
            "exit_code": exit_code,
        }
    ]


def evaluate_assertions(
    expect: TestExpectations,
    exit_code: int,
    stdout: str,
    stderr: str,
) -> list[dict[str, Any]]:
    """Evaluate all assertions and return detailed results.

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
    """
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
