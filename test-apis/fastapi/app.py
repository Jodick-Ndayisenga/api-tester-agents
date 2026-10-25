from __future__ import annotations

import asyncio
from typing import Annotated

from fastapi import FastAPI, Header, HTTPException, Query, status
from pydantic import BaseModel, Field

app = FastAPI(title="API Tester FastAPI Fixture", version="1.0.0")

USERS: dict[int, dict[str, object]] = {
    1: {"id": 1, "name": "Ada Lovelace", "email": "ada@example.com"},
    2: {"id": 2, "name": "Grace Hopper", "email": "grace@example.com"},
}


class UserInput(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    email: str = Field(pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class User(UserInput):
    id: int


@app.get("/health", tags=["system"])
def health() -> dict[str, str]:
    return {"status": "ok", "service": "fastapi-fixture"}


@app.get("/api/v1/users", response_model=list[User], tags=["users"])
def list_users(limit: Annotated[int, Query(ge=1, le=100)] = 20) -> list[dict[str, object]]:
    return list(USERS.values())[:limit]


@app.get("/api/v1/users/{user_id}", response_model=User, tags=["users"])
def get_user(user_id: int) -> dict[str, object]:
    user = USERS.get(user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    return user


@app.post("/api/v1/users", response_model=User, status_code=status.HTTP_201_CREATED, tags=["users"])
def create_user(payload: UserInput) -> dict[str, object]:
    user_id = max(USERS, default=0) + 1
    user = {"id": user_id, **payload.model_dump()}
    USERS[user_id] = user
    return user


@app.put("/api/v1/users/{user_id}", response_model=User, tags=["users"])
def update_user(user_id: int, payload: UserInput) -> dict[str, object]:
    if user_id not in USERS:
        raise HTTPException(status_code=404, detail="User not found")
    USERS[user_id] = {"id": user_id, **payload.model_dump()}
    return USERS[user_id]


@app.delete("/api/v1/users/{user_id}", tags=["users"])
def delete_user(user_id: int) -> dict[str, object]:
    if USERS.pop(user_id, None) is None:
        raise HTTPException(status_code=404, detail="User not found")
    return {"deleted": True, "id": user_id}


@app.get("/api/v1/search", tags=["search"])
def search(q: Annotated[str, Query(min_length=2)]) -> dict[str, object]:
    matches = [user for user in USERS.values() if q.lower() in str(user["name"]).lower()]
    return {"query": q, "results": matches}


@app.get("/api/v1/admin/secret", tags=["admin"])
def admin_secret(authorization: str | None = Header(default=None)) -> dict[str, str]:
    if authorization != "Bearer test-token":
        raise HTTPException(status_code=401, detail="Bearer token required")
    return {"message": "admin access granted"}


@app.get("/api/v1/buggy", tags=["diagnostics"])
def buggy() -> dict[str, str]:
    raise HTTPException(status_code=500, detail="Intentional fixture failure")


@app.get("/api/v1/slow", tags=["diagnostics"])
async def slow(delay_ms: Annotated[int, Query(ge=0, le=5000)] = 100) -> dict[str, int]:
    await asyncio.sleep(delay_ms / 1000)
    return {"delay_ms": delay_ms}
