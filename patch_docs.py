import re

with open("docs/QUALITY_GAP_ANALYSIS.md", "r") as f:
    content = f.read()

# Update summary table
content = content.replace("| Medium   | 7 | 4 | 11 |", "| Medium   | 8 | 3 | 11 |")
content = content.replace("| **Total** | **20** | **12** | **32** |", "| **Total** | **21** | **11** | **32** |")

# Update QG-012 row
old_row = "| 12 | Medium | 32 | api-contract | QG-012: JSON report schema differs between single-spec and multi-spec modes | `runner.py` / `cli.py` | Single-spec returns a flat `RunSummary` dict. Multi-spec wraps results in an outer envelope. Consumers must handle both shapes. | -- | Unify report schema: always use envelope format, single-spec wraps one entry | git blame cli.py | M (1-2 days) | Deferred |"
new_row = "| 12 | Medium | 32 | api-contract | QG-012: JSON report schema differs between single-spec and multi-spec modes | `runner.py` / `cli.py` | Fixed: Unified report schema to always use envelope format with 'summary' and 'specs' keys. Single-spec mode wraps the one entry. | -- | Commit | -- | -- | **Closed** |"
content = content.replace(old_row, new_row)

with open("docs/QUALITY_GAP_ANALYSIS.md", "w") as f:
    f.write(content)
print("Patched docs/QUALITY_GAP_ANALYSIS.md")
