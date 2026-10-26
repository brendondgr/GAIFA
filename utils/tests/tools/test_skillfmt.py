"""skill-sources 1.1: the open skill format's frontmatter and checks, and the mods' copies of the parser."""

from pathlib import Path

from utils import skillfmt

ROOT = Path(__file__).resolve().parents[3]

FOLDED = """---
name: pdf-forms
description: >
  Fill in PDF forms and read their fields.
  Use when the user mentions a form.
license: MIT
allowed-tools: Bash Read
metadata:
  author: someone
  version: "1.2"
  mcp-servers: blender
created: 2026-01-02
---
# Filling forms

Steps.
"""


def test_folded_description_lists_and_nested_metadata():
    s = skillfmt.load(FOLDED, "pdf-forms")
    assert s["name"] == "pdf-forms" and s["problems"] == []
    assert s["description"] == "Fill in PDF forms and read their fields. Use when the user mentions a form."
    assert s["meta"]["metadata"] == {"author": "someone", "version": "1.2", "mcp-servers": "blender"}
    assert s["meta"]["license"] == "MIT" and s["meta"]["allowed-tools"] == "Bash Read"
    assert s["meta"]["created"] == "2026-01-02"                      # a YAML date, JSON-safe
    assert s["body"].startswith("# Filling forms")


def test_literal_block_and_a_list():
    s = skillfmt.parse("---\nname: a\ndescription: |\n  line one\n  line two\npaths:\n  - src/**\n  - '*.md'\n---\nbody\n")
    assert s["description"] == "line one\nline two" and s["meta"]["paths"] == ["src/**", "*.md"] and s["body"] == "body\n"


def test_no_frontmatter_broken_yaml_and_not_a_mapping():
    s = skillfmt.load("# Just text\n", "x")
    assert s["body"] == "# Just text\n" and "no frontmatter" in s["problems"][0]
    s = skillfmt.parse("---\nname: [unclosed\ndescription: x\n---\nbody")
    assert s["problems"] and "valid YAML" in s["problems"][0] and s["name"] == ""
    assert "key: value" in skillfmt.parse("---\n- a\n- b\n---\n")["problems"][0]
    assert skillfmt.parse("---\nname: a\n")["problems"]           # never closed: no frontmatter


def test_crlf_bom_and_dots_close():
    s = skillfmt.parse("﻿---\r\nname: a\r\ndescription: d\r\n...\r\nbody\r\n")
    assert (s["name"], s["description"], s["body"]) == ("a", "d", "body\r\n")


def test_name_rules():
    ok = skillfmt.check("pdf-forms", "pdf-forms", "d")
    assert ok == []
    for bad in ("PDF", "-a", "a-", "a--b", "a_b", "a" * 65):
        assert skillfmt.check(bad, None, "d"), bad
    assert "doesn't match its folder" in skillfmt.check("a", "b", "d")[0]
    assert skillfmt.check("", None, "d") == ["no name"]
    assert "no description" in skillfmt.check("a", None, "")[0]
    assert "1025 characters" in skillfmt.check("a", None, "x" * 1025)[0]


def test_numbers_and_null_become_text():
    s = skillfmt.parse("---\nname: 123\ndescription:\n---\n")
    assert s["name"] == "123" and s["description"] == ""


def test_flag():
    assert skillfmt.flag({"disable-model-invocation": True}, "disable-model-invocation")
    assert skillfmt.flag({"x": "true"}, "x") and not skillfmt.flag({"x": "no"}, "x") and not skillfmt.flag({}, "x")


def test_the_mods_copies_are_identical():
    hub = (ROOT / "utils" / "skillfmt.py").read_bytes()
    for copy in ("services/agent/agent/skillfmt.py", "services/workspace/skillfmt.py"):
        assert (ROOT / copy).read_bytes() == hub, f"{copy} differs from utils/skillfmt.py: copy it again"
