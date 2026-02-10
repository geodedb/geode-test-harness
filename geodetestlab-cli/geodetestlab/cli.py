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

from lib.runner import RunnerError, _kill_stale_servers, run_tests
from lib.spec import SpecValidationError, load_spec
from lib.utils import SecretResolutionError, resolve_secrets
from server.simple_manager import ServerManager

app = typer.Typer(
    name="geodetestlab",
    help="Interactive CLI testing system for Geode graph database with LLM fuzzing",
    rich_markup_mode="rich",
)

console = Console()
console_err = Console(stderr=True)


def _kill_geode_processes() -> None:
    """Kill any orphaned geode server processes started by this test run.

    This is a cleanup function to ensure geode processes don't linger after
    the test harness is interrupted or exits.
    """
    import subprocess

    try:
        # Kill geode serve processes (matching temp dir pattern)
        subprocess.run(
            ["pkill", "-9", "-f", "geode serve.*geode-test-"],
            capture_output=True,
            timeout=5,
        )
    except Exception:
        pass

    try:
        # Also kill any geode query processes
        subprocess.run(
            ["pkill", "-9", "-f", "geode query"],
            capture_output=True,
            timeout=5,
        )
    except Exception:
        pass


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
        result["summary"] = summary
    except RunnerError as exc:
        result["exit_code"] = 3
        result["error"] = str(exc)

    return result


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
        spec_files = sorted(
            list(specs.glob("*.yaml")) + list(specs.glob("*.yml"))
        )
        if not spec_files:
            console_err.print(f"Error: No YAML files found in directory: {specs}", style="red")
            raise typer.Exit(code=2)

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

    # Kill stale servers once before running any specs
    # This must happen exactly once, not per-worker, to avoid
    # parallel workers killing each other's servers.
    _kill_stale_servers()

    # Aggregate results across all spec files
    total_exit_code = 0
    aggregate_summary: dict = {"total": 0, "passed": 0, "failed": 0, "skipped": 0}
    all_results: list[dict] = []

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
                    executor.shutdown(wait=False, cancel_futures=True)  # noqa: B023

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
                    ): spec_file
                    for spec_file in spec_files
                }

                # Collect results as they complete
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
                            break
                        console_err.print(f"Spec {spec_file} generated exception: {exc}", style="red")
                        total_exit_code = max(total_exit_code, 3)
                        continue

                    if result["error"]:
                        console_err.print(result["error"], style="red")

                    total_exit_code = max(total_exit_code, result["exit_code"])
                    summary = result["summary"]
                    aggregate_summary["total"] += summary.get("total", 0)
                    aggregate_summary["passed"] += summary.get("passed", 0)
                    aggregate_summary["failed"] += summary.get("failed", 0)
                    aggregate_summary["skipped"] += summary.get("skipped", 0)
                    all_results.append({"spec": result["spec"], "summary": summary})

                    if not ci and verbose:
                        passed = summary.get("passed", 0)
                        failed = summary.get("failed", 0)
                        total = summary.get("total", 0)
                        has_error = result.get("error") is not None
                        # FAIL if: failed > 0, or error occurred, or no tests ran at all
                        if failed > 0 or has_error or total == 0:
                            status = "[red]FAIL[/red]"
                        else:
                            status = "[green]PASS[/green]"
                        console.print(f"  {status} {spec_file.name}: {passed} passed, {failed} failed")

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
                except SpecValidationError:
                    console_err.print(f"SCHEMA_ERROR in {spec_file}", style="red")
                    total_exit_code = max(total_exit_code, 2)
                    continue
                except Exception:
                    console_err.print(f"SCHEMA_ERROR in {spec_file}", style="red")
                    total_exit_code = max(total_exit_code, 2)
                    continue

                # Resolve secrets before attempting to run tests
                try:
                    secrets, env_vars = resolve_secrets(spec_obj)
                except SecretResolutionError as exc:
                    console_err.print(str(exc), style="red")
                    total_exit_code = max(total_exit_code, 4)
                    continue

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
                        report_json=None,  # We'll write aggregate report at the end
                        dry_run=dry_run,
                        ci_mode=ci,
                        seed=seed,
                        spec_path=str(spec_file),
                        geode_binary=geode_binary,
                        server_port=server_port,
                        verbose=verbose,
                        transport=current_transport,
                    )
                    # Aggregate results
                    total_exit_code = max(total_exit_code, exit_code)
                    aggregate_summary["total"] += summary.get("total", 0)
                    aggregate_summary["passed"] += summary.get("passed", 0)
                    aggregate_summary["failed"] += summary.get("failed", 0)
                    aggregate_summary["skipped"] += summary.get("skipped", 0)
                    all_results.append({"spec": str(spec_file), "summary": summary})
                except RunnerError as exc:
                    console_err.print(str(exc), style="red")
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

    # Print final single‑line JSON summary
    print(json.dumps({"summary": aggregate_summary}, separators=(",", ":")))

    # Show rich summary if not in CI mode
    if not ci:
        _show_rich_summary(aggregate_summary)

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


def _show_rich_summary(summary: dict) -> None:
    """Display a rich formatted summary of test results."""
    table = Table(title="Test Results Summary")
    table.add_column("Metric", style="cyan")
    table.add_column("Count", style="bold")

    total = summary.get("total", 0)
    passed = summary.get("passed", 0)
    failed = summary.get("failed", 0)
    skipped = summary.get("skipped", 0)

    table.add_row("Total", str(total))
    table.add_row("Passed", f"[green]{passed}[/green]")
    table.add_row("Failed", f"[red]{failed}[/red]" if failed > 0 else str(failed))
    table.add_row("Skipped", f"[yellow]{skipped}[/yellow]" if skipped > 0 else str(skipped))

    console.print()
    console.print(table)

    if failed == 0:
        console.print("\n[green]✓ All tests passed![/green]")
    else:
        console.print(f"\n[red]✗ {failed} test(s) failed[/red]")


# Add subcommands to the main app
app.add_typer(secrets_app, name="secrets")
app.add_typer(server_app, name="server")


def main() -> None:
    """Entry point for console_scripts entrypoint."""
    app()


if __name__ == "__main__":
    main()
