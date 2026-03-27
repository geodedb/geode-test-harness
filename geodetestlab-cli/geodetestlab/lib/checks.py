"""Expectation checking for geodetestlab test results.

Provides functions to verify CLI output and HTTP responses against
expected values defined in test specifications.
"""

from __future__ import annotations

import re

import httpx

from .spec import HttpExpected, TestCase


def check_expectations(
    test_case: TestCase,
    output: str,
    error: str,
    exit_code: int,
) -> bool:
    """Check if test output matches expectations."""
    expected = test_case.expected

    # Check exit code (supports single int or list of ints)
    if expected.exit_code is not None:
        if isinstance(expected.exit_code, list):
            if exit_code not in expected.exit_code:
                return False
        elif exit_code != expected.exit_code:
            return False

    # Check status (success vs error) - only if exit_code not explicitly specified
    # This allows tests to specify exit_code without also needing to set status
    if expected.exit_code is None:
        if expected.status == "success" and exit_code != 0:
            return False
        if expected.status == "error" and exit_code == 0:
            return False

    # Check result contains (legacy format - single string or list)
    if expected.result_contains:
        if isinstance(expected.result_contains, dict):
            # Dict: check each key-value pair appears in output
            for k, v in expected.result_contains.items():
                if str(k) not in output or str(v) not in output:
                    return False
        elif isinstance(expected.result_contains, list):
            for item in expected.result_contains:
                if isinstance(item, dict):
                    for k, v in item.items():
                        if str(k) not in output or str(v) not in output:
                            return False
                else:
                    if str(item) not in output:
                        return False
        else:
            if str(expected.result_contains) not in output:
                return False

    # Check result not contains (legacy format - single string or list)
    if expected.result_not_contains:
        if isinstance(expected.result_not_contains, dict):
            all_found = True
            for k, v in expected.result_not_contains.items():
                if str(k) not in output or str(v) not in output:
                    all_found = False
                    break
            if all_found:
                return False
        elif isinstance(expected.result_not_contains, list):
            for item in expected.result_not_contains:
                if isinstance(item, dict):
                    all_found = True
                    for k, v in item.items():
                        if str(k) not in output or str(v) not in output:
                            all_found = False
                            break
                    if all_found:
                        return False
                else:
                    if str(item) in output:
                        return False
        else:
            if str(expected.result_not_contains) in output:
                return False

    # Check result matches (legacy format - single regex or list)
    if expected.result_matches:
        if isinstance(expected.result_matches, list):
            for pattern in expected.result_matches:
                if not re.search(pattern, output):
                    return False
        elif not re.search(expected.result_matches, output):
            return False

    # Check error contains (legacy format - single string or list)
    if expected.error_contains:
        if isinstance(expected.error_contains, list):
            for item in expected.error_contains:
                if str(item) not in error:
                    return False
        else:
            if str(expected.error_contains) not in error:
                return False

    # Check stdout_contains (list of substrings that must ALL be present)
    # Note: checks combined stdout+stderr for backward compatibility (961 usages).
    # Use output_contains for explicit combined semantics.
    if expected.stdout_contains:
        combined = output + error
        for item in expected.stdout_contains:
            if isinstance(item, dict):
                # Dict items represent expected key-value pairs in result rows.
                # Check that each key and its stringified value appear in the output.
                for k, v in item.items():
                    k_str = str(k)
                    v_str = str(v)
                    if k_str not in combined or v_str not in combined:
                        return False
            else:
                substring = str(item) if not isinstance(item, str) else item
                if substring not in output and substring not in error:
                    return False

    # Check output_contains (list of substrings in combined stdout+stderr — QG-010)
    if expected.output_contains:
        combined = output + error
        for item in expected.output_contains:
            if isinstance(item, dict):
                for k, v in item.items():
                    k_str = str(k)
                    v_str = str(v)
                    if k_str not in combined or v_str not in combined:
                        return False
            else:
                substring = str(item) if not isinstance(item, str) else item
                if substring not in combined:
                    return False

    # Check stderr_contains (list of substrings that must ALL be present)
    if expected.stderr_contains:
        for item in expected.stderr_contains:
            substring = str(item) if not isinstance(item, str) else item
            if substring not in error:
                return False

    # Check stdout_not_contains (list of substrings that must NOT be present)
    if expected.stdout_not_contains:
        for item in expected.stdout_not_contains:
            if isinstance(item, dict):
                # For not_contains with dicts, fail if ALL key-value pairs are found
                all_found = True
                for k, v in item.items():
                    if str(k) not in output or str(v) not in output:
                        all_found = False
                        break
                if all_found:
                    return False
            else:
                substring = str(item) if not isinstance(item, str) else item
                if substring in output:
                    return False

    # Check stderr_not_contains (list of substrings that must NOT be present)
    if expected.stderr_not_contains:
        for item in expected.stderr_not_contains:
            substring = str(item) if not isinstance(item, str) else item
            if substring in error:
                return False

    # Check stdout_regex (list of regex patterns that must ALL match)
    # Note: Geode CLI often outputs to stderr, so we also check stderr as fallback
    if expected.stdout_regex:
        for pattern in expected.stdout_regex:
            # Check stdout first, then stderr as fallback
            if not re.search(pattern, output) and not re.search(pattern, error):
                return False

    # Check stderr_regex (list of regex patterns that must ALL match)
    if expected.stderr_regex:
        for pattern in expected.stderr_regex:
            if not re.search(pattern, error):
                return False

    # Check stdout_exact (exact match after stripping whitespace)
    # Note: Also checks stderr as fallback since Geode CLI often outputs to stderr
    if expected.stdout_exact is not None:
        expected_stripped = expected.stdout_exact.strip()
        output_stripped = output.strip()
        error_stripped = error.strip()
        if output_stripped != expected_stripped and error_stripped != expected_stripped:
            return False

    # Check stderr_exact (exact match after stripping whitespace)
    if expected.stderr_exact is not None:
        if error.strip() != expected.stderr_exact.strip():
            return False

    return True


def check_http_expectations(
    response: httpx.Response,
    expected: HttpExpected,
    verbose: bool,
) -> bool:
    """Check if HTTP response matches expectations."""
    # Check status code
    if expected.status_code is not None and response.status_code != expected.status_code:
        if verbose:
            print(f"    Expected status {expected.status_code}, got {response.status_code}")
        return False

    # Check content type
    if expected.content_type is not None:
        content_type = response.headers.get("content-type", "")
        if expected.content_type not in content_type:
            if verbose:
                print(f"    Expected content-type containing '{expected.content_type}', got '{content_type}'")
            return False

    # Check body contains
    body = response.text
    if expected.body_contains:
        for substring in expected.body_contains:
            if substring not in body:
                if verbose:
                    print(f"    Body missing expected substring: '{substring}'")
                return False

    # Check body not contains
    if expected.body_not_contains:
        for substring in expected.body_not_contains:
            if substring in body:
                if verbose:
                    print(f"    Body contains unexpected substring: '{substring}'")
                return False

    # Check body regex
    if expected.body_regex:
        for pattern in expected.body_regex:
            if not re.search(pattern, body):
                if verbose:
                    print(f"    Body doesn't match regex: '{pattern}'")
                return False

    # Check headers
    if expected.headers:
        for header_name, header_value in expected.headers.items():
            actual = response.headers.get(header_name)
            if actual is None or header_value not in actual:
                if verbose:
                    print(f"    Header '{header_name}' expected '{header_value}', got '{actual}'")
                return False

    return True
