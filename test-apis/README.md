# API Tester target projects

This directory contains three small APIs designed specifically to exercise the
root API Tester project:

| Project | Framework | Default port |
|---|---|---:|
| `fastapi` | Python FastAPI | 8001 |
| `node` | Node.js built-in HTTP server | 8002 |
| `nestjs` | NestJS + TypeScript | 8003 |

They intentionally expose the same route family so that the tester can run the
same contract against different implementations. Each project has its own
`api-spec.yaml` and README.

The APIs store data in memory. Restarting a server resets the sample users.
They are local testing fixtures, not production applications.

## Routes included

- `GET /health`: health check.
- `GET /api/v1/users?limit=...`: list users.
- `GET /api/v1/users/{id}`: retrieve one user.
- `POST /api/v1/users`: create a user and validate its body.
- `PUT /api/v1/users/{id}`: update a user.
- `DELETE /api/v1/users/{id}`: delete a user.
- `GET /api/v1/search?q=...`: required query parameter example.
- `GET /api/v1/admin/secret`: protected route requiring `Bearer test-token`.
- `GET /api/v1/buggy`: intentionally returns `500` so diagnosis and reports can be tested.
- `GET /api/v1/slow?delay_ms=...`: bounded delay for timeout/concurrency experiments.

## Running the tester

Start one target API using its README, then run from the repository root:

```bash
api-tester run \
  --spec test-apis/fastapi/api-spec.yaml \
  --base-url http://localhost:8001 \
  --batch-size 3
```

Try filters against the same specification:

```bash
api-tester run \
  --spec test-apis/node/api-spec.yaml \
  --base-url http://localhost:8002 \
  --include-prefix /api/v1/users \
  --methods GET,POST
```

The intentionally broken route should produce a failure and an audit record:

```bash
api-tester run \
  --spec test-apis/nestjs/api-spec.yaml \
  --base-url http://localhost:8003 \
  --tags diagnostics \
  --allow-failures
```
