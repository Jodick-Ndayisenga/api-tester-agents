# API Tester

API Tester is a Python command-line tool that turns an endpoint specification into HTTP contract tests. When a test fails, it can use local Ollama models to diagnose the failure, propose a source-code fix, review that fix, verify it in an isolated Git worktree, and commit an approved change to a separate branch.

The complete, file-by-file documentation is in [docs/PROJECT_GUIDE.md](docs/PROJECT_GUIDE.md).

## Quick start

```bash
source .venv/bin/activate
ollama serve
ollama pull qwen2.5-coder:14b
ollama pull deepseek-r1:14b
ollama create qwen-tester -f Modelfile.qwen14
ollama create r1-tester -f Modelfile.r1
api-tester smoke
api-tester run --spec examples/endpoints.yaml --base-url http://localhost:8000
```

The target API at `http://localhost:8000` must already be running. Reports are written to `reports/`, which is intentionally ignored by Git.

## Main commands

```bash
api-tester run --spec SPEC --base-url URL
api-tester run --spec SPEC --base-url URL --auth
api-tester run --spec SPEC --base-url URL --source PATH --fix
api-tester run --spec SPEC --base-url URL --source PATH --fix --start-cmd 'node src/server.js'
api-tester run --spec SPEC --base-url URL --source PATH --fix --start-cmd 'node src/server.js' --auto-approve
api-tester smoke
```

Use `--fix` only when `--source` points to a Git worktree/repository. The fixer does not edit the original checkout directly: it creates `.worktrees/`, applies a guarded full-file proposal, optionally verifies the API, asks the reviewer model for approval, and commits to an `ai-fix/...` branch.
