from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from rich.progress import Progress, SpinnerColumn, TextColumn

from .analyzer import analyze
from .audit import AuditBridge, AuditStore
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
from .terminal import console

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
    audit_case_id: int | None = None

@dataclass
class RunReport:
    base_url: str
    total: int = 0
    passed: int = 0
    failures: list[FailureReport] = field(default_factory=list)
    audit_run_id: str | None = None

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


async def _run_pipeline_impl(spec_path: Path, endpoints: list,
                       base_url: str, source_dir: Path | None,
                       auth_used: bool, do_fix: bool, auto_approve: bool,
                       start_cmd: str | None = None,
                       concurrency: int | None = None,
                       retries: int | None = None,
                       batch_size: int | None = None,
                       completed_batches: set[int] | None = None,
                       stop_after_failures: int | None = None,
                       audit: AuditStore | None = None,
                       run_id: str | None = None,
                       bridge: AuditBridge | None = None) -> RunReport:
    import asyncio
    if concurrency is not None and concurrency <= 0:
        raise ValueError("concurrency must be positive")
    if retries is not None and retries < 0:
        raise ValueError("retries must be non-negative")
    effective_batch_size = batch_size or SETTINGS.batch_size
    if effective_batch_size <= 0:
        raise ValueError("batch_size must be positive")
    if stop_after_failures is not None and stop_after_failures <= 0:
        raise ValueError("stop_after_failures must be positive")
    report = RunReport(base_url=base_url)
    console.print(f"[bold]Loaded {len(endpoints)} endpoints[/bold] from {spec_path.name}")

    completed = completed_batches or set()
    for start in range(0, len(endpoints), effective_batch_size):
        batch_number = start // effective_batch_size + 1
        if batch_number in completed:
            console.print(f"[dim]Skipping completed batch {batch_number}[/dim]")
            continue
        batch = endpoints[start:start + effective_batch_size]
        batch_id: int | None = None
        if audit and run_id:
            batch_id = await audit.start_batch(run_id, batch_number, start, len(batch))
        try:
            with Progress(SpinnerColumn(), TextColumn("{task.description}"),
                          console=console, transient=True) as prog:
                task = prog.add_task(
                    f"Running batch {batch_number} ({len(batch)} endpoints)...", total=None
                )
                results = await run_all(
                    batch, base_url, auth_used, timeout=SETTINGS.http_timeout,
                    concurrency=concurrency or SETTINGS.concurrency,
                    retries=SETTINGS.http_retries if retries is None else retries,
                )
                prog.remove_task(task)

            report.total += len(results)
            report.passed += sum(1 for r in results if r.passed)
            case_ids: list[int] = []
            if audit and run_id:
                case_ids = await audit.record_results(run_id, results, batch_id)
            failing = [r for r in results if not r.passed]
            if batch_id is not None and audit is not None:
                await audit.finish_batch(batch_id, len(results), len(failing))
            console.print(f"[green]{sum(r.passed for r in results)}[/green] passed / "
                          f"[red]{len(failing)}[/red] failed in batch {batch_number}")

            if failing:
                with Progress(SpinnerColumn(), TextColumn("{task.description}"), console=console) as prog:
                    task = prog.add_task(f"Diagnosing {len(failing)} failures...", total=len(failing))
                    for result_index, r in enumerate(results):
                        if r.passed:
                            continue
                        fr = FailureReport(result=r)
                        if case_ids:
                            fr.audit_case_id = case_ids[result_index]
                        try:
                            source_trace = None
                            if bridge and fr.audit_case_id:
                                def source_trace(files, case_id=fr.audit_case_id):
                                    return bridge.trace_source(case_id, files)
                            fr.diagnosis = await asyncio.to_thread(
                                analyze, r, source_dir, bridge.trace_llm if bridge else None, source_trace
                            )
                            if audit and run_id and fr.audit_case_id:
                                await audit.record_diagnosis(run_id, fr.audit_case_id, fr.diagnosis)
                            console.print(f"  [cyan]{r.case.name}[/cyan] -> "
                                          f"{fr.diagnosis.category} (conf {fr.diagnosis.confidence:.2f})")
                        except Exception as e:
                            console.print(f"  [red]analysis failed for {r.case.name}: {e}[/red]")
                        report.failures.append(fr)
                        prog.advance(task)
            if stop_after_failures and len(report.failures) >= stop_after_failures:
                console.print(f"[yellow]Stopping after {len(report.failures)} failures[/yellow]")
                break
        except Exception:
            if batch_id is not None and audit is not None:
                await audit.finish_batch(batch_id, 0, 0, status="failed")
            raise

    console.print(f"[bold]Run total:[/bold] [green]{report.passed}[/green] passed / "
                  f"[red]{len(report.failures)}[/red] failed (of {report.total})")
    if not report.failures:
        return report

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
            fix = await asyncio.to_thread(
                propose_fix, fr.diagnosis, source_dir, file_path,
                bridge.trace_llm if bridge else None,
            )
            fr.fix = fix
        except Exception as e:
            console.print(f"  [red]fix generation failed: {e}[/red]")
            continue

        wt_path, branch = create_worktree(source_dir, f"fix-{i:03d}")
        fr.branch = branch
        if audit and run_id and fr.audit_case_id:
            await audit.record_event(run_id, "worktree_created", {
                "case_id": fr.audit_case_id, "branch": branch, "worktree": str(wt_path),
            })
        try:
            diff_text = apply_full_file(wt_path, target_rel, fix.full_content)
            fr.unified_diff = diff_text
            if audit and run_id and fr.audit_case_id:
                await audit.record_fix(run_id, fr.audit_case_id, fix, diff_text)
        except PatchRejected as e:
            console.print(f"  [red]fix rejected: {e}[/red]")
            if audit and run_id and fr.audit_case_id:
                await audit.record_event(run_id, "patch_rejected", {
                    "case_id": fr.audit_case_id, "reason": str(e),
                })
            discard_patch(wt_path, source_dir)
            continue

        fr.applied = True

        if start_cmd:
            passed, output = await _verify_from_worktree(
                wt_path, start_cmd, fr.result, base_url
            )
            fr.test_after_fix_passed = passed
            fr.test_after_fix_output = output
            if audit and run_id and fr.audit_case_id:
                await audit.record_verification(
                    run_id, fr.audit_case_id, passed, output
                )
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
                bridge.trace_llm if bridge else None,
            )
            fr.verdict = verdict
            if audit and run_id and fr.audit_case_id:
                await audit.record_review(run_id, fr.audit_case_id, verdict)
        except Exception as e:
            console.print(f"  [red]review failed: {e}[/red]")
            discard_patch(wt_path, source_dir)
            fr.applied = False
            continue
        if not verdict.approve:
            console.print(f"  [red]reviewer rejected:[/red] {verdict.reasoning}")
            if audit and run_id and fr.audit_case_id:
                await audit.record_event(run_id, "fix_rejected_by_reviewer", {
                    "case_id": fr.audit_case_id, "reasoning": verdict.reasoning,
                })
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
            if console.input("  Commit to branch? [y/N] ").strip().lower() != "y":
                discard_patch(wt_path, source_dir)
                fr.applied = False
                continue

        try:
            sha = commit_patch(wt_path,
                message=f"fix(api): {fr.diagnosis.root_cause[:72]}\n\n"
                        f"Auto-generated for: {fr.result.case.name}",
                files=[target_rel])
            fr.commit_sha = sha
            if audit and run_id and fr.audit_case_id:
                await audit.record_event(run_id, "commit_created", {
                    "case_id": fr.audit_case_id, "branch": branch, "commit_sha": sha,
                })
            console.print(f"  [green]committed {sha[:8]} to {branch}[/green]")
        except Exception as e:
            console.print(f"  [red]commit failed: {e}[/red]")
            discard_patch(wt_path, source_dir)
            fr.applied = False
    return report


