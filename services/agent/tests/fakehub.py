"""A small stand-in for AIHub's tools API (the real one is tested in utils/tests/tools): the index,
schemas, calls with permissions and approvals, jobs, outputs, skills and the event stream.

Tools: hub_list_services (core, read), fake_get (read), fake_make_image (generate, asks aspect),
fake_render (generate job, `seconds`), fake_wipe (destructive), fake_fail (read, errors),
gen3d_make_3d (generate job), tts_speak (generate).
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import time
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import Response, StreamingResponse

PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAQAAAAECAIAAAAmkwkpAAAAEElEQVR4nGP4z8AARAwQBQA/5Qf8oNBe9QAAAABJRU5ErkJggg==")


def T(name: str, mod: str, risk: str, props: dict[str, Any], required: list[str] | None = None, core: bool = False,
      ask: list[str] | None = None, job: bool = False, desc: str = "") -> dict[str, Any]:
    return {"name": name, "mod": mod, "risk": risk, "core": core, "summary": desc or name, "available": True,
            "description": desc or name, "parameters": {"type": "object", "properties": props, "required": required or [],
                                                         "additionalProperties": False},
            "ask": ask or [], "examples": [], "job": job, "source": "manifest"}


TOOLS = [
    T("hub_list_services", "hub", "read", {}, core=True, desc="List the mods"),
    T("fake_get", "fake", "read", {"id": {"type": "string"}}, ["id"], desc="Read one item"),
    T("fake_make_image", "fake", "generate", {"prompt": {"type": "string"}, "aspect": {"type": "string", "enum": ["1:1", "16:9"]},
                                               "image": {"type": "string", "format": "aihub-file", "x-kind": "image"}},
      ["prompt"], ask=["aspect"], desc="Make an image from text"),
    T("fake_render", "fake", "generate", {"prompt": {"type": "string"}, "seconds": {"type": "number"}}, ["prompt"], job=True,
      desc="Render a video job"),
    T("fake_wipe", "fake", "destructive", {"id": {"type": "string"}}, ["id"], desc="Delete an item"),
    T("fake_fail", "fake", "read", {}, desc="Always fails"),
    T("gen3d_make_3d", "gen3d", "generate", {
        "prompt": {"type": "string"}, "image": {"type": "string", "format": "aihub-file", "x-kind": "image"},
        "engine": {"type": "string", "enum": ["cube3d", "trellis2", "hunyuan21", "sam3d_body"], "x-options": {   # plan 20.4
            "cube3d": {"label": "Cube3D", "excludes": ["image"], "default": True, "good_for": "a mesh from text"},
            "trellis2": {"label": "TRELLIS.2", "needs": ["image"], "default": True, "good_for": "objects"},
            "hunyuan21": {"label": "Hunyuan3D 2.1", "needs": ["image"], "good_for": "characters"},
            "sam3d_body": {"label": "SAM 3D Body", "needs": ["image"], "good_for": "a person's body"}}}},
      job=True, ask=["engine"], desc="Make a 3D model from text or a picture"),
    T("tts_speak", "tts", "generate", {"text": {"type": "string"}, "name": {"type": "string"}}, ["text"], ask=["name"],
      desc="Speak text aloud"),
]


def _model_view(t: dict[str, Any]) -> dict[str, Any]:
    props = {k: {kk: vv for kk, vv in p.items() if kk != "x-options"} for k, p in t["parameters"]["properties"].items()}
    return {**t, "parameters": {**t["parameters"], "properties": props}}


class FakeHub:
    def __init__(self) -> None:
        self.tools = {t["name"]: t for t in TOOLS}
        self.calls: list[dict[str, Any]] = []         # every executed call: {name, arguments, mode}
        self.attempts: list[dict[str, Any]] = []      # every call request
        self.approvals: dict[str, dict[str, Any]] = {}
        self.running: dict[str, dict[str, Any]] = {}
        self.outputs: dict[str, dict[str, Any]] = {}
        self.cancelled: list[str] = []
        self.views: list[str] = []                    # the `view` each GET /api/tools asked for
        self.subs: set[asyncio.Queue[dict[str, Any]]] = set()
        self.skills = {("fake", "drawing"): {"description": "How to pick image settings", "body": "Use 16:9 for landscapes."}}
        self.app = self._app()
        self.n = 0

    def publish(self, ev: dict[str, Any]) -> None:
        for q in list(self.subs):
            q.put_nowait(ev)

    def _output(self, kind: str, title: str, prompt: str) -> dict[str, Any]:
        self.n += 1
        oid = hashlib.sha1(f"{title}{self.n}".encode()).hexdigest()[:12]
        o = {"id": oid, "service": "fake", "kind": kind, "title": title, "url": f"/api/outputs/{oid}/file",
             "preview": f"/api/outputs/{oid}/preview", "meta": {"prompt": prompt}, "files": [], "created_ts": time.time(),
             "size_bytes": len(PNG), "path": f"outputs/fake/{oid}.png"}
        self.outputs[oid] = o
        return {"output_id": oid, "ref": f"output:{oid}", "kind": kind, "title": title, "url": o["url"],
                "preview": o["preview"], "summary": title, "prompt": prompt}

    async def _execute(self, cid: str, name: str, args: dict[str, Any], mode: str) -> dict[str, Any]:
        self.calls.append({"name": name, "arguments": args, "mode": mode, "call_id": cid})
        if name == "fake_fail":
            return {"status": "error", "call_id": cid, "tool": name, "error": {"code": "upstream_error", "detail": "it broke", "fix": "try later"}}
        if name == "fake_make_image":
            return {"status": "done", "call_id": cid, "tool": name, "result": {"aspect": args.get("aspect")},
                    "outputs": [self._output("image", args["prompt"], args["prompt"])]}
        if name == "tts_speak":
            return {"status": "done", "call_id": cid, "tool": name, "result": {"voice": args.get("name")},
                    "outputs": [self._output("audio", args["text"][:40], args["text"])]}
        if name in ("fake_render", "gen3d_make_3d"):
            await asyncio.sleep(float(args.get("seconds") or 0.3))
            kind = "video" if name == "fake_render" else "model3d"
            return {"status": "done", "call_id": cid, "tool": name, "result": {"state": "done"},
                    "outputs": [self._output(kind, args["prompt"], args["prompt"])]}
        if name == "hub_list_services":
            return {"status": "done", "call_id": cid, "tool": name, "result": {"services": [{"id": "fake", "state": "ready"}]}}
        return {"status": "done", "call_id": cid, "tool": name, "result": {"ok": True, **args}}

    def _start(self, name: str, args: dict[str, Any], mode: str) -> dict[str, Any]:
        cid = f"call_{len(self.running) + len(self.calls) + 1}_{int(time.time() * 1000) % 100000}"
        st: dict[str, Any] = {"status": "running", "call_id": cid, "tool": name, "progress": 0.0}

        async def run() -> None:
            try:
                st.update(await self._execute(cid, name, args, mode))
            except asyncio.CancelledError:
                st.update({"status": "cancelled"})
                self.cancelled.append(cid)

        st["task"] = asyncio.create_task(run())
        self.running[cid] = st
        return st

    @staticmethod
    def public(st: dict[str, Any]) -> dict[str, Any]:
        return {k: v for k, v in st.items() if k != "task"}

    async def _wait(self, st: dict[str, Any], wait: float) -> dict[str, Any]:
        try:
            await asyncio.wait_for(asyncio.shield(st["task"]), timeout=wait)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            pass
        return self.public(st)

    def _app(self) -> FastAPI:
        app = FastAPI()

        @app.get("/api/tools/index")
        def index() -> list:
            return [{k: t[k] for k in ("name", "mod", "risk", "core", "summary", "available")} for t in self.tools.values()]

        @app.get("/api/tools")
        def tools(names: str | None = None, q: str | None = None, view: str = "full") -> list:
            self.views.append(view)
            if view == "model":                        # the hub writes x-options into the descriptions; here they're just dropped
                return [_model_view(t) for t in tools_full(names, q)]
            return tools_full(names, q)

        def tools_full(names: str | None, q: str | None) -> list:
            if q is not None:
                words = q.lower().split()
                return [t for t in self.tools.values() if any(w in (t["name"] + t["description"]).lower() for w in words)][:8]
            if names:
                want = names.split(",")
                missing = [n for n in want if n not in self.tools]
                if missing:
                    raise HTTPException(404, {"code": "unknown_tool"})
                return [self.tools[n] for n in want]
            return list(self.tools.values())

        @app.post("/api/tools/{name}/call")
        async def call(name: str, request: Request, wait: float = 1800) -> dict:
            body = await request.json()
            args, mode = body.get("arguments") or {}, body.get("mode") or "ask"
            self.attempts.append({"name": name, "arguments": args, "mode": mode, "origin": body.get("origin")})
            t = self.tools.get(name)
            if t is None:
                return {"status": "error", "tool": name, "error": {"code": "unknown_tool", "detail": f"no tool {name}"}}
            filled = []
            for k, p in t["parameters"]["properties"].items():     # x-options defaults, as the hub fills them (plan 20.1)
                o = p.get("x-options") or {}
                if k not in args and o:
                    pick = next((v for v, x in o.items() if x.get("default") and all(n in args for n in x.get("needs", []))
                                 and not any(n in args for n in x.get("excludes", []))), None)
                    if pick:
                        args = {**args, k: pick}
                        filled.append(k)
            missing = [r for r in t["parameters"]["required"] if r not in args]
            if missing:
                return {"status": "error", "tool": name, "error": {"code": "invalid_arguments", "detail": f"{missing[0]} is required",
                                                                   "fix": f"add {missing[0]}"}}
            risk = t["risk"]
            if mode == "read_only" and risk != "read":
                return {"status": "denied", "tool": name, "error": {"code": "denied", "detail": "read-only"}}
            if risk != "read" and not (mode == "auto" and risk != "destructive"):
                aid = f"ap_{len(self.approvals) + 1}"
                a = {"id": aid, "tool": name, "arguments": args, "ask_fields": t["ask"], "risk": risk, "origin": body.get("origin") or {},
                     "state": "pending", "created_ts": time.time(), "call_id": None, "final": None}
                self.approvals[aid] = a
                self.publish({"type": "approval", "approval": a})
                return {**({"filled": filled} if filled else {}), "status": "needs_approval", "tool": name, "approval_id": aid, "arguments": args, "ask_fields": t["ask"],
                        "risk": risk, "schema": t["parameters"], "description": t["description"]}
            return await self._wait(self._start(name, args, mode), wait)

        @app.get("/api/tools/calls/{cid}")
        async def call_status(cid: str, wait: float = 0) -> dict:
            st = self.running.get(cid)
            if st is None:
                raise HTTPException(404, "no call")
            return await self._wait(st, wait)

        @app.post("/api/tools/calls/{cid}/cancel")
        async def cancel(cid: str) -> dict:
            st = self.running.get(cid)
            if st is None:
                raise HTTPException(404, "no call")
            st["task"].cancel()
            await asyncio.gather(st["task"], return_exceptions=True)
            return self.public(st)

        @app.get("/api/tools/calls/{cid}/result")
        def call_result(cid: str, offset: int = 0, limit: int = 8000) -> dict:
            st = self.running[cid]
            text = json.dumps(st.get("result"))
            return {"call_id": cid, "offset": offset, "limit": limit, "total": len(text), "text": text[offset:offset + limit]}

        @app.get("/api/approvals/{aid}")
        def approval(aid: str) -> dict:
            return self.approvals[aid]

        @app.post("/api/approvals/{aid}")
        async def decide(aid: str, request: Request, wait: float = 0) -> Any:
            body = await request.json()
            a = self.approvals.get(aid)
            if a is None:
                raise HTTPException(404, "no approval")
            if a["state"] != "pending":
                return Response(json.dumps({"detail": "already decided", "code": "already_decided"}), 409, media_type="application/json")
            args = body.get("arguments") if body.get("arguments") is not None else a["arguments"]
            t = self.tools[a["tool"]]
            if "aspect" in args and args["aspect"] not in t["parameters"]["properties"].get("aspect", {}).get("enum", [args["aspect"]]):
                return Response(json.dumps({"detail": "aspect: not allowed", "code": "invalid_arguments"}), 422, media_type="application/json")
            if not body.get("approve"):
                a.update(state="denied", reason=body.get("reason"))
                self.publish({"type": "approval", "approval": a})
                return {"status": "denied", "tool": a["tool"], "approval_id": aid,
                        "error": {"code": "denied_by_user", "detail": body.get("reason") or "the user said no"}}
            st = self._start(a["tool"], args, "approved")
            a.update(state="approved", final=args, call_id=st["call_id"])
            self.publish({"type": "approval", "approval": a})
            return await self._wait(st, wait)

        @app.get("/api/outputs/{oid}")
        def output(oid: str) -> dict:
            if oid not in self.outputs:
                raise HTTPException(404, "no output")
            return self.outputs[oid]

        @app.get("/api/outputs/{oid}/file")
        @app.get("/api/outputs/{oid}/preview")
        def output_file(oid: str) -> Response:
            if oid not in self.outputs:
                raise HTTPException(404, "no output")
            return Response(PNG, media_type="image/png")

        @app.get("/api/services")
        def services() -> list:
            return [{"id": "fake", "name": "Fake", "state": "ready", "load": "loaded"}]

        @app.get("/api/memory")
        def memory() -> dict:
            return {"total_bytes": 128e9, "available_bytes": 90e9}

        @app.get("/api/skills")
        def skills() -> list:
            return [{"mod": m, "name": n, "description": s["description"]} for (m, n), s in self.skills.items()]

        @app.get("/api/skills/{mod}/{name}")
        def skill(mod: str, name: str) -> dict:
            s = self.skills.get((mod, name))
            if s is None:
                raise HTTPException(404, "no skill")
            return {"mod": mod, "name": name, **s}

        @app.get("/api/events")
        async def events(request: Request) -> StreamingResponse:
            q: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
            self.subs.add(q)

            async def gen():
                try:
                    yield ": hi\n\n"
                    while True:
                        try:
                            ev = await asyncio.wait_for(q.get(), timeout=1)
                        except asyncio.TimeoutError:
                            yield ": ping\n\n"
                            continue
                        yield f"data: {json.dumps(ev)}\n\n"
                finally:
                    self.subs.discard(q)

            return StreamingResponse(gen(), media_type="text/event-stream")

        return app
