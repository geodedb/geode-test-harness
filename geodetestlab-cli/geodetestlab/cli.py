"""Command line interface for the geodetestlab tool.

This module defines the Typer application and the various commands exposed to
users for testing Geode database functionality. It orchestrates loading the
specification, resolving secrets, managing server lifecycle, invoking tests,
and handling error conditions and exit codes according to the requirements.
"""

from __future__ import annotations

import atexit
import json
import os
import signal
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Any

import typer
from rich.console import Console
from rich.table import Table

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib.cli_formatters import _show_rich_summary  # noqa: E402
from lib.cli_workers import _run_single_spec  # noqa: E402
from lib.failure_log import (  # noqa: E402
    append_failure,
    finalize_failure_log,
    init_failure_log,
)
from lib.runner import RunnerError, _kill_stale_servers, run_tests  # noqa: E402
from lib.spec import SpecValidationError, load_spec  # noqa: E402
from lib.utils import SecretResolutionError, resolve_secrets  # noqa: E402
from server.simple_manager import ServerManager  # noqa: E402

# ---------------------------------------------------------------------------
# Exit codes returned by the ``run`` command.
# ---------------------------------------------------------------------------
EXIT_SUCCESS = 0  # All tests passed
EXIT_TEST_FAILURE = 1  # One or more tests failed
EXIT_SPEC_ERROR = 2  # Spec loading / validation error
EXIT_RUNNER_ERROR = 3  # Runner or server lifecycle error
EXIT_SECRET_ERROR = 4  # Secret resolution failed
EXIT_INTERRUPTED = 130  # Ctrl-C (SIGINT)

app = typer.Typer(
    name="geodetestlab",
    help=(
        "Interactive CLI testing system for Geode graph database with LLM fuzzing.\n\n"
        "Exit codes:\n\n"
        "  0  All tests passed\n\n"
        "  1  One or more tests failed\n\n"
        "  2  Spec loading / validation error\n\n"
        "  3  Runner or server lifecycle error\n\n"
        "  4  Secret resolution failed\n\n"
        "  130  Interrupted (SIGINT)\n"
    ),
    rich_markup_mode="rich",
)

console = Console(force_terminal=True)
console_err = Console(stderr=True, force_terminal=True)


_tracked_pids: set[int] = set()


def _flush_report(
    report_json: Path | None,
    aggregate_summary: dict[str, int],
    all_results: list[dict[str, Any]],
) -> None:
    """Write the in-progress report to ``report_json`` after each spec.

    Lets observers `tail`/`jq` the report mid-run instead of waiting until
    every spec finishes. Writes are atomic-via-rename (no torn reads).
    """
    if report_json is None:
        return
    report_data = {
        "summary": aggregate_summary,
        "specs": all_results,
    }
    try:
        report_json.parent.mkdir(parents=True, exist_ok=True)
        tmp = report_json.with_suffix(report_json.suffix + ".tmp")
        tmp.write_text(json.dumps(report_data, indent=2))
        tmp.replace(report_json)
    except Exception:
        # Best-effort: an incremental flush failure should not crash the run.
        pass


def parse_shard(value: str) -> tuple[int, int]:
    """Parse a 'K/N' shard selector into (K, N), 1 <= K <= N."""
    parts = value.split("/")
    if len(parts) != 2:
        raise ValueError(f"--shard must be K/N (e.g. 2/3), got {value!r}")
    try:
        index, total = int(parts[0]), int(parts[1])
    except ValueError as exc:
        raise ValueError(f"--shard must be K/N with integers, got {value!r}") from exc
    if total < 1 or index < 1 or index > total:
        raise ValueError(f"--shard needs 1 <= K <= N, got {value!r}")
    return index, total


def select_shard(spec_files: list[Path], index: int, total: int) -> list[Path]:
    """Return shard ``index`` of ``total`` (1-based), dealt round-robin."""
    return [f for i, f in enumerate(spec_files) if i % total == index - 1]


def track_pid(pid: int) -> None:
    """Register a PID for cleanup on exit."""
    _tracked_pids.add(pid)


def untrack_pid(pid: int) -> None:
    """Remove a PID from the cleanup set."""
    _tracked_pids.discard(pid)