async def run_pipeline(spec_path: Path, base_url: str, source_dir: Path | None,
                       auth_used: bool, do_fix: bool, auto_approve: bool,
                       start_cmd: str | None = None,
                       concurrency: int | None = None,
                       retries: int | None = None,
                       batch_size: int | None = None,
                       include_prefix: str | None = None,
                       exclude_prefix: str | None = None,
                       methods: set[str] | None = None,
                       tags: set[str] | None = None,
                       resume_run_id: str | None = None,
                       stop_after_failures: int | None = None,
                       database_url: str | None = None,
                       audit_enabled: bool | None = None) -> RunReport:
    """Run the pipeline and persist a complete redacted audit trail."""
    import asyncio
    enabled = SETTINGS.audit_enabled if audit_enabled is None else audit_enabled
    store = await AuditStore.open(database_url or SETTINGS.database_url) if enabled else None
    raw_spec = spec_path.read_text(errors="replace")
    suffix = spec_path.suffix.lower()
    spec_format = "yaml" if suffix in (".yaml", ".yml") else "json"
    run_id: str | None = None
    bridge: AuditBridge | None = None
    completed_batches: set[int] = set()
    try:
        if any((include_prefix, exclude_prefix, methods, tags)):
            endpoints = load_endpoints(
                spec_path, base_url, include_prefix=include_prefix,
                exclude_prefix=exclude_prefix, methods=methods, tags=tags,
            )
        else:
            # Keep the two-argument call compatible with integrations that
            # replace the loader (for example, lightweight test harnesses).
            endpoints = load_endpoints(spec_path, base_url)
        if store:
            if resume_run_id:
                existing = await store.get_run(resume_run_id)
                if existing is None:
                    raise ValueError(f"Audit run not found: {resume_run_id}")
                import hashlib
                expected_hash = hashlib.sha256(raw_spec.encode("utf-8")).hexdigest()
                if existing.spec_sha256 != expected_hash:
                    raise ValueError("Cannot resume: the specification has changed")
                previous = existing.config_json.get("invocation", {}) if existing.config_json else {}
                requested = {
                    "batch_size": batch_size or SETTINGS.batch_size,
                    "include_prefix": include_prefix,
                    "exclude_prefix": exclude_prefix,
                    "methods": sorted(methods or set()),
                    "tags": sorted(tags or set()),
                }
                mismatches = [
                    key for key, value in requested.items()
                    if key in previous and previous[key] != value
                ]
                if existing.base_url != base_url:
                    mismatches.append("base_url")
                if mismatches:
                    raise ValueError(
                        "Cannot resume with different execution settings: "
                        + ", ".join(mismatches)
                    )
                run_id = resume_run_id
                completed_batches = await store.completed_batches(run_id)
            else:
                run_id = await store.start_run(
                    str(spec_path), base_url, raw_spec, spec_format, endpoints,
                    auth_used, do_fix,
                    invocation={
                        "source_dir": str(source_dir) if source_dir else None,
                        "auto_approve": auto_approve, "start_cmd": start_cmd,
                        "concurrency": concurrency, "retries": retries,
                        "batch_size": batch_size or SETTINGS.batch_size,
                        "include_prefix": include_prefix, "exclude_prefix": exclude_prefix,
                        "methods": sorted(methods or set()), "tags": sorted(tags or set()),
                        "stop_after_failures": stop_after_failures,
                        "audit_enabled": enabled,
                    },
                )
            bridge = AuditBridge(store, run_id, asyncio.get_running_loop())
        else:
            if resume_run_id:
                raise ValueError("--resume requires audit to be enabled")
            completed_batches = set()
        report = await _run_pipeline_impl(
            spec_path, endpoints, base_url, source_dir, auth_used, do_fix,
            auto_approve, start_cmd, concurrency, retries, batch_size,
            completed_batches, stop_after_failures, store, run_id, bridge,
        )
        report.audit_run_id = run_id
        if bridge:
            await bridge.drain()
        if store and run_id:
            await store.finish_run(run_id, report)
        return report
    except Exception as exc:
        if bridge:
            await bridge.drain()
        if store and run_id:
            await store.finish_run(run_id, RunReport(base_url=base_url), str(exc))
        raise
    finally:
        if store:
            await store.close()
