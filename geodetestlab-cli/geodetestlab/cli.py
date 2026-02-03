"""Command line interface for the geodetestlab tool.

This module defines the Typer application and the various commands exposed to
users for testing Geode database functionality. It orchestrates loading the
specification, resolving secrets, managing server lifecycle, invoking tests,
and handling error conditions and exit codes according to the requirements.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib.runner import RunnerError, run_tests
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


@app.command("run")
def run(
    *,
    spec: Path = typer.Option(..., exists=True, readable=True, help="Path to the YAML test specification"),
    llm_provider: str = typer.Option(
        "mock",
        help="LLM provider to use for fuzzing (mock, openai, or geode-ai)",
        show_default=True,
    ),
    model: Optional[str] = typer.Option(
        None,
        help="LLM model identifier when using openai or geode-ai provider",
    ),
    max_cases: Optional[int] = typer.Option(
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
    report_json: Optional[Path] = typer.Option(
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
    seed: Optional[int] = typer.Option(
        None,
        help="Random seed to pass to the LLM provider for deterministic fuzzing",
    ),
    geode_binary: Optional[str] = typer.Option(
        None,
        help="Path to the geode binary (auto-detected if not specified)",
    ),
    server_port: Optional[int] = typer.Option(
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
) -> None:
    """Execute all tests defined in a specification file.

    This command validates the provided YAML specification, resolves any
    secrets referenced within it, optionally manages a Geode server instance,
    uses an LLM provider to generate additional fuzzed cases, and then executes
    the target CLI binary according to the defined tests. A single‑line JSON
    summary is always printed to stdout. Exit codes are defined by the outcome
    of parsing, secret resolution, server management, runtime errors, and
    assertion results.
    """
    if not ci and verbose:
        console.print("[yellow]Starting Geode CLI test execution...[/yellow]")

    try:
        spec_obj = load_spec(spec)
    except SpecValidationError:
        # Schema or specification validation error
        console_err.print("SCHEMA_ERROR", style="red")
        raise typer.Exit(code=2)
    except Exception:
        # Unexpected parsing error
        console_err.print("SCHEMA_ERROR", style="red")
        raise typer.Exit(code=2)

    # Resolve secrets before attempting to run tests
    try:
        secrets, env_vars = resolve_secrets(spec_obj)
    except SecretResolutionError as exc:
        console_err.print(str(exc), style="red")
        raise typer.Exit(code=4)

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
            report_json=report_json,
            dry_run=dry_run,
            ci_mode=ci,
            seed=seed,
            spec_path=str(spec),
            geode_binary=geode_binary,
            server_port=server_port,
            verbose=verbose,
        )
    except RunnerError as exc:
        # Runtime/setup error – typically binary not found or other unexpected issues
        console_err.print(str(exc), style="red")
        raise typer.Exit(code=3)

    # Print final single‑line JSON summary
    print(json.dumps({"summary": summary}, separators=(",", ":")))

    # Show rich summary if not in CI mode
    if not ci:
        _show_rich_summary(summary)

    # Exit with determined exit code (0 for success, 1 if any test failed)
    raise typer.Exit(code=exit_code)


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
        raise typer.Exit(code=2)
    try:
        resolve_secrets(spec_obj)
    except SecretResolutionError as exc:
        console_err.print(str(exc), style="red")
        raise typer.Exit(code=4)
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
        raise typer.Exit(code=2)
    try:
        secrets, _ = resolve_secrets(spec_obj)
    except SecretResolutionError as exc:
        console_err.print(str(exc), style="red")
        raise typer.Exit(code=4)
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
    data_dir: Optional[Path] = typer.Option(None, help="Data directory for the server"),
    geode_binary: Optional[str] = typer.Option(None, help="Path to the geode binary"),
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
        raise typer.Exit(code=3)


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
        raise typer.Exit(code=3)


@server_app.command("status")
def server_status(
    *,
    port: Optional[int] = typer.Option(None, min=1024, max=65535, help="Check specific port"),
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
