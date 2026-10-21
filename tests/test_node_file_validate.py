"""node_file_write content validation tests."""

from openvort.core.execution.node_tools import _validate_content


def test_valid_files_pass():
    assert _validate_content("/w/a.json", '{"a": [1, 2]}') == ""
    assert _validate_content("/w/a.py", "def f():\n    return 1\n") == ""
    assert _validate_content("/w/pom.xml", "<project><a/></project>") == ""
    java = (
        "class A {\n"
        "    // } in comment\n"
        "    /* ( in block */\n"
        "    String s = \"}{\";\n"
        "    char c = '{';\n"
        "    String t = \"\"\"\n        ) text block\n        \"\"\";\n"
        "    Map<String, Object> m() { return null; }\n"
        "}\n"
    )
    assert _validate_content("/w/A.java", java) == ""
    assert _validate_content("/w/README.md", "{{{ anything") == ""


def test_invalid_files_fail():
    assert _validate_content("/w/a.json", '{"a": 1, filtering}').startswith("语法错误")
    assert "第 2 行" in _validate_content("/w/a.py", "x = 1\ndef f(:\n")
    assert _validate_content("/w/a.xml", "<a><b></a>").startswith("语法错误")
    err = _validate_content("/w/A.java", "class A {\n    void f() {\n}\n")
    assert err.startswith("括号不平衡") and "第 1 行" in err
    assert "第 2 行" in _validate_content("/w/A.java", "class A {\n  f());\n}\n")
