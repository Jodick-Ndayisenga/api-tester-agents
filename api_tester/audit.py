"""Durable, redacted audit storage for API Tester runs.

The database is an audit sink: failures to write audit data are intentionally
visible to the caller rather than silently losing the record. Payloads are
redacted and bounded before they are stored.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import Boolean, DateTime, Float, Integer, JSON, String, Text, func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from .config import SETTINGS
from .schemas import Diagnosis, Endpoint, FixProposal, TestResult, Verdict


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


_SECRET_PATTERNS = [
    (re.compile(r"(?i)(authorization\s*[:=]\s*)(?:bearer\s+)?[^\s,;]+"), r"\1***"),
    (re.compile(r"(?i)(bearer\s+)[^\s,;]+"), r"\1***"),
    (re.compile(r"(?i)(api[_-]?key|secret|password|token)(\s*[:=]\s*)['\"]?[^'\"\s,;]+"), r"\1\2***"),
    (re.compile(r"-----BEGIN [^-]+ PRIVATE KEY-----.*?-----END [^-]+ PRIVATE KEY-----", re.DOTALL), "[PRIVATE KEY REDACTED]"),
]


def redact_text(value: str, max_chars: int = SETTINGS.audit_max_chars) -> str:
    for pattern, replacement in _SECRET_PATTERNS:
        value = pattern.sub(replacement, value)
    if len(value) > max_chars:
        return value[:max_chars] + "\n...[truncated]"
    return value


def sanitize(value: Any, max_chars: int = SETTINGS.audit_max_chars) -> Any:
    """Convert arbitrary payloads into redacted, JSON-safe, bounded values."""
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    if isinstance(value, dict):
        return {str(k): sanitize(v, max_chars) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [sanitize(v, max_chars) for v in value]
    if isinstance(value, bytes):
        return redact_text(value.decode("utf-8", errors="replace"), max_chars)
    if isinstance(value, str):
        return redact_text(value, max_chars)
    try:
        json.dumps(value)
        return value
    except TypeError:
        return redact_text(str(value), max_chars)


def payload_hash(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


class Base(DeclarativeBase):
    pass


class AuditRun(Base):
    __tablename__ = "audit_runs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    status: Mapped[str] = mapped_column(String(32), default="running")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    base_url: Mapped[str] = mapped_column(Text)
    spec_path: Mapped[str] = mapped_column(Text)
    spec_format: Mapped[str] = mapped_column(String(32))
    spec_sha256: Mapped[str] = mapped_column(String(64))
    raw_spec: Mapped[str] = mapped_column(Text)
    auth_used: Mapped[bool] = mapped_column(Boolean, default=False)
    do_fix: Mapped[bool] = mapped_column(Boolean, default=False)
    total: Mapped[int] = mapped_column(Integer, default=0)
    passed: Mapped[int] = mapped_column(Integer, default=0)
    failed: Mapped[int] = mapped_column(Integer, default=0)
    config_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


class AuditEndpoint(Base):
    __tablename__ = "audit_endpoints"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String(36), index=True)
    ordinal: Mapped[int] = mapped_column(Integer)
    method: Mapped[str] = mapped_column(String(16))
    path: Mapped[str] = mapped_column(Text)
    endpoint_json: Mapped[dict[str, Any]] = mapped_column(JSON)


class AuditBatch(Base):
    __tablename__ = "audit_batches"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String(36), index=True)
    batch_number: Mapped[int] = mapped_column(Integer)
    start_index: Mapped[int] = mapped_column(Integer)
    endpoint_count: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(32), default="running")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    result_count: Mapped[int] = mapped_column(Integer, default=0)
    failure_count: Mapped[int] = mapped_column(Integer, default=0)


class AuditCase(Base):
    __tablename__ = "audit_cases"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String(36), index=True)
    ordinal: Mapped[int] = mapped_column(Integer)
    name: Mapped[str] = mapped_column(Text)
    method: Mapped[str] = mapped_column(String(16))
    path: Mapped[str] = mapped_column(Text)
    case_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    batch_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)


class AuditAttempt(Base):
    __tablename__ = "audit_attempts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String(36), index=True)
    case_id: Mapped[int] = mapped_column(Integer, index=True)
    attempt_no: Mapped[int] = mapped_column(Integer, default=1)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    passed: Mapped[bool] = mapped_column(Boolean)
    actual_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    request_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    response_json: Mapped[Any | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration_ms: Mapped[float] = mapped_column(Float, default=0.0)
    batch_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)


class AuditDiagnosis(Base):
    __tablename__ = "audit_diagnoses"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String(36), index=True)
    case_id: Mapped[int] = mapped_column(Integer, index=True)
    diagnosis_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AuditSourceContext(Base):
    __tablename__ = "audit_source_context"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String(36), index=True)
    case_id: Mapped[int] = mapped_column(Integer, index=True)
    file_path: Mapped[str] = mapped_column(Text)
    content: Mapped[str] = mapped_column(Text)
    content_sha256: Mapped[str] = mapped_column(String(64))
    redacted: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AuditLlmInteraction(Base):
    __tablename__ = "audit_llm_interactions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String(36), index=True)
    kind: Mapped[str] = mapped_column(String(32))
    model: Mapped[str] = mapped_column(String(255))
    attempt_no: Mapped[int] = mapped_column(Integer, default=1)
    schema_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    system_prompt: Mapped[str] = mapped_column(Text)
    user_prompt: Mapped[str] = mapped_column(Text)
    raw_response: Mapped[str] = mapped_column(Text)
    validation_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration_ms: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AuditFixProposal(Base):
    __tablename__ = "audit_fix_proposals"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String(36), index=True)
    case_id: Mapped[int] = mapped_column(Integer, index=True)
    file_path: Mapped[str] = mapped_column(Text)
    full_content: Mapped[str] = mapped_column(Text)
    content_sha256: Mapped[str] = mapped_column(String(64))
    explanation: Mapped[str] = mapped_column(Text)
    risk: Mapped[str] = mapped_column(String(16))
    unified_diff: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AuditReview(Base):
    __tablename__ = "audit_reviews"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String(36), index=True)
    case_id: Mapped[int] = mapped_column(Integer, index=True)
    verdict_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AuditVerification(Base):
    __tablename__ = "audit_verifications"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String(36), index=True)
    case_id: Mapped[int] = mapped_column(Integer, index=True)
    passed: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    output: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AuditEvent(Base):
    __tablename__ = "audit_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String(36), index=True)
    event_type: Mapped[str] = mapped_column(String(64), index=True)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AuditStore:
    def __init__(self, engine: AsyncEngine):
        self.engine = engine
        self.sessions = async_sessionmaker(engine, expire_on_commit=False)

    @classmethod
    async def open(cls, url: str) -> "AuditStore":
        engine = create_async_engine(url, future=True)
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        return cls(engine)

    async def close(self) -> None:
        await self.engine.dispose()

    async def get_run(self, run_id: str) -> AuditRun | None:
        async with self.sessions() as session:
            return await session.get(AuditRun, run_id)

    async def _event(self, session: AsyncSession, run_id: str, event_type: str, payload: Any) -> None:
        session.add(AuditEvent(run_id=run_id, event_type=event_type, payload_json=sanitize(payload)))

    async def start_run(
        self,
        spec_path: str,
        base_url: str,
        raw_spec: str,
        spec_format: str,
        endpoints: list[Endpoint],
        auth_used: bool,
        do_fix: bool,
        invocation: dict[str, Any] | None = None,
    ) -> str:
        import uuid

        run_id = str(uuid.uuid4())
        raw_hash = hashlib.sha256(raw_spec.encode("utf-8")).hexdigest()
        settings = {k: v for k, v in SETTINGS.__dict__.items() if k not in {"database_url"}}
        settings["invocation"] = sanitize(invocation or {})
        async with self.sessions() as session:
            session.add(AuditRun(
                id=run_id, status="running", base_url=base_url, spec_path=spec_path,
                spec_format=spec_format, spec_sha256=raw_hash, raw_spec=redact_text(raw_spec),
                auth_used=auth_used, do_fix=do_fix, config_json=sanitize(settings),
            ))
            for ordinal, endpoint in enumerate(endpoints):
                session.add(AuditEndpoint(
                    run_id=run_id, ordinal=ordinal, method=endpoint.method,
                    path=endpoint.path, endpoint_json=sanitize(endpoint),
                ))
            await self._event(session, run_id, "run_started", {
                "spec_path": spec_path, "spec_format": spec_format,
                "endpoint_count": len(endpoints), "base_url": base_url,
            })
            await session.commit()
        return run_id

    async def start_batch(
        self, run_id: str, batch_number: int, start_index: int, endpoint_count: int,
    ) -> int:
        async with self.sessions() as session:
            row = AuditBatch(
                run_id=run_id, batch_number=batch_number, start_index=start_index,
                endpoint_count=endpoint_count,
            )
            session.add(row)
            await self._event(session, run_id, "batch_started", {
                "batch_number": batch_number, "start_index": start_index,
                "endpoint_count": endpoint_count,
            })
            await session.flush()
            await session.commit()
            return row.id

    async def completed_batches(self, run_id: str) -> set[int]:
        async with self.sessions() as session:
            rows = (await session.scalars(
                select(AuditBatch.batch_number).where(
                    AuditBatch.run_id == run_id, AuditBatch.status == "completed"
                )
            )).all()
            return set(rows)

    async def finish_batch(self, batch_id: int, result_count: int, failure_count: int, status: str = "completed") -> None:
        async with self.sessions() as session:
            row = await session.get(AuditBatch, batch_id)
            if row is not None:
                row.status = status
                row.finished_at = utcnow()
                row.result_count = result_count
                row.failure_count = failure_count
                await session.commit()

    async def record_results(
        self, run_id: str, results: list[TestResult], batch_id: int | None = None,
    ) -> list[int]:
        case_ids: list[int] = []
        async with self.sessions() as session:
            for ordinal, result in enumerate(results):
                case = result.case
                row = AuditCase(
                    run_id=run_id, ordinal=ordinal, name=case.name,
                    method=case.method, path=case.path, case_json=sanitize(case), batch_id=batch_id,
                )
                session.add(row)
                await session.flush()
                case_ids.append(row.id)
                request = {
                    "method": case.method, "path": case.path,
                    "query": case.request_query, "headers": case.request_headers,
                    "body": case.request_body,
                }
                attempts = result.attempts or [{
                    "attempt_no": 1, "passed": result.passed,
                    "actual_status": result.actual_status,
                    "response_body": result.response_body, "error": result.error,
                    "duration_ms": result.duration_ms,
                }]
                for attempt in attempts:
                    session.add(AuditAttempt(
                        run_id=run_id, case_id=row.id, batch_id=batch_id,
                        attempt_no=int(attempt.get("attempt_no", 1)),
                        passed=bool(attempt.get("passed", result.passed)),
                        actual_status=attempt.get("actual_status"),
                        request_json=sanitize(request),
                        response_json=sanitize(attempt.get("response_body")),
                        error=redact_text(str(attempt.get("error") or "")),
                        duration_ms=float(attempt.get("duration_ms", 0.0)),
                    ))
            await self._event(session, run_id, "tests_completed", {
                "total": len(results), "passed": sum(r.passed for r in results),
                "failed": sum(not r.passed for r in results), "batch_id": batch_id,
            })
            await session.commit()
        return case_ids

    async def record_diagnosis(self, run_id: str, case_id: int, diagnosis: Diagnosis) -> None:
        async with self.sessions() as session:
            session.add(AuditDiagnosis(run_id=run_id, case_id=case_id, diagnosis_json=sanitize(diagnosis)))
            await self._event(session, run_id, "diagnosis_completed", {"case_id": case_id, "diagnosis": diagnosis})
            await session.commit()

    async def record_source(self, run_id: str, case_id: int, files: list[dict[str, str]]) -> None:
        async with self.sessions() as session:
            for item in files:
                content = redact_text(item["content"])
                session.add(AuditSourceContext(
                    run_id=run_id, case_id=case_id, file_path=item["path"],
                    content=content, content_sha256=hashlib.sha256(item["content"].encode()).hexdigest(),
                ))
            await session.commit()

    async def record_llm(self, run_id: str, payload: dict[str, Any]) -> None:
        async with self.sessions() as session:
            session.add(AuditLlmInteraction(
                run_id=run_id,
                kind=str(payload.get("kind", "unknown")),
                model=str(payload.get("model", "")),
                attempt_no=int(payload.get("attempt_no", 1)),
                schema_name=payload.get("schema_name"),
                system_prompt=redact_text(str(payload.get("system", ""))),
                user_prompt=redact_text(str(payload.get("user", ""))),
                raw_response=redact_text(str(payload.get("response", ""))),
                validation_error=redact_text(str(payload["error"])) if payload.get("error") else None,
                duration_ms=float(payload.get("duration_ms", 0.0)),
            ))
            await session.commit()

    async def record_fix(self, run_id: str, case_id: int, fix: FixProposal, diff: str) -> None:
        raw_content = fix.full_content
        async with self.sessions() as session:
            session.add(AuditFixProposal(
                run_id=run_id, case_id=case_id, file_path=fix.file_path,
                full_content=redact_text(raw_content), content_sha256=hashlib.sha256(raw_content.encode()).hexdigest(),
                explanation=redact_text(fix.explanation), risk=fix.risk, unified_diff=redact_text(diff),
            ))
            await self._event(session, run_id, "fix_proposed", {"case_id": case_id, "file_path": fix.file_path})
            await session.commit()

    async def record_review(self, run_id: str, case_id: int, verdict: Verdict) -> None:
        async with self.sessions() as session:
            session.add(AuditReview(run_id=run_id, case_id=case_id, verdict_json=sanitize(verdict)))
            await self._event(session, run_id, "review_completed", {
                "case_id": case_id, "approve": verdict.approve,
            })
            await session.commit()

    async def record_verification(self, run_id: str, case_id: int, passed: bool | None, output: str) -> None:
        async with self.sessions() as session:
            session.add(AuditVerification(
                run_id=run_id, case_id=case_id, passed=passed, output=redact_text(output),
            ))
            await self._event(session, run_id, "verification_completed", {
                "case_id": case_id, "passed": passed,
            })
            await session.commit()

    async def record_event(self, run_id: str, event_type: str, payload: Any) -> None:
        async with self.sessions() as session:
            await self._event(session, run_id, event_type, payload)
            await session.commit()

    async def finish_run(self, run_id: str, report: Any, error: str | None = None) -> None:
        async with self.sessions() as session:
            row = await session.get(AuditRun, run_id)
            if row is not None:
                totals = await session.execute(
                    select(
                        func.coalesce(func.sum(AuditBatch.result_count), 0),
                        func.coalesce(func.sum(AuditBatch.failure_count), 0),
                    ).where(AuditBatch.run_id == run_id, AuditBatch.status == "completed")
                )
                total, failed = totals.one()
                row.status = "failed" if error else "completed"
                row.finished_at = utcnow()
                row.total = int(total) if not error else report.total
                row.failed = int(failed) if not error else len(report.failures)
                row.passed = row.total - row.failed if not error else report.passed
                row.error = redact_text(error or "") if error else None
                await self._event(session, run_id, "run_finished", {
                    "status": row.status, "total": row.total,
                    "passed": row.passed, "failed": row.failed,
                })
                await session.commit()

    async def export_run(self, run_id: str) -> dict[str, Any]:
        """Return every persisted row for one run as a JSON-serializable object."""
        models = [
            AuditEndpoint, AuditBatch, AuditCase, AuditAttempt, AuditDiagnosis,
            AuditSourceContext, AuditLlmInteraction, AuditFixProposal,
            AuditReview, AuditVerification, AuditEvent,
        ]
        output: dict[str, Any] = {"run_id": run_id}
        async with self.sessions() as session:
            run = await session.get(AuditRun, run_id)
            if run is None:
                raise ValueError(f"Audit run not found: {run_id}")
            output["audit_runs"] = [
                {key: value for key, value in run.__dict__.items() if not key.startswith("_")}
            ]
            for model in models:
                rows = (await session.scalars(
                    select(model).where(getattr(model, "run_id") == run_id)
                )).all()
                output[model.__tablename__] = [
                    {key: value for key, value in row.__dict__.items() if not key.startswith("_")}
                    for row in rows
                ]
        return json.loads(json.dumps(output, default=str))


class AuditBridge:
    """Thread-safe bridge used by synchronous LLM calls running in worker threads."""

    def __init__(self, store: AuditStore, run_id: str, loop: asyncio.AbstractEventLoop):
        self.store = store
        self.run_id = run_id
        self.loop = loop
        self.futures: list[Any] = []

    def trace_llm(self, payload: dict[str, Any]) -> None:
        future = asyncio.run_coroutine_threadsafe(
            self.store.record_llm(self.run_id, payload), self.loop
        )
        self.futures.append(future)

    def trace_source(self, case_id: int, files: list[dict[str, str]]) -> None:
        future = asyncio.run_coroutine_threadsafe(
            self.store.record_source(self.run_id, case_id, files), self.loop
        )
        self.futures.append(future)

    async def drain(self) -> None:
        if self.futures:
            await asyncio.gather(*(asyncio.wrap_future(f) for f in self.futures))
            self.futures.clear()

