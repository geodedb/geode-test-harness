from __future__ import annotations

from pathlib import Path
from typing import Any

from .runner import RunnerError, run_tests
from .spec import SpecValidationError, load_spec
from .utils import SecretResolutionError, resolve_secrets


def _run_single_spec(
    spec_file: Path,
    llm_provider: str,
    model: str | None,
    max_cases: int | None,
    timeout_ms: int,
    server_timeout_ms: int,
    dry_run: bool,
    ci_mode: bool,
    seed: int | None,
    geode_binary: str | None,
    server_port: int | None,
    verbose: bool,
    transport: str = "quic",
) -> dict[str, Any]:
    """Run tests for a single spec file.

    This function is designed to be called from a ProcessPoolExecutor.
    It returns a dict with the results instead of raising exceptions.
    """
    result: dict[str, Any] = {
        "spec": str(spec_file),
        "exit_code": 0,
        "summary": {"total": 0, "passed": 0, "failed": 0, "skipped": 0},
        "error": None,
        "skip_reason": None,
    }

    try:
        spec_obj = load_spec(spec_file)
    except SpecValidationError as exc:
        result["exit_code"] = 2
        result["error"] = f"SCHEMA_ERROR in {spec_file}: {exc}"
        return result
    except Exception as exc:
        result["exit_code"] = 2
        result["error"] = f"SCHEMA_ERROR in {spec_file}: {exc}"
        return result

    if getattr(spec_obj, "skip", None):
        result["skip_reason"] = str(spec_obj.skip)

    try:
        secrets, env_vars = resolve_secrets(spec_obj)
    except SecretResolutionError as exc:
        result["exit_code"] = 4
        result["error"] = str(exc)
        return result

    try:
        exit_code, summary = run_tests(
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
        result["summary"] = summary
    except RunnerError as exc:
        result["exit_code"] = 3
        result["error"] = str(exc)

    return result
