"""Documents for the eval (plan 24.5): a small PDF writer (Helvetica text, one string per page;
the mod can't use the hub's test fixtures) and the 20-page report whose answer is only on page 7."""

from __future__ import annotations

import io


def _esc(s: str) -> str:
    return s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def pdf(pages: list[str]) -> bytes:
    n = len(pages)
    ids = [4 + 2 * i for i in range(n)]
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>",
            f"<< /Type /Pages /Kids [{' '.join(f'{p} 0 R' for p in ids)}] /Count {n} >>".encode(),
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>"]
    for i, text in enumerate(pages):
        ops = ["BT", "/F1 10 Tf", "12 TL", "60 760 Td"] + [f"({_esc(line)}) Tj" if k == 0 else f"T* ({_esc(line)}) Tj"
                                                           for k, line in enumerate(text.split("\n"))] + ["ET"]
        stream = "\n".join(ops).encode("cp1252", errors="replace")
        objs.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 3 0 R >> >> /Contents {ids[i] + 1} 0 R >>".encode())
        objs.append(f"<< /Length {len(stream)} >>\nstream\n".encode() + stream + b"\nendstream")
    out = io.BytesIO()
    out.write(b"%PDF-1.4\n")
    offs = []
    for k, body in enumerate(objs, 1):
        offs.append(out.tell())
        out.write(f"{k} 0 obj\n".encode() + body + b"\nendobj\n")
    x = out.tell()
    out.write(f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode() + b"".join(f"{o:010d} 00000 n \n".encode() for o in offs))
    out.write(f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{x}\n%%EOF\n".encode())
    return out.getvalue()


TOPICS = ["the lamp room", "the fog signal", "the stairs", "the supply boat", "the weather log", "the paint schedule",
          "the keeper's household", "the oil store", "the radio", "the visitors", "the gallery rail", "the lens",
          "the tide tables", "the generator", "the garden", "the boathouse", "the library", "the winter storms",
          "the rescue drills", "the closing notes"]


def lighthouse_report() -> bytes:
    """20 pages, ~1,600 characters each (≈ 8,000 tokens: a card, not inline). Only page 7 names the cat."""
    pages = []
    for i, topic in enumerate(TOPICS):
        lines = [f"Section {i + 1}: {topic.capitalize()}"]
        lines += [f"Line {k}: the inspectors noted that {topic} at the North Rock light was in fair order this season." for k in range(18)]
        if i == 6:
            lines[9] = "Line 8: the keeper's cat, a grey tabby named Biscuit, sleeps by the lamp room door."
        pages.append("\n".join(lines))
    return pdf(pages)
