"""The agent's local tools: ask_user, update_todos, find_tools, load_tools, read_skill,
view_output, read_result, remember."""

from __future__ import annotations

import base64
import io
import json
import re
from typing import TYPE_CHECKING, Any

from . import context as ctx
from .knowledge import Knowledge

if TYPE_CHECKING:
    from .loop import Agent
    from .tools import ToolSet

MAX_SIDE = 1024
REF = re.compile(r"^#?(\d+)$")
TEXT_PEEK = 2000  # view_output on a text or document output: this many characters, then hub_read_document


class Local:
    def __init__(self, agent: Agent) -> None:
        self.a = agent

    def ok(self, tid: str, cid: str, name: str, content: Any, **extra: Any) -> str:
        text = content if isinstance(content, str) else json.dumps(content, ensure_ascii=False, default=str)
        self.a._result(tid, cid, name, {"status": "done", "content": text, **extra})
        return "ok"

    def err(self, tid: str, cid: str, name: str, code: str, detail: str, fix: str | None = None) -> str:
        e = {"code": code, "detail": detail, **({"fix": fix} if fix else {})}
        self.a._result(tid, cid, name, {"status": "error", "error": e})
        return "ok"

    async def run(self, tid: str, cid: str, name: str, args: dict[str, Any], tools: ToolSet, thread: dict[str, Any]) -> str:
        fn = getattr(self, f"t_{name}")
        try:
            return await fn(tid, cid, args, tools, thread)
        except (KeyError, TypeError, ValueError) as e:
            return self.err(tid, cid, name, "invalid_arguments", f"{type(e).__name__}: {e}", "check the tool's parameters")

    # ---- ask_user ----------------------------------------------------------------------------

    async def t_ask_user(self, tid: str, cid: str, args: dict[str, Any], tools: ToolSet, thread: dict[str, Any]) -> str:
        if self.a._find(tid, "question", cid):
            return "waiting"   # still waiting for the answer
        qs = args.get("questions")
        problems = []
        if not isinstance(qs, list) or not 1 <= len(qs) <= 4:
            problems.append("questions: send 1–4 questions")
        else:
            for i, q in enumerate(qs):
                if not isinstance(q, dict) or not str(q.get("question") or "").strip():
                    problems.append(f"questions[{i}].question is required")
                    continue
                opts = q.get("options")
                if not isinstance(opts, list) or not 2 <= len(opts) <= 4:
                    problems.append(f"questions[{i}].options: give 2–4 options")
                else:
                    q["options"] = [o if isinstance(o, dict) else {"label": str(o)} for o in opts]
        if problems:
            return self.err(tid, cid, "ask_user", "invalid_arguments", "; ".join(problems),
                            'e.g. {"questions": [{"question": "Which style?", "header": "Style", "options": [{"label": "Photo"}, {"label": "Ink"}]}]}')
        self.a.emit(tid, "question", {"id": cid, "questions": qs})
        return "waiting"

    # ---- todos -------------------------------------------------------------------------------

    async def t_update_todos(self, tid: str, cid: str, args: dict[str, Any], tools: ToolSet, thread: dict[str, Any]) -> str:
        items = [{"text": str(i.get("text", ""))[:200], "state": i.get("state", "pending")}
                 for i in args.get("items") or [] if isinstance(i, dict)]
        if not items:
            return self.err(tid, cid, "update_todos", "invalid_arguments", "items: send the whole list")
        for i in items:
            if i["state"] not in ("pending", "in_progress", "done", "failed"):
                i["state"] = "pending"
        self.a.emit(tid, "todos", {"items": items})
        done = sum(i["state"] == "done" for i in items)
        return self.ok(tid, cid, "update_todos", f"Checklist saved ({done}/{len(items)} done).")

    # ---- tools on demand ---------------------------------------------------------------------

    async def t_find_tools(self, tid: str, cid: str, args: dict[str, Any], tools: ToolSet, thread: dict[str, Any]) -> str:
        query = str(args.get("query") or "")
        hits = await self.a.hub.search(query)
        off = sorted({h["mod"] for h in hits if h["mod"] in tools.disabled} | {g for g in tools.disabled if g in query.lower()})
        hits = [h for h in hits if h["mod"] not in tools.disabled]
        if not hits:
            groups = sorted({t["mod"] for t in tools.index} - tools.disabled)
            return self.ok(tid, cid, "find_tools", (_off_note(off) + " " if off else "") +
                           "No tools match. The groups are: " + ", ".join(groups))
        return self.ok(tid, cid, "find_tools", {"tools": [{"name": h["name"], "summary": h["summary"], "risk": h["risk"],
                                                           "loaded": h["name"] in tools.full} for h in hits],
                                                "next": "load_tools with the names you need"})

    async def t_load_tools(self, tid: str, cid: str, args: dict[str, Any], tools: ToolSet, thread: dict[str, Any]) -> str:
        names = args.get("names") or []
        if isinstance(names, str):
            names = [n.strip() for n in names.split(",")]
        group = args.get("group")
        if group and group in tools.disabled:
            return self.err(tid, cid, "load_tools", "disabled", _off_note([group]),
                            "don't try again; tell the user, who can turn the group back on in the composer")
        ok, bad = tools.load(names, group)
        await tools.refresh()
        self.a._save_loaded(tid, tools)
        out: dict[str, Any] = {"loaded": ok}
        off = sorted({t["mod"] for n in bad if (t := tools.by_name(n)) and t["mod"] in tools.disabled})
        bad = [n for n in bad if not ((t := tools.by_name(n)) and t["mod"] in tools.disabled)]
        if off:
            out["turned_off"] = _off_note(off) + " Don't try again; tell the user, who can turn them back on in the composer."
        if bad:
            out["unknown"] = bad
            out["fix"] = "use find_tools to get exact names"
        return self.ok(tid, cid, "load_tools", out)

    # ---- skills, memory ----------------------------------------------------------------------

    async def t_read_skill(self, tid: str, cid: str, args: dict[str, Any], tools: ToolSet, thread: dict[str, Any]) -> str:
        k = Knowledge(self.a.cfg.data, self.a.hub)
        name = str(args.get("name") or "")
        mod = name.split("/", 1)[0] if "/" in name else next((s["source"] for s in await k.skills() if s["name"] == name), None)
        if mod in tools.disabled:                      # a turned-off mod's skill is about tools this chat can't use
            return self.err(tid, cid, "read_skill", "disabled", f"the {mod} tools are turned off in this chat",
                            "tell the user it's turned off; they can turn it back on in the composer")
        body = await k.read(name)
        if body is None:
            return self.err(tid, cid, "read_skill", "not_found", f"no skill {name!r}", "the skill list is in your instructions")
        return self.ok(tid, cid, "read_skill", body)

    async def t_remember(self, tid: str, cid: str, args: dict[str, Any], tools: ToolSet, thread: dict[str, Any]) -> str:
        text = str(args.get("text") or "").strip()
        if not text:
            return self.err(tid, cid, "remember", "invalid_arguments", "text is empty")
        if (thread.get("settings") or {}).get("dry_run"):     # an eval thread: never touch the real memory
            self.a.emit(tid, "memory", {"text": text, "topic": args.get("topic"), "dry_run": True})
            return self.ok(tid, cid, "remember", "Saved to memory.")
        topic = args.get("topic")
        try:                                   # a preference in the hub, for every chat (plan 21.4)
            p = await self.a.hub.create_pref({"value": text, "cue": topic or "", "source": "stated",
                                              "evidence": [{"kind": "thread", "ref": tid}]})
        except Exception as e:  # noqa: BLE001: learning off, or the hub away: keep the old file
            Knowledge(self.a.cfg.data, self.a.hub).remember(text, topic)
            self.a.emit(tid, "memory", {"text": text, "topic": topic, "file": True})
            return self.ok(tid, cid, "remember", f"Saved to memory ({type(e).__name__}: kept in the memory file).")
        self.a.emit(tid, "memory", {"text": text, "topic": topic, "pref_id": p.get("id")})
        return self.ok(tid, cid, "remember", "Saved: it's one of the user's preferences now.")

    # ---- outputs -----------------------------------------------------------------------------

    def resolve_ref(self, tid: str, ref: str) -> str | None:
        ref = ref.strip()
        if ref.startswith("output:"):
            return ref[7:]
        m = REF.match(ref)
        if m:
            n = int(m.group(1))
            for o in ctx.outputs(self.a.store.events(tid, types=("tool_result", "user"))):
                if o.get("n") == n:
                    return o["output_id"]
            return None
        return ref if re.fullmatch(r"[0-9a-f]{12}", ref) else None

    async def t_view_output(self, tid: str, cid: str, args: dict[str, Any], tools: ToolSet, thread: dict[str, Any]) -> str:
        ref = str(args.get("ref") or "")
        oid = self.resolve_ref(tid, ref)
        if not oid:
            return self.err(tid, cid, "view_output", "unknown_output", f"{ref!r} isn't an output in this chat",
                            "use #n from the outputs table, or output:<id>")
        try:
            o = await self.a.hub.output(oid)
        except Exception:  # noqa: BLE001
            return self.err(tid, cid, "view_output", "unknown_output", f"output {oid} is gone (deleted?)")
        info = {"title": o["title"], "kind": o["kind"], "meta": {k: v for k, v in (o.get("meta") or {}).items()
                                                                  if k in ("prompt", "model", "params", "seed", "voice", "source")},
                "dims": o.get("dims"), "duration_s": o.get("duration_s")}
        model = thread.get("model") or self.a.cfg.model
        meta = await self.a.llm.meta(model)
        if o["kind"] in ("text", "document"):
            return await self._view_text(tid, cid, oid, o, info, args.get("page"), meta.get("vision") is not False)
        visual = o["kind"] == "image" or (o["kind"] in ("video", "model3d") and o.get("preview"))
        if not visual or meta.get("vision") is False:
            why = "this model can't see images" if visual else f"a {o['kind']} has no picture to show"
            return self.ok(tid, cid, "view_output", {"note": f"{why}; here are its details", **info})
        try:
            data, ctype = await self.a.hub.output_bytes(oid, preview=o["kind"] != "image")
            url = to_data_url(data)
        except Exception as e:  # noqa: BLE001
            return self.ok(tid, cid, "view_output", {"note": f"couldn't load the picture ({e}); here are its details", **info})
        return self.ok(tid, cid, "view_output", {"note": "the picture follows", **info}, image={"output_id": oid, "url": url,
                                                                                            "label": o["title"]})

    async def _view_text(self, tid: str, cid: str, oid: str, o: dict[str, Any], info: dict[str, Any], page: Any,
                         vision: bool) -> str:
        """A text or document output: a PDF page as an image (`page`), else the start of its text (plan 24.4)."""
        name = f"output:{oid} {o['title']}"
        info = {k: v for k, v in info.items() if v is not None and k not in ("dims", "duration_s")} | {"subtype": o.get("subtype")}
        if page is not None:
            n = int(page)
            if o.get("subtype") != "pdf":
                return self.err(tid, cid, "view_output", "no_page", f"{name} is not a PDF, so it has no pages",
                                "read it with hub_read_document")
            if not vision:
                w = await self.a.hub.output_text(oid, page=n, limit=6000)
                return self.ok(tid, cid, "view_output", "This model can't see images; here is the page's text.\n"
                               + ctx.untrusted(f"{name} p.{n}", w["text"]))
            try:
                data = await self.a.hub.output_page(oid, n)
            except Exception as e:  # noqa: BLE001: no_page and the like
                return self.err(tid, cid, "view_output", getattr(e, "code", "no_page"), str(e), "check the page number")
            return self.ok(tid, cid, "view_output", {"note": f"page {n} of the PDF follows as an image", **info},
                           image={"output_id": oid, "url": to_data_url(data), "label": f"{o['title']} p.{n}"})
        try:
            w = await self.a.hub.output_text(oid, limit=TEXT_PEEK)
        except Exception as e:  # noqa: BLE001
            return self.ok(tid, cid, "view_output", {"note": f"couldn't read its text ({e})", **info})
        size = f"{w['pages']} pages, " if w["pages"] else f"{w['lines']} lines, "
        head = (f"{name} ({o.get('subtype') or o['kind']}, {size}~{w['tokens']:,} tokens). The first {len(w['text']):,} "
                f"characters follow; read the rest with hub_read_document(ref, offset={w['next_offset']})" if w["next_offset"] is not None
                else f"{name} ({o.get('subtype') or o['kind']}, {size}~{w['tokens']:,} tokens), all of it:")
        if w["scanned"]:
            head += f". Pages without text (scanned): {', '.join(map(str, w['scanned'][:20]))}; view_output(ref, page=N) shows one"
        return self.ok(tid, cid, "view_output", head + "\n" + ctx.untrusted(name, w["text"]))

    def images(self, events: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
        return {e["seq"]: e["payload"]["image"] for e in events if e["type"] == "tool_result" and e["payload"].get("image")}

    async def t_read_result(self, tid: str, cid: str, args: dict[str, Any], tools: ToolSet, thread: dict[str, Any]) -> str:
        seq = int(args["seq"])
        off, lim = int(args.get("offset") or 0), min(int(args.get("limit") or 12000), 40000)
        e = self.a.store.event(tid, seq)
        if e is None or e["type"] != "tool_result":
            return self.err(tid, cid, "read_result", "not_found", f"event {seq} isn't a tool result")
        p = e["payload"]
        if p.get("call_id"):
            try:
                page = await self.a.hub.call_result(p["call_id"], off, lim)
                return self.ok(tid, cid, "read_result", {"seq": seq, "offset": off, "total": page["total"], "text": page["text"]})
            except Exception:  # noqa: BLE001 - fall back to what the thread kept
                pass
        text = p.get("content") if isinstance(p.get("content"), str) else json.dumps(p.get("content"))
        return self.ok(tid, cid, "read_result", {"seq": seq, "offset": off, "total": len(text or ""), "text": (text or "")[off:off + lim]})


def to_data_url(data: bytes) -> str:
    """An image as a JPEG data URL, at most MAX_SIDE pixels on its long side."""
    try:
        from PIL import Image

        im = Image.open(io.BytesIO(data))
        im = im.convert("RGB")
        im.thumbnail((MAX_SIDE, MAX_SIDE))
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=85)
        data = buf.getvalue()
    except Exception:  # noqa: BLE001 - send it as it is
        pass
    return "data:image/jpeg;base64," + base64.b64encode(data).decode()


def _off_note(groups: list[str]) -> str:
    return f"The {', '.join(groups)} tools are turned off in this chat, so they can't be loaded or used."
