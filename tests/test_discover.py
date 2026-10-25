import json

from api_tester.discover import load_endpoints


def test_yaml_loads_query_and_path_values(tmp_path):
    spec = tmp_path / "endpoints.yaml"
    spec.write_text(
        """endpoints:
  - method: GET
    path: /users/{id}
    path_params: {id: 7}
    query: {limit: 2}
    expect_status: [200]
"""
    )
    endpoint = load_endpoints(spec)[0]
    assert endpoint.path_params == {"id": 7}
    assert endpoint.query == {"limit": 2}


def test_openapi_resolves_refs_and_parameters(tmp_path):
    spec = {
        "openapi": "3.0.0",
        "components": {
            "schemas": {
                "User": {
                    "type": "object",
                    "properties": {"name": {"type": "string", "example": "Ada"}},
                    "required": ["name"],
                }
            }
        },
        "paths": {
            "/users/{id}": {
                "get": {
                    "parameters": [
                        {"name": "id", "in": "path", "required": True, "example": 9},
                        {"name": "limit", "in": "query", "required": True, "example": 3},
                    ],
                    "responses": {"200": {"description": "ok"}},
                }
            },
            "/users": {
                "post": {
                    "requestBody": {
                        "content": {
                            "application/json": {
                                "schema": {"$ref": "#/components/schemas/User"}
                            }
                        }
                    },
                    "responses": {"201": {"description": "created"}},
                }
            },
        },
    }
    path = tmp_path / "openapi.json"
    path.write_text(json.dumps(spec))
    endpoints = load_endpoints(path)
    get = next(e for e in endpoints if e.method == "GET")
    post = next(e for e in endpoints if e.method == "POST")
    assert get.path_params == {"id": 9}
    assert get.query == {"limit": 3}
    assert post.body == {"name": "Ada"}
    assert post.required_fields == ["name"]


def test_openapi_filters_by_prefix_method_and_tag(tmp_path):
    spec = {
        "openapi": "3.0.0",
        "paths": {
            "/users": {"get": {"tags": ["users"], "responses": {"200": {}}}},
            "/users/internal": {"post": {"tags": ["users"], "responses": {"201": {}}}},
            "/orders": {"get": {"tags": ["orders"], "responses": {"200": {}}}},
        },
    }
    path = tmp_path / "openapi.json"
    path.write_text(json.dumps(spec))

    endpoints = load_endpoints(
        path, include_prefix="/users", exclude_prefix="/users/internal",
        methods={"get"}, tags={"users"},
    )
    assert [(endpoint.method, endpoint.path) for endpoint in endpoints] == [("GET", "/users")]

