import re

with open('docs/QUALITY_GAP_ANALYSIS.md', 'r') as f:
    text = f.read()

# Replace the row in the table
old_row = "| 6 | Medium | 36 | readability | QG-006: `run_cli_test()` is 258 lines, nesting depth 8 | `executor.py:71-328` | Single function handles: setup files, auth, transport resolution, GQL detection, command building, DSN, sequential tests, process execution, timeout handling, output checking. | -- | Extract helpers: `_build_cli_command()`, `_resolve_transport_address()`, `_execute_and_check()` | git blame executor.py | M (2-3 days) | Deferred |"
new_row = "| 6 | Medium | 36 | readability | QG-006: `run_cli_test()` is 258 lines, nesting depth 8 | `executor.py:71-328` | Fixed: Extracted `_build_cli_command()` and `_execute_and_check()` | -- | Extract helpers: `_build_cli_command()`, `_resolve_transport_address()`, `_execute_and_check()` | git blame executor.py | M (2-3 days) | **Closed** |"

if old_row in text:
    text = text.replace(old_row, new_row)
else:
    print("Could not find exact old_row. Let's try regex.")
    text = re.sub(r"\| 6 \| Medium \| 36 \| readability \| QG-006: `run_cli_test\(\)` is 258 lines, nesting depth 8 \| `executor\.py:71-328` \|.*?\| Deferred \|", new_row, text)

with open('docs/QUALITY_GAP_ANALYSIS.md', 'w') as f:
    f.write(text)

print("Updated QUALITY_GAP_ANALYSIS.md")
