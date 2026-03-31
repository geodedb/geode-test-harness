import re

with open("geodetestlab-cli/geodetestlab/cli.py", "r") as f:
    content = f.read()

old_3 = """                        aggregate_summary["skipped"] += use_summary.get("skipped", 0)
                        all_results.append({"spec": use_result["spec"], "summary": use_summary})"""

new_3 = """                        aggregate_summary["skipped"] += use_summary.get("skipped", 0)
                        spec_entry = {"spec": use_result["spec"], "summary": use_summary}
                        if "results" in use_result:
                            spec_entry["results"] = use_result["results"]
                        all_results.append(spec_entry)"""

if old_3 in content:
    content = content.replace(old_3, new_3)
    print("Patched parallel execution retry block")
else:
    print("Failed to patch parallel execution retry block")

with open("geodetestlab-cli/geodetestlab/cli.py", "w") as f:
    f.write(content)
