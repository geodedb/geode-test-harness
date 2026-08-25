from rich.console import Console
from rich.table import Table


def _show_rich_summary(summary: dict[str, int], console: Console) -> None:
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

    if failed > 0:
        console.print(f"\n[red]✗ {failed} test(s) failed[/red]")
    elif total == 0:
        # Zero cases executed is never a success: it means every spec was
        # skipped or never ran (e.g. a managed server that failed to start).
        console.print("\n[yellow]! No tests were executed[/yellow]")
    else:
        console.print("\n[green]✓ All tests passed![/green]")
