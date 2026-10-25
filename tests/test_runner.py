import httpx

from api_tester.runner import _generate_cases, run_all
from api_tester.schemas import Endpoint


def test_generate_cases_carries_query_and_serialization_metadata():
    endpoint = Endpoint(
        method="POST", path="/users", query={"tenant": "demo"},
        body={"name": "Ada"}, expect_status=[201],
    )
    cases = _generate_cases(endpoint, auth_used=False)
    assert cases[0].request_query == {"tenant": "demo"}
    assert cases[0].idempotent is False
    assert {case.name.split()[0] for case in cases} == {"happy_path", "empty_body", "invalid_json"}


async def test_run_all_sends_query_parameters():
    seen = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(200, json={"ok": True})

    transport = httpx.MockTransport(handler)
    # Patch the client constructor only for this test without requiring a server.
    original = httpx.AsyncClient

    class Client(httpx.AsyncClient):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = transport
            super().__init__(*args, **kwargs)

    try:
        from api_tester import runner
        runner.httpx.AsyncClient = Client
        results = await run_all(
            [Endpoint(method="GET", path="/users", query={"page": 2}, expect_status=[200])],
            "http://test", False, concurrency=1,
        )
    finally:
        runner.httpx.AsyncClient = original
    assert results[0].passed is True
    assert "page=2" in seen[0]

