from sqlalchemy import func, select

from api_tester.audit import AuditEvent, AuditLlmInteraction, AuditStore
from api_tester.schemas import Endpoint, TestCase as ApiTestCase, TestResult as ApiTestResult


async def test_audit_store_persists_run_cases_results_and_redacts(tmp_path):
    store = await AuditStore.open(f"sqlite+aiosqlite:///{tmp_path / 'audit.db'}")
    try:
        endpoint = Endpoint(
            method="GET", path="/health", headers={"Authorization": "Bearer secret"},
            expect_status=[200],
        )
        run_id = await store.start_run(
            "spec.yaml", "http://localhost:8000", "token: secret",
            "yaml", [endpoint], False, False,
        )
        result = ApiTestResult(
            case=ApiTestCase(
                name="happy_path GET /health", method="GET", path="/health",
                request_headers={"Authorization": "Bearer secret"}, expected_status=[200],
            ),
            passed=False, actual_status=500, response_body={"token": "secret"},
            error="expected [200], got 500",
        )
        case_ids = await store.record_results(run_id, [result])
        await store.record_llm(run_id, {
            "kind": "analyzer", "model": "local", "attempt_no": 1,
            "system": "secret=hidden", "user": "Authorization: Bearer secret",
            "response": '{"ok": true}', "duration_ms": 1.0,
        })
        await store.finish_run(run_id, type("Report", (), {
            "total": 1, "passed": 0, "failures": [result],
        })())

        async with store.sessions() as session:
            event_count = await session.scalar(
                select(func.count()).select_from(AuditEvent).where(AuditEvent.run_id == run_id)
            )
            llm = await session.scalar(select(AuditLlmInteraction).where(AuditLlmInteraction.run_id == run_id))
        assert case_ids
        assert event_count >= 2
        assert llm is not None
        assert "secret" not in llm.user_prompt
        assert "secret=***" in llm.system_prompt
    finally:
        await store.close()


async def test_pipeline_returns_audit_run_id(tmp_path, monkeypatch):
    import api_tester.orchestrator as orchestrator

    spec = tmp_path / "spec.yaml"
    spec.write_text("endpoints:\n  - method: GET\n    path: /health\n    expect_status: [200]\n")
    endpoint = Endpoint(method="GET", path="/health", expect_status=[200])
    result = ApiTestResult(
        case=ApiTestCase(name="happy", method="GET", path="/health", expected_status=[200]),
        passed=True, actual_status=200, attempts=[
            {"attempt_no": 1, "passed": True, "actual_status": 200,
             "response_body": {"ok": True}, "duration_ms": 1.0}
        ],
    )

    monkeypatch.setattr(orchestrator, "load_endpoints", lambda path, base_url: [endpoint])

    async def fake_run_all(*args, **kwargs):
        return [result]

    monkeypatch.setattr(orchestrator, "run_all", fake_run_all)
    report = await orchestrator.run_pipeline(
        spec, "http://localhost:8000", None, False, False, False,
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'pipeline.db'}",
    )
    assert report.audit_run_id