def _kill_geode_processes() -> None:
    """Kill orphaned geode server processes started by this test run.

    Uses tracked PIDs when available, falling back to pattern-based
    pkill only for processes matching our temp-dir naming convention.
    """

    # First, kill any PIDs we explicitly tracked
    for pid in list(_tracked_pids):
        try:
            os.kill(pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError, OSError):
            pass
        _tracked_pids.discard(pid)

    # Fallback: servers in our test temp dirs whose owning run is gone. Never
    # a machine-wide pkill: that killed the servers of other live runs.
    from lib.server import kill_orphaned_test_servers

    kill_orphaned_test_servers(signal.SIGKILL)


def _kill_child_processes() -> None:
    """Kill all child processes of the current process."""
    import subprocess

    try:
        # Use pkill to kill all children of our process group
        subprocess.run(
            ["pkill", "-9", "-P", str(os.getpid())],
            capture_output=True,
            timeout=5,
        )
    except Exception:
        pass


# Register cleanup on exit
atexit.register(_kill_geode_processes)


@app.command("run")
def run(
    *,
    spec: Path | None = typer.Option(
        None,
        exists=True,
        readable=True,
        help="Path to a single YAML test specification file",
    ),
    specs: Path | None = typer.Option(
        None,
        exists=True,
        help="Path to a directory containing YAML test specifications",
    ),
    output: Path | None = typer.Option(
        None,
        help="Alias for --report-json: path to write a full machine‑readable report JSON",
    ),
    llm_provider: str = typer.Option(
        "mock",
        help="LLM provider to use for fuzzing (mock, openai, or geode-ai)",
        show_default=True,
    ),
    model: str | None = typer.Option(
        None,
        help="LLM model identifier when using openai or geode-ai provider",
    ),
    max_cases: int | None = typer.Option(
        None,
        min=0,
        help="Maximum number of additional fuzzed cases to generate",
    ),
    timeout_ms: int = typer.Option(
        30000,
        min=1,
        help="Per-case timeout in milliseconds",
        show_default=True,
    ),
    server_timeout_ms: int = typer.Option(
        60000,
        min=1000,
        help="Server startup/shutdown timeout in milliseconds",
        show_default=True,
    ),
    report_json: Path | None = typer.Option(
        None,
        help="Optional path to write a full machine‑readable report JSON",
    ),
    failure_file: str | None = typer.Option(
        None,
        "--failure-file",
        help=(
            "Path to a human/agent-readable file that captures every test "
            "FAILURE with detail, written live as failures occur (tail -f it "
            "during a run; point an agent at it afterward). Defaults to "
            "'<report-dir>/test-failures.md' (or reports/test-failures.md), or "
            "$GEODE_FAILURE_FILE. Pass an empty string to disable."
        ),
    ),
    dry_run: bool = typer.Option(
        False,
        help="Do not execute commands or start servers, just enumerate cases",
    ),
    ci: bool = typer.Option(
        False,
        help="Run in CI mode (non-interactive, simplified output)",
    ),
    seed: int | None = typer.Option(
        None,
        help="Random seed to pass to the LLM provider for deterministic fuzzing",
    ),
    geode_binary: str | None = typer.Option(
        None,
        help="Path to the geode binary (auto-detected if not specified)",
    ),
    server_port: int | None = typer.Option(
        None,
        min=1024,
        max=65535,
        help="Port for managed Geode server (auto-allocated if not specified)",
    ),
    verbose: bool = typer.Option(
        False,
        "--verbose",
        "-v",
        help="Enable verbose output including server logs",
    ),
    parallel: int = typer.Option(
        1,
        "--parallel",
        "-j",
        min=1,
        help="Number of spec files to run in parallel (default: 1, sequential)",
    ),
    transport: str = typer.Option(
        "quic",
        help="Transport protocol: quic, grpc, or both",
    ),
    force_cluster_size: int = typer.Option(
        1,
        "--force-cluster-size",
        min=1,
        max=10,
        help=(
            "Promote specs lacking a `cluster:` block to N-node clusters. "
            "Specs with `single_node_only: true` opt out. Default 1 = no "
            "promotion (single-node behavior). Use 3/5/10 to run the full "
            "suite against multi-node deployments."
        ),
    ),
    shard: str | None = typer.Option(
        None,
        "--shard",
        help=(
            "Run only shard K of N of the spec directory, written 'K/N' "
            "(1-based, e.g. 2/3). Specs are dealt round-robin over the sorted "
            "file list, so the N shards together cover every spec exactly "
            "once. Used by CI's `parallel:` test-all jobs."
        ),
    ),
) -> None:
    """Execute all tests defined in a specification file or directory.

    This command validates the provided YAML specification(s), resolves any
    secrets referenced within them, optionally manages a Geode server instance,
    uses an LLM provider to generate additional fuzzed cases, and then executes
    the target CLI binary according to the defined tests. A single‑line JSON
    summary is always printed to stdout. Exit codes are defined by the outcome
    of parsing, secret resolution, server management, runtime errors, and
    assertion results.

    Use --spec for a single file or --specs for a directory of specs.
    """
    # Handle --output as alias for --report-json
    if output is not None and report_json is None:
        report_json = output

    # Resolve the streaming failure-file path. Precedence: explicit --failure-file
    # (empty string disables), then $GEODE_FAILURE_FILE, then a default next to
    # the JSON report, else reports/test-failures.md.
    if failure_file is None:
        env_ff = os.environ.get("GEODE_FAILURE_FILE")
        if env_ff is not None:
            failure_file = env_ff
        elif report_json is not None:
            failure_file = str(report_json.parent / "test-failures.md")
        else:
            failure_file = "reports/test-failures.md"
    failure_file = failure_file or None  # empty string -> disabled

    # Validate that exactly one of --spec or --specs is provided
    if spec is None and specs is None:
        console_err.print("Error: Either --spec (file) or --specs (directory) must be provided", style="red")
        raise typer.Exit(code=2)
    if spec is not None and specs is not None:
        console_err.print("Error: Cannot specify both --spec and --specs", style="red")
        raise typer.Exit(code=2)

    # Collect spec files to run
    spec_files: list[Path] = []
    if spec is not None:
        spec_files = [spec]
    elif specs is not None:
        if not specs.is_dir():
            console_err.print(f"Error: --specs path is not a directory: {specs}", style="red")
            raise typer.Exit(code=2)
        # Find all YAML files in the directory
        spec_files = sorted(list(specs.glob("*.yaml")) + list(specs.glob("*.yml")))
        if not spec_files:
            console_err.print(f"Error: No YAML files found in directory: {specs}", style="red")
            raise typer.Exit(code=2)

    if shard is not None:
        try:
            shard_index, shard_total = parse_shard(shard)
        except ValueError as exc:
            console_err.print(f"Error: {exc}", style="red")
            raise typer.Exit(code=2) from exc
        spec_files = select_shard(spec_files, shard_index, shard_total)
        if not ci and verbose:
            console.print(f"[dim]Shard {shard_index}/{shard_total}: {len(spec_files)} spec files[/dim]")

    # Determine which transports to run
    transports_to_run = ["quic", "grpc"] if transport == "both" else [transport]

    if not ci and verbose:
        console.print("[yellow]Starting Geode CLI test execution...[/yellow]")
        if len(spec_files) > 1:
            parallel_msg = f" (parallel={parallel})" if parallel > 1 else ""
            console.print(f"[dim]Found {len(spec_files)} spec files to run{parallel_msg}[/dim]")
        if transport == "both":
            console.print("[dim]Running with both QUIC and gRPC transports[/dim]")
        elif transport == "grpc":
            console.print("[dim]Running with gRPC transport[/dim]")

    # Resolve geode binary once, before workers start (PERF-013).
    # This avoids each worker spawning subprocesses to find the binary.
    if geode_binary is None:
        from lib.utils import find_geode_binary

        try:
            geode_binary = find_geode_binary()
        except FileNotFoundError:
            pass  # Let workers report the error individually

    # Kill stale servers ONLY when running a directory of specs (--specs).
    # When running a single spec (--spec), skip: the caller (e.g., a parallel
    # runner) is responsible for one-time cleanup before spawning workers.
    # Calling pkill inside each worker kills other workers' servers (GH-516).
    if specs is not None:
        _kill_stale_servers()

    # Aggregate results across all spec files
    total_exit_code = 0
    aggregate_summary: dict[str, int] = {"total": 0, "passed": 0, "failed": 0, "skipped": 0}
    all_results: list[dict[str, Any]] = []
    # Spec-level errors (schema error / runner crash / worker exception) — no
    # per-test results to scan, so track them separately for the failure file.
    spec_error_entries: list[dict[str, str]] = []

    def _record_spec_error(spec_path: str, message: str) -> None:
        append_failure(
            failure_file,
            spec=spec_path,
            test_name="<spec-level error>",
            error=message,
            kind="spec",
        )
        spec_error_entries.append({"spec": spec_path, "test": "<spec-level error>", "error": message})

    # Truncate + header the streaming failure file once, before any worker runs.
    # Individual failures are then appended live (flock-guarded) from within each
    # spec's run — including across the parallel ProcessPoolExecutor workers.
    _ff_target = str(spec) if spec is not None else (str(specs) if specs is not None else "")
    init_failure_log(
        failure_file,
        target=_ff_target,
        transport=",".join(transports_to_run),
        binary=geode_binary or "",
    )

    # Run specs for each transport
    for current_transport in transports_to_run:
        if not ci and verbose and len(transports_to_run) > 1:
            console.print(f"\n[cyan]Running with {current_transport.upper()} transport...[/cyan]")

        # Run specs in parallel or sequentially based on --parallel flag
        if parallel > 1 and len(spec_files) > 1:
            # Parallel execution using ProcessPoolExecutor
            # Use min of parallel and spec_files count to avoid idle workers
            max_workers = min(parallel, len(spec_files))

            if not ci and verbose:
                console.print(f"[dim]Starting {max_workers} parallel workers...[/dim]")

            executor = None
            interrupted = False

            # Set up signal handler to gracefully handle Ctrl+C
            original_sigint = signal.getsignal(signal.SIGINT)
            original_sigterm = signal.getsignal(signal.SIGTERM)

            def signal_handler(signum: int, frame: Any) -> None:
                nonlocal interrupted, executor
                if interrupted:
                    # Second interrupt - force exit
                    if not ci:
                        console.print("\n[red]Force exiting...[/red]")
                    _kill_geode_processes()
                    _kill_child_processes()
                    os._exit(130)

                interrupted = True
                if not ci:
                    console.print("\n[yellow]Interrupt received, shutting down workers...[/yellow]")

                # Shutdown executor immediately
                if executor:  # noqa: B023
                    executor.shutdown(wait=False, cancel_futures=True)  # type: ignore[unreachable]  # noqa: B023

                # Kill all geode and child processes to ensure cleanup
                _kill_geode_processes()
                _kill_child_processes()

            signal.signal(signal.SIGINT, signal_handler)
            signal.signal(signal.SIGTERM, signal_handler)

            try:
                executor = ProcessPoolExecutor(max_workers=max_workers)
                # Submit all specs to the executor
                future_to_spec = {
                    executor.submit(
                        _run_single_spec,
                        spec_file,
                        llm_provider,
                        model,
                        max_cases,
                        timeout_ms,
                        server_timeout_ms,
                        dry_run,
                        ci,
                        seed,
                        geode_binary,
                        None,  # server_port=None to auto-allocate unique ports
                        verbose,
                        current_transport,
                        force_cluster_size,
                        failure_file,
                    ): spec_file
                    for spec_file in spec_files
                }

                # Collect results as they complete
                failed_specs: list[tuple[Path, dict[str, Any]]] = []
                for future in as_completed(future_to_spec):
                    if interrupted:
                        # Cancel remaining futures
                        for f in future_to_spec:
                            f.cancel()
                        break

                    spec_file = future_to_spec[future]
                    try:
                        result = future.result(timeout=1)
                    except Exception as exc:
                        if interrupted:
                            break  # type: ignore[unreachable]
                        console_err.print(f"Spec {spec_file} generated exception: {exc}", style="red")
                        _record_spec_error(str(spec_file), f"worker exception: {exc}")
                        total_exit_code = max(total_exit_code, 3)
                        continue

                    if result["error"]:
                        console_err.print(result["error"], style="red")
                        _record_spec_error(str(spec_file), str(result["error"]))

                    summary = result["summary"]
                    failed_count = summary.get("failed", 0)
                    total_count = summary.get("total", 0)
                    has_error = result.get("error") is not None
                    skip_reason = result.get("skip_reason")

                    if failed_count > 0 or has_error or (total_count == 0 and not skip_reason):
                        # Track failed specs for retry
                        failed_specs.append((spec_file, result))
                    else:
                        total_exit_code = max(total_exit_code, result["exit_code"])
                        aggregate_summary["total"] += summary.get("total", 0)
                        aggregate_summary["passed"] += summary.get("passed", 0)
                        aggregate_summary["failed"] += summary.get("failed", 0)
                        aggregate_summary["skipped"] += summary.get("skipped", 0)
                        spec_entry = {"spec": result["spec"], "summary": summary}
                        if "results" in result:
                            spec_entry["results"] = result["results"]
                        if skip_reason:
                            spec_entry["skip_reason"] = skip_reason
                        all_results.append(spec_entry)
                        _flush_report(report_json, aggregate_summary, all_results)

                    if not ci:
                        passed = summary.get("passed", 0)
                        if total_count == 0 and skip_reason:
                            status = "[yellow]SKIP[/yellow]"
                            console.print(
                                f"  {status} {spec_file.name}: 0 passed, 0 failed (skipped: {skip_reason[:80]})"
                            )
                        elif failed_count > 0 or has_error or total_count == 0:
                            console.print(f"  [red]FAIL[/red] {spec_file.name}: {passed} passed, {failed_count} failed")
                        else:
                            console.print(
                                f"  [green]PASS[/green] {spec_file.name}: {passed} passed, {failed_count} failed"
                            )
                        sys.stdout.flush()

                # Retry failed specs serially to eliminate false positives
                # from resource contention during parallel execution.
                if failed_specs and not interrupted:
                    if not ci:
                        console.print(f"\n[yellow]Retrying {len(failed_specs)} failed spec(s) serially...[/yellow]")

                    # Kill any leftover geode processes before retries
                    _kill_geode_processes()

                    for spec_file, _original_result in failed_specs:
                        if not ci and verbose:
                            console.print(f"  [dim]Retrying {spec_file.name}...[/dim]")

                        retry_result = _run_single_spec(
                            spec_file,
                            llm_provider,
                            model,
                            max_cases,
                            timeout_ms,
                            server_timeout_ms,
                            dry_run,
                            ci,
                            seed,
                            geode_binary,
                            None,
                            verbose,
                            current_transport,
                            force_cluster_size,
                        )

                        retry_summary = retry_result["summary"]
                        retry_failed = retry_summary.get("failed", 0)
                        retry_total = retry_summary.get("total", 0)
                        retry_has_error = retry_result.get("error") is not None

                        if retry_failed == 0 and not retry_has_error and retry_total > 0:
                            # Retry passed — use retry result (contention was the cause)
                            use_result = retry_result
                            if not ci:
                                console.print(
                                    f"  [green]PASS[/green] {spec_file.name}: "
                                    f"{retry_summary.get('passed', 0)} passed (retry succeeded)"
                                )
                                sys.stdout.flush()
                        else:
                            # Retry also failed — genuine failure, use retry result
                            use_result = retry_result
                            if not ci:
                                console.print(
                                    f"  [red]FAIL[/red] {spec_file.name}: "
                                    f"{retry_summary.get('passed', 0)} passed, "
                                    f"{retry_failed} failed (confirmed failure)"
                                )
                                sys.stdout.flush()

                        use_summary = use_result["summary"]
                        total_exit_code = max(total_exit_code, use_result["exit_code"])
                        aggregate_summary["total"] += use_summary.get("total", 0)
                        aggregate_summary["passed"] += use_summary.get("passed", 0)
                        aggregate_summary["failed"] += use_summary.get("failed", 0)
                        aggregate_summary["skipped"] += use_summary.get("skipped", 0)
                        spec_entry = {"spec": use_result["spec"], "summary": use_summary}
                        if "results" in use_result:
                            spec_entry["results"] = use_result["results"]
                        all_results.append(spec_entry)
                        _flush_report(report_json, aggregate_summary, all_results)

            except KeyboardInterrupt:
                interrupted = True
                if not ci:
                    console.print("\n[yellow]Keyboard interrupt, shutting down...[/yellow]")
            finally:
                # Restore original signal handlers
                signal.signal(signal.SIGINT, original_sigint)
                signal.signal(signal.SIGTERM, original_sigterm)

                # Shutdown executor
                if executor:
                    executor.shutdown(wait=False, cancel_futures=True)

                # Clean up any remaining geode and child processes
                _kill_geode_processes()
                _kill_child_processes()

                if interrupted:
                    raise typer.Exit(code=130)  # Standard exit code for SIGINT

        else:
            # Sequential execution (original behavior)
            for spec_file in spec_files:
                if not ci and verbose and len(spec_files) > 1:
                    console.print(f"\n[cyan]Running spec: {spec_file.name}[/cyan]")

                try:
                    spec_obj = load_spec(spec_file)
                except SpecValidationError as exc:
                    console_err.print(f"SCHEMA_ERROR in {spec_file}", style="red")
                    _record_spec_error(str(spec_file), f"SCHEMA_ERROR: {exc}")
                    total_exit_code = max(total_exit_code, 2)
                    continue
                except Exception as exc:
                    console_err.print(f"SCHEMA_ERROR in {spec_file}", style="red")
                    _record_spec_error(str(spec_file), f"SCHEMA_ERROR: {exc}")
                    total_exit_code = max(total_exit_code, 2)
                    continue

                # Resolve secrets before attempting to run tests
                try:
                    secrets, env_vars = resolve_secrets(spec_obj)
                except SecretResolutionError as exc:
                    console_err.print(str(exc), style="red")
                    _record_spec_error(str(spec_file), f"SECRET_ERROR: {exc}")
                    total_exit_code = max(total_exit_code, 4)
                    continue

                try:
                    run_kwargs: dict[str, Any] = {
                        "spec": spec_obj,
                        "secrets": secrets,
                        "env_overrides": env_vars,
                        "llm_provider": llm_provider,
                        "model": model,
                        "max_cases": max_cases,
                        "timeout_ms": timeout_ms,
                        "server_timeout_ms": server_timeout_ms,
                        "report_json": None,  # We'll write aggregate report at the end
                        "dry_run": dry_run,
                        "ci_mode": ci,
                        "seed": seed,
                        "spec_path": str(spec_file),
                        "geode_binary": geode_binary,
                        "server_port": server_port,
                        "verbose": verbose,
                        "transport": current_transport,
                        "force_cluster_size": force_cluster_size,
                        "failure_file": failure_file,
                    }
                    exit_code, summary = run_tests(**run_kwargs)
                    failed_count = summary.get("failed", 0)
                    total_count = summary.get("total", 0)
                    retried = False
                    spec_skipped = bool(getattr(spec_obj, "skip", None))
                    # A single failure in the sequential run is most often a
                    # transient/contention false positive (slow bootstrap, a
                    # dropped QUIC handshake, etc.). Re-run the spec once
                    # serially; if it passes, treat the original as transient.
                    # Mirrors the retry the parallel path already performs.
                    # NB: a spec with a top-level `skip:` directive contributes
                    # zero cases by design — don't treat that as a failure or
                    # waste a retry on it.
                    if (failed_count > 0 or (total_count == 0 and not spec_skipped)) and not dry_run:
                        retried = True
                        _kill_geode_processes()
                        if not ci and verbose:
                            console.print(f"  [dim]Retrying {spec_file.name}...[/dim]")
                        # Don't re-stream retry failures — the first attempt already
                        # streamed live, and the authoritative post-retry list is
                        # written to the failure file's Final section.
                        run_kwargs["failure_file"] = None
                        exit_code, summary = run_tests(**run_kwargs)
                        failed_count = summary.get("failed", 0)
                        total_count = summary.get("total", 0)
                    # Aggregate results
                    total_exit_code = max(total_exit_code, exit_code)
                    aggregate_summary["total"] += summary.get("total", 0)
                    aggregate_summary["passed"] += summary.get("passed", 0)
                    aggregate_summary["failed"] += summary.get("failed", 0)
                    aggregate_summary["skipped"] += summary.get("skipped", 0)
                    spec_entry = {"spec": str(spec_file), "summary": summary}
                    if "results" in summary:
                        spec_entry["results"] = summary.pop("results")
                    all_results.append(spec_entry)
                    _flush_report(report_json, aggregate_summary, all_results)
                    if not ci:
                        passed = summary.get("passed", 0)
                        if total_count == 0 and spec_skipped:
                            status = "[yellow]SKIP[/yellow]"
                            note = f" (skipped: {spec_obj.skip[:80]})"
                        else:
                            is_fail = failed_count > 0 or total_count == 0
                            status = "[red]FAIL[/red]" if is_fail else "[green]PASS[/green]"
                            note = ""
                            if retried:
                                note = " (confirmed failure)" if is_fail else " (retry succeeded)"
                        console.print(f"  {status} {spec_file.name}: {passed} passed, {failed_count} failed{note}")
                        sys.stdout.flush()
                except RunnerError as exc:
                    console_err.print(str(exc), style="red")
                    _record_spec_error(str(spec_file), f"RUNNER_ERROR: {exc}")
                    total_exit_code = max(total_exit_code, 3)
                    continue

    # Write aggregate report if requested
    if report_json is not None:
        report_data = {
            "summary": aggregate_summary,
            "specs": all_results,
        }
        report_json.parent.mkdir(parents=True, exist_ok=True)
        report_json.write_text(json.dumps(report_data, indent=2))

    # Finalize the streaming failure file: append the authoritative post-retry
    # failure list (per-test failures scanned from the aggregated results, plus
    # any spec-level errors) so an agent has one clean checklist to work from.
    _failed_entries: list[dict[str, str]] = []
    for _spec_entry in all_results:
        for _r in _spec_entry.get("results", []):
            if not _r.get("passed", True) and not _r.get("skip_reason"):
                _failed_entries.append(
                    {
                        "spec": _spec_entry.get("spec", "?"),
                        "test": _r.get("name", "?"),
                        "error": _r.get("error", ""),
                    }
                )
    _failed_entries.extend(spec_error_entries)
    finalize_failure_log(
        failure_file,
        aggregate=aggregate_summary,
        failed_entries=_failed_entries,
    )

    # Print final single‑line JSON summary
    print(json.dumps({"summary": aggregate_summary}, separators=(",", ":")))

    # Show rich summary if not in CI mode
    if not ci:
        _show_rich_summary(aggregate_summary, console)

    # Exit with determined exit code (0 for success, 1 if any test failed)
    raise typer.Exit(code=total_exit_code)


