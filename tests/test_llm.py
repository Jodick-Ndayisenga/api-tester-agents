from api_tester.llm import _extract_json, _strip_thinking


def test_json_extraction_handles_braces_inside_strings():
    raw = '<think>private reasoning</think> prose {"text": "use {id}"}'
    assert _extract_json(raw) == '{"text": "use {id}"}'


def test_thinking_tags_are_removed():
    assert _strip_thinking("<thinking>hidden</thinking> visible") == "visible"

