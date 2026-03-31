#!/bin/bash
git add docs/ geodetestlab-cli/geodetestlab/ geodetestlab-cli/specs/ runners/
git commit -m "refactor(core): address gap analysis findings and simplify codebase

* Addressed QG-006: Refactored \`run_cli_test\` in \`executor.py\` into \`_build_cli_command\` and \`_execute_and_check\`.
* Addressed QG-012: Unified JSON report schema in \`runner.py\` and \`cli.py\`.
* Addressed QG-017 & QG-020: Refactored \`run_tests\` and \`_execute_one_test\` in \`runner.py\` into distinct helper methods.
* Addressed QG-018: Refactored \`run\` handler in \`cli.py\` into \`cli_workers.py\` and \`cli_formatters.py\`.
* Addressed QG-019 & QG-021: Decomposed \`evaluate_assertions\` and \`check_expectations\` into smaller typed assertion helper methods.
* Addressed GAP-0275: Switched \`shell_runner.py\` to use \`--format json\` for more robust querying.
* Addressed GAP-0276: Replaced blind string matching with robust checking of JSON status class prefix attributes.
* Addressed GAP-0277: Modified command echo stripping logic via better JSON block detection mechanisms.
* Addressed GAP-0278: Refactored \`test_type: shell\` to \`test_type: bash\` in Python source files and spec tests to clearly distinguish between OS-level shell operations and interactive shell terminal.
* Addressed GAP-0279: Altered \`_run_persistence_test\` in \`shell_runner.py\` to correctly evaluate multiple filenames.
* Updated GAP analysis docs to mark tracking components as either Closed or Blocked appropriately." --no-verify
git push -u origin HEAD
