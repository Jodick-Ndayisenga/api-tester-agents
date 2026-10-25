from __future__ import annotations

import json
import re
import time
from typing import Callable, TypeVar

import ollama
from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)
_THINKING_RE = re.compile(r"<think(?:ing)?>.*?</think(?:ing)?>", re.DOTALL)

def _strip_thinking(text: str) -> str:
    return _THINKING_RE.sub("", text).strip()

def _extract_json(text: str) -> str:
    text = _strip_thinking(text)
    decoder = json.JSONDecoder()
    for start, char in enumerate(text):
        if char != "{":
            continue
        try:
            _, end = decoder.raw_decode(text[start:])
            return text[start:start + end]
        except json.JSONDecodeError:
            continue
    return text

def _content(resp) -> str:
    """Extract message content from an ollama response (works for dict AND pydantic)."""
    if isinstance(resp, dict):
        return resp["message"]["content"]
    return resp.message.content

def chat_json(model: str, system: str, user: str, schema: type[T],
              num_ctx: int = 4096, temperature: float = 0.15,
              max_retries: int = 2,
              trace: Callable[[dict], None] | None = None,
              kind: str = "json") -> T:
    messages = [
        {"role": "system", "content": system + "\n\nReturn ONLY valid JSON matching this schema:\n"
                                             + json.dumps(schema.model_json_schema(), indent=2)},
        {"role": "user", "content": user},
    ]
    last_err: str | None = None
    last_raw: str = ""
    for attempt_no in range(1, max_retries + 2):
        started = time.perf_counter()
        if last_err is not None:
            messages.append({"role": "assistant", "content": last_raw})
            messages.append({"role": "user",
                             "content": f"Your previous output failed validation: {last_err}\n"
                                        "Return ONLY valid JSON - no prose, no markdown."})
        resp = ollama.chat(model=model, messages=messages, format="json",
                           options={"num_ctx": num_ctx, "temperature": temperature})
        last_raw = _content(resp)
        try:
            parsed = schema.model_validate_json(_extract_json(last_raw))
            if trace:
                trace({
                    "kind": kind, "model": model, "attempt_no": attempt_no,
                    "schema_name": schema.__name__, "system": messages[0]["content"],
                    "user": messages[-1]["content"], "response": last_raw,
                    "duration_ms": (time.perf_counter() - started) * 1000,
                })
            return parsed
        except Exception as e:
            last_err = str(e)
            if trace:
                trace({
                    "kind": kind, "model": model, "attempt_no": attempt_no,
                    "schema_name": schema.__name__, "system": messages[0]["content"],
                    "user": messages[-1]["content"], "response": last_raw,
                    "error": last_err, "duration_ms": (time.perf_counter() - started) * 1000,
                })
    raise ValueError(f"LLM failed to return valid {schema.__name__}: {last_err}")

def chat_text(model: str, system: str, user: str,
              num_ctx: int = 4096, temperature: float = 0.15,
              trace: Callable[[dict], None] | None = None,
              kind: str = "text") -> str:
    started = time.perf_counter()
    resp = ollama.chat(model=model,
        messages=[{"role": "system", "content": system},
                  {"role": "user", "content": user}],
        options={"num_ctx": num_ctx, "temperature": temperature})
    content = _content(resp)
    if trace:
        trace({
            "kind": kind, "model": model, "attempt_no": 1,
            "system": system, "user": user, "response": content,
            "duration_ms": (time.perf_counter() - started) * 1000,
        })
    return _strip_thinking(content)
