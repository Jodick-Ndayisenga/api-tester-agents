# API Tester: Complete Project Guide

This document is written for two audiences at once. If you are new to APIs, start with the beginner sections and follow the first-run walkthrough. If you already build backend systems, use the detailed sections on request generation, concurrency, OpenAPI interpretation, local LLM contracts, Git safety, CI, and extension points. The goal is that every important behavior is understandable without reading the source code first.

## Table of contents

- [1. What this project is](#1-what-this-project-is)
- [2. What the project does not do](#2-what-the-project-does-not-do)
- [3. Repository layout](#3-repository-layout)
- [4. Requirements](#4-requirements)
  - [4.1 Python](#41-python)
  - [4.2 Python dependencies](#42-python-dependencies)
  - [4.3 Ollama](#43-ollama)
- [5. Installation](#5-installation)
- [6. Configuration](#6-configuration)
  - [Choosing SQLite or PostgreSQL](#choosing-sqlite-or-postgresql)
- [7. Running the target API](#7-running-the-target-api)
- [8. Endpoint specifications](#8-endpoint-specifications)
  - [8.1 YAML format](#81-yaml-format)
  - [8.2 OpenAPI JSON format](#82-openapi-json-format)
- [9. Test generation and HTTP behavior](#9-test-generation-and-http-behavior)
  - [Large specifications: filtering, batching, and resuming](#large-specifications-filtering-batching-and-resuming)
- [10. The end-to-end pipeline](#10-the-end-to-end-pipeline)
  - [10.1 Durable audit database](#101-durable-audit-database)
  - [What is redacted and why](#what-is-redacted-and-why)
  - [Auditing disabled](#auditing-disabled)
- [11. CLI commands and options](#11-cli-commands-and-options)
  - [11.1 `api-tester run`](#111-api-tester-run)
  - [11.2 `api-tester smoke`](#112-api-tester-smoke)
  - [11.3 `api-tester audit-export`](#113-api-tester-audit-export)
- [12. LLM workflow and JSON guarantees](#12-llm-workflow-and-json-guarantees)
  - [Analyzer](#analyzer)
  - [Fixer](#fixer)
  - [Reviewer](#reviewer)
- [13. Git and safety behavior](#13-git-and-safety-behavior)
- [14. Reports](#14-reports)
  - [Terminal output and Rich](#terminal-output-and-rich)
- [15. File-by-file reference](#15-file-by-file-reference)
- [16. Common operating procedures](#16-common-operating-procedures)
- [17. Troubleshooting](#17-troubleshooting)
- [18. Current limitations and maintenance notes](#18-current-limitations-and-maintenance-notes)
- [19. Recommended development workflow](#19-recommended-development-workflow)
- [20. Beginner concepts: the vocabulary you need](#20-beginner-concepts-the-vocabulary-you-need)
- [21. First-run walkthrough for a complete beginner](#21-first-run-walkthrough-for-a-complete-beginner)
  - [Step 1: enter the project](#step-1-enter-the-project)
  - [Step 2: create and activate an isolated Python environment](#step-2-create-and-activate-an-isolated-python-environment)
  - [Step 3: install the package and development tools](#step-3-install-the-package-and-development-tools)
  - [Step 4: check the command exists](#step-4-check-the-command-exists)
  - [Step 5: prepare Ollama](#step-5-prepare-ollama)
  - [Step 6: start the target API](#step-6-start-the-target-api)
  - [Step 7: run the example specification](#step-7-run-the-example-specification)
  - [Step 8: read the report](#step-8-read-the-report)
- [22. A concrete request lifecycle](#22-a-concrete-request-lifecycle)
- [23. Designing good specifications](#23-designing-good-specifications)
- [24. Concurrency, idempotency, and retries in depth](#24-concurrency-idempotency-and-retries-in-depth)
- [25. Authentication behavior in depth](#25-authentication-behavior-in-depth)
- [26. Understanding a failure report](#26-understanding-a-failure-report)
- [27. CI usage](#27-ci-usage)
- [28. Developer workflow for changing this project](#28-developer-workflow-for-changing-this-project)
- [29. Verification checklist before calling a release stable](#29-verification-checklist-before-calling-a-release-stable)
- [30. Glossary of implementation terms](#30-glossary-of-implementation-terms)

## 1. What this project is

API Tester is a contract-testing and assisted-repair tool for HTTP APIs. Its basic job is:

1. Read endpoint definitions from YAML or OpenAPI JSON.
2. Turn each endpoint into one or more test cases.
3. Send those cases asynchronously to a running API.
4. Compare actual HTTP status codes with the statuses declared by the specification.
5. Save a Markdown report.
6. For failures, optionally send the failure and selected source files to a local analyzer model.
7. Optionally ask a workhorse model for a complete replacement of one source file.
8. Apply that replacement in an isolated Git worktree, enforce safety checks, optionally start the patched API, and rerun the failing request.
9. Ask a reviewer model whether the change is acceptable.
10. If approved, commit it to a new `ai-fix/...` branch; otherwise remove the temporary worktree and branch.

The project is deliberately local-model oriented. It uses the Ollama Python client and does not call a hosted LLM API in the code shown here.

## 2. What the project does not do

- It does not start the original API for the initial test run. You must start the target service yourself.
- It does not discover routes from a live server. Discovery comes from YAML or OpenAPI JSON.
- It primarily asserts status codes. It does not currently assert response schemas, response bodies, headers, latency budgets, or database state.
- It does not authenticate by itself. It only reuses headers declared in the endpoint specification and, when `--auth` is enabled, creates a request with the `Authorization` header removed.
- It does not merge branches or push commits.
- It retries failed idempotent HTTP requests when configured, but does not retry mutating requests.
- It does not yet assert response schemas, response bodies, headers, latency budgets, or database state; the current contract assertion is primarily the HTTP status code.

## 3. Repository layout

```text
.
├── api_tester/                 Python package
│   ├── __init__.py             Package version
│   ├── analyzer.py             Failure analysis and source selection
│   ├── cli.py                  Typer command-line interface
│   ├── config.py               Environment-backed settings
│   ├── discover.py             YAML/OpenAPI loading
│   ├── fixer.py                Full-file fix proposal generation
│   ├── llm.py                  Ollama calls and JSON normalization
│   ├── orchestrator.py         End-to-end pipeline
│   ├── report.py               Markdown report writer
│   ├── terminal.py             Shared Rich console and traceback setup
│   ├── reviewer.py             Proposed-fix review
│   ├── runner.py               Test-case generation and HTTP execution
│   ├── safety.py               Git worktrees, diff guards, syntax checks
│   └── schemas.py              Pydantic data models
├── examples/
│   ├── endpoints.yaml          Hand-authored endpoint specification
│   └── openapi.json             OpenAPI 3 sample specification
├── compose.yaml                 Optional PostgreSQL audit database
├── reports/                    Generated reports; ignored by Git
├── Modelfile.qwen14            Ollama workhorse model definition
├── Modelfile.r1                Ollama analyzer model definition
├── pyproject.toml              Package metadata and dependencies
├── .env.example                Supported environment variables
├── .env                        Local configuration; ignored by Git
└── .gitignore                  Ignored generated/local files
```

`api_tester.egg-info/` is generated package metadata. It records the installed name, dependencies, console entry point, and source list; normally you do not edit it by hand.

## 4. Requirements

### 4.1 Python

`pyproject.toml` requires Python 3.11 or newer. The project uses modern type syntax such as `dict[str, Any] | None`, so older Python versions are not supported.

### 4.2 Python dependencies

The declared runtime dependencies are:

| Package | Use |
|---|---|
| `typer` | CLI commands and options |
| `rich` | Colored output and progress indicators |
| `httpx` | Async HTTP requests |
| `pydantic` | Runtime validation of endpoint, result, diagnosis, fix, and verdict data |
| `pyyaml` | YAML endpoint specifications |
| `ollama` | Calls to the local Ollama service |
| `python-dotenv` | Loads `.env` before settings are created |
| `sqlalchemy[asyncio]` | Database models and asynchronous persistence |
| `aiosqlite` | Default local SQLite database driver |
| `asyncpg` | PostgreSQL driver for Docker/deployment |

### 4.3 Ollama

Install and start Ollama using the instructions for your operating system. Then download the base models and create the two custom model names expected by the default configuration:

```bash
ollama serve
ollama pull qwen2.5-coder:14b
ollama pull deepseek-r1:14b
ollama create qwen-tester -f Modelfile.qwen14
ollama create r1-tester -f Modelfile.r1
ollama list
```

The model files mean:

- `Modelfile.qwen14` is based on `qwen2.5-coder:14b`, uses a 4,096-token context, temperature `0.15`, and `top_p 0.9`.
- `Modelfile.r1` is based on `deepseek-r1:14b`, uses an 8,192-token context, and temperature `0.3`.

`api-tester smoke` checks that the two configured custom model names can be found. It does not test a complete diagnosis or fix.

## 5. Installation

From the project root:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e '.[dev]'
```

The editable install exposes the console command `api-tester`, which is wired by `pyproject.toml` to `api_tester.cli:app`.

The first audited run creates `api_tester.db` automatically when the default SQLite URL is used. That file is ignored by Git. No separate migration command is required for a new local database; SQLAlchemy creates the tables on startup.

Useful checks:

```bash
python --version
python -m pip show api-tester
api-tester --help
api-tester run --help
api-tester smoke
python -m compileall -q api_tester
```

If the executable is not on `PATH`, use the module through the virtual environment or reinstall:

```bash
.venv/bin/api-tester --help
.venv/bin/python -m pip install -e '.[dev]'
```

## 6. Configuration

`api_tester/config.py` calls `load_dotenv()` as soon as the module is imported, then creates one immutable `SETTINGS` object. Values are read once per process; changing `.env` while a command is running has no effect.

Copy the example file if desired:

```bash
cp .env.example .env
```

Supported variables:

| Variable | Default | Meaning |
|---|---:|---|
| `ANALYZER_MODEL` | `r1-tester` | Ollama model used by `analyzer.py` |
| `WORKHORSE_MODEL` | `qwen-tester` | Ollama model used by fixer and reviewer |
| `ANALYZER_NUM_CTX` | `8192` | Analyzer context size passed to Ollama |
| `WORKHORSE_NUM_CTX` | `4096` | Fixer/reviewer context size |
| `MAX_FILE_CHARS` | `60000` | Maximum source text sent to an LLM and maximum source text read for a proposal |
| `MAX_DIFF_LINES` | `200` | Maximum added/removed diff lines for a proposed full-file change |
| `MAX_FILES_TOUCHED` | `5` | Maximum source files included in analyzer context |
| `MAX_FIX_ATTEMPTS` | `3` | Maximum complete-file proposal attempts |
| `HTTP_TIMEOUT` | `15.0` | Timeout for initial HTTP requests, in seconds |
| `HTTP_RETRIES` | `1` | Retries for failed idempotent requests |
| `CONCURRENCY` | `4` | Maximum concurrent read-only requests |
| `BATCH_SIZE` | `100` | Number of discovered endpoints in one resumable execution batch |
| `VERIFY_PORT_OFFSET` | `1000` | Added to the original port for post-fix verification |
| `VERIFY_STARTUP_TIMEOUT` | `20.0` | How long to wait for the patched service to answer `/health` |
| `VERIFY_TIMEOUT` | `30.0` | Timeout for the post-fix request |
| `DATABASE_URL` | `sqlite+aiosqlite:///./api_tester.db` | Audit database connection string |
| `AUDIT_ENABLED` | `true` | Enable durable audit persistence |
| `AUDIT_MAX_CHARS` | `200000` | Maximum stored length for one text payload after redaction |

Values are parsed with `int()` or `float()`. Invalid values cause an import-time error, so keep numeric variables numeric.

### Choosing SQLite or PostgreSQL

SQLite is the easiest option for one developer and one process:

```dotenv
DATABASE_URL=sqlite+aiosqlite:///./api_tester.db
```

For a Dockerized PostgreSQL database:

```bash
docker compose up -d audit-db
```

Use this connection string in `.env`:

```dotenv
DATABASE_URL=postgresql+asyncpg://api_tester:api_tester_local_password@localhost:5432/api_tester
```

Check the database container:

```bash
docker compose ps
docker compose logs audit-db
```

Stop the container without deleting its data:

```bash
docker compose stop audit-db
```

Remove the container and its persistent volume only when you intentionally want to erase local audit history:

```bash
docker compose down
docker compose down -v
```

The second command is destructive for the local PostgreSQL volume. Export important runs first.

## 7. Running the target API

Start the API under test separately. For example, a Node service might be started with:

```bash
PORT=8000 HOST=127.0.0.1 node src/server.js
```

Confirm it responds before running the tester:

```bash
curl -i http://localhost:8000/health
```

The initial run uses the exact `--base-url` supplied to the CLI. The URL is passed to `httpx.AsyncClient(base_url=...)`; endpoint paths should therefore normally begin with `/`.

## 8. Endpoint specifications

### 8.1 YAML format

YAML must contain an `endpoints` list. Each item maps directly to the `Endpoint` Pydantic model:

```yaml
endpoints:
  - method: GET
    path: /health
    expect_status: [200]
  - method: POST
    path: /users
    headers:
      Authorization: Bearer test-token
      X-Tenant: demo
    body:
      name: Test User
      email: test@example.com
    expect_status: [200, 201]
  - method: GET
    path: /users/{id}
    path_params:
      id: 1
    expect_status: [200, 404]
```

Fields:

- `method`: HTTP method. The runner has special behavior for `POST`, `PUT`, and `PATCH`.
- `path`: Relative endpoint path.
- `body`: JSON body for the happy path.
- `headers`: Headers sent on generated cases.
- `query`: Query-string parameters sent with the request, for example `?page=2`.
- `expect_status`: Accepted status codes for the happy path; default is `[200]`.
- `path_params`: Replacements for `{id}` and `:id` syntax.
- `required_fields`: Used to decide whether PUT/PATCH invalid-body cases should be generated.

### 8.2 OpenAPI JSON format

The loader reads `paths`, supports only `get`, `post`, `put`, `patch`, and `delete`, and creates one `Endpoint` for each supported operation. It extracts every 2xx response code as a happy-path success code. OpenAPI 3 JSON and the common Swagger 2.0 JSON shape are accepted because both describe operations under `paths`; Swagger 2 body parameters are converted into the same normalized request-body representation.

For JSON request bodies, it recursively creates a sample from basic schema types. Examples, defaults, and the first enum value are preferred when present:

- object: one value for each property;
- string: `example` or `"test"`;
- integer: `example` or `1`;
- number: `example` or `1.0`;
- boolean: `true`;
- array: one generated item;
- unsupported or missing type: `null`.

The loader reads required request-body property names into `required_fields`, extracts required path/query/header parameters, and supports local `#/...` schema references. Required path parameters without an example, default, or `x-test.path_params` value cause a clear specification error instead of silently creating a test for the wrong resource.

OpenAPI operations can add project-specific cases through `x-test`:

```json
{
  "get": {
    "x-test": {
      "path_params": {"id": 999},
      "extra_cases": [
        {
          "method": "GET",
          "path": "/users/999",
          "expect_status": [404]
        }
      ]
    },
    "responses": {"200": {"description": "OK"}}
  }
}
```

An `extra_cases` item is passed directly to `Endpoint(**extra)`, so it must use `Endpoint` field names. For an OpenAPI path such as `/users/{id}`, provide an example, default, or `x-test.path_params`; otherwise loading stops with a missing-parameter error rather than sending a misleading request to `/users/1`.

Swagger 2.0 body example:

```json
{
  "swagger": "2.0",
  "paths": {
    "/users": {
      "post": {
        "parameters": [
          {
            "name": "user",
            "in": "body",
            "required": true,
            "schema": {
              "type": "object",
              "properties": {"name": {"type": "string", "example": "Ada"}},
              "required": ["name"]
            }
          }
        ],
        "responses": {"201": {"description": "Created"}}
      }
    }
  }
}
```

The redacted Swagger/OpenAPI document is stored in `audit_runs.raw_spec`, and its SHA-256 digest is calculated from the original input and stored in `audit_runs.spec_sha256`. This lets an auditor prove which specification version produced a run without requiring the database to retain credentials embedded in the document.

## 9. Test generation and HTTP behavior

For every endpoint, `runner.py` generates a happy-path case. It then adds cases according to the method:

| Condition | Generated case | Expected statuses |
|---|---|---|
| `--auth` enabled | Same request without an `Authorization` header | `[401, 403]` |
| `POST` | Empty JSON object | `[400, 422]` |
| `POST` | Malformed JSON bytes `{not valid json` | `[400, 422]` |
| `PUT`/`PATCH` and `required_fields` is non-empty | Empty JSON object | `[400, 422]` |
| `PUT`/`PATCH` and `required_fields` is non-empty | Malformed JSON | `[400, 422]` |

The path substitution algorithm first replaces configured `{name}` and `:name` values. YAML specifications with unresolved placeholders use the runner fallback value `1`; OpenAPI path parameters are validated during discovery and should normally be resolved before reaching the runner. Path values are not URL-encoded automatically, so values containing `/`, spaces, or reserved characters should be encoded by the specification author.

Read-only requests are executed concurrently with bounded workers; the default concurrency is 4. Mutating requests are serialized to avoid test interference. `GET` and `DELETE` send headers and query parameters. `POST`, `PUT`, and `PATCH` send JSON except for the malformed-JSON case, which sends raw invalid bytes and forces `Content-Type: application/json`. Failed idempotent requests can be retried using `HTTP_RETRIES` or the CLI `--retries` option.

### Large specifications: filtering, batching, and resuming

The complete specification is parsed once, but the runner never submits every route as one giant task set. Endpoints are divided into batches (100 by default), and each batch has a bounded request worker pool. This limits memory use, keeps progress visible, and prevents a huge API from overwhelming the target service.

Use filters before batching when you want to test only part of a contract:

```bash
api-tester run -s openapi.yaml -u http://localhost:8000 \
  --include-prefix /v1/admin \
  --exclude-prefix /v1/admin/internal \
  --methods GET,POST \
  --tags users,accounts \
  --batch-size 50
```

`--include-prefix` keeps matching paths, `--exclude-prefix` removes matching paths, `--methods` is a comma-separated case-insensitive method allow-list, and `--tags` keeps OpenAPI/Swagger operations having at least one selected tag. Filters are applied during discovery, so excluded routes do not create audit endpoint or test-case rows.

Every audited batch has a number, source index, endpoint count, status, result count, and failure count. If a process stops after a completed batch, continue it with the printed run UUID:

```bash
api-tester run -s openapi.yaml -u http://localhost:8000 \
  --batch-size 50 --stop-after-failures 10
api-tester run -s openapi.yaml -u http://localhost:8000 \
  --batch-size 50 --resume RUN_UUID
```

Resume is intentionally audit-backed. The specification must still have the same SHA-256 hash; otherwise the command stops rather than silently mixing results from different contracts. Completed batches are skipped, while incomplete batches are executed again. Keep the same filters and batch size when resuming so batch numbers refer to the same endpoint ordering. `--stop-after-failures` is useful for staged or incident-focused runs and counts failures across the current invocation.

Each result records the request case, pass/fail state, status if a response arrived, a parsed JSON body or up to 2,000 characters of text, an error string, and elapsed milliseconds. A network exception becomes a failed result rather than stopping the complete run. Only transport and timeout failures are retried, and only when the case is marked idempotent.

## 10. The end-to-end pipeline

The main function is `orchestrator.run_pipeline()`:

```text
spec file
   │
   ▼
load_endpoints ──► Endpoint objects
   │
   ▼
run_all ─────────► TestResult objects
   │
   ├── all pass ─► RunReport ─► Markdown report
   │
   └── failures
          │
          ▼
       analyze each failure with analyzer model
          │
          ├── no --fix ─► report diagnoses
          │
          └── --fix + Git source
                 │
                 ▼
              propose complete file with workhorse model
                 │
                 ▼
              create isolated worktree and apply guarded content
                 │
                 ├── optional --start-cmd verification on offset port
                 │
                 ▼
              reviewer model
                 │
                 ├── reject/failure ─► discard worktree and branch
                 │
                 └── approve ─► optional human approval ─► commit branch
```

The CLI always writes a report after `run_pipeline()` returns, including when the fix phase is skipped or a particular failure cannot be diagnosed. By default, it then exits with status `1` if any tests failed, which makes it suitable for CI. Use `--allow-failures` when you want a report without a failing process status.

When auditing is enabled, the CLI also prints an `Audit run:` UUID. Keep that UUID with the Markdown report; it is the primary key for retrieving every database record belonging to that run.

## 10.1 Durable audit database

The Markdown report is a summary for people. The database is the detailed audit trail for machines, investigations, and historical comparisons. A run is created before HTTP execution and receives a UUID. Every later row carries that UUID directly or through its case ID.

The database contains these logical records:

| Table | What it records |
|---|---|
| `audit_runs` | Base URL, specification path and redacted raw snapshot, exact specification hash, effective configuration and invocation options, start/end state, and totals. |
| `audit_endpoints` | Every normalized endpoint loaded from YAML, OpenAPI, or Swagger. |
| `audit_batches` | Resumable execution units: batch number, endpoint range, status, result count, and failure count. |
| `audit_cases` | Every generated concrete case, including happy, auth, empty-body, and malformed-JSON cases. |
| `audit_attempts` | Every HTTP attempt, including retries, request data, response data, status, error, and duration. |
| `audit_diagnoses` | Analyzer model output for a failed case. |
| `audit_source_context` | Source files shown to the analyzer, redacted content, and original-content hash. |
| `audit_llm_interactions` | Model name, role (`analyzer`, `fixer`, or `reviewer`), prompts, responses, validation errors, attempts, and latency. |
| `audit_fix_proposals` | Proposed file path, redacted full content, content hash, explanation, risk, and computed diff. |
| `audit_reviews` | Reviewer approval, reasoning, and concerns. |
| `audit_verifications` | Post-fix status and verification output. |
| `audit_events` | Append-style lifecycle events such as run start, test completion, diagnosis completion, fix proposal, and run finish. |

The relationships are:

```text
audit_runs
├── audit_endpoints
├── audit_batches
├── audit_cases
│   ├── audit_attempts
│   ├── audit_diagnoses
│   ├── audit_source_context
│   ├── audit_fix_proposals
│   ├── audit_reviews
│   └── audit_verifications
├── audit_llm_interactions
└── audit_events
```

The implementation uses SQLAlchemy async sessions. SQLite and PostgreSQL use the same models and persistence methods, so changing `DATABASE_URL` does not change what is recorded. Tables are created automatically on startup for this initial version. For a production deployment, add versioned migrations before changing table definitions in place.

### What is redacted and why

Audit is designed to preserve evidence without becoming a credential store. Before persistence, it redacts common authorization, bearer, API-key, secret, password, token, and private-key patterns. Large text fields are bounded by `AUDIT_MAX_CHARS`. The fix and source records retain SHA-256 hashes so you can detect which exact content was involved without necessarily storing the complete unredacted secret-bearing text.

The redaction is pattern-based, not magic. Do not point `--source` at a broad home directory or a production checkout containing unrelated secrets. Use a narrow source root and a test environment.

### Auditing disabled

Use this only when database persistence is unavailable or intentionally out of scope:

```bash
api-tester run ... --no-audit
```

With auditing disabled, the normal Markdown report and HTTP pipeline still work, but no run UUID, database rows, LLM audit entries, or durable lifecycle records are created.

## 11. CLI commands and options

The installed command is named `api-tester`. Every command accepts `--help`; this prints the options for that command without running a test:

```bash
api-tester --help
api-tester run --help
api-tester smoke --help
api-tester audit-export --help
```

The short forms `-s` and `-u` are aliases for `--spec` and `--base-url`. Boolean options do not take `true` or `false` after them: write `--auth` to enable authentication cases, `--no-audit` to disable auditing, or `--allow-failures` to change the exit-code policy. A path such as `SPEC`, `PATH`, or `URL` in an example is a placeholder that must be replaced with a real value.

### 11.1 `api-tester run`

```bash
api-tester run \
  --spec examples/endpoints.yaml \
  --base-url http://localhost:8000 \
  --report-dir reports
```

Options:

| Option | Required/default | Meaning and accepted value |
|---|---|---|
| `--spec`, `-s` | Required | Existing `.yaml`, `.yml`, or `.json` endpoint/OpenAPI/Swagger file. Typer checks that the path exists. |
| `--base-url`, `-u` | Required | API origin, such as `http://localhost:8000`. Endpoint paths are appended to this URL. Do not include an endpoint path here. |
| `--source` | Omitted | Source directory used for analyzer context. It is needed for `--fix`; if omitted, the fix stage is skipped. When supplied for fixes, it must be inside a Git repository. |
| `--auth` | Disabled | Adds missing-authorization negative cases. It does not create credentials or log in. |
| `--fix` | Disabled | Enables diagnosis, fix proposal, isolated worktree, review, optional verification, and commit stages. Without it, failures are reported only. |
| `--auto-approve` | Disabled | Removes the human commit prompt after reviewer approval. It never bypasses the reviewer and should be used carefully in CI. |
| `--fail-on-test-failure` / `--allow-failures` | Fail by default | Controls the process exit code. Both write a report; the first returns `1` when cases fail, while the second returns `0` for report-collection jobs. |
| `--start-cmd` | Omitted | Shell command used to start the patched API in a temporary worktree. Enables post-fix verification; the process receives `PORT` and `HOST`. Quote commands containing spaces. |
| `--report-dir` | `reports` | Directory where the Markdown report is written. It is created if necessary. |
| `--concurrency` | `CONCURRENCY` (`4`) | Positive integer for concurrent read-only request workers. Mutating requests are still serialized. |
| `--retries` | `HTTP_RETRIES` (`1`) | Non-negative integer. Retries only idempotent cases after timeout/transport failures, not ordinary HTTP error statuses. |
| `--batch-size` | `BATCH_SIZE` (`100`) | Positive number of discovered endpoints per audit/resume batch. Smaller values reduce restart cost and memory pressure. |
| `--include-prefix` | Omitted | Keeps only paths beginning with the supplied string, such as `/v1/users`. |
| `--exclude-prefix` | Omitted | Removes paths beginning with the supplied string, such as `/internal`. |
| `--methods` | Omitted | Comma-separated allow-list, case-insensitive: `GET,POST,PATCH`. Empty means all supported methods. |
| `--tags` | Omitted | Comma-separated OpenAPI/Swagger tag allow-list. An operation is kept when it has at least one selected tag. |
| `--stop-after-failures` | Omitted | Positive integer. Stops after that many failed generated cases, leaving completed batches available for `--resume`. |
| `--resume` | Omitted | Existing audit-run UUID. Requires auditing, the same specification bytes/hash, base URL, route filters, and batch-size choice. Completed batches are skipped. |
| `--database-url` | `DATABASE_URL` | SQLAlchemy async connection URL, for example `sqlite+aiosqlite:///./api_tester.db` or the PostgreSQL URL shown earlier. |
| `--audit` / `--no-audit` | Audit enabled | Turns durable database recording on or off for this invocation. `--resume` cannot be used with `--no-audit`. |

Numeric options reject invalid values before execution: `--concurrency`, `--batch-size`, and `--stop-after-failures` must be at least 1; `--retries` may be 0 or greater. Options that are omitted inherit their environment-backed defaults where documented above.

Safe diagnosis-only run:

```bash
api-tester run -s examples/endpoints.yaml -u http://localhost:8000
```

Diagnosis with source context but no modifications:

```bash
api-tester run -s examples/endpoints.yaml -u http://localhost:8000 --source /path/to/api
```

Interactive fix workflow:

```bash
api-tester run \
  -s examples/endpoints.yaml \
  -u http://localhost:8000 \
  --source /path/to/api \
  --fix \
  --start-cmd 'node src/server.js'
```

Non-interactive commit workflow:

```bash
api-tester run \
  -s examples/endpoints.yaml \
  -u http://localhost:8000 \
  --source /path/to/api \
  --fix \
  --start-cmd 'node src/server.js' \
  --auto-approve
```

For `--start-cmd`, the process runs with its working directory set to the temporary worktree and environment variables `PORT` and `HOST` set. If the original URL uses port 8000 and the default offset is 1000, the verification server is expected at port 9000. The readiness check polls `GET /health`.

The command returns these practical outcomes:

| Situation | Report written? | Exit status |
|---|---:|---:|
| Every generated test passes | Yes | `0` |
| One or more generated tests fail | Yes | `1` by default |
| One or more tests fail with `--allow-failures` | Yes | `0` |
| Invalid CLI input or invalid specification | Usually no | Non-zero |

This distinction matters in automation: a Markdown report is useful for diagnosis, but the exit status is what normally tells a CI job whether to stop.

### 11.2 `api-tester smoke`

```bash
api-tester smoke
```

This calls `ollama.show()` for both configured model names and exits with status 1 if either model is unavailable.

`smoke` has no project-specific options. It reads `ANALYZER_MODEL` and `WORKHORSE_MODEL` from `.env`/the environment, so change those variables when using different Ollama model names. It does not contact the target API, inspect a specification, or run a test case.

### 11.3 `api-tester audit-export`

Export every stored row for one run into one JSON document:

```bash
api-tester audit-export \
  --run-id 7b2c1b6f-2d22-4e6f-9f59-3f9f1f16b9c0 \
  --output audit-7b2c1b6f.json
```

The command reads the database configured by `DATABASE_URL`. To export from another database:

```bash
api-tester audit-export \
  --database-url postgresql+asyncpg://api_tester:api_tester_local_password@localhost:5432/api_tester \
  --run-id RUN_ID \
  --output audit.json
```

The export contains named arrays for runs, endpoints, cases, attempts, diagnoses, source context, LLM interactions, fix proposals, reviews, verifications, and lifecycle events. Stored text is redacted and bounded; hashes remain available to identify the original content without storing an unbounded secret.

Options:

- `--run-id`: required UUID printed by `api-tester run` when auditing is enabled.
- `--output`, `-o`: destination JSON file; defaults to `audit-export.json`. Parent directories should already exist.
- `--database-url`: optional database override. If omitted, `DATABASE_URL` is used.

The export command is read-only with respect to audit records. It creates or checks the database schema while opening the connection, but it does not alter the selected run.

## 12. LLM workflow and JSON guarantees

`llm.chat_json()` sends a system message containing the model's JSON schema and a user message containing the task. It asks Ollama for `format="json"`, extracts the message from either a dictionary response or an Ollama response object, removes `<think>...</think>` and `<thinking>...</thinking>` blocks, uses a JSON decoder that understands braces inside quoted strings, and validates the result with Pydantic.

It allows three attempts by default (`max_retries + 1`, with `max_retries=2`). After a validation error it appends the previous assistant output and a correction request to the conversation. If all attempts fail, it raises `ValueError`.

There is also `chat_text()`, which returns cleaned model text, but the current pipeline uses `chat_json()` for analysis, fixes, and review.

### Analyzer

`analyzer.analyze()` formats the failure with the method, path, expected and actual status, request body, redacted authorization/cookie headers, response excerpt, and error. It searches the source directory for supported source extensions and scores files by endpoint path segments and filename hints such as `controller`, `route`, `handler`, `view`, and `endpoint`. Up to six candidate files are included, further limited by `MAX_FILES_TOUCHED` and `MAX_FILE_CHARS`.

Before source text reaches the model, common credential-shaped values are redacted, including authorization/bearer values, API keys, secrets, passwords, tokens, and private-key blocks. This is a safety layer, not a guarantee that every secret format is detected; keep source roots narrow and review what is sent to the model.

The analyzer is instructed to return a `Diagnosis` and to identify suspected files only from the supplied `### relative/path` headers. Returned paths are normalized and filtered against the files actually shown to the model.

### Fixer

`fixer.propose_fix()` reads one suspected file and asks the workhorse model for a complete replacement. The model must return a `FixProposal` with the relative file path, complete content, explanation, and risk. Markdown fences are removed if the model incorrectly adds them. If the model call fails, the fixer retries up to `MAX_FIX_ATTEMPTS`; each call also has the structured-output retries implemented by `chat_json()`.

The fixer intentionally requests the entire file rather than a model-generated patch. The safety layer computes the actual diff from the old and new content.

### Reviewer

`reviewer.review()` receives the diagnosis, computed unified diff, fix explanation, and post-fix status. Its prompt requires rejection when the post-fix test failed and asks it to reject unrelated changes, obvious bugs, missing imports, or syntax problems. The returned `Verdict` controls whether the temporary change can be committed. A verification status of `None` means verification was unavailable or intentionally skipped; it does not mean the test passed.

## 13. Git and safety behavior

The fix stage requires `--source` to be inside a Git worktree. It creates:

```text
<repo>/.worktrees/fix-000-<random>
branch: ai-fix/fix-000-<random>
```

The worktree starts from `HEAD`. The original checkout is not directly modified.

Before writing a proposed file, `apply_full_file()` checks:

1. The target already exists; the tool refuses to create a new file.
2. The new content is not identical to the old content.
3. A missing final newline is normalized.
4. The new file is not less than 70% of the old file length, which catches likely truncation.
5. Existing import lines were not dropped.
6. The computed diff is no larger than `MAX_DIFF_LINES` changed lines.
7. Python files pass `py_compile` when Python is available.
8. JavaScript files pass `node --check` when Node is available.
9. The resolved target path remains inside the temporary worktree, preventing a malformed relative path or symlink from escaping the isolation boundary.

If verification is enabled, a failed post-fix test always prevents a commit. If verification is unavailable, the reviewer is allowed to judge the diff with an unknown result. Without `--start-cmd`, the code records verification as skipped.

On reviewer rejection, failed verification, fix rejection, or a declined interactive prompt, `discard_patch()` removes the temporary worktree and deletes the temporary `ai-fix/...` branch. On success, `commit_patch()` stages the selected target and creates a commit on the temporary branch. The tool does not merge or push it.

The module also contains lower-level `apply_patch()`, `validate_patch_shape()`, `remove_worktree()`, and `compute_diff()` helpers. The current orchestrator uses `apply_full_file()` and `discard_patch()` instead of the lower-level patch application function.

The verifier redirects the patched server's standard output and standard error so a verbose server cannot fill an unread pipe and hang the tester. It checks that `/health` returns a successful response and detects a server that exits before becoming ready. Startup readiness uses `VERIFY_STARTUP_TIMEOUT`; the post-fix request uses `VERIFY_TIMEOUT`.

## 14. Reports

`report.write_report()` creates the output directory and writes:

```text
reports/report-YYYYMMDD-HHMMSS-microseconds.md
```

The report includes the base URL, generation time, total/passed/failed counts, and for each failure:

- method and path;
- expected and actual statuses;
- execution error;
- diagnosis, category, severity, confidence, suspected files, and fix hint;
- proposed diff and risk;
- reviewer approval, reasoning, and concerns;
- whether the change was applied;
- post-fix verification result;
- branch and commit SHA when committed.

If no failures exist, it writes `_All tests passed._`.

Existing reports in this repository are useful examples of the output format. They are generated artifacts and are excluded by `.gitignore`.

### Terminal output and Rich

Rich is the terminal presentation layer for the application. `api_tester/terminal.py` creates one shared `Console` with automatic terminal detection, markup support, disabled automatic highlighting, and soft wrapping. The CLI installs Rich tracebacks without exposing local variables, which keeps unexpected errors readable without printing sensitive process state.

The shared console is used for model status, success/failure summaries, warnings, fix progress, verification output, commit messages, audit identifiers, and interactive commit prompts. `orchestrator.py` uses Rich `Progress` indicators for batches and diagnosis work. The `--help` screens are provided by Typer/Rich integration.

Rich normally enables colors and styling only when the destination terminal supports them. When output is redirected or captured by CI, Rich degrades to plain text so logs remain readable. Markdown reports and JSON audit exports are intentionally written as files and are not formatted with terminal markup.

## 15. File-by-file reference

### `pyproject.toml`

Defines the package name (`api-tester`), version (`0.1.0`), Python requirement, dependencies, build backend, console script, and package discovery rule. The console entry point is:

```text
api-tester = api_tester.cli:app
```

### `api_tester/__init__.py`

Defines `__version__ = "0.1.0"`. It has no runtime orchestration logic.

### `api_tester/schemas.py`

Defines the Pydantic models:

- `Endpoint`: normalized input endpoint.
- `TestCase`: one concrete request to execute.
- `TestResult`: outcome of one request.
- `Diagnosis`: analyzer output, with constrained category, severity, and confidence.
- `FixProposal`: complete-file fix output.
- `Verdict`: reviewer output.

These models are the contracts between pipeline stages. Pydantic rejects missing required fields and invalid literal values, and constrains `Diagnosis.confidence` to 0 through 1.

### `api_tester/config.py`

Loads `.env`, defines the frozen `Settings` dataclass, parses all environment values, and creates the process-wide `SETTINGS` instance.

### `api_tester/audit.py`

Defines the SQLAlchemy tables and persistence service. `AuditStore.open()` creates an asynchronous database engine and initializes the tables. `start_run()` stores the raw specification, its hash, normalized endpoints, configuration, and a run-start event. `record_results()` stores every generated case and every HTTP attempt, including retries. Other methods store diagnoses, source context, LLM interactions, fixes, reviews, verification, lifecycle events, final status, and complete JSON export. `AuditBridge` schedules database writes safely when synchronous LLM code is running inside worker threads.

### `api_tester/discover.py`

`load_endpoints()` selects YAML or OpenAPI JSON based on the file extension. `_from_yaml()` creates `Endpoint` objects from `data["endpoints"]`. `_from_openapi()` maps supported OpenAPI operations and optional `x-test.extra_cases`. The remaining helpers extract success codes, generate sample JSON bodies, and collect required request-body fields.

OpenAPI discovery also extracts required path, query, and header parameters, resolves local `#/...` references, and prefers examples, defaults, and enum values when generating sample data. The `base_url` argument currently exists in `load_endpoints()` but is not used.

### `api_tester/runner.py`

`_substitute_path()` resolves path parameters. `_generate_cases()` builds happy, missing-auth, empty-body, and invalid-JSON cases and carries query parameters and idempotency metadata into each `TestCase`. `_execute()` sends one request, records an attempt object, parses its response, retries only idempotent transport/timeout failures, and converts errors into failed results. `run_all()` creates one async HTTP client, runs read-only cases with bounded concurrency, serializes mutation cases, gathers all cases, and returns results in task order. `TestResult.attempts` preserves retry history for the audit database.

### `api_tester/analyzer.py`

Contains the analyzer system prompt, failure serialization, source candidate search, suspected-file normalization, secret redaction, and `analyze()`. Authorization and cookie header values are redacted before model input. Source files are limited to common TypeScript, JavaScript, Python, Go, Ruby, Java, and Kotlin extensions, and the number of files included is bounded by `MAX_FILES_TOUCHED`.

### `api_tester/fixer.py`

Contains the complete-file fixer prompt and `propose_fix()`. It reads the selected source file, asks the configured workhorse model for a `FixProposal`, and strips accidental Markdown fences from `full_content`.

### `api_tester/llm.py`

Provides Ollama integration. `_strip_thinking()` removes reasoning tags, `_extract_json()` uses JSON decoding so braces inside quoted strings are handled correctly, `_content()` supports both response shapes, `chat_json()` validates structured output with retries, and `chat_text()` returns plain cleaned text.

### `api_tester/reviewer.py`

Defines the strict review prompt and calls `chat_json()` to convert the diagnosis, diff, explanation, and verification result into a `Verdict`.

### `api_tester/safety.py`

Wraps Git commands, identifies Git repositories, creates and removes worktrees, checks patch shape, applies low-level patches, computes diffs, validates full-file proposals, performs optional syntax checks, and commits approved files.

### `api_tester/orchestrator.py`

Defines `FailureReport` and `RunReport`, readiness polling, isolated verification, and `run_pipeline()`. This is the central coordinator and contains the policy decisions about confidence, source requirements, reviewer approval, verification failure, and interactive commit approval.

### `api_tester/report.py`

Converts a `RunReport` into a timestamped Markdown file. It does not serialize raw request/response bodies into the report; it focuses on failures, diagnoses, diffs, decisions, and commit metadata.

### `api_tester/cli.py`

Creates the Typer app, defines `run` and `smoke`, installs the shared Rich terminal configuration, validates the optional source directory, prints configured models, invokes the async pipeline with `asyncio.run()`, writes the report, and returns a non-zero status for failed tests unless `--allow-failures` is used.

### `api_tester/terminal.py`

Owns the shared Rich `Console` and `configure_terminal()`. Keeping this configuration in one module prevents the CLI and orchestrator from using inconsistent output settings. It also installs concise Rich tracebacks for command-line failures while leaving library imports free from terminal side effects until the CLI starts.

### `examples/endpoints.yaml`

Demonstrates hand-authored health, list, create, and parameterized detail cases. It shows a request body, accepted multiple success codes, and explicit `path_params`.

### `examples/openapi.json`

Demonstrates OpenAPI 3 loading for GET and POST operations, generated request bodies, required fields, and multiple response codes.

### `Modelfile.qwen14` and `Modelfile.r1`

Define the two custom Ollama model configurations used by the default `.env.example` names.

### `.env.example`, `.gitignore`, and generated metadata

`.env.example` documents local settings. `.gitignore` excludes virtual environments, secrets, bytecode, reports, and temporary worktrees. `api_tester.egg-info/` is setuptools metadata produced by installation.

## 16. Common operating procedures

### Run tests only

```bash
source .venv/bin/activate
api-tester run --spec examples/endpoints.yaml --base-url http://localhost:8000
less reports/report-*.md
```

### Run with authentication negative cases

Put a valid header in the endpoint specification, then run:

```bash
api-tester run -s examples/endpoints.yaml -u http://localhost:8000 --auth
```

The missing-auth case only removes the header named `Authorization` case-insensitively. It does not invent valid credentials or test invalid credentials.

### Diagnose source-aware failures

```bash
api-tester run \
  -s examples/endpoints.yaml \
  -u http://localhost:8000 \
  --source /absolute/path/to/api
```

The source directory can be outside this project. The analyzer reads source text but the command does not modify it unless `--fix` is also supplied.

### Create and inspect a fix branch

```bash
api-tester run -s examples/endpoints.yaml -u http://localhost:8000 \
  --source /absolute/path/to/api --fix
git -C /absolute/path/to/api branch --list 'ai-fix/*'
git -C /absolute/path/to/api log --oneline --all --decorate -10
```

If you decline the prompt or a guard rejects the patch, the temporary worktree and branch are removed. If a fix is committed, the branch remains so a developer can inspect, test, merge, or delete it manually.

## 17. Troubleshooting

### `api-tester: command not found`

Activate the virtual environment or use `.venv/bin/api-tester`; then run `python -m pip install -e .`.

### Ollama connection error

Start `ollama serve`, confirm `ollama list`, and run `api-tester smoke`. If your Ollama server is remote or uses a non-default endpoint, configure the Ollama client environment according to your Ollama installation; this project itself does not define an Ollama host setting.

### Model missing

The configured names must exist exactly. Recreate them with the Modelfiles or override `ANALYZER_MODEL` and `WORKHORSE_MODEL` in `.env`.

### All requests fail with connection errors

The target API is probably not running, the base URL/port is wrong, or the service is bound to another host. Test it directly with `curl`.

### OpenAPI request body is wrong

The sample generator supports basic schemas and local `$ref` values, but not every complex construct such as `allOf`, `oneOf`, `anyOf`, or security schemes. Add examples, defaults, required parameter values, or `x-test` overrides for precise test data. Remember that status codes are currently the main assertion.

### Fix phase says source must be a Git repo

Run `git -C /path/to/api status` and pass the repository or a directory inside it as `--source`. The fix phase intentionally refuses non-Git sources.

### Verification never becomes ready

The verifier expects the patched API to use the supplied `PORT`, to listen on the supplied `HOST`, and to expose `GET /health`. Adjust `--start-cmd`, the application startup behavior, or `VERIFY_PORT_OFFSET`/`VERIFY_STARTUP_TIMEOUT`.

### Patch rejected as too large or truncated

The model must return the complete current file with only the necessary change. Increase `MAX_DIFF_LINES` or `MAX_FILE_CHARS` only after reviewing the risk; a rejection is often evidence that the model output was incomplete or unnecessarily broad.

### Fixes are not attempted

The orchestrator skips fixes when there is no diagnosis, no suspected file, or confidence below `0.5`. It also skips a fix when the file proposal fails safety checks or when the reviewer rejects it.

## 18. Current limitations and maintenance notes

These are implementation facts to keep in mind when extending the project:

1. OpenAPI support resolves local `$ref` values, but not every complex schema construct such as `allOf`, `oneOf`, or `anyOf`.
2. The runner checks status codes only; response schemas, bodies, headers, latency budgets, and database state are not yet asserted.
3. `base_url` is accepted by discovery but unused there because the HTTP client owns URL composition.
4. The verifier uses a shell command through `create_subprocess_shell`; pass trusted commands only.
5. Report timestamps use the machine's local clock.
6. The focused test suite does not replace full end-to-end tests against a real target API and Ollama models.

## 19. Recommended development workflow

```bash
source .venv/bin/activate
python -m pip install -e '.[dev]'
python -m compileall -q api_tester
api-tester --help
api-tester smoke
```

For a behavior change, update or add an example specification, run it against a controlled local API, inspect the generated report, and test both diagnosis-only and fix-enabled modes. For changes to safety logic, test rejection paths as well as successful commits in a disposable Git repository.

Before accepting an AI-generated branch, inspect it yourself:

```bash
git -C /path/to/api show --stat --oneline BRANCH_NAME
git -C /path/to/api diff HEAD..BRANCH_NAME
git -C /path/to/api -c core.autocrlf=false show BRANCH_NAME:relative/path/to/file
```

The tool is an accelerator and reviewer, not a replacement for application tests, security review, or human ownership of the final merge.

## 20. Beginner concepts: the vocabulary you need

If you are new to backend development, these words explain the rest of this guide:

| Term | Plain-language meaning |
|---|---|
| API | A service that receives requests and sends responses, usually over HTTP. |
| Endpoint | One address plus an HTTP method, such as `GET /users/1`. |
| HTTP method | The action requested: `GET` reads, `POST` creates, `PUT` replaces, `PATCH` partially updates, and `DELETE` removes. |
| Status code | The numeric result of a request. `2xx` usually means success, `4xx` means the request is invalid or unauthorized, and `5xx` means the server failed. |
| Contract | The agreement describing how an endpoint should behave: paths, inputs, outputs, and statuses. |
| Specification | The YAML or OpenAPI file that describes that contract to API Tester. |
| Test case | One concrete request generated from an endpoint definition. |
| Test result | The recorded outcome of one request, including status, body, error, and duration. |
| Idempotent request | A request that can safely be repeated without causing another logical side effect. `GET` is normally idempotent; `POST` normally is not. |
| LLM | A language model. Here, it is run locally through Ollama. |
| Diagnosis | The analyzer model's structured explanation of why a test failed. |
| Worktree | A second checkout managed by Git, used so a proposed fix does not alter the original checkout. |
| Diff | A line-by-line description of what changed between two files. |
| CI | Continuous integration: an automated job that runs checks after a commit or pull request. |

The simplest mental model is: **the specification is the expectation, the target API is the system being observed, and the report is the evidence**. The AI stages are optional assistants that explain and propose changes after evidence exists.

## 21. First-run walkthrough for a complete beginner

This walkthrough assumes you have a target API listening on port 8000.

### Step 1: enter the project

```bash
cd /Users/jodickndayisenga/Desktop/agent_api_tester
```

The project root is the directory containing `pyproject.toml`, `api_tester/`, and `examples/`.

### Step 2: create and activate an isolated Python environment

```bash
python3 -m venv .venv
source .venv/bin/activate
```

The virtual environment keeps this project's dependencies separate from the rest of your computer. After activation, `python` and `api-tester` should resolve to `.venv/bin/`.

On Windows PowerShell, the activation command is usually:

```powershell
.venv\Scripts\Activate.ps1
```

### Step 3: install the package and development tools

```bash
python -m pip install --upgrade pip
python -m pip install -e '.[dev]'
```

The `-e` means editable installation: changes in the local source tree are used immediately. The `[dev]` extra installs test and quality tools in addition to runtime dependencies.

If the environment has no `pip` module but has `uv`, use:

```bash
uv pip install --python .venv/bin/python -e '.[dev]'
```

### Step 4: check the command exists

```bash
api-tester --help
```

If this fails, use the absolute virtual-environment executable:

```bash
.venv/bin/api-tester --help
```

### Step 5: prepare Ollama

The initial HTTP tests can run without a language model if all tests pass. Diagnosis and fix generation require Ollama.

```bash
ollama serve
ollama pull qwen2.5-coder:14b
ollama pull deepseek-r1:14b
ollama create qwen-tester -f Modelfile.qwen14
ollama create r1-tester -f Modelfile.r1
api-tester smoke
```

`smoke` checks model availability. It does not contact your API.

### Step 6: start the target API

Start the application in a separate terminal. The exact command depends on that application. For example:

```bash
PORT=8000 HOST=127.0.0.1 node src/server.js
```

Then check it manually:

```bash
curl -i http://localhost:8000/health
```

If `curl` cannot connect, API Tester cannot connect either. Fix the target service first.

### Step 7: run the example specification

```bash
api-tester run \
  --spec examples/endpoints.yaml \
  --base-url http://localhost:8000
```

The tool will print the models it intends to use, the number of loaded endpoints, a pass/fail summary, and the report path.

### Step 8: read the report

```bash
ls reports/
less reports/report-*.md
```

If a test failed, start with `Expected`, `Actual`, and `Error`. Only then read the AI diagnosis. The HTTP response is evidence; the diagnosis is an interpretation that should be checked.

## 22. A concrete request lifecycle

Suppose the specification contains:

```yaml
endpoints:
  - method: GET
    path: /users/{id}
    path_params:
      id: 42
    query:
      include: profile
    headers:
      Authorization: Bearer example-token
    expect_status: [200, 404]
```

The system transforms it as follows:

1. YAML becomes an `Endpoint` object.
2. The runner replaces `{id}` with `42`.
3. It creates a happy-path `TestCase` with path `/users/42`, query `include=profile`, and the authorization header.
4. If `--auth` was supplied, it creates a second case with the authorization header removed and expects `401` or `403`.
5. The HTTP client sends requests with the configured base URL:

   ```text
   GET http://localhost:8000/users/42?include=profile
   Authorization: Bearer example-token
   ```

6. If the response status is `200` or `404`, the happy-path case passes.
7. If the response status is something else, the case becomes a failure and may be sent to the analyzer.
8. The result stores the status, response body excerpt, error text, and elapsed time.

This distinction is important: an endpoint definition may produce multiple test cases. “Loaded 4 endpoints” does not necessarily mean “4 HTTP requests.” A POST endpoint can create three cases: happy path, empty body, and malformed JSON; `--auth` can add another.

## 23. Designing good specifications

A good specification is explicit about data that the API needs and conservative about expected behavior.

### Prefer real valid values

Weak:

```yaml
body:
  email: test
```

Better:

```yaml
body:
  name: Ada Lovelace
  email: ada@example.test
  role: viewer
```

Use values that are valid for the target API but safe for a test environment. Avoid real customer data and production credentials.

### List all accepted success statuses intentionally

If an endpoint may return either `200` or `201`, write both:

```yaml
expect_status: [200, 201]
```

Do not list every possible status simply to make failures disappear. A `500` should normally remain a failure.

### Keep negative cases meaningful

The built-in empty-body and malformed-JSON cases are useful for create/update endpoints. For domain-specific failures, use `x-test.extra_cases` or YAML entries:

```yaml
  - method: POST
    path: /payments
    body:
      amount: -1
      currency: USD
    expect_status: [400, 422]
```

### Be careful with state

If `POST /users` creates a real record, repeated runs may create repeated records. Use a disposable database, deterministic test identifiers, cleanup endpoints, or a dedicated test environment. API Tester does not reset your database.

## 24. Concurrency, idempotency, and retries in depth

### Why concurrency exists

Parallel read-only requests make a large API specification faster. The semaphore limits the number of active read-only requests so the tester does not overwhelm the target service.

### Why mutations are serialized

Mutations can change shared state. If a create, update, and delete run simultaneously, the result may depend on scheduling rather than the contract. API Tester therefore serializes cases marked non-idempotent.

This is a safety default, not a complete test dependency engine. If your API requires a particular sequence—create an object, then update it, then delete it—you should eventually model those operations as an explicit scenario rather than relying on endpoint ordering.

### What is retried

The runner retries only:

- `httpx.TimeoutException`;
- `httpx.TransportError`;
- cases marked idempotent.

It does not retry a normal `400`, `401`, `404`, or `500`, because those are responses from the application and repeating them usually does not fix the contract violation. It does not retry POST/PUT/PATCH negative cases because repeating a mutation can create side effects.

The delay grows exponentially for each retry attempt. Configure the count with:

```bash
api-tester run ... --retries 2
```

or:

```dotenv
HTTP_RETRIES=2
```

Use retries to tolerate temporary network instability, not to hide an unreliable API.

## 25. Authentication behavior in depth

API Tester does not implement a login flow. It assumes the specification already contains whatever headers the API needs.

Example:

```yaml
headers:
  Authorization: Bearer test-token
  X-Tenant: example
```

With `--auth`, the runner copies the headers and removes only the header whose name is `Authorization`, ignoring capitalization. It then expects `401` or `403`.

This means:

- it does not obtain a token;
- it does not test token expiry;
- it does not test malformed tokens unless you define an extra case;
- it does not remove cookies or custom authentication headers;
- it applies the missing-auth case globally to generated endpoints.

For more advanced auth testing, define explicit extra cases with separate headers and expected statuses. Never place production tokens in a committed YAML file.

## 26. Understanding a failure report

Consider this simplified failure:

```text
Expected: [400, 422]
Actual:   500
Error:    expected [400, 422], got 500
```

Interpretation:

1. The test intentionally sent an invalid or incomplete request.
2. The contract says the server should reject it as a client error.
3. The server instead crashed or exposed an internal error.
4. The failure is evidence of a validation or error-handling defect.

The diagnosis may then contain:

- `root_cause`: concise explanation;
- `category`: normalized classification such as `validation` or `auth`;
- `confidence`: model confidence from `0.0` to `1.0`;
- `suspected_files`: only files shown to the model;
- `fix_hint`: suggested direction;
- `severity`: business/operational importance.

Confidence is not correctness. A confidence of `1.0` means the model is confident, not that the proposed change has been proven. Verification and human review remain important.

## 27. CI usage

A minimal CI sequence is:

```bash
python -m pip install -e '.[dev]'
python -m compileall -q api_tester tests
pytest -q
ruff check api_tester tests
mypy api_tester
api-tester run \
  --spec examples/endpoints.yaml \
  --base-url http://localhost:8000
```

The final command returns status `1` when API tests fail. A CI job should normally preserve the generated report as an artifact:

```yaml
artifacts:
  when: always
  paths:
    - reports/
```

For CI, prefer diagnosis-only mode first. Automatically committing AI-generated fixes from CI is a policy decision with security and governance implications. If you do enable it, use a disposable branch, a tightly scoped source directory, trusted startup commands, and a human approval step before merging.

## 28. Developer workflow for changing this project

### Change a schema

1. Update the Pydantic model in `schemas.py`.
2. Update discovery or runner construction so the new field is populated.
3. Update the HTTP execution logic if the field affects a request.
4. Add a test that proves the field survives the full relevant path.
5. Update the YAML/OpenAPI examples and this guide.

### Change request execution

1. Decide whether the new behavior affects idempotent and mutating methods differently.
2. Add a unit test using a mock transport rather than a live internet service.
3. Check timeout, retry, cancellation, and response parsing behavior.
4. Verify that failures become useful `TestResult` objects rather than crashing the whole run.

### Change LLM prompts or schemas

1. Preserve strict JSON output requirements.
2. Test malformed JSON, reasoning tags, missing fields, and invalid enum values.
3. Do not trust a model-provided file path without validating it against files actually shown.
4. Keep the diff and source-size limits active.
5. Add a report example if the output format changes.

### Change safety behavior

Test both sides of every guard:

- valid patch accepted;
- identical patch rejected;
- truncated patch rejected;
- dropped import rejected;
- syntax error rejected;
- path escaping the worktree rejected;
- oversized diff rejected;
- reviewer rejection cleaned up;
- declined commit cleaned up.

Use a disposable Git repository for worktree tests. Never experiment with destructive Git behavior in an important checkout.

## 29. Verification checklist before calling a release stable

### Functional

- YAML specifications load.
- OpenAPI JSON specifications load.
- Path, query, and header parameters are sent correctly.
- Happy-path statuses are checked.
- Empty-body and malformed-JSON cases behave as expected.
- Authentication-negative cases remove only the intended header.
- Read-only requests can run concurrently.
- Mutations are serialized.
- Transport retries are bounded and limited to safe cases.

### AI workflow

- Ollama model names are configurable.
- Structured responses validate against Pydantic schemas.
- Reasoning tags and JSON-in-prose are handled.
- Source candidates are bounded and redacted.
- Suspected paths are restricted to shown files.
- Fix proposals are complete files, not fragments.
- Reviewer rejection prevents commits.

### Safety

- The original checkout is not modified during proposal generation.
- Worktree targets cannot escape the worktree.
- Diff size is bounded.
- Syntax checks run when language tools are available.
- Failed verification prevents commits.
- Temporary branches are removed when a proposal is rejected.
- Successful branches are clearly reported.

### Operations

- Reports are written even when failures occur.
- CI receives a non-zero exit code for failed tests.
- Logs do not expose credentials unnecessarily.
- Timeouts are finite.
- The target API and verification API use separate ports.

## 30. Glossary of implementation terms

| Implementation term | Meaning in this project |
|---|---|
| `Endpoint` | Pydantic representation of one specification-level operation. |
| `TestCase` | One fully resolved request, including path, body, headers, query, and expected statuses. |
| `TestResult` | The outcome returned by the HTTP runner. |
| `RunReport` | Aggregate count and list of failed cases for one CLI run. |
| `FailureReport` | A failed result plus optional diagnosis, fix, diff, verdict, branch, and verification information. |
| `Diagnosis` | Structured analyzer output. |
| `FixProposal` | Structured complete-file output from the fixer model. |
| `Verdict` | Structured approval/rejection from the reviewer model. |
| `SETTINGS` | One process-wide immutable configuration object created during import. |
| `source_dir` | Directory searched for context and used as the source root for proposed fixes. |
| `source_prefix` | Path from the Git repository root to `source_dir`, needed because worktrees operate from repository root. |
| `target_rel` | Repository-relative path of the file being changed in a worktree. |
| `PatchRejected` | Safety exception that prevents a proposed change from progressing. |

When debugging, follow the data in this order: `Endpoint` → `TestCase` → `TestResult` → `FailureReport` → `Diagnosis` → `FixProposal` → `Verdict` → optional Git commit.
