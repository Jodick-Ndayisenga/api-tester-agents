from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class Endpoint(BaseModel):
    method: str
    path: str
    body: dict[str, Any] | None = None
    headers: dict[str, str] = Field(default_factory=dict)
    query: dict[str, Any] = Field(default_factory=dict)
    expect_status: list[int] = Field(default_factory=lambda: [200])
    path_params: dict[str, Any] = Field(default_factory=dict)
    required_fields: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)

class TestCase(BaseModel):
    name: str
    method: str
    path: str
    request_body: Any | None = None
    request_headers: dict[str, str] = Field(default_factory=dict)
    request_query: dict[str, Any] = Field(default_factory=dict)
    expected_status: list[int]
    idempotent: bool = True

class TestResult(BaseModel):
    case: TestCase
    passed: bool
    actual_status: int | None = None
    response_body: Any | None = None
    error: str | None = None
    duration_ms: float = 0.0
    attempts: list[dict[str, Any]] = Field(default_factory=list)

class Diagnosis(BaseModel):
    root_cause: str = Field(..., description="1-3 sentence explanation of the root cause")
    confidence: float = Field(..., ge=0.0, le=1.0)
    category: Literal[
        "server_error", "validation", "auth", "contract_violation",
        "not_found", "timeout", "wrong_status", "other"
    ]
    suspected_files: list[str] = Field(default_factory=list)
    fix_hint: str
    severity: Literal["critical", "high", "medium", "low"]

class FixProposal(BaseModel):
    file_path: str
    full_content: str
    explanation: str
    risk: Literal["low", "medium", "high"]

class Verdict(BaseModel):
    approve: bool
    reasoning: str
    concerns: list[str] = Field(default_factory=list)
