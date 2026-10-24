#!/usr/bin/env python3
"""Merge the per-shard test-all reports into reports/results.json.

test-all runs as `parallel:` shards, each writing
reports/shards/<CI_NODE_INDEX>/results.json. Downstream jobs (triage,
coverage, HTML report) read a single reports/results.json; this sums the
shard summaries and concatenates their spec lists. It is a no-op when no
shard reports exist, so the downstream "no results" paths still apply.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


def merge(reports_dir: Path) -> int:
    shard_files = sorted(reports_dir.glob("shards/*/results.json"))
    if not shard_files:
        print("merge_shard_results: no shard reports found")
        return 0
    summary: dict[str, int] = {}
    specs: list[object] = []
    for path in shard_files:
        data = json.loads(path.read_text())
        for key, value in data.get("summary", {}).items():
            if isinstance(value, int):
                summary[key] = summary.get(key, 0) + value
        specs.extend(data.get("specs", []))
    out = reports_dir / "results.json"
    out.write_text(json.dumps({"summary": summary, "specs": specs}, indent=2))
    print(
        f"merge_shard_results: merged {len(shard_files)} shard report(s) into {out}: {summary}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(merge(Path(sys.argv[1] if len(sys.argv) > 1 else "reports")))
