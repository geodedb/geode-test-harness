import os

filepath = "geodetestlab-cli/geodetestlab/lib/checks.py"

with open(filepath, "r") as f:
    content = f.read()

new_func = """def _check_exit_code(expected, exit_code: int) -> bool:
    if expected.exit_code is not None:
        if isinstance(expected.exit_code, list):
            if exit_code not in expected.exit_code:
                return False
        elif exit_code != expected.exit_code:
            return False
    return True

def _check_status(expected, exit_code: int) -> bool:
    if expected.exit_code is None:
        if expected.status == "success" and exit_code != 0:
            return False
        if expected.status == "error" and exit_code == 0:
            return False
    return True

def _check_result_contains(expected, output: str) -> bool:
    if expected.result_contains:
        if isinstance(expected.result_contains, dict):
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
    return True

def _check_result_not_contains(expected, output: str) -> bool:
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
    return True

def _check_result_matches(expected, output: str) -> bool:
    if expected.result_matches:
        if isinstance(expected.result_matches, list):
            for pattern in expected.result_matches:
                if not re.search(pattern, output):
                    return False
        elif not re.search(expected.result_matches, output):
            return False
    return True

def _check_error_contains(expected, error: str) -> bool:
    if expected.error_contains:
        if isinstance(expected.error_contains, list):
            for item in expected.error_contains:
                if str(item) not in error:
                    return False
        else:
            if str(expected.error_contains) not in error:
                return False
    return True

def _check_stdout_contains(expected, output: str, error: str) -> bool:
    if expected.stdout_contains:
        combined = output + error
        for item in expected.stdout_contains:
            if isinstance(item, dict):
                for k, v in item.items():
                    k_str = str(k)
                    v_str = str(v)
                    if k_str not in combined or v_str not in combined:
                        return False
            else:
                substring = str(item) if not isinstance(item, str) else item
                if substring not in output and substring not in error:
                    return False
    return True

def _check_output_contains(expected, output: str, error: str) -> bool:
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
    return True

def _check_stderr_contains(expected, error: str) -> bool:
    if expected.stderr_contains:
        for item in expected.stderr_contains:
            substring = str(item) if not isinstance(item, str) else item
            if substring not in error:
                return False
    return True

def _check_stdout_not_contains(expected, output: str) -> bool:
    if expected.stdout_not_contains:
        for item in expected.stdout_not_contains:
            if isinstance(item, dict):
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
    return True

def _check_stderr_not_contains(expected, error: str) -> bool:
    if expected.stderr_not_contains:
        for item in expected.stderr_not_contains:
            substring = str(item) if not isinstance(item, str) else item
            if substring in error:
                return False
    return True

def _check_stdout_regex(expected, output: str, error: str) -> bool:
    if expected.stdout_regex:
        for pattern in expected.stdout_regex:
            if not re.search(pattern, output) and not re.search(pattern, error):
                return False
    return True

def _check_stderr_regex(expected, error: str) -> bool:
    if expected.stderr_regex:
        for pattern in expected.stderr_regex:
            if not re.search(pattern, error):
                return False
    return True

def _check_stdout_exact(expected, output: str, error: str) -> bool:
    if expected.stdout_exact is not None:
        expected_stripped = expected.stdout_exact.strip()
        output_stripped = output.strip()
        error_stripped = error.strip()
        if output_stripped != expected_stripped and error_stripped != expected_stripped:
            return False
    return True

def _check_stderr_exact(expected, error: str) -> bool:
    if expected.stderr_exact is not None:
        if error.strip() != expected.stderr_exact.strip():
            return False
    return True

def check_expectations(
    test_case: TestCase,
    output: str,
    error: str,
    exit_code: int,
) -> bool:
    \"\"\"Check if test output matches expectations.\"\"\"
    expected = test_case.expected

    if not _check_exit_code(expected, exit_code): return False
    if not _check_status(expected, exit_code): return False
    if not _check_result_contains(expected, output): return False
    if not _check_result_not_contains(expected, output): return False
    if not _check_result_matches(expected, output): return False
    if not _check_error_contains(expected, error): return False
    if not _check_stdout_contains(expected, output, error): return False
    if not _check_output_contains(expected, output, error): return False
    if not _check_stderr_contains(expected, error): return False
    if not _check_stdout_not_contains(expected, output): return False
    if not _check_stderr_not_contains(expected, error): return False
    if not _check_stdout_regex(expected, output, error): return False
    if not _check_stderr_regex(expected, error): return False
    if not _check_stdout_exact(expected, output, error): return False
    if not _check_stderr_exact(expected, error): return False

    return True
"""

start_idx = content.find("def check_expectations(")
end_idx = content.find("def check_http_expectations(")

if start_idx != -1 and end_idx != -1:
    content = content[:start_idx] + new_func + "\n\n" + content[end_idx:]
    with open(filepath, "w") as f:
        f.write(content)
    print("Successfully replaced check_expectations")
else:
    print("Could not find check_expectations or check_http_expectations")
