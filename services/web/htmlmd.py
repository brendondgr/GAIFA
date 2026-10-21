"""What trafilatura's markdown loses, put back (plan 30.8), and a structured fallback for pages it finds no main
content in. Pure functions over the page's bytes and the markdown; `pages.convert` calls them.

- **Code blocks:** trafilatura drops a block's language and its blank lines (`import x\\n\\ndef f():` comes out
  without the blank line). Each fenced block whose text matches a `<pre>` of the page (ignoring whitespace) is
  written again from the `<pre>`: its lines as they were, its language from a `language-*`, `lang-*` or
  `highlight-source-*` class, and a blank line after the fence.
- **Tables:** pages that lay out text with tables (GitHub's comments) come out as rows with no header line, which
  no renderer shows as a table: a run of one-cell rows becomes paragraphs; wider rows get a header line, so the
  first row heads them.
- **Heading anchors:** Sphinx's `¶`, and the `#`, `§` and `🔗` permalinks other sites put after a heading or a
  definition (`[¶](https://docs.python.org#shlex.split)`, a bare `¶` at the end of a line), are dropped outside code
  (`strip_anchors`).
- **Fallback:** `plain(body)` keeps the page's structure (headings, paragraphs, list items, code, table rows),
  where `trafilatura.html2txt` gives one line of text.
"""

from __future__ import annotations

import re

import lxml.html

LANG = re.compile(r"\b(?:language|lang|highlight-source|highlight)-([A-Za-z0-9_+#.-]{1,20})\b")
FENCE = re.compile(r"(?m)^```[^\n`]*\n(.*?)\n?^```[ \t]*$", re.S)
SKIP = {"script", "style", "noscript", "template", "svg", "head", "iframe", "object", "canvas"}
BLOCK = {"p", "div", "section", "article", "main", "header", "footer", "nav", "aside", "ul", "ol", "table", "tbody",
         "thead", "form", "fieldset", "figure", "figcaption", "dl", "dt", "dd", "address", "details", "summary",
         "blockquote", "hr", "body", "html"}
HEADINGS = {f"h{n}": n for n in range(1, 7)}
MAX_BLOCKS = 500
LANG_ALIAS = {"python3": "python", "py3": "python", "default": "", "none": "", "text": "", "plaintext": "", "plain": ""}


def _key(text: str) -> str:
    return re.sub(r"\s+", "", text)


def _root(body: bytes):
    try:
        return lxml.html.fromstring(body)
    except (ValueError, lxml.etree.ParserError):
        return None


def code_blocks(body: bytes) -> dict[str, tuple[str, str]]:
    """The page's `<pre>` blocks: whitespace-free text → (language or "", text as written)."""
    root = _root(body)
    out: dict[str, tuple[str, str]] = {}
    if root is None:
        return out
    for pre in root.iter("pre"):
        text = pre.text_content().strip("\n")
        if not text.strip():
            continue
        classes = " ".join(filter(None, [pre.get("class"), *(c.get("class") for c in pre.iter("code")),
                                         *(p.get("class") for p in pre.iterancestors() if p.tag == "div")][:6]))
        m = LANG.search(classes)
        lang = m[1].lower() if m else ""
        out.setdefault(_key(text), (LANG_ALIAS.get(lang, lang), text))
        if len(out) >= MAX_BLOCKS:
            break
    return out


def restore_code(md: str, blocks: dict[str, tuple[str, str]]) -> str:
    """Each fenced block of `md` that matches a `<pre>`: written again with its language and its lines."""
    if not blocks:
        return md

    def again(m: re.Match) -> str:
        lang, text = blocks.get(_key(m[1]), ("", m[1]))
        fence = "````" if "```" in text else "```"
        return f"{fence}{lang}\n{text}\n{fence}\n"
    return _blank_after_fences(FENCE.sub(again, md))


ANCHOR_TEXT = r"(?:¶|#|§|🔗|\U0001f517|permalink|permalink to this (?:headline|heading|definition|section))"
ANCHOR_LINK = re.compile(r"\[\s*" + ANCHOR_TEXT + r"?\s*\]\(\s*<?[^()\s<>]*>?(?:\s+\"[^\"\n]*\")?\s*\)", re.I)
BARE_ANCHOR = re.compile(r"[ \t]*[¶🔗]+[ \t]*$", re.M)


