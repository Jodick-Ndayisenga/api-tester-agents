# FastAPI target

## Setup

From this directory:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

## Start

```bash
uvicorn app:app --host 127.0.0.1 --port 8001 --reload
```

The API is available at `http://localhost:8001`. FastAPI also exposes its
generated documentation at `/docs` and `/redoc`.

Run the tester from the repository root with:

```bash
api-tester run -s test-apis/fastapi/api-spec.yaml -u http://localhost:8001
```
