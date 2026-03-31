import re

with open("geodetestlab-cli/geodetestlab/cli.py", "r") as f:
    content = f.read()

old_2 = """                aggregate_summary["skipped"] += summary.get("skipped", 0)
                all_results.append({"spec": result["spec"], "summary": summary})"""

new_2 = """                aggregate_summary["skipped"] += summary.get("skipped", 0)
                spec_entry = {"spec": result["spec"], "summary": summary}
                if "results" in result:
                    spec_entry["results"] = result["results"]
                all_results.append(spec_entry)"""

if old_2 in content:
    content = content.replace(old_2, new_2)
    print("Patched parallel execution success block")
else:
    print("Failed to patch parallel execution success block")

with open("geodetestlab-cli/geodetestlab/cli.py", "w") as f:
    f.write(content)
