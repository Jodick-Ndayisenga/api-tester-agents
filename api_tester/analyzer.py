from __future__ import annotations

import json
import re
from pathlib import Path

from .config import SETTINGS
from .llm import chat_json
from .schemas import Diagnosis, TestResult

SYSTEM = """You are a senior backend engineer diagnosing a failing API test.

You will receive HTTP request/response details, the error message, and possibly
relevant source files. Output a JSON Diagnosis identifying the ROOT CAUSE.

Rules:
- Be specific. "Add validation" is too vague; say what to change and where.
- suspected_files MUST be copied verbatim from the `###` header line of a file in
  the source_files section. If you see `### server.js`, use exactly `server.js`.
  Do NOT invent paths. Do NOT use absolute paths. Do NOT prefix with the source
  root. If no source files are provided, leave empty and lower confidence.
- confidence is your real confidence (0-1). Do not inflate.
"""

def _format_failure(result: TestResult) -> str:
    c = result.case
    return json.dumps({
        "case": c.name,
        "method": c.method, "path": c.path,
        "expected_status": c.expected_status, "actual_status": result.actual_status,
        "request_body": c.request_body,
        "request_headers": {k: ("***" if k.lower() in ("authorization", "cookie") else v)
                            for k, v in c.request_headers.items()},
        "response_body": str(result.response_body)[:3000],
        "error": result.error,
    }, indent=2)

def _gather_source(failing_path: str, source_dir: Path | None) -> tuple[str, list[Path]]:
    if source_dir is None or not source_dir.exists():
        return "", []
    EXCLUDED_DIRS = {
        "node_modules", ".git", ".venv", "venv", ".env", "dist", "build",
        "__pycache__", ".pytest_cache", ".mypy_cache", ".next", ".nuxt",
        "coverage", ".coverage", "target", "out", "bin", "obj",
        ".idea", ".vscode", ".cache", ".turbo", ".parcel-cache",
        ".worktrees",
    }
    segments = [s for s in failing_path.split("/") if s and not s.startswith("{") and not s.startswith(":")]
    candidates: list[tuple[int, Path]] = []
    for f in source_dir.rglob("*"):
        if not f.is_file() or f.suffix not in (".ts", ".js", ".jsx", ".tsx", ".py", ".go", ".rb", ".java", ".kt"):
            continue
        if any(part in EXCLUDED_DIRS for part in f.parts):
            continue
        try:
            text = f.read_text(errors="ignore")
        except Exception:
            continue
        score = sum(1 for seg in segments if seg in text)
        if score > 0:
            name = str(f).lower()
            if any(tag in name for tag in ("controller", "route", "handler", "view", "endpoint")):
                score += 5
            candidates.append((score, f))
    candidates.sort(reverse=True, key=lambda x: x[0])

    parts: list[str] = []
    files: list[Path] = []
    total = 0
    max_candidates = min(6, SETTINGS.max_files_touched)
    for _, f in candidates[:max_candidates]:
        try:
            content = f.read_text(errors="ignore")
        except Exception:
            continue
        if total + len(content) > SETTINGS.max_file_chars:
            content = content[: SETTINGS.max_file_chars - total]
        rel = f.relative_to(source_dir)
        parts.append(f"### {rel}\n```\n{content}\n```")
        files.append(f)
        total += len(content)
        if total >= SETTINGS.max_file_chars:
            break
    return "\n\n".join(parts), files

def _normalize_suspected(returned: list[str], source_dir: Path, files: list[Path]) -> list[str]:
    """Accept absolute, relative, or basename-only forms; keep only paths under source_dir."""
    allowed_rel = {str(p.relative_to(source_dir)) for p in files}
    by_name = {p.name: str(p.relative_to(source_dir)) for p in files}
    out: list[str] = []
    for raw in returned:
        s = raw.strip().lstrip("./").lstrip("/")
        s = s.removeprefix("a/")
        try:
            abs_p = Path(raw)
            if abs_p.is_absolute():
                s = str(abs_p.relative_to(source_dir))
        except Exception:
            pass
        if s in allowed_rel:
            if s not in out:
                out.append(s)
            continue
        if s in by_name and by_name[s] not in out:
            out.append(by_name[s])
    return out

def analyze(result: TestResult, source_dir: Path | None,
            trace=None, source_trace=None) -> Diagnosis:
    source_text, files = _gather_source(result.case.path, source_dir)
    header = ""
    if source_dir and files:
        header = f"## Source root\n{source_dir}\n\n"
    user = header + "## Failure\n" + _format_failure(result) + \
           "\n\n## Source files\n" + (source_text or "(none provided)")
    if source_trace and files:
        assert source_dir is not None
        source_trace([{"path": str(f.relative_to(source_dir)), "content": f.read_text(errors="ignore")} for f in files])
    user = _redact_secrets(user)
    diag = chat_json(model=SETTINGS.analyzer_model, system=SYSTEM, user=user,
                     schema=Diagnosis, num_ctx=SETTINGS.analyzer_num_ctx, temperature=0.3,
                     trace=trace, kind="analyzer")
    if files and source_dir:
        diag.suspected_files = _normalize_suspected(diag.suspected_files, source_dir, files)
    return diag

_SECRET_PATTERNS = [
    (re.compile(r"(?i)(authorization\s*[:=]\s*)(?:bearer\s+)?[^\s,;]+"), r"\1***"),
    (re.compile(r"(?i)(bearer\s+)[^\s,;]+"), r"\1***"),
    (re.compile(r"(?i)(api[_-]?key|secret|password|token)(\s*[:=]\s*)['\"]?[^'\"\s,;]+"), r"\1\2***"),
    (re.compile(r"-----BEGIN [^-]+ PRIVATE KEY-----.*?-----END [^-]+ PRIVATE KEY-----", re.DOTALL), "[PRIVATE KEY REDACTED]"),
]

def _redact_secrets(text: str) -> str:
    for pattern, replacement in _SECRET_PATTERNS:
        text = pattern.sub(replacement, text)
    return text
