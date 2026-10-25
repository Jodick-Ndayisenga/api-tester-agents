from __future__ import annotations

import asyncio
import json
from pathlib import Path

import typer
from .config import SETTINGS
from .orchestrator import run_pipeline
from .report import write_report
from .terminal import configure_terminal, console

app = typer.Typer(add_completion=True, help="Multi-agent API contract tester.")
configure_terminal()

@app.command()
def run(
    spec: Path = typer.Option(..., "--spec", "-s", exists=True),
    base_url: str = typer.Option(..., "--base-url", "-u"),
    source: Path | None = typer.Option(None, "--source"),
    auth: bool = typer.Option(False, "--auth"),
    fix: bool = typer.Option(False, "--fix"),
    auto_approve: bool = typer.Option(False, "--auto-approve"),
    fail_on_test_failure: bool = typer.Option(
        True, "--fail-on-test-failure/--allow-failures",
        help="Exit with status 1 when API tests fail (CI-friendly default).",
    ),
    start_cmd: str | None = typer.Option(
        None, "--start-cmd",
        help="Command to start the API from a worktree, e.g. 'node src/server.js'. "
             "Enables real post-fix verification. Use $PORT for the port.",
    ),
    report_dir: Path = typer.Option(Path("reports"), "--report-dir"),
    concurrency: int | None = typer.Option(None, "--concurrency", min=1),
    retries: int | None = typer.Option(None, "--retries", min=0),
    batch_size: int | None = typer.Option(None, "--batch-size", min=1,
                                          help="Number of endpoints processed before moving to the next resumable batch."),
    include_prefix: str | None = typer.Option(None, "--include-prefix",
                                              help="Only test paths beginning with this prefix."),
    exclude_prefix: str | None = typer.Option(None, "--exclude-prefix",
                                              help="Skip paths beginning with this prefix."),
    methods: str | None = typer.Option(None, "--methods",
                                        help="Comma-separated HTTP methods, for example GET,POST."),
    tags: str | None = typer.Option(None, "--tags",
                                    help="Comma-separated OpenAPI tags to include."),
    resume: str | None = typer.Option(None, "--resume",
                                      help="Resume a previous audit run by its run UUID."),
    stop_after_failures: int | None = typer.Option(None, "--stop-after-failures", min=1,
                                                   help="Stop after this many failed cases; useful for staged runs."),
    database_url: str | None = typer.Option(None, "--database-url"),
    audit: bool = typer.Option(True, "--audit/--no-audit"),
) -> None:
    if source is not None and not source.is_dir():
        raise typer.BadParameter("--source must be an existing directory", param_hint="--source")
    method_set = {item.strip().upper() for item in methods.split(",") if item.strip()} if methods else None
    tag_set = {item.strip() for item in tags.split(",") if item.strip()} if tags else None
    console.print(f"[bold]Models:[/bold] {SETTINGS.analyzer_model} (analyzer), "
                  f"{SETTINGS.workhorse_model} (fixer/reviewer)")
    report = asyncio.run(run_pipeline(
        spec_path=spec, base_url=base_url, source_dir=source, auth_used=auth,
        do_fix=fix, auto_approve=auto_approve, start_cmd=start_cmd,
        concurrency=concurrency, retries=retries,
        batch_size=batch_size, include_prefix=include_prefix,
        exclude_prefix=exclude_prefix, methods=method_set, tags=tag_set,
        resume_run_id=resume, stop_after_failures=stop_after_failures,
        database_url=database_url, audit_enabled=audit))
    out = write_report(report, report_dir)
    console.print(f"\n[bold]Report:[/bold] {out}")
    if report.audit_run_id:
        console.print(f"[bold]Audit run:[/bold] {report.audit_run_id}")
    if fail_on_test_failure and report.failures:
        raise typer.Exit(code=1)

@app.command()
def smoke() -> None:
    """Verify Ollama is running and both custom models exist."""
    import ollama
    ok = True
    for name in (SETTINGS.analyzer_model, SETTINGS.workhorse_model):
        try:
            ollama.show(name)
            console.print(f"[green]ok[/green] {name}")
        except Exception as e:
            msg = (str(e) or type(e).__name__).splitlines()[0]
            console.print(f"[red]MISSING[/red] {name}  ({msg})")
            ok = False
    if not ok:
        raise typer.Exit(code=1)


@app.command("audit-export")
def audit_export(
    run_id: str = typer.Option(..., "--run-id"),
    output: Path = typer.Option(Path("audit-export.json"), "--output", "-o"),
    database_url: str | None = typer.Option(None, "--database-url"),
) -> None:
    """Export every stored record for one audit run to a JSON file."""
    from .audit import AuditStore

    async def export() -> dict:
        store = await AuditStore.open(database_url or SETTINGS.database_url)
        try:
            return await store.export_run(run_id)
        finally:
            await store.close()

    data = asyncio.run(export())
    output.write_text(json.dumps(data, indent=2, default=str) + "\n")
    console.print(f"[bold]Audit export:[/bold] {output}")

if __name__ == "__main__":
    app()
