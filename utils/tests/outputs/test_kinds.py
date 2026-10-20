"""Plan 24.1: every listed extension has its kind, and text and documents their subtype."""

from __future__ import annotations

import pytest

from utils.outputs.entries import KINDS, kind_of, subtype_of

TEXT = {
    "markdown": ("md", "markdown"),
    "plain": ("txt", "log", "rst"),
    "code": ("py", "js", "mjs", "ts", "tsx", "jsx", "rs", "go", "c", "h", "cpp", "hpp", "cc", "java", "kt", "swift", "rb",
             "php", "lua", "sh", "bash", "zsh", "fish", "ps1", "sql", "r", "jl", "cs"),
    "config": ("toml", "yaml", "yml", "ini", "cfg", "conf", "env.example", "xml"),
    "web": ("html", "htm", "css", "scss"),
    "data": ("json", "jsonl", "csv", "tsv"),
    "subtitles": ("srt", "vtt"),
    "notebook": ("ipynb",),
}
DOCUMENTS = ("pdf", "docx", "epub", "pptx", "xlsx", "odt")


@pytest.mark.parametrize("family,ext", [(f, e) for f, exts in TEXT.items() for e in exts])
def test_text_extensions(family, ext):
    for name in (f"notes.{ext}", f"NOTES.{ext.upper()}", f"143012-a-b.{ext}"):
        assert kind_of(name) == "text", name
        assert subtype_of(name).split(":")[0] == family, name


@pytest.mark.parametrize("ext", DOCUMENTS)
def test_document_extensions(ext):
    assert kind_of(f"paper.{ext}") == "document" and subtype_of(f"paper.{ext}") == ext


def test_subtypes_name_the_language_or_format():
    assert subtype_of("a.py") == "code:python" and subtype_of("a.tsx") == "code:tsx" and subtype_of("a.hpp") == "code:cpp"
    assert subtype_of("a.yml") == "config:yaml" and subtype_of(".env.example") == "config:env" and subtype_of("a.htm") == "web:html"
    assert subtype_of("a.csv") == "data:csv" and subtype_of("a.md") == "markdown" and subtype_of("a.ipynb") == "notebook"
    assert subtype_of("a.png") is None and subtype_of("README") is None


def test_kinds_list_document_and_the_old_kinds_hold():
    assert "document" in KINDS
    assert (kind_of("a.wav"), kind_of("a.png"), kind_of("a.mp4"), kind_of("a.glb"), kind_of("a.zip"), kind_of("a.exe")) == \
        ("audio", "image", "video", "model3d", "archive", "other")
