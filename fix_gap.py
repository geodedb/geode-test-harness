import sys

with open('docs/GAP_ANALYSIS.md', 'r') as f:
    text = f.read()

text = text.replace("- **Status:** Open\n- **Category:** Reliability\n- **Severity:** High\n- **Description:** `runners/shell_runner.py` extracts JSON", "- **Status:** Closed\n- **Category:** Reliability\n- **Severity:** High\n- **Description:** `runners/shell_runner.py` extracts JSON")
text = text.replace("- **Recommendation:** Use strictly `--format json` where possible, or build a robust parser that handles the shell's exact output schema instead of relying on regex fallbacks.", "- **Resolution:** Modified `start_shell` to use `--format json`. Modified `execute_query` to look for outer `{` and `}` directly and use robust `json.loads`.")

text = text.replace("- **Status:** Open\n- **Category:** Reliability\n- **Severity:** Medium\n- **Description:** The shell runner checks `if \"Error\" in output or \"error\" in output.lower():`", "- **Status:** Closed\n- **Category:** Reliability\n- **Severity:** Medium\n- **Description:** The shell runner checks `if \"Error\" in output or \"error\" in output.lower():`")
text = text.replace("- **Recommendation:** Rely on explicit command exit codes, standardized status block outputs (like `status_class`), or specific shell error prefixes rather than generic substring matching.", "- **Resolution:** Now checks the JSON `status_class` attribute for values not starting with \"00\", or explicit Error log prefixes for shell errors.")

text = text.replace("- **Status:** Open\n- **Category:** Reliability\n- **Severity:** Medium\n- **Description:** `send_command` tries to strip the echoed command", "- **Status:** Closed\n- **Category:** Reliability\n- **Severity:** Medium\n- **Description:** `send_command` tries to strip the echoed command")
text = text.replace("- **Recommendation:** Use specific markers/boundaries, or rely solely on non-interactive programmatic interfaces when testing query results, reserving `pexpect` only for testing specific interactive UX aspects (like autocompletion or prompt coloring).", "- **Resolution:** Simplified echo handling by finding the JSON block directly via braces which naturally skips the command echo text.")

text = text.replace("- **Status:** Open\n- **Category:** Maintainability\n- **Severity:** Low\n- **Description:** In `executor.py`, `test_type: shell` means running an OS bash script", "- **Status:** Closed\n- **Category:** Maintainability\n- **Severity:** Low\n- **Description:** In `executor.py`, `test_type: shell` means running an OS bash script")
text = text.replace("- **Recommendation:** Rename `test_type: shell` in `executor.py` to `bash` or `os_shell`, or clearly distinguish `geode_shell` from `os_shell` in the test specs.", "- **Resolution:** Renamed `test_type: shell` in `executor.py` to `test_type: bash` across the codebase, test specs, and security unit tests.")

text = text.replace("- **Status:** Open\n- **Category:** Extensibility\n- **Severity:** Low\n- **Description:** `_run_persistence_test` in `shell_runner.py` hardcodes the check for `graph_store.dat`.", "- **Status:** Closed\n- **Category:** Extensibility\n- **Severity:** Low\n- **Description:** `_run_persistence_test` in `shell_runner.py` hardcodes the check for `graph_store.dat`.")
text = text.replace("- **Recommendation:** Allow the test spec to define the expected files or use a command that explicitly verifies the total database size/health.", "- **Resolution:** `_run_persistence_test` now checks `step.get(\"files\", [\"graph_store.dat\"])` to allow tests to optionally specify multiple persistence files.")

text = text.replace("## Open Gaps (5)", "## Open Gaps (0)")

old_table = '''| High | 1 | 0 | 14 | 2 | 17 |
| Medium | 2 | 3 | 22 | 10 | 37 |
| Low | 2 | 0 | 20 | 5 | 27 |
| **Total** | **5** | **3** | **58** | **18** | **84** |'''

new_table = '''| High | 0 | 0 | 15 | 2 | 17 |
| Medium | 0 | 3 | 24 | 10 | 37 |
| Low | 0 | 0 | 22 | 5 | 27 |
| **Total** | **0** | **3** | **63** | **18** | **84** |'''

text = text.replace(old_table, new_table)

with open('docs/GAP_ANALYSIS.md', 'w') as f:
    f.write(text)
print('Done!')
