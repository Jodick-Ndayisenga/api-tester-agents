from __future__ import annotations

from datetime import datetime
from pathlib import Path

from .orchestrator import RunReport


def write_report(report: RunReport, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    path = out_dir / f"report-{ts}.md"
    lines = [f"# API Test Report - {report.base_url}\n",
             f"**Generated:** {datetime.now().isoformat(timespec='seconds')}\n",
             f"**Total:** {report.total}  |  **Passed:** {report.passed}  |  "
             f"**Failed:** {len(report.failures)}\n"]
    if report.audit_run_id:
        lines.append(f"**Audit run:** `{report.audit_run_id}`\n")
    if not report.failures:
        lines.append("\n_All tests passed._\n")
    for i, fr in enumerate(report.failures, 1):
        c = fr.result.case
        lines.append(f"\n## {i}. {c.method} {c.path}\n")
        lines.append(f"- Expected: {c.expected_status}")
        lines.append(f"- Actual:   {fr.result.actual_status}")
        lines.append(f"- Error:    {fr.result.error}")
        if fr.diagnosis:
            d = fr.diagnosis
            lines.append("\n### Diagnosis\n")
            lines.append(f"- Root cause: {d.root_cause}")
            lines.append(f"- Category:   {d.category}")
            lines.append(f"- Severity:   {d.severity}")
            lines.append(f"- Confidence: {d.confidence:.2f}")
            if d.suspected_files:
                lines.append("- Suspected:  " + ", ".join(f"`{f}`" for f in d.suspected_files))
            lines.append(f"- Fix hint:   {d.fix_hint}")
        if fr.fix and fr.unified_diff:
            lines.append(f"\n### Proposed Fix ({fr.fix.file_path}, risk={fr.fix.risk})\n")
            lines.append("```diff")
            lines.append(fr.unified_diff)
            lines.append("```")
            lines.append(f"\n_{fr.fix.explanation}_\n")
        if fr.verdict:
            lines.append("\n### Verdict\n")
            lines.append(f"- Approve: {fr.verdict.approve}")
            lines.append(f"- Reasoning: {fr.verdict.reasoning}")
            for cn in fr.verdict.concerns:
                lines.append(f"- ! {cn}")
        lines.append(f"\n- Applied: {fr.applied}")
        if fr.test_after_fix_passed is True:
            lines.append("- Verified:  \u2705 failing test now passes")
        elif fr.test_after_fix_passed is False:
            lines.append("- Verified:  \u274c failing test still fails")
        elif fr.test_after_fix_output:
            lines.append(f"- Verified:  \u26a0\ufe0f  {fr.test_after_fix_output}")
        if fr.branch:
            lines.append(f"- Branch:  `{fr.branch}`")
        if fr.commit_sha:
            lines.append(f"- Commit:  `{fr.commit_sha}`")
        lines.append("")
    path.write_text("\n".join(lines))
    return path
