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

async def _execute(client: httpx.AsyncClient, case: TestCase, retries: int = 0) -> TestResult:
    started = time.perf_counter()
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
        return TestResult(case=case, passed=passed, actual_status=r.status_code,
                          response_body=body, error=error, duration_ms=duration)
    except (httpx.TimeoutException, httpx.TransportError) as e:
        if retries > 0 and case.idempotent:
            await asyncio.sleep(0.2 * (2 ** (retries - 1)))
            return await _execute(client, case, retries - 1)
        return TestResult(case=case, passed=False,
                          error=f"{type(e).__name__}: {e}",
                          duration_ms=(time.perf_counter() - started) * 1000)
    except Exception as e:
        return TestResult(case=case, passed=False,
                          error=f"{type(e).__name__}: {e}",
                          duration_ms=(time.perf_counter() - started) * 1000)

async def run_all(endpoints: list[Endpoint], base_url: str, auth_used: bool,
                  timeout: float = 15.0, concurrency: int = 4,
                  retries: int = 0) -> list[TestResult]:
    sem = asyncio.Semaphore(concurrency)
    async with httpx.AsyncClient(base_url=base_url, timeout=timeout) as client:
        async def bounded(case: TestCase) -> TestResult:
            async with sem:
                return await _execute(client, case)
        cases = [c for ep in endpoints for c in _generate_cases(ep, auth_used)]
        async def run_case(case: TestCase) -> TestResult:
            if case.idempotent:
                return await bounded(case)
            async with mutation_lock:
                return await _execute(client, case, retries=0)
        mutation_lock = asyncio.Lock()
        tasks = [run_case(c) for c in cases]
        return list(await asyncio.gather(*tasks))
