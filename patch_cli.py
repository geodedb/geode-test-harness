import re

with open("geodetestlab-cli/geodetestlab/cli.py", "r") as f:
    content = f.read()

# 1. Patch _run_single_spec
old_1 = """        exit_code, summary = run_tests(
            spec=spec_obj,
            secrets=secrets,
            env_overrides=env_vars,
            llm_provider=llm_provider,
            model=model,
            max_cases=max_cases,
            timeout_ms=timeout_ms,
            server_timeout_ms=server_timeout_ms,
            report_json=None,
            dry_run=dry_run,
            ci_mode=ci_mode,
            seed=seed,
            spec_path=str(spec_file),
            geode_binary=geode_binary,
            server_port=server_port,
            verbose=verbose,
            transport=transport,
        )
        result["exit_code"] = exit_code
        result["summary"] = summary"""

new_1 = """        exit_code, summary = run_tests(
            spec=spec_obj,
            secrets=secrets,
            env_overrides=env_vars,
            llm_provider=llm_provider,
            model=model,
            max_cases=max_cases,
            timeout_ms=timeout_ms,
            server_timeout_ms=server_timeout_ms,
            report_json=None,
            dry_run=dry_run,
            ci_mode=ci_mode,
            seed=seed,
            spec_path=str(spec_file),
            geode_binary=geode_binary,
            server_port=server_port,
            verbose=verbose,
            transport=transport,
        )
        result["exit_code"] = exit_code
        if "results" in summary:
            result["results"] = summary.pop("results")
        result["summary"] = summary"""

if old_1 in content:
    content = content.replace(old_1, new_1)
    print("Patched _run_single_spec")
else:
    print("Failed to patch _run_single_spec")

# 2. Patch parallel execution success block
old_2 = """                        aggregate_summary["skipped"] += summary.get("skipped", 0)
                        all_results.append({"spec": result["spec"], "summary": summary})"""

new_2 = """                        aggregate_summary["skipped"] += summary.get("skipped", 0)
                        spec_entry = {"spec": result["spec"], "summary": summary}
                        if "results" in result:
                            spec_entry["results"] = result["results"]
                        all_results.append(spec_entry)"""

if old_2 in content:
    content = content.replace(old_2, new_2)
    print("Patched parallel execution success block")
else:
    print("Failed to patch parallel execution success block")

# 3. Patch parallel execution retry block
old_3 = """                aggregate_summary["skipped"] += use_summary.get("skipped", 0)
                all_results.append({"spec": use_result["spec"], "summary": use_summary})"""

new_3 = """                aggregate_summary["skipped"] += use_summary.get("skipped", 0)
                spec_entry = {"spec": use_result["spec"], "summary": use_summary}
                if "results" in use_result:
                    spec_entry["results"] = use_result["results"]
                all_results.append(spec_entry)"""

if old_3 in content:
    content = content.replace(old_3, new_3)
    print("Patched parallel execution retry block")
else:
    print("Failed to patch parallel execution retry block")

# 4. Patch sequential execution block
old_4 = """                    aggregate_summary["skipped"] += summary.get("skipped", 0)
                    all_results.append({"spec": str(spec_file), "summary": summary})"""

new_4 = """                    aggregate_summary["skipped"] += summary.get("skipped", 0)
                    spec_entry = {"spec": str(spec_file), "summary": summary}
                    if "results" in summary:
                        spec_entry["results"] = summary.pop("results")
                    all_results.append(spec_entry)"""

if old_4 in content:
    content = content.replace(old_4, new_4)
    print("Patched sequential execution block")
else:
    print("Failed to patch sequential execution block")

with open("geodetestlab-cli/geodetestlab/cli.py", "w") as f:
    f.write(content)
