"""The agent's local tools: ask_user, update_todos, find_tools, load_tools, read_skill,
view_output, read_result, chat_search, memory_search, remember; and a project chat's (projects/tools.py)."""

from __future__ import annotations

import base64
import io
import json
import re
from typing import TYPE_CHECKING, Any

from . import context as ctx
from . import show, skillfmt
from .knowledge import Knowledge
from .projects.tools import ProjectTools
from .tasks.notes import TaskTools

if TYPE_CHECKING:
    from .loop import Agent
    from .tools import ToolSet

MAX_SIDE = 1024
REF = re.compile(r"^#?(\d+)$")
TEXT_PEEK = 2000  # view_output on a text or document output: this many characters, then hub_read_document
# view_output on a dry run's stand-in, in a dry-run chat (the eval): its picture is a labelled card or another
# output's preview, and a model that looks at it retries or gives up on a chain the eval means to test
STAND_IN = ("a dry-run stand-in: this chat is an evaluation, so nothing was generated and there is no picture to "
            "look at. Treat it as a good result of its prompt and carry on as you would with the real output")


class Local(ProjectTools, TaskTools):
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
        if (thread.get("settings") or {}).get("unattended"):       # a scheduled run (scheduled-tasks 2.4): no one to answer
            return self.err(tid, cid, "ask_user", "unattended", "this is a scheduled run and no one is here to answer",
                            "decide yourself, carry on, and say in your summary what you assumed")
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
        from .tools import group_of, hidden_group
        hits = await self.a.hub.search(query)
        off = sorted({h["mod"] for h in hits if h["mod"] in tools.disabled} | {g for g in tools.disabled if g in query.lower()})
        named = query.lower()                       # mcp-client 4.1: a hidden server's tools only when the query names it
        hits = [h for h in hits if not tools.off(h) and not (tools.hidden(h) and group_of(h)[4:].lower() not in named)]
        if not hits:
            groups = sorted({group_of(t) for t in tools.index if not tools.off(t)
                             and (not hidden_group(group_of(t)) or not tools.hidden(t))})
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
        if ":" in name.split("/", 1)[0] and not name.startswith("memory:"):
            mod = "workspace"                          # a workspace folder's skill (skill-sources 2.2)
        if mod in tools.disabled:                      # a turned-off mod's skill is about tools this chat can't use
            return self.err(tid, cid, "read_skill", "disabled", f"the {mod} tools are turned off in this chat",
                            "tell the user it's turned off; they can turn it back on in the composer")
        try:
            from .projects.origin import chat_envs
            body = await k.read(name, tid, chat_envs(thread.get("settings"), self.a.projects) or None)   # plan projects 2.2
        except skillfmt.SkillFileError as e:
            return self.err(tid, cid, "read_skill", e.code, e.detail, "the skill's files are listed after its body")
        if body is None:
            return self.err(tid, cid, "read_skill", "not_found", f"no skill {name!r}", "the skill list is in your instructions")
        return self.ok(tid, cid, "read_skill", body + await self._skill_servers(tid, k, name, tools))

    async def _skill_servers(self, tid: str, k: Knowledge, name: str, tools: ToolSet) -> str:
        """mcp-client 4.1: a skill that names MCP servers (`metadata.mcp-servers`) turns their tools on in this chat."""
        servers = skillfmt.mcp_servers(await k.meta(name))
        if not servers:
            return ""
        from .tools import group_of
        notes = []
        for sid in servers:
            g = f"mcp:{sid}"
            if any(group_of(t) == g for t in tools.index):
                if g in tools.disabled:
                    notes.append(f"The MCP server {sid} is turned off in this chat: tell the user, who can turn it on in the composer.")
                    continue
                ok, _ = tools.load(group=g)
                notes.append(f"The MCP server {sid}'s tools are loaded: {', '.join(ok)}.")
            else:
                notes.append(f"This skill uses the MCP server {sid}, which isn't set up and approved in GAIFA: tell the user to "
                             "add it and approve its tools on the MCP servers page.")
        await tools.refresh()
        self.a._save_loaded(tid, tools)
        return "\n\n---\n" + "\n".join(notes)

    async def t_remember(self, tid: str, cid: str, args: dict[str, Any], tools: ToolSet, thread: dict[str, Any]) -> str:
        """Only an empty text or an eval's thread ends here: the loop runs `remember` as the agent mod's
        agent_memory_save through the hub, so the chat's mode and permissions decide it like any write (structured-memory 3.2)."""
        text = str(args.get("text") or "").strip()
        if not text:
            return self.err(tid, cid, "remember", "invalid_arguments", "text is empty")
        if not (thread.get("settings") or {}).get("dry_run"):
            return self.err(tid, cid, "remember", "unavailable", "remember runs through the hub", "try again")
        self.a.emit(tid, "memory", {"text": text, "topic": args.get("topic"), "dry_run": True})   # an eval: never the real memory
        return self.ok(tid, cid, "remember", "Saved to memory.")

    def remembered(self, tid: str, res: dict[str, Any], args: dict[str, Any]) -> dict[str, Any]:
        """`remember`'s result once the hub ran it as agent_memory_save: the chat's `memory` event (with what the fact
        is about) and a plain answer, with the related facts it may replace."""
        out = res.get("result") if isinstance(res.get("result"), dict) else {}
        saved = out.get("saved") or {}
        if res.get("status") != "done" or not saved:
            return res
        about = [p for p in saved.get("about") or [] if p != "you"]
        self.a.emit(tid, "memory", {"text": saved.get("text", args.get("text")), "fact_id": saved.get("id"), "about": about,
                                    "topic": about[0] if about else None})
        content = "Saved to memory" + (f" under {', '.join(about)}" if about else "") + "."
        if out.get("related"):
            content += " Related facts: " + "; ".join(f"{r['id']}: {r['text']}" for r in out["related"]) + f". {out.get('note', '')}"
        return {**res, "content": content}

    # ---- outputs -----------------------------------------------------------------------------

    async def t_show(self, tid: str, cid: str, args: dict[str, Any], tools: ToolSet, thread: dict[str, Any]) -> str:
        """Plan 47.1: a chart, table or pictures in the reply, checked here; the chat draws `data.show`."""
        async def read(oid: str) -> tuple[bytes, dict[str, Any]]:
            o = await self.a.hub.output(oid)
            data, _ = await self.a.hub.output_bytes(oid, preview=False)
            return data, {"name": (o.get("url") or o.get("title") or ""), "kind": o.get("kind")}

        try:
            spec = await show.check(args, lambda r: self.resolve_ref(tid, r), read)
        except show.ShowError as e:
            return self.err(tid, cid, "show", "invalid_arguments", f"{e.field}: {e.detail}", e.fix)
        return self.ok(tid, cid, "show", show.summary(spec), data={"show": spec})

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
        info = {"title": ctx.label(o["title"]), "kind": o["kind"], "meta": {k: v for k, v in (o.get("meta") or {}).items()
                                                                  if k in ("prompt", "model", "params", "seed", "voice", "source")},
                "dims": o.get("dims"), "duration_s": o.get("duration_s")}
        if (thread.get("settings") or {}).get("dry_run") and (o.get("meta") or {}).get("dry_run"):
            return self.ok(tid, cid, "view_output", {"note": STAND_IN, **info})
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
                                                                                            "label": ctx.label(o["title"])})

    async def _view_text(self, tid: str, cid: str, oid: str, o: dict[str, Any], info: dict[str, Any], page: Any,
                         vision: bool) -> str:
        """A text or document output: a PDF page as an image (`page`), else the start of its text (plan 24.4)."""
        name = f"output:{oid} {ctx.label(o['title'])}"
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
                           image={"output_id": oid, "url": to_data_url(data), "label": f"{ctx.label(o['title'])} p.{n}"})
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

    async def t_chat_search(self, tid: str, cid: str, args: dict[str, Any], tools: ToolSet, thread: dict[str, Any]) -> str:
        """Plan 28.5: earlier chats by meaning, through the embed mod's `chats`."""
        s = getattr(self.a, "summaries", None)
        if s is None:
            return self.err(tid, cid, "chat_search", "unavailable", "the summariser isn't running")
        try:
            hits = await s.search(str(args.get("query") or ""), int(args.get("limit") or 5))
        except Exception as e:  # noqa: BLE001: no embed mod
            return self.err(tid, cid, "chat_search", "unavailable", f"search by meaning needs the embed mod ({e})",
                            fix="tell the user chat search needs the Embeddings mod running")
        hits = [h for h in hits if h["thread_id"] != tid]                  # not the chat it's asked from
        # a summary retells a chat that may have read pages or files: data, never instructions
        hits = [{**h, "title": ctx.label(h.get("title")),
                 "summary": ctx.untrusted(f"chat {h['thread_id']} summary", str(h.get("summary") or ""))} for h in hits]
        return self.ok(tid, cid, "chat_search", {"chats": hits} if hits else {"chats": [], "note": "no earlier chat matches"})

    async def t_memory_search(self, tid: str, cid: str, args: dict[str, Any], tools: ToolSet, thread: dict[str, Any]) -> str:
        """structured-memory 2.3: names, keywords and meaning, fused."""
        from .memory.model import MemoryError
        from .memory.search import search
        from .projects.memory import keep_private
        try:
            r = await search(self.a.memory, self.a.hub, str(args.get("query") or ""), args.get("entity") or None,
                             args.get("kind") or None, bool(args.get("history")), int(args.get("limit") or 10))
        except MemoryError as e:
            return self.err(tid, cid, "memory_search", e.code, e.detail, e.fix)
        r = keep_private(self.a.memory, r, (thread.get("settings") or {}).get("project"))   # plan projects 4.2
        self.a.memory.touch([f["id"] for f in r["facts"]])
        if not r["facts"] and not r["entities"]:
            r["note"] = "nothing in memory matches: ask the user if it matters"
        if not r.pop("meaning"):
            r["note"] = (r.get("note", "") + " (searched by names and words only: the Embeddings mod isn't running)").strip()
        return self.ok(tid, cid, "memory_search", r)

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
