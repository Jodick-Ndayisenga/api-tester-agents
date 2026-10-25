from __future__ import annotations

from .config import SETTINGS
from .llm import chat_json
from .schemas import Diagnosis, FixProposal, Verdict

SYSTEM = """You are a strict code reviewer.

You receive a diagnosis, a unified diff (computed by the harness from the model's
proposed full file), and the post-fix test status.

Approve ONLY if:
1. The diff plausibly addresses the diagnosed root cause.
2. The diff is minimal with no unrelated changes.
3. No obvious new bugs (null deref, missing import, wrong type, syntax error).
4. If the post-fix test PASSED, prefer approval unless the diff is suspicious.
5. If the post-fix test FAILED, reject.
6. If the post-fix test status is UNKNOWN (passed=None), judge on diff quality alone.
"""

def review(diag: Diagnosis, fix: FixProposal, diff_text: str,
           test_passed: bool | None, test_output: str, trace=None) -> Verdict:
    user = (
        f"## Diagnosis\n{diag.model_dump_json(indent=2)}\n\n"
        f"## Proposed fix (file: {fix.file_path}, risk: {fix.risk})\n"
        f"```diff\n{diff_text}\n```\n\n"
        f"## Explanation\n{fix.explanation}\n\n"
        f"## Test result\npassed={test_passed}\n```\n{test_output[:2000]}\n```"
    )
    return chat_json(
        model=SETTINGS.workhorse_model, system=SYSTEM, user=user,
        schema=Verdict, num_ctx=SETTINGS.workhorse_num_ctx, temperature=0.1,
        trace=trace, kind="reviewer",
    )
