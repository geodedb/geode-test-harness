import re
from pathlib import Path

cli_path = Path("geodetestlab-cli/geodetestlab/cli.py")
content = cli_path.read_text()

# We need to insert the helper functions before the `run` command.
# Let's find the `@app.command("run")` line.
run_idx = content.find('@app.command("run")')

helpers = """
def _discover_specs(spec: Path | None, specs: Path | None) -> list[Path]:
    \"\"\"Discover spec files from the provided arguments.\"\"\"
    if spec is None and specs is None:
        console_err.print("Error: Either --spec (file) or --specs (directory) must be provided", style="red")
        raise typer.Exit(code=2)
    if spec is not None and specs is not None:
        console_err.print("Error: Cannot specify both --spec and --specs", style="red")
        raise typer.Exit(code=2)

    spec_files: list[Path] = []
    if spec is not None:
        spec_files = [spec]
    elif specs is not None:
        if not specs.is_dir():
            console_err.print(f"Error: --specs path is not a directory: {specs}", style="red")
            raise typer.Exit(code=2)
        spec_files = sorted(list(specs.glob("*.yaml")) + list(specs.glob("*.yml")))
        if not spec_files:
            console_err.print(f"Error: No YAML files found in directory: {specs}", style="red")
            raise typer.Exit(code=2)
    return spec_files


def _generate_reports(
    report_json: Path | None,
    aggregate_summary: dict[str, int],
    all_results: list[dict[str, Any]],
    ci: bool,
) -> None:
    \"\"\"Generate and output reports for the test run.\"\"\"
    if report_json is not None:
        report_data = {
            "summary": aggregate_summary,
            "specs": all_results,
        }
        report_json.parent.mkdir(parents=True, exist_ok=True)
        report_json.write_text(json.dumps(report_data, indent=2))

    print(json.dumps({"summary": aggregate_summary}, separators=(",", ":")))

    if not ci:
        _show_rich_summary(aggregate_summary)


def _run_parallel(
    spec_files: list[Path],
    llm_provider: str,
    model: str | None,
    max_cases: int | None,
    timeout_ms: int,
    server_timeout_ms: int,
    dry_run: bool,
    ci: bool,
    seed: int | None,
    geode_binary: str | None,
    verbose: bool,
    current_transport: str,
    parallel: int,
    aggregate_summary: dict[str, int],
    all_results: list[dict[str, Any]],
) -> int:
    \"\"\"Run tests in parallel.\"\"\"
    total_exit_code = 0
    max_workers = min(parallel, len(spec_files))

    if not ci and verbose:
        console.print(f"[dim]Starting {max_workers} parallel workers...[/dim]")

    executor = None
    interrupted = False

    original_sigint = signal.getsignal(signal.SIGINT)
    original_sigterm = signal.getsignal(signal.SIGTERM)

    def signal_handler(signum: int, frame: Any) -> None:
        nonlocal interrupted, executor
        if interrupted:
            if not ci:
                console.print("\\n[red]Force exiting...[/red]")
            _kill_geode_processes()
            _kill_child_processes()
            import os
            os._exit(130)

        interrupted = True
        if not ci:
            console.print("\\n[yellow]Interrupt received, shutting down workers...[/yellow]")

        if executor:
            executor.shutdown(wait=False, cancel_futures=True)

        _kill_geode_processes()
        _kill_child_processes()

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    try:
        executor = ProcessPoolExecutor(max_workers=max_workers)
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
                None,
                verbose,
                current_transport,
            ): spec_file
            for spec_file in spec_files
        }

        failed_specs: list[tuple[Path, dict[str, Any]]] = []
        for future in as_completed(future_to_spec):
            if interrupted:
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

            summary = result["summary"]
            failed_count = summary.get("failed", 0)
            total_count = summary.get("total", 0)
            has_error = result.get("error") is not None

            if failed_count > 0 or has_error or total_count == 0:
                failed_specs.append((spec_file, result))
            else:
                total_exit_code = max(total_exit_code, result["exit_code"])
                aggregate_summary["total"] += summary.get("total", 0)
                aggregate_summary["passed"] += summary.get("passed", 0)
                aggregate_summary["failed"] += summary.get("failed", 0)
                aggregate_summary["skipped"] += summary.get("skipped", 0)
                all_results.append({"spec": result["spec"], "summary": summary})

            if not ci and verbose:
                passed = summary.get("passed", 0)
                if failed_count > 0 or has_error or total_count == 0:
                    status = "[red]FAIL[/red]"
                else:
                    status = "[green]PASS[/green]"
                console.print(f"  {status} {spec_file.name}: {passed} passed, {failed_count} failed")

        if failed_specs and not interrupted:
            if not ci:
                console.print(f"\\n[yellow]Retrying {len(failed_specs)} failed spec(s) serially...[/yellow]")

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
                )

                retry_summary = retry_result["summary"]
                retry_failed = retry_summary.get("failed", 0)
                retry_total = retry_summary.get("total", 0)
                retry_has_error = retry_result.get("error") is not None

                if retry_failed == 0 and not retry_has_error and retry_total > 0:
                    use_result = retry_result
                    if not ci and verbose:
                        console.print(
                            f"  [green]PASS[/green] {spec_file.name}: "
                            f"{retry_summary.get('passed', 0)} passed (retry succeeded)"
                        )
                else:
                    use_result = retry_result
                    if not ci and verbose:
                        console.print(
                            f"  [red]FAIL[/red] {spec_file.name}: "
                            f"{retry_summary.get('passed', 0)} passed, "
                            f"{retry_failed} failed (confirmed failure)"
                        )

                use_summary = use_result["summary"]
                total_exit_code = max(total_exit_code, use_result["exit_code"])
                aggregate_summary["total"] += use_summary.get("total", 0)
                aggregate_summary["passed"] += use_summary.get("passed", 0)
                aggregate_summary["failed"] += use_summary.get("failed", 0)
                aggregate_summary["skipped"] += use_summary.get("skipped", 0)
                all_results.append({"spec": use_result["spec"], "summary": use_summary})

    except KeyboardInterrupt:
        interrupted = True
        if not ci:
            console.print("\\n[yellow]Keyboard interrupt, shutting down...[/yellow]")
    finally:
        signal.signal(signal.SIGINT, original_sigint)
        signal.signal(signal.SIGTERM, original_sigterm)

        if executor:
            executor.shutdown(wait=False, cancel_futures=True)

        _kill_geode_processes()
        _kill_child_processes()

        if interrupted:
            raise typer.Exit(code=130)

    return total_exit_code

"""

