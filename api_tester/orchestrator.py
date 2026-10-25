from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn

from .analyzer import analyze
from .config import SETTINGS
from .discover import load_endpoints
from .fixer import propose_fix
from .reviewer import review
from .runner import run_all
from .safety import (
    PatchRejected,
    apply_full_file,
    commit_patch,
    create_worktree,
    discard_patch,
    is_git_repo,
)
from .schemas import Diagnosis, FixProposal, TestResult, Verdict

console = Console()

@dataclass
class FailureReport:
    result: TestResult
    diagnosis: Diagnosis | None = None
    fix: FixProposal | None = None
    unified_diff: str = ""
    verdict: Verdict | None = None
    applied: bool = False
    commit_sha: str | None = None
    branch: str | None = None
    test_after_fix_passed: bool | None = None
    test_after_fix_output: str = ""

@dataclass
class RunReport:
    base_url: str
    total: int = 0
    passed: int = 0
    failures: list[FailureReport] = field(default_factory=list)

async def _wait_ready(base_url: str, timeout: float) -> bool:
    import asyncio
    import time as _time

    import httpx
    deadline = _time.time() + timeout
    while _time.time() < deadline:
        try:
            async with httpx.AsyncClient(timeout=1.0) as c:
                response = await c.get(f"{base_url}/health")
                if 200 <= response.status_code < 400:
                    return True
        except Exception:
            await asyncio.sleep(0.3)
    return False


