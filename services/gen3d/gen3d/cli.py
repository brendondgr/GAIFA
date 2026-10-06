"""Terminal job commands behind `gen3d make` / `gen3d jobs` (stdlib only: talks to the running API)."""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request


def _call(url: str, method: str = "GET", body: dict | None = None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={"content-type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        sys.exit(f"gen3d: {e.code} {e.read().decode(errors='replace')}")


def fmt_s(s: float | None) -> str:
    if s is None:
        return "-"
    s = int(round(s))
    return f"{s // 60}m{s % 60:02d}s" if s >= 60 else f"{s}s"


def _line(j: dict) -> str:
    eta = j.get("eta") or {}
    st = j["status"]
    if st == "running":
        cur = next((f"{k}:{v.get('sub') or ''} {v.get('step') or ''}/{v.get('total') or ''}".rstrip("/ ")
                    for k, v in j["stages"].items() if v.get("state") == "running"), "")
        st = f"running {cur}  done in {fmt_s(eta.get('eta_s'))}"
    elif st == "queued":
        st = f"queued #{eta.get('queue_position', '?')}  done in {fmt_s(eta.get('eta_s'))}"
    elif st == "failed":
        st = f"failed: {j.get('error')}"
    return f"{j['id']}  {time.strftime('%H:%M', time.localtime(j['created']))}  {(j.get('title') or '')[:40]:40s}  {st}"


def make(a) -> None:
    stages = ["shape"]
    parts = [p.strip() for p in (a.parts or "").split(",") if p.strip()]
    if parts:
        stages.append("parts")
    if a.rig:
        stages.append("rig")
    if not a.no_preview:
        stages.append("preview")
    body = {"prompt": a.prompt, "stages": stages, "preset": a.preset, "chat_id": a.chat or "new",
            "shape": {k: v for k, v in {"seed": a.seed, "resolution_base": a.res,
                                        "bbox": a.bbox}.items() if v is not None},
            "parts": {"parts": parts, **({"steps": a.steps} if a.steps else {})}}
    if a.deterministic:
        body["shape"]["top_p"] = None
    job = _call(f"{a.url}/v1/jobs", "POST", body)
    print(_line(job))
    print(f"  files: {a.url}/v1/jobs/{job['id']}/download   ui: {a.url}/ui/#{job['chat_id']}")
    if a.wait:
        last = ""
        while True:
            time.sleep(2)
            job = _call(f"{a.url}/v1/jobs/{job['id']}")
            line = _line(job)
            if line != last:
                print("\r" + line[:150].ljust(150), end="", flush=True)
                last = line
            if job["status"] in ("done", "failed", "canceled"):
                print()
                break
        if job["status"] == "done":
            for f in job["files"]:
                print(f"  {a.url}/v1/jobs/{job['id']}/files/{f}")


def jobs(a) -> None:
    for j in reversed(_call(f"{a.url}/v1/jobs?limit={a.n}")["jobs"]):
        print(_line(j))


def main() -> None:
    p = argparse.ArgumentParser(prog="gen3d")
    sub = p.add_subparsers(dest="cmd", required=True)
    m = sub.add_parser("make")
    m.add_argument("prompt")
    m.add_argument("--url", required=True)
    m.add_argument("--parts", help='comma-separated part names, e.g. "seat, backrest, legs"')
    m.add_argument("--rig", action="store_true", help="rig the parts for games")
    m.add_argument("--preset", choices=["lowpoly", "fast", "balanced", "quality"])
    m.add_argument("--seed", type=int)
    m.add_argument("--res", type=float, help="shape resolution_base (7-9)")
    m.add_argument("--steps", type=int, help="CubePart steps")
    m.add_argument("--bbox", type=float, nargs=3, metavar=("W", "H", "D"))
    m.add_argument("--deterministic", action="store_true", help="argmax decoding (top_p = null)")
    m.add_argument("--chat", help="add to this chat id (default: a new chat)")
    m.add_argument("--no-preview", action="store_true")
    m.add_argument("--wait", action="store_true", help="follow progress until done")
    j = sub.add_parser("jobs")
    j.add_argument("n", nargs="?", type=int, default=15)
    j.add_argument("--url", required=True)
    a = p.parse_args()
    {"make": make, "jobs": jobs}[a.cmd](a)


if __name__ == "__main__":
    main()
