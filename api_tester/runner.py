from __future__ import annotations

import asyncio
import re
import time
from typing import Any

import httpx

from .schemas import Endpoint, TestCase, TestResult


def _substitute_path(path: str, path_params: dict[str, Any]) -> str:
    out = path
    for k, v in path_params.items():
        out = out.replace(f"{{{k}}}", str(v)).replace(f":{k}", str(v))
    return re.sub(r"\{[^}]+\}", "1", out)

def _generate_cases(ep: Endpoint, auth_used: bool) -> list[TestCase]:
    cases: list[TestCase] = []
    resolved = _substitute_path(ep.path, ep.path_params)
    body = ep.body
    cases.append(TestCase(
        name=f"happy_path {ep.method} {ep.path}", method=ep.method, path=resolved,
        request_body=body, request_headers=ep.headers, expected_status=ep.expect_status,
        request_query=ep.query, idempotent=ep.method.upper() in ("GET", "HEAD", "OPTIONS"),
    ))
    if auth_used:
        h = {k: v for k, v in ep.headers.items() if k.lower() != "authorization"}
        cases.append(TestCase(
            name=f"missing_auth {ep.method} {ep.path}", method=ep.method, path=resolved,
            request_body=body, request_headers=h, expected_status=[401, 403],
            request_query=ep.query, idempotent=ep.method.upper() in ("GET", "HEAD", "OPTIONS"),
        ))
    if ep.method.upper() == "POST":
        cases.append(TestCase(
            name=f"empty_body {ep.method} {ep.path}", method=ep.method, path=resolved,
            request_body={}, request_headers=ep.headers, expected_status=[400, 422],
            request_query=ep.query, idempotent=False,
        ))
        cases.append(TestCase(
            name=f"invalid_json {ep.method} {ep.path}", method=ep.method, path=resolved,
            request_body=None, request_headers=ep.headers, expected_status=[400, 422],
            request_query=ep.query, idempotent=False,
        ))
    elif ep.method.upper() in ("PUT", "PATCH") and ep.required_fields:
        # Only expect 400/422 on PUT/PATCH when the spec declares required fields
        cases.append(TestCase(
            name=f"empty_body {ep.method} {ep.path}", method=ep.method, path=resolved,
            request_body={}, request_headers=ep.headers, expected_status=[400, 422],
            request_query=ep.query, idempotent=False,
        ))
        cases.append(TestCase(
            name=f"invalid_json {ep.method} {ep.path}", method=ep.method, path=resolved,
            request_body=None, request_headers=ep.headers, expected_status=[400, 422],
            request_query=ep.query, idempotent=False,
        ))
    return cases

async def _execute(
    client: httpx.AsyncClient,
    case: TestCase,
    retries: int = 0,
    attempt_no: int = 1,
    attempt_log: list[dict[str, Any]] | None = None,
) -> TestResult:
    started = time.perf_counter()
    attempt_log = attempt_log if attempt_log is not None else []
    try:
        kwargs: dict[str, Any] = {"headers": case.request_headers}
        if case.method.upper() in ("POST", "PUT", "PATCH"):
            if case.name.startswith("invalid_json"):
                kwargs["content"] = b"{not valid json"
                kwargs["headers"] = {**case.request_headers, "Content-Type": "application/json"}
            else:
                kwargs["json"] = case.request_body
        r = await client.request(case.method, case.path, params=case.request_query, **kwargs)
        duration = (time.perf_counter() - started) * 1000
        passed = r.status_code in case.expected_status
        try:
            body: Any = r.json()
        except ValueError:
            body = r.text[:2000]
        error = None if passed else f"expected {case.expected_status}, got {r.status_code}"
        attempt_log.append({
            "attempt_no": attempt_no, "passed": passed, "actual_status": r.status_code,
            "response_body": body, "error": error, "duration_ms": duration,
        })
        return TestResult(case=case, passed=passed, actual_status=r.status_code,
                          response_body=body, error=error, duration_ms=duration,
                          attempts=attempt_log)
    except (httpx.TimeoutException, httpx.TransportError) as e:
        duration = (time.perf_counter() - started) * 1000
        attempt_log.append({
            "attempt_no": attempt_no, "passed": False, "actual_status": None,
            "response_body": None, "error": f"{type(e).__name__}: {e}",
            "duration_ms": duration,
        })
        if retries > 0 and case.idempotent:
            await asyncio.sleep(0.2 * (2 ** (retries - 1)))
            return await _execute(client, case, retries - 1, attempt_no + 1, attempt_log)
        return TestResult(case=case, passed=False,
                          error=f"{type(e).__name__}: {e}",
                          duration_ms=duration, attempts=attempt_log)
    except Exception as e:
        duration = (time.perf_counter() - started) * 1000
        attempt_log.append({
            "attempt_no": attempt_no, "passed": False, "actual_status": None,
            "response_body": None, "error": f"{type(e).__name__}: {e}",
            "duration_ms": duration,
        })
        return TestResult(case=case, passed=False,
                          error=f"{type(e).__name__}: {e}",
                          duration_ms=duration, attempts=attempt_log)

async def run_all(endpoints: list[Endpoint], base_url: str, auth_used: bool,
                  timeout: float = 15.0, concurrency: int = 4,
                  retries: int = 0) -> list[TestResult]:
    if concurrency <= 0:
        raise ValueError("concurrency must be positive")
    async with httpx.AsyncClient(base_url=base_url, timeout=timeout) as client:
        cases = [c for ep in endpoints for c in _generate_cases(ep, auth_used)]
        queue: asyncio.Queue[tuple[int, TestCase] | None] = asyncio.Queue()
        results: list[TestResult | None] = [None] * len(cases)

        async def run_case(case: TestCase) -> TestResult:
            return await _execute(client, case, retries if case.idempotent else 0)

        mutation_lock = asyncio.Lock()

        async def worker() -> None:
            while True:
                item = await queue.get()
                try:
                    if item is None:
                        return
                    index, case = item
                    if case.idempotent:
                        results[index] = await run_case(case)
                    else:
                        async with mutation_lock:
                            results[index] = await run_case(case)
                finally:
                    queue.task_done()

        worker_count = min(concurrency, max(1, len(cases)))
        workers = [asyncio.create_task(worker()) for _ in range(worker_count)]
        for index, case in enumerate(cases):
            await queue.put((index, case))
        await queue.join()
        for _ in workers:
            await queue.put(None)
        await asyncio.gather(*workers)
        return [result for result in results if result is not None]
