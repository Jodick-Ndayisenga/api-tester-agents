from __future__ import annotations

from pathlib import Path

from .config import SETTINGS
from .llm import chat_json
from .schemas import Diagnosis, FixProposal

SYSTEM = """You are a senior backend engineer writing a complete fix for a failing API test.

You will receive a diagnosis and the FULL current content of ONE source file.
Your job is to return a JSON FixProposal containing the COMPLETE new file content.

Rules:
- file_path MUST be copied verbatim from the `###` header of the file you were
  shown (e.g. if you saw `### server.js`, use exactly `server.js`).
- full_content MUST contain the ENTIRE new file, not just changed lines. Preserve
  everything that does not need to change, byte-for-byte: imports, comments,
  formatting, blank lines, ordering.
- Do NOT wrap full_content in markdown fences.
- Do NOT add explanatory comments about the fix.
- Do NOT omit any part of the file as "..." or "// unchanged".
- Change ONLY what is needed to fix the diagnosed bug. No refactors, no reformatting.
- Include any necessary new imports at the top of the file.
- If you cannot fix within one file, still produce your best attempt and set risk to "high".
"""

def propose_fix(diag: Diagnosis, source_root: Path, file_path: str, trace=None) -> FixProposal:
    target = source_root / file_path
    if not target.exists():
        raise FileNotFoundError(f"File does not exist: {target}")
    content = target.read_text(errors="ignore")
    if len(content) > SETTINGS.max_file_chars:
        content = content[: SETTINGS.max_file_chars]

    user = (
        f"## Diagnosis\n{diag.model_dump_json(indent=2)}\n\n"
        f"## File: {file_path}\n"
        f"## Current content\n{content}\n\n"
        f"Return a FixProposal for `{file_path}` containing the complete new file content."
    )
    last_error: Exception | None = None
    for _ in range(SETTINGS.max_fix_attempts):
        try:
            fix = chat_json(
                model=SETTINGS.workhorse_model, system=SYSTEM, user=user,
                schema=FixProposal, num_ctx=SETTINGS.workhorse_num_ctx, temperature=0.1,
                trace=trace, kind="fixer",
            )
            break
        except Exception as exc:
            last_error = exc
    else:
        raise ValueError(f"fix generation failed after {SETTINGS.max_fix_attempts} attempts: {last_error}")
    # Sanitize: strip markdown fences if the model added them
    fc = fix.full_content
    if fc.startswith("```"):
        fc = fc.split("\n", 1)[1] if "\n" in fc else fc
        fc = fc.removesuffix("```")
        fc = fc.removesuffix("\n")
        fix.full_content = fc
    return fix
