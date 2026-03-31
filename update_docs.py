import os

filepath = "docs/QUALITY_GAP_ANALYSIS.md"

with open(filepath, "r") as f:
    content = f.read()

# Update Summary table
content = content.replace("| Low      | 8 | 8 | 16 |", "| Low      | 10 | 6 | 16 |")
content = content.replace("| **Total** | **20** | **12** | **32** |", "| **Total** | **22** | **10** | **32** |")

# Update QG-019 row
old_qg019 = "| 19 | Low | 20 | complexity | QG-019: `evaluate_assertions()` is 243 lines, depth 6 | `assertions.py:114-356` | Long function with many assertion type branches. Each branch is independent and could be a separate method. | -- | Extract per-assertion-type methods; use dispatch dict | git blame assertions.py | M (1-2 days) | Deferred |"
new_qg019 = "| 19 | Low | 20 | complexity | QG-019: `evaluate_assertions()` is 243 lines, depth 6 | `assertions.py:114-356` | Long function with many assertion type branches. Each branch is independent and could be a separate method. | -- | Fixed: extracted per-assertion-type methods | -- | -- | **Closed** |"
content = content.replace(old_qg019, new_qg019)

# Update QG-021 row
old_qg021 = "| 21 | Low | 20 | complexity | QG-021: `check_expectations()` is 170 lines, depth 7 | `checks.py:16-186` | Linear chain of if-blocks for each expectation field. Readable but long. Lower priority than the dual-system issue (QG-004). | -- | Extract per-field checkers; or deprecate in favor of assertions.py | git blame checks.py | -- | Deferred |"
new_qg021 = "| 21 | Low | 20 | complexity | QG-021: `check_expectations()` is 170 lines, depth 7 | `checks.py:16-186` | Linear chain of if-blocks for each expectation field. Readable but long. Lower priority than the dual-system issue (QG-004). | -- | Fixed: extracted per-field checkers | -- | -- | **Closed** |"
content = content.replace(old_qg021, new_qg021)

with open(filepath, "w") as f:
    f.write(content)

print("Successfully updated QUALITY_GAP_ANALYSIS.md")