new_content = content[:run_idx] + helpers + content[run_idx:]

# Now we need to replace the body of `run`
run_body_start = new_content.find('    # Handle --output as alias for --report-json')
run_body_end = new_content.find('secrets_app = typer.Typer(help="Subcommands for working with secrets defined in a test spec.")')

new_run_body = """    # Handle --output as alias for --report-json
    if output is not None and report_json is None:
        report_json = output

    spec_files = _discover_specs(spec, specs)

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

    if geode_binary is None:
        from lib.utils import find_geode_binary
        try:
            geode_binary = find_geode_binary()
        except FileNotFoundError:
            pass

    if specs is not None:
        _kill_stale_servers()

    total_exit_code = 0
    aggregate_summary: dict[str, int] = {"total": 0, "passed": 0, "failed": 0, "skipped": 0}
    all_results: list[dict[str, Any]] = []

    for current_transport in transports_to_run:
        if not ci and verbose and len(transports_to_run) > 1:
            console.print(f"\\n[cyan]Running with {current_transport.upper()} transport...[/cyan]")

        if parallel > 1 and len(spec_files) > 1:
            exit_code = _run_parallel(
                spec_files,
                llm_provider,
                model,
                max_cases,
                timeout_ms,
                server_timeout_ms,
                dry_run,
                ci,
                seed,
                geode_binary,
                verbose,
                current_transport,
                parallel,
                aggregate_summary,
                all_results,
            )
            total_exit_code = max(total_exit_code, exit_code)
        else:
            for spec_file in spec_files:
                if not ci and verbose and len(spec_files) > 1:
                    console.print(f"\\n[cyan]Running spec: {spec_file.name}[/cyan]")

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
                        report_json=None,
                        dry_run=dry_run,
                        ci_mode=ci,
                        seed=seed,
                        spec_path=str(spec_file),
                        geode_binary=geode_binary,
                        server_port=server_port,
                        verbose=verbose,
                        transport=current_transport,
                    )
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

    _generate_reports(report_json, aggregate_summary, all_results, ci)

    raise typer.Exit(code=total_exit_code)


"""

new_content = new_content[:run_body_start] + new_run_body + new_content[run_body_end:]

cli_path.write_text(new_content)
