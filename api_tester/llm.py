from __future__ import annotations

import json
import re
from typing import TypeVar

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
              max_retries: int = 2) -> T:
    messages = [
        {"role": "system", "content": system + "\n\nReturn ONLY valid JSON matching this schema:\n"
                                             + json.dumps(schema.model_json_schema(), indent=2)},
        {"role": "user", "content": user},
    ]
    last_err: str | None = None
    last_raw: str = ""
    for _ in range(max_retries + 1):
        if last_err is not None:
            messages.append({"role": "assistant", "content": last_raw})
            messages.append({"role": "user",
                             "content": f"Your previous output failed validation: {last_err}\n"
                                        "Return ONLY valid JSON - no prose, no markdown."})
        resp = ollama.chat(model=model, messages=messages, format="json",
                           options={"num_ctx": num_ctx, "temperature": temperature})
        last_raw = _content(resp)
        try:
            return schema.model_validate_json(_extract_json(last_raw))
        except Exception as e:
            last_err = str(e)
    raise ValueError(f"LLM failed to return valid {schema.__name__}: {last_err}")

def chat_text(model: str, system: str, user: str,
              num_ctx: int = 4096, temperature: float = 0.15) -> str:
    resp = ollama.chat(model=model,
        messages=[{"role": "system", "content": system},
                  {"role": "user", "content": user}],
        options={"num_ctx": num_ctx, "temperature": temperature})
    return _strip_thinking(_content(resp))