async def _verify_from_worktree(
    worktree: Path,
    start_cmd: str,
    original_result: TestResult,
    base_url: str,
) -> tuple[bool | None, str]:
    """Spawn the API from the worktree on base_port+offset, re-run the failing test, kill it."""
    import asyncio
    import os
    from urllib.parse import urlparse

    import httpx

    parsed = urlparse(base_url)
    base_port = parsed.port or 8000
    verify_port = base_port + SETTINGS.verify_port_offset
    verify_url = f"{parsed.scheme}://{parsed.hostname}:{verify_port}"

    env = {**os.environ, "PORT": str(verify_port), "HOST": parsed.hostname or "127.0.0.1"}
    console.print(f"  [dim]starting: {start_cmd}  (cwd={worktree.name}, PORT={verify_port})[/dim]")
    try:
        proc = await asyncio.create_subprocess_shell(
            start_cmd,
            cwd=str(worktree),
            env=env,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
    except Exception as e:
        return None, f"failed to spawn server: {e}"

    try:
        ready_task = asyncio.create_task(_wait_ready(verify_url, SETTINGS.verify_startup_timeout))
        while not ready_task.done():
            if proc.returncode is not None:
                return None, f"server exited before becoming ready (code {proc.returncode})"
            await asyncio.sleep(0.1)
        ready = await ready_task
        if not ready:
            return None, f"server did not respond on {verify_url} within {SETTINGS.verify_startup_timeout}s"

        case = original_result.case
        kwargs: dict = {"headers": case.request_headers}
        if case.method.upper() in ("POST", "PUT", "PATCH"):
            if case.name.startswith("invalid_json"):
                kwargs["content"] = b"{not valid json"
                kwargs["headers"] = {**case.request_headers, "Content-Type": "application/json"}
            else:
                kwargs["json"] = case.request_body

        async with httpx.AsyncClient(base_url=verify_url, timeout=SETTINGS.verify_timeout) as c:
            r = await c.request(case.method, case.path, params=case.request_query, **kwargs)
        passed = r.status_code in case.expected_status
        try:
            body_snip = r.json()
        except Exception:
            body_snip = r.text[:500]
        output = f"verify status={r.status_code} expected={case.expected_status} body={body_snip}"
        return passed, output
    finally:
        try:
            proc.terminate()
            try:
                await asyncio.wait_for(proc.wait(), timeout=5.0)
            except TimeoutError:
                proc.kill()
        except Exception:
            pass


async def run_pipeline(spec_path: Path, base_url: str, source_dir: Path | None,
                       auth_used: bool, do_fix: bool, auto_approve: bool,
                       start_cmd: str | None = None,
                       concurrency: int | None = None,
                       retries: int | None = None) -> RunReport:
    import asyncio
    if concurrency is not None and concurrency <= 0:
        raise ValueError("concurrency must be positive")
    if retries is not None and retries < 0:
        raise ValueError("retries must be non-negative")
    report = RunReport(base_url=base_url)
    endpoints = load_endpoints(spec_path, base_url)
    console.print(f"[bold]Loaded {len(endpoints)} endpoints[/bold] from {spec_path.name}")

    with Progress(SpinnerColumn(), TextColumn("{task.description}"),
                  console=console, transient=True) as prog:
        t = prog.add_task("Running tests...", total=None)
        results = await run_all(
            endpoints, base_url, auth_used, timeout=SETTINGS.http_timeout,
            concurrency=concurrency or SETTINGS.concurrency,
            retries=SETTINGS.http_retries if retries is None else retries,
        )
        prog.remove_task(t)

    report.total = len(results)
    report.passed = sum(1 for r in results if r.passed)
    failing = [r for r in results if not r.passed]
    console.print(f"[green]{report.passed}[/green] passed / "
                  f"[red]{len(failing)}[/red] failed (of {report.total})")
    if not failing:
        return report

    with Progress(SpinnerColumn(), TextColumn("{task.description}"), console=console) as prog:
        task = prog.add_task(f"Diagnosing {len(failing)} failures...", total=len(failing))
        for r in failing:
            fr = FailureReport(result=r)
            try:
                fr.diagnosis = await asyncio.to_thread(analyze, r, source_dir)
                console.print(f"  [cyan]{r.case.name}[/cyan] -> "
                              f"{fr.diagnosis.category} (conf {fr.diagnosis.confidence:.2f})")
            except Exception as e:
                console.print(f"  [red]analysis failed for {r.case.name}: {e}[/red]")
            report.failures.append(fr)
            prog.advance(task)

    if not do_fix:
        return report
    if source_dir is None or not is_git_repo(source_dir):
        console.print("[yellow]Skipping fix phase: --source must be a git repo.[/yellow]")
        return report

    # Compute the path of --source relative to the git repo root, so we can
    # translate "server.js" (relative to --source) into "src/server.js"
    # (relative to the repo, which is what the worktree root uses).
    import subprocess as _sp
    try:
        repo_root = Path(_sp.run(
            ["git", "-C", str(source_dir), "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, check=True,
        ).stdout.strip())
        source_prefix = source_dir.resolve().relative_to(repo_root.resolve())
    except Exception as e:
        console.print(f"[red]Could not compute source prefix: {e}[/red]")
        return report
    if str(source_prefix) == ".":
        source_prefix = Path("")

    for i, fr in enumerate(report.failures):
        if not fr.diagnosis or not fr.diagnosis.suspected_files:
            console.print(f"[dim]Skip {fr.result.case.name}: no suspected files[/dim]")
            continue
        if fr.diagnosis.confidence < 0.5:
            console.print(f"[dim]Skip {fr.result.case.name}: low confidence[/dim]")
            continue
        file_path = fr.diagnosis.suspected_files[0]
        target_rel = str(source_prefix / file_path) if str(source_prefix) else file_path
        console.print(f"\n[bold]Attempting fix:[/bold] {fr.result.case.name} -> {target_rel}")
        try:
            fix = await asyncio.to_thread(propose_fix, fr.diagnosis, source_dir, file_path)
            fr.fix = fix
        except Exception as e:
            console.print(f"  [red]fix generation failed: {e}[/red]")
            continue

        wt_path, branch = create_worktree(source_dir, f"fix-{i:03d}")
        fr.branch = branch
        try:
            diff_text = apply_full_file(wt_path, target_rel, fix.full_content)
            fr.unified_diff = diff_text
        except PatchRejected as e:
            console.print(f"  [red]fix rejected: {e}[/red]")
            discard_patch(wt_path, source_dir)
            continue

        fr.applied = True

        if start_cmd:
            passed, output = await _verify_from_worktree(
                wt_path, start_cmd, fr.result, base_url
            )
            fr.test_after_fix_passed = passed
            fr.test_after_fix_output = output
            if passed is True:
                console.print("  [green]verified:[/green] failing test now passes")
            elif passed is False:
                console.print("  [red]verified:[/red] failing test still fails")
                console.print(f"    {output[:200]}")
            else:
                console.print(f"  [yellow]verification unavailable:[/yellow] {output[:200]}")
        else:
            fr.test_after_fix_passed = None
            fr.test_after_fix_output = "no --start-cmd provided; verification skipped"
            console.print("  [dim]verification skipped (no --start-cmd)[/dim]")

        try:
            verdict = await asyncio.to_thread(
                review,
                fr.diagnosis, fix, diff_text,
                fr.test_after_fix_passed,
                fr.test_after_fix_output,
            )
            fr.verdict = verdict
        except Exception as e:
            console.print(f"  [red]review failed: {e}[/red]")
            discard_patch(wt_path, source_dir)
            fr.applied = False
            continue
        if not verdict.approve:
            console.print(f"  [red]reviewer rejected:[/red] {verdict.reasoning}")
            discard_patch(wt_path, source_dir)
            fr.applied = False
            continue

        if fr.test_after_fix_passed is False:
            console.print("  [red]refusing to commit: post-fix verification failed[/red]")
            discard_patch(wt_path, source_dir)
            fr.applied = False
            continue

        console.print("  [green]reviewer approved[/green]")
        if not auto_approve:
            console.print("  ---- diff ----")
            console.print(diff_text, markup=False)
            console.print("  ---- explanation ----")
            console.print(fix.explanation)
            if input("  Commit to branch? [y/N] ").strip().lower() != "y":
                discard_patch(wt_path, source_dir)
                fr.applied = False
                continue

        try:
            sha = commit_patch(wt_path,
                message=f"fix(api): {fr.diagnosis.root_cause[:72]}\n\n"
                        f"Auto-generated for: {fr.result.case.name}",
                files=[target_rel])
            fr.commit_sha = sha
            console.print(f"  [green]committed {sha[:8]} to {branch}[/green]")
        except Exception as e:
            console.print(f"  [red]commit failed: {e}[/red]")
            discard_patch(wt_path, source_dir)
            fr.applied = False
    return report
