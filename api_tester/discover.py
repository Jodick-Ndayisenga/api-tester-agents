from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from .schemas import Endpoint


def load_endpoints(spec_path: Path, base_url: str = "") -> list[Endpoint]:
    if spec_path.suffix in (".yaml", ".yml"):
        return _from_yaml(spec_path)
    if spec_path.suffix == ".json":
        return _from_openapi(spec_path)
    raise ValueError(f"Unsupported spec: {spec_path.suffix}")

def _from_yaml(path: Path) -> list[Endpoint]:
    data = yaml.safe_load(path.read_text())
    if not isinstance(data, dict) or not isinstance(data.get("endpoints"), list):
        raise ValueError("YAML specification must contain an 'endpoints' list")
    return [Endpoint(**e) for e in data["endpoints"]]

def _from_openapi(path: Path) -> list[Endpoint]:
    spec = json.loads(path.read_text())
    endpoints: list[Endpoint] = []
    if not isinstance(spec.get("paths"), dict):
        raise ValueError("OpenAPI specification must contain a 'paths' object")
    for raw_path, methods in spec.get("paths", {}).items():
        for method, op in methods.items():
            if method.lower() not in ("get", "post", "put", "patch", "delete"):
                continue
            op = _resolve_refs(op, spec)
            x_test = op.get("x-test") or {}
            path_params = _extract_path_params(raw_path, op, x_test)
            query = _extract_query_params(op, x_test)
            headers = _extract_header_params(op, x_test)
            endpoints.append(Endpoint(
                method=method.upper(), path=raw_path,
                body=_sample_body(op, spec), expect_status=_extract_success_codes(op),
                path_params=path_params, query=query, headers=headers,
                required_fields=_extract_required_fields(op),
            ))
            for extra in x_test.get("extra_cases") or []:
                endpoints.append(Endpoint(**extra))
    return endpoints

def _extract_success_codes(op: dict) -> list[int]:
    codes = []
    for code in op.get("responses", {}):
        try:
            c = int(code)
            if 200 <= c < 300:
                codes.append(c)
        except ValueError:
            pass
    return codes or [200]

def _resolve_refs(value: Any, root: dict) -> Any:
    if isinstance(value, dict) and "$ref" in value:
        ref = value["$ref"]
        if not ref.startswith("#/"):
            return value
        current: Any = root
        try:
            for part in ref[2:].split("/"):
                current = current[part.replace("~1", "/").replace("~0", "~")]
            resolved = _resolve_refs(current, root)
            remainder = {k: _resolve_refs(v, root) for k, v in value.items() if k != "$ref"}
            if isinstance(resolved, dict):
                return {**resolved, **remainder}
            return resolved
        except (KeyError, TypeError):
            return value
    if isinstance(value, dict):
        return {k: _resolve_refs(v, root) for k, v in value.items()}
    if isinstance(value, list):
        return [_resolve_refs(v, root) for v in value]
    return value

def _extract_path_params(raw_path: str, op: dict, x_test: dict) -> dict[str, Any]:
    values = dict(x_test.get("path_params") or {})
    for param in op.get("parameters", []):
        if param.get("in") != "path":
            continue
        name = param.get("name")
        schema = param.get("schema") or {}
        if name and name not in values:
            values[name] = param.get("example", schema.get("example", schema.get("default", _sample_from_schema(schema))))
    missing = [p for p in _path_names(raw_path) if p not in values]
    if missing:
        raise ValueError(f"Missing values for required path parameter(s): {', '.join(missing)}")
    return values

def _path_names(path: str) -> list[str]:
    import re
    return re.findall(r"\{([^}]+)\}", path)

def _extract_query_params(op: dict, x_test: dict) -> dict[str, Any]:
    values = dict(x_test.get("query") or {})
    for param in op.get("parameters", []):
        if param.get("in") != "query" or not param.get("required"):
            continue
        name = param.get("name")
        schema = param.get("schema") or {}
        if name and name not in values:
            values[name] = param.get("example", schema.get("example", schema.get("default", _sample_from_schema(schema))))
    return values

def _extract_header_params(op: dict, x_test: dict) -> dict[str, str]:
    values = {str(k): str(v) for k, v in (x_test.get("headers") or {}).items()}
    for param in op.get("parameters", []):
        if param.get("in") == "header" and param.get("required") and param.get("name"):
            schema = param.get("schema") or {}
            values.setdefault(param["name"], str(param.get("example", schema.get("example", "test"))))
    return values

def _sample_body(op: dict, root: dict | None = None) -> dict[str, Any] | None:
    rb = op.get("requestBody", {})
    schema = rb.get("content", {}).get("application/json", {}).get("schema", {})
    if not schema:
        return None
    return _sample_from_schema(_resolve_refs(schema, root or op))

def _sample_from_schema(schema: dict) -> Any:
    if "example" in schema:
        return schema["example"]
    if "default" in schema:
        return schema["default"]
    if schema.get("enum"):
        return schema["enum"][0]
    t = schema.get("type")
    if t == "object" or "properties" in schema:
        return {k: _sample_from_schema(v) for k, v in schema.get("properties", {}).items()}
    if t == "string":
        return schema.get("example", "test")
    if t == "integer":
        return schema.get("example", 1)
    if t == "number":
        return schema.get("example", 1.0)
    if t == "boolean":
        return True
    if t == "array":
        return [_sample_from_schema(schema.get("items", {"type": "string"}))]
    return None

def _extract_required_fields(op: dict) -> list[str]:
    schema = op.get("requestBody", {}).get("content", {}).get(
        "application/json", {}).get("schema", {})
    return list(schema.get("required") or [])
