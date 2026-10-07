"""`python -m evals.vision [models…]`: can each model see images (plan 13.5's vision check)?

Draws a test card (a red circle, a green square and the number 47 on a blue background), asks the
model what it sees, and checks the answer names them.
"""

from __future__ import annotations

import asyncio
import base64
import io
import json
import sys
import time

import httpx
from PIL import Image, ImageDraw


def card() -> str:
    im = Image.new("RGB", (512, 512), (30, 60, 160))
    d = ImageDraw.Draw(im)
    d.ellipse((60, 60, 220, 220), fill=(220, 30, 30))
    d.rectangle((300, 300, 460, 460), fill=(30, 200, 60))
    d.text((300, 120), "47", fill=(255, 255, 255), font_size=96) if hasattr(d, "text") else None
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


async def check(model: str, url: str = "http://127.0.0.1:4000/v1") -> dict:
    msg = [{"role": "user", "content": [{"type": "text", "text": "List the shapes with their colors, and the number written in this image. Answer in one line."},
                                        {"type": "image_url", "image_url": {"url": card()}}]}]
    t0 = time.time()
    async with httpx.AsyncClient(timeout=300, trust_env=False) as c:
        r = await c.post(url + "/chat/completions", json={"model": model, "messages": msg})
    out = {"model": model, "status": r.status_code, "seconds": round(time.time() - t0, 1)}
    if r.status_code != 200:
        out["error"] = r.text[:300]
        out["vision"] = False
        return out
    text = (r.json()["choices"][0]["message"].get("content") or "").lower()
    out["answer"] = text[:300]
    hits = {"red circle": "red" in text and "circle" in text, "green square": "green" in text and "square" in text, "47": "47" in text}
    out["hits"] = hits
    out["vision"] = sum(hits.values()) >= 2
    return out


async def main(models: list[str]) -> None:
    res = [await check(m) for m in models]
    print(json.dumps(res, indent=1))


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1:] or ["skynet", "gemma4-26B"]))
