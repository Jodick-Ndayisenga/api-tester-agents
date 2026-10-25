from __future__ import annotations

import asyncio
from pathlib import Path

import typer
from rich.console import Console

from .config import SETTINGS
from .orchestrator import run_pipeline
from .report import write_report

app = typer.Typer(add_completion=False, help="Multi-agent API contract tester.")
console = Console()

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
) -> None:
    if source is not None and not source.is_dir():
        raise typer.BadParameter("--source must be an existing directory", param_hint="--source")
    console.print(f"[bold]Models:[/bold] {SETTINGS.analyzer_model} (analyzer), "
                  f"{SETTINGS.workhorse_model} (fixer/reviewer)")
    report = asyncio.run(run_pipeline(
        spec_path=spec, base_url=base_url, source_dir=source, auth_used=auth,
        do_fix=fix, auto_approve=auto_approve, start_cmd=start_cmd,
        concurrency=concurrency, retries=retries))
    out = write_report(report, report_dir)
    console.print(f"\n[bold]Report:[/bold] {out}")
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

if __name__ == "__main__":
    app()