secrets_app = typer.Typer(help="Subcommands for working with secrets defined in a test spec.")


@secrets_app.command("check")
def secrets_check(*, spec: Path = typer.Option(..., exists=True, readable=True, help="Path to the YAML spec")) -> None:
    """Verify that all required secrets can be resolved.

    If any required secret cannot be resolved from the configured source (env
    or keyring), the command exits with code 4.
    """
    try:
        spec_obj = load_spec(spec)
    except SpecValidationError:
        console_err.print("SCHEMA_ERROR", style="red")
        raise typer.Exit(code=2) from None
    try:
        resolve_secrets(spec_obj)
    except SecretResolutionError as exc:
        console_err.print(str(exc), style="red")
        raise typer.Exit(code=4) from None
    # No missing secrets
    console.print("[green]All required secrets are resolvable[/green]")
    raise typer.Exit(code=0)


@secrets_app.command("list")
def secrets_list(
    *,
    spec: Path = typer.Option(..., exists=True, readable=True, help="Path to the YAML spec"),
    show: bool = typer.Option(False, help="Show secret values instead of masking them"),
) -> None:
    """List the secret names defined in the spec.

    By default, the values are masked. Pass --show to display the values
    directly. Note that revealing secret values prints them to your
    terminal; use with care. Secret values are never persisted to disk.
    """
    try:
        spec_obj = load_spec(spec)
    except SpecValidationError:
        console_err.print("SCHEMA_ERROR", style="red")
        raise typer.Exit(code=2) from None
    try:
        secrets, _ = resolve_secrets(spec_obj)
    except SecretResolutionError as exc:
        console_err.print(str(exc), style="red")
        raise typer.Exit(code=4) from None
    if not spec_obj.secrets:
        console.print("[yellow]No secrets defined in spec[/yellow]")
        raise typer.Exit(code=0)

    table = Table(title="Secrets Configuration")
    table.add_column("Name", style="cyan")
    table.add_column("Source", style="magenta")
    table.add_column("Value", style="green" if show else "dim")

    for name, config in spec_obj.secrets.items():
        value = secrets.get(name)
        display = value if (show and value is not None) else "***"
        table.add_row(name, config.source, display)

    console.print(table)
    raise typer.Exit(code=0)


