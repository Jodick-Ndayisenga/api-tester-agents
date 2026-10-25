from __future__ import annotations

import difflib
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from .config import SETTINGS


class PatchRejected(Exception):
    pass

def _git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(repo), *args],
                          capture_output=True, text=True, check=check)

def is_git_repo(path: Path) -> bool:
    r = subprocess.run(["git", "-C", str(path), "rev-parse", "--is-inside-work-tree"],
                       capture_output=True, text=True)
    return r.returncode == 0 and r.stdout.strip() == "true"

def create_worktree(repo: Path, name: str, base_branch: str = "HEAD") -> tuple[Path, str]:
    """Create a fresh worktree + branch. Never reuses stale state."""
    import uuid
    unique = uuid.uuid4().hex[:6]
    branch = f"ai-fix/{name}-{unique}"
    wt_root = repo / ".worktrees"
    wt_root.mkdir(exist_ok=True)
    wt_path = wt_root / f"{name}-{unique}"
    _git(repo, "worktree", "add", "-b", branch, str(wt_path), base_branch)
    return wt_path, branch

def remove_worktree(repo: Path, wt_path: Path, branch: str, keep_branch: bool = True) -> None:
    _git(repo, "worktree", "remove", "--force", str(wt_path), check=False)
    if not keep_branch:
        _git(repo, "branch", "-D", branch, check=False)

def _count_diff_lines(diff: str) -> int:
    return sum(1 for line in diff.splitlines()
               if line.startswith(("+", "-")) and not line.startswith(("+++", "---")))

def validate_patch_shape(diff: str, file_path: str) -> None:
    lines = _count_diff_lines(diff)
    if lines > SETTINGS.max_diff_lines:
        raise PatchRejected(f"Diff too large: {lines} > {SETTINGS.max_diff_lines}")
    if f"a/{file_path}" not in diff or f"b/{file_path}" not in diff:
        raise PatchRejected(f"Diff must reference a/{file_path} and b/{file_path}")

def apply_patch(worktree: Path, diff: str) -> None:
    with tempfile.NamedTemporaryFile("w", suffix=".patch", delete=False) as f:
        f.write(diff if diff.endswith("\n") else diff + "\n")
        patch_file = f.name
    try:
        r = subprocess.run(
            ["git", "-C", str(worktree), "apply", "--check", "-p1", patch_file],
            capture_output=True, text=True,
        )
        if r.returncode != 0:
            raise PatchRejected(f"Patch does not apply: {r.stderr.strip()}")
        subprocess.run(["git", "-C", str(worktree), "apply", "-p1", patch_file],
                       check=True, capture_output=True, text=True)
    finally:
        Path(patch_file).unlink(missing_ok=True)

def commit_patch(worktree: Path, message: str, files: list[str]) -> str:
    _git(worktree, "add", *files)
    _git(worktree, "commit", "-m", message)
    return _git(worktree, "rev-parse", "HEAD").stdout.strip()

def discard_patch(worktree: Path, repo: Path) -> None:
    """Remove worktree + delete its branch entirely. Leaves no residue."""
    branch = ""
    try:
        r = _git(worktree, "rev-parse", "--abbrev-ref", "HEAD", check=False)
        branch = r.stdout.strip()
    except Exception:
        pass
    _git(repo, "worktree", "remove", "--force", str(worktree), check=False)
    if branch and branch.startswith("ai-fix/"):
        _git(repo, "branch", "-D", branch, check=False)

def compute_diff(old: str, new: str, rel_path: str) -> str:
    old_lines = old.splitlines(keepends=True)
    new_lines = new.splitlines(keepends=True)
    return "".join(difflib.unified_diff(
        old_lines, new_lines,
        fromfile=f"a/{rel_path}", tofile=f"b/{rel_path}",
    ))

def _normalize_newlines(text: str) -> str:
    if text and not text.endswith("\n"):
        text += "\n"
    return text

def _sanity_check_full_content(old: str, new: str) -> None:
    if not old.strip():
        return
    if len(new) < len(old) * 0.7:
        pct = (1 - len(new) / len(old)) * 100
        raise PatchRejected(f"New content is {pct:.0f}% shorter than original — likely truncated")
    def imports(text: str) -> set[str]:
        pats = [
            r"^\s*import\s+.+$",
            r"^\s*from\s+\S+\s+import\s+.+$",
            r"^\s*(?:const|let|var)\s+\w+\s*=\s*require\([^)]+\)\s*;?$",
        ]
        out: set[str] = set()
        for pat in pats:
            for m in re.finditer(pat, text, re.MULTILINE):
                out.add(m.group(0).strip())
        return out
    missing = imports(old) - imports(new)
    if missing:
        raise PatchRejected(f"New content dropped import(s): {sorted(missing)}")

def _syntax_check(target: Path) -> None:
    suffix = target.suffix.lower()
    try:
        if suffix in (".js", ".cjs", ".mjs"):
            r = subprocess.run(["node", "--check", str(target)],
                               capture_output=True, text=True)
            if r.returncode != 0:
                raise PatchRejected(f"JS syntax error: {r.stderr.strip()[:300]}")
        elif suffix == ".py":
            r = subprocess.run([sys.executable, "-m", "py_compile", str(target)],
                               capture_output=True, text=True)
            if r.returncode != 0:
                raise PatchRejected(f"Python syntax error: {r.stderr.strip()[:300]}")
    except FileNotFoundError:
        pass  # node/python missing — skip check

def apply_full_file(worktree: Path, target_rel: str, new_content: str) -> str:
    """Write new_content to worktree/target_rel (repo-relative path).

    target_rel is the path relative to the *worktree root*, i.e. it already
    includes the source-dir prefix from --source. Example: if --source is
    <repo>/src and the failing file is server.js, target_rel = "src/server.js".
    """
    root = worktree.resolve()
    target = (worktree / target_rel).resolve()
    if target != root and root not in target.parents:
        raise PatchRejected(f"Target path escapes worktree: {target_rel!r}")
    if not target.is_file():
        raise PatchRejected(
            f"Target file does not exist in worktree: {target} "
            f"(target_rel={target_rel!r}). Refusing to create a new file."
        )
    old = target.read_text()
    new_content = _normalize_newlines(new_content)
    old_norm = _normalize_newlines(old)
    if old_norm == new_content:
        raise PatchRejected("Proposed content is identical to current file — no fix produced")

    _sanity_check_full_content(old_norm, new_content)
    diff = compute_diff(old_norm, new_content, target_rel)
    line_count = _count_diff_lines(diff)
    if line_count > SETTINGS.max_diff_lines:
        raise PatchRejected(f"Diff too large: {line_count} lines (max {SETTINGS.max_diff_lines})")

    target.write_text(new_content)
    _syntax_check(target)
    return diff