def _anchor(m: re.Match) -> str:
    """A permalink: `[¶](…)`, `[🔗](…)`, or `[#](…#x)` / `[](…#x)` / `[permalink](…#x)` that point at an anchor."""
    s = m[0]
    text = s[1:s.index("]")].strip()
    if text in ("¶", "🔗", "§") or (s.count("#") > (1 if text == "#" else 0) and "#" in s[s.index("]"):]):
        return ""
    return s


def strip_anchors(md: str) -> str:
    """Heading and definition permalinks (Sphinx's `¶`, `#`, `§`, `🔗`, "Permalink to this headline") removed, outside
    code fences."""
    out, inside = [], False
    for line in md.split("\n"):
        if line.startswith(("```", "~~~")):
            inside = not inside
        elif not inside and any(c in line for c in "¶#§🔗["):
            new = BARE_ANCHOR.sub("", ANCHOR_LINK.sub(_anchor, line))
            line = new.rstrip() if new != line else line
        out.append(line)
    return "\n".join(out)


def _blank_after_fences(md: str) -> str:
    """A blank line after each closing fence, so the next paragraph or heading isn't glued to it."""
    out, inside = [], False
    lines = md.split("\n")
    for i, line in enumerate(lines):
        out.append(line)
        if line.startswith("```"):
            if inside and i + 1 < len(lines) and lines[i + 1].strip():
                out.append("")
            inside = not inside
    return "\n".join(out)


def fix_tables(md: str) -> str:
    """Rows without a header line: one-cell rows become paragraphs; wider ones get a header line."""
    lines, out, i = md.split("\n"), [], 0
    in_code = False
    while i < len(lines):
        if lines[i].startswith("```"):
            in_code = not in_code
        if in_code or not lines[i].lstrip().startswith("|"):
            out.append(lines[i])
            i += 1
            continue
        j = i
        while j < len(lines) and (lines[j].lstrip().startswith("|") or (not lines[j].strip() and j + 1 < len(lines)
                                                                         and lines[j + 1].lstrip().startswith("|"))):
            j += 1
        rows = [r for r in lines[i:j] if r.strip()]
        if any(re.fullmatch(r"\s*\|?\s*:?-{3,}.*", r) for r in rows[1:2]):   # a real table
            out.extend(lines[i:j])
        else:
            cells = [[c.strip() for c in r.strip().strip("|").split(" | ")] for r in rows]
            if all(len(c) == 1 for c in cells):
                for c in cells:
                    out.extend([c[0], ""])
            else:
                width = max(len(c) for c in cells)
                out.extend([rows[0], "|" + "---|" * width, *rows[1:]])
        i = j
    return "\n".join(out)


def plain(body: bytes) -> str:
    """The page's visible text with its structure, for pages trafilatura finds no main content in."""
    root = _root(body)
    if root is None:
        return ""
    parts: list[str] = []

    def walk(el) -> None:
        tag = el.tag if isinstance(el.tag, str) else None        # comments and processing instructions: no text
        if tag in SKIP:
            parts.append(_inline(el.tail))
            return
        if tag == "pre":
            parts.append("\n\n```\n" + el.text_content().strip("\n") + "\n```\n\n" + _inline(el.tail))
            return
        if tag in HEADINGS:
            parts.append("\n\n" + "#" * HEADINGS[tag] + " ")
        elif tag == "li":
            parts.append("\n- ")
        elif tag == "br":
            parts.append("\n")
        elif tag == "tr":
            parts.append("\n|")
        elif tag in ("td", "th"):
            parts.append(" ")
        elif tag in BLOCK:
            parts.append("\n\n")
        if tag is not None:
            parts.append(_inline(el.text))
            for child in el:
                walk(child)
        if tag in ("td", "th"):
            parts.append(" |")
        elif tag in HEADINGS or tag in BLOCK:
            parts.append("\n\n")
        parts.append(_inline(el.tail))

    walk(root)
    text = "".join(parts)
    chunks = re.split(r"(\n```\n.*?\n```\n)", text, flags=re.S)     # code as it is; the rest tidied
    for k in range(0, len(chunks), 2):
        c = "\n".join(line.strip() for line in chunks[k].split("\n"))
        chunks[k] = re.sub(r"\n{3,}", "\n\n", re.sub(r"(?m)^(#+|-) *$\n?", "", c))
    return fix_tables(re.sub(r"\n{3,}", "\n\n", "".join(chunks)).strip())


def _inline(s: str | None) -> str:
    return re.sub(r"\s+", " ", s) if s else ""