server_app = typer.Typer(help="Subcommands for managing Geode server instances.")


@server_app.command("start")
def server_start(
    *,
    port: int = typer.Option(8443, min=1024, max=65535, help="Port to bind the server to"),
    data_dir: Path | None = typer.Option(None, help="Data directory for the server"),
    geode_binary: str | None = typer.Option(None, help="Path to the geode binary"),
    timeout_ms: int = typer.Option(60000, min=1000, help="Startup timeout in milliseconds"),
    background: bool = typer.Option(False, help="Start server in background and exit"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable verbose server output"),
) -> None:
    """Start a managed Geode server instance for testing.

    This command starts a Geode server and waits for it to become ready.
    The server will be automatically stopped when the command exits unless
    --background is specified.
    """
    mgr = ServerManager(geode_binary=geode_binary, port=port, data_dir=data_dir, timeout_ms=timeout_ms, verbose=verbose)

    try:
        if not background:
            console.print(f"[yellow]Starting Geode server on port {port}...[/yellow]")

        mgr.start()

        if background:
            console.print(f"[green]Server started on port {port} (PID: {mgr.process.pid})[/green]")
            console.print(f"[dim]Data directory: {mgr.data_dir}[/dim]")
            raise typer.Exit(code=0)
        else:
            console.print(f"[green]Server ready on port {port}[/green]")
            console.print("[dim]Press Ctrl+C to stop the server[/dim]")

            try:
                # Keep the server running until interrupted
                mgr.wait()
            except KeyboardInterrupt:
                console.print("\n[yellow]Stopping server...[/yellow]")
            finally:
                mgr.stop()
                console.print("[green]Server stopped[/green]")

    except Exception as exc:
        console_err.print(f"[red]Failed to start server: {exc}[/red]")
        raise typer.Exit(code=3) from None


@server_app.command("stop")
def server_stop(
    *,
    port: int = typer.Option(8443, min=1024, max=65535, help="Port of the server to stop"),
    force: bool = typer.Option(False, help="Force kill the server process"),
) -> None:
    """Stop a running Geode server instance by port."""
    try:
        if ServerManager.stop_by_port(port, force=force):
            console.print(f"[green]Server on port {port} stopped[/green]")
        else:
            console.print(f"[yellow]No server found on port {port}[/yellow]")
            raise typer.Exit(code=1)
    except Exception as exc:
        console_err.print(f"[red]Failed to stop server: {exc}[/red]")
        raise typer.Exit(code=3) from None


@server_app.command("status")
def server_status(
    *,
    port: int | None = typer.Option(None, min=1024, max=65535, help="Check specific port"),
) -> None:
    """Show status of running Geode server instances."""
    servers = ServerManager.list_servers(port)

    if not servers:
        if port:
            console.print(f"[yellow]No server found on port {port}[/yellow]")
        else:
            console.print("[yellow]No Geode servers are currently running[/yellow]")
        raise typer.Exit(code=0)

    table = Table(title="Running Geode Servers")
    table.add_column("PID", style="cyan")
    table.add_column("Port", style="magenta")
    table.add_column("Status", style="green")
    table.add_column("Data Directory", style="dim")

    for server in servers:
        table.add_row(str(server["pid"]), str(server["port"]), server["status"], server.get("data_dir", "unknown"))

    console.print(table)


# Add subcommands to the main app
app.add_typer(secrets_app, name="secrets")
app.add_typer(server_app, name="server")


def main() -> None:
    """Entry point for console_scripts entrypoint."""
    app()


if __name__ == "__main__":
    main()
