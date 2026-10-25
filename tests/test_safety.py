import pytest

from api_tester.safety import PatchRejected, apply_full_file


def test_apply_full_file_rejects_truncated_content(tmp_path):
    target = tmp_path / "server.js"
    target.write_text("const one = 1;\nconst two = 2;\n")
    with pytest.raises(PatchRejected, match="shorter"):
        apply_full_file(tmp_path, "server.js", "const one = 1;\n")


def test_apply_full_file_rejects_missing_import(tmp_path):
    target = tmp_path / "module.py"
    target.write_text("import json\n\nvalue = 1\n")
    with pytest.raises(PatchRejected, match="import"):
        apply_full_file(tmp_path, "module.py", "value = 2\n\n# retained length\n")

