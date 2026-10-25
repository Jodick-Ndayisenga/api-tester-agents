# Test API command runbook

Copy-and-paste commands for switching API Tester to SQLite, installing the
fixture APIs, starting them one at a time, and testing them. Replace the root
path if your checkout is elsewhere.

## Table of contents

- [1. Switch from PostgreSQL to SQLite](#1-switch-from-postgresql-to-sqlite)
- [2. Prepare API Tester](#2-prepare-api-tester)
- [3. FastAPI](#3-fastapi)
- [4. Plain Node.js](#4-plain-nodejs)
- [5. NestJS](#5-nestjs)
- [6. Test variations](#6-test-variations)
- [7. Stop and clean up](#7-stop-and-clean-up)
- [8. Troubleshooting](#8-troubleshooting)

All commands below assume:

```bash
cd /Users/jodickndayisenga/Desktop/agent_api_tester
```

## 1. Switch from PostgreSQL to SQLite

SQLite is the default local audit database. It is a local file and does not
need Docker, a database server, or credentials.

Stop PostgreSQL if it is running:

```bash
docker compose stop audit-db
```

In `.env`, use:

```dotenv
DATABASE_URL=sqlite+aiosqlite:///./api_tester.db
AUDIT_ENABLED=true
```

Or configure the current terminal without editing `.env`:

```bash
export DATABASE_URL='sqlite+aiosqlite:///./api_tester.db'
export AUDIT_ENABLED=true
```

Shell exports take precedence over `.env` and apply only to the current
terminal session. Verify the file setting with:

```bash
grep '^DATABASE_URL=' .env
```

The first audited run creates `api_tester.db` automatically. It is ignored by
Git. Export a run later with:

```bash
api-tester audit-export --run-id RUN_UUID --output audit-export.json
```

Replace `RUN_UUID` with the UUID printed by `api-tester run`.

## 2. Prepare API Tester

Use the root project virtual environment for all tester commands:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e '.[dev]'
api-tester --help
api-tester run --help
```

If the command is not found, use `.venv/bin/api-tester`. Run each API server
in a separate terminal from the terminal running API Tester.

## 3. FastAPI

### Install dependencies

```bash
cd test-apis/fastapi
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

### Start the server

Keep this terminal open:

```bash
cd /Users/jodickndayisenga/Desktop/agent_api_tester/test-apis/fastapi
source .venv/bin/activate
uvicorn app:app --host 127.0.0.1 --port 8001 --reload
```

Check readiness:

```bash
curl -i http://127.0.0.1:8001/health
```

### Test FastAPI

In the root tester terminal:

```bash
cd /Users/jodickndayisenga/Desktop/agent_api_tester
source .venv/bin/activate
api-tester run \
  --spec test-apis/fastapi/api-spec.yaml \
  --base-url http://127.0.0.1:8001 \
  --batch-size 3 \
  --allow-failures
```

Stop it with `Ctrl+C` before starting the next fixture.

## 4. Plain Node.js

### Install and start

The fixture uses Node built-ins only, but install the local package for a
consistent setup:

```bash
cd /Users/jodickndayisenga/Desktop/agent_api_tester/test-apis/node
npm install
npm start
```

It listens on port `8002`. Check it:

```bash
curl -i http://127.0.0.1:8002/health
```

### Test Node.js

```bash
cd /Users/jodickndayisenga/Desktop/agent_api_tester
source .venv/bin/activate
api-tester run \
  --spec test-apis/node/api-spec.yaml \
  --base-url http://127.0.0.1:8002 \
  --batch-size 3 \
  --allow-failures
```

Stop it with `Ctrl+C` before starting NestJS.

## 5. NestJS

### Install and build

```bash
cd /Users/jodickndayisenga/Desktop/agent_api_tester/test-apis/nestjs
npm install
npm run build
```

### Start the server

```bash
npm run start:dev
```

It listens on port `8003`. Check it from another terminal:

```bash
curl -i http://127.0.0.1:8003/health
```

### Test NestJS

```bash
cd /Users/jodickndayisenga/Desktop/agent_api_tester
source .venv/bin/activate
api-tester run \
  --spec test-apis/nestjs/api-spec.yaml \
  --base-url http://127.0.0.1:8003 \
  --batch-size 3 \
  --allow-failures
```

## 6. Test variations

The `buggy` route intentionally returns `500` while its specification expects
`200`. Therefore full fixture runs produce a failure. `--allow-failures`
still writes the report but returns shell status `0`.

Test only passing user routes:

```bash
api-tester run \
  --spec test-apis/node/api-spec.yaml \
  --base-url http://127.0.0.1:8002 \
  --tags users \
  --methods GET,POST \
  --batch-size 2
```

Test the protected route and generate a missing-authorization case:

```bash
api-tester run \
  --spec test-apis/fastapi/api-spec.yaml \
  --base-url http://127.0.0.1:8001 \
  --tags admin \
  --auth \
  --allow-failures
```

Test only diagnostic routes:

```bash
api-tester run \
  --spec test-apis/nestjs/api-spec.yaml \
  --base-url http://127.0.0.1:8003 \
  --tags diagnostics \
  --allow-failures
```

Skip audit recording for one run:

```bash
api-tester run \
  --spec test-apis/node/api-spec.yaml \
  --base-url http://127.0.0.1:8002 \
  --tags users \
  --no-audit
```

Do not use `--no-audit` if you need a UUID, resume support, or JSON export.

Resume an interrupted run using its printed UUID:

```bash
api-tester run \
  --spec test-apis/node/api-spec.yaml \
  --base-url http://127.0.0.1:8002 \
  --batch-size 3 \
  --resume RUN_UUID \
  --allow-failures
```

Use the same specification, base URL, filters, and batch size when resuming.

## 7. Stop and clean up

Stop a running fixture with:

```text
Ctrl+C
```

Optional cleanup of local tester output:

```bash
cd /Users/jodickndayisenga/Desktop/agent_api_tester
rm -f api_tester.db
rm -rf reports
```

These commands permanently remove local audit history and generated reports.
Run them only when those records are no longer needed.

Stop PostgreSQL if it was previously enabled:

```bash
docker compose stop audit-db
```

## 8. Troubleshooting

### Tester command not found

```bash
cd /Users/jodickndayisenga/Desktop/agent_api_tester
source .venv/bin/activate
```

Or use `.venv/bin/api-tester` directly.

### SQLite is not being used

```bash
grep '^DATABASE_URL=' .env
echo "$DATABASE_URL"
export DATABASE_URL='sqlite+aiosqlite:///./api_tester.db'
```

The shell value wins over `.env`.

### Port already in use

Stop the old server with `Ctrl+C`, or choose another port and use the matching
base URL. For Node.js, for example:

```bash
PORT=9002 npm start
api-tester run -s test-apis/node/api-spec.yaml -u http://127.0.0.1:9002
```

### NestJS does not start

```bash
cd test-apis/nestjs
npm install
npm run build
```

### The command exits with status 1

That is expected for the intentional `/api/v1/buggy` failure. Use
`--allow-failures` to collect its report without a failing shell status, or
filter to `--tags users` for a passing run.
