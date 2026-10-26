"""The structured memory's routes (plan structured-memory 1.2), for the Memory page and the memory tools.

    GET    /v1/memory/tree                      kinds → entities (with children and fact counts), proposed count
    GET    /v1/memory/entities/{id}             an entity (id, name, alias or path) with its facts, replaced facts, history
    POST   /v1/memory/entities                  {kind, name, parent?, summary?, aliases?, anchors?}
    PATCH  /v1/memory/entities/{id}             {name?, parent?, summary?, kind?, aliases_add?, aliases_remove?, anchors_add?, anchors_remove?, state?}
    POST   /v1/memory/entities/{id}/merge       {into}
    GET    /v1/memory/facts                     ?state=&entity=&q=&current=
    POST   /v1/memory/facts                     {text, about?, kind?, valid_from?, valid_until?, replaces?, source?}
    PATCH  /v1/memory/facts/{id}                {text?, about?, kind?, valid_from?, valid_until?, state?}
    DELETE /v1/memory/facts/{id}                forget it for real
    POST   /v1/memory/undo/{log_id}
    GET    /v1/memory/log                       ?target=&limit=
"""

from __future__ import annotations

import json
from typing import Any, Literal

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from .memory.model import MemoryError

KIND = Literal["project", "person", "place", "tool", "topic", "organization", "projects", "people", "places", "tools",
               "topics", "organizations"]


class Anchor(BaseModel):
    kind: Literal["workspace", "folder", "git"]
    value: str = Field(min_length=1, max_length=1000)


class EntityIn(BaseModel):
    kind: KIND
    name: str = Field(min_length=1, max_length=120)
    parent: str | None = None
    summary: str = Field("", max_length=600)
    aliases: list[str] = Field(default_factory=list, max_length=50)
    anchors: list[Anchor] = Field(default_factory=list, max_length=20)


class EntityPatch(BaseModel):
    name: str | None = Field(None, max_length=120)
    parent: str | None = Field("", description="Another entity to move under; null: to the top; leave out to keep it")
    summary: str | None = Field(None, max_length=600)
    kind: KIND | None = None
    aliases_add: list[str] = Field(default_factory=list, max_length=50)
    aliases_remove: list[str] = Field(default_factory=list, max_length=50)
    anchors_add: list[Anchor] = Field(default_factory=list, max_length=20)
    anchors_remove: list[Anchor] = Field(default_factory=list, max_length=20)
    state: Literal["active", "archived", "proposed"] | None = None


class MergeIn(BaseModel):
    into: str = Field(min_length=1, max_length=200)


class FactIn(BaseModel):
    text: str = Field(min_length=1, max_length=1000)
    about: list[Any] = Field(default_factory=list, max_length=10, description="Entities: ids, paths, names, or {name, kind}")
    kind: Literal["preference", "fact", "event", "procedure"] = "fact"
    valid_from: str | None = None
    valid_until: str | None = None
    replaces: str | None = None
    source: Literal["stated", "inferred"] = "stated"
    evidence: list[dict[str, Any]] = Field(default_factory=list, max_length=20)


class FactPatch(BaseModel):
    text: str | None = Field(None, max_length=1000)
    about: list[Any] | None = Field(None, max_length=10)
    kind: Literal["preference", "fact", "event", "procedure"] | None = None
    valid_from: str | None = Field("", description="A date like 2026-10-26; null clears it; leave out to keep it")
    valid_until: str | None = Field("", description="A date like 2026-10-26; null clears it; leave out to keep it")
    state: Literal["proposed", "active", "retired", "rejected"] | None = None


class SaveIn(BaseModel):
    text: str = Field(min_length=1, max_length=1000, description="The fact, as one sentence that stands on its own "
                      "(\"Prefers 16:9 images\", \"GAIFA's mods use ports 5100-5199\")")
    about: list[str] = Field(default_factory=list, max_length=6, description="What it's about: names or paths of projects, "
                             "people, places, tools, topics (\"GAIFA\", \"projects/GAIFA\", \"people/Ana\"). Leave out for the user. "
                             "An unknown name makes a new entry; a path's first part (projects, people, places, tools, topics) gives its kind")
    kind: Literal["preference", "fact", "event", "procedure"] = Field("fact", description="preference: how the user likes things")
    replaces: str | None = Field(None, description="The id of a fact this one makes out of date (from memory_search); it's kept as history")
    valid_from: str | None = Field(None, description="When it starts to hold, YYYY-MM-DD (default: always)")
    valid_until: str | None = Field(None, description="When it stops holding, YYYY-MM-DD (a trip, a deadline)")


class EntityToolIn(BaseModel):
    entity: str = Field(min_length=1, max_length=200, description="The entry's name, an old name, its path or id")
    kind: Literal["project", "person", "place", "tool", "topic", "organization"] | None = Field(
        None, description="Makes the entry when there's none by that name")
    rename: str | None = Field(None, max_length=120, description="Its new name (the old one stays an alias, so it's still found)")
    aliases: list[str] = Field(default_factory=list, max_length=10, description="Other names it goes by")
    parent: str | None = Field(None, description="Put it under this entry (a name or path)")
    summary: str | None = Field(None, max_length=600, description="One sentence on what it is")


class ForgetIn(BaseModel):
    fact: str = Field(min_length=1, max_length=40, description="The fact's id (from memory_search)")


def origin_thread(request: Request) -> str | None:
    try:
        o = json.loads(request.headers.get("x-gaifa-origin") or "{}")
    except ValueError:
        return None
    t = o.get("thread") if isinstance(o, dict) else None
    return t if isinstance(t, str) else None


def entity_view(m: Any, ref: str) -> dict[str, Any]:
    e = m.need(ref)
    facts = m.facts_of(e["id"], current=False)
    return {**m.public(e), "facts": [f for f in facts if f["current"]],
            "proposed": [f for f in facts if f["state"] == "proposed"],
            "history": [f for f in facts if not f["current"] and f["state"] != "proposed"],
            "children": [m.public(c) for c in m._rows("SELECT * FROM mem_entities WHERE parent = ? AND state = 'active' "
                                                       "ORDER BY name COLLATE NOCASE", (e["id"],))],
            "log": m.log(e["id"], 50)}


def add_routes(app: FastAPI) -> None:
    def M(request: Request) -> Any:
        return request.app.state.agent.memory

    @app.exception_handler(MemoryError)
    async def memory_error(_: Request, e: MemoryError) -> JSONResponse:
        return JSONResponse({"detail": e.detail, "code": e.code, **({"fix": e.fix} if e.fix else {})}, e.status)

    @app.get("/v1/memory/tree", summary="Memory's kinds, each with its entities and their children, and how many wait for review")
    def tree(request: Request) -> dict:
        return M(request).tree()

    @app.get("/v1/memory/entities/{ref:path}", summary="An entity (by id, name, alias or path) with its facts and history")
    def entity(ref: str, request: Request) -> dict:
        return entity_view(M(request), ref)

    @app.post("/v1/memory/entities", status_code=201, summary="Make an entity: a project, person, place, tool, topic or organization")
    def create(body: EntityIn, request: Request) -> dict:
        return M(request).create_entity(body.kind, body.name, body.parent, body.summary, body.aliases,
                                        [a.model_dump() for a in body.anchors])

    @app.patch("/v1/memory/entities/{ref:path}", summary="Rename (the old name stays an alias), move, describe, re-kind, or change aliases and anchors")
    def update(ref: str, body: EntityPatch, request: Request) -> dict:
        m = M(request)
        sent = body.model_fields_set
        if body.state is not None:
            m.set_entity_state(ref, body.state)
        if sent - {"state"}:
            return m.update_entity(ref, body.name, body.parent if "parent" in sent else "", body.summary, body.kind,
                                   body.aliases_add, body.aliases_remove, [a.model_dump() for a in body.anchors_add],
                                   [a.model_dump() for a in body.anchors_remove])
        return m.public(m.need(ref) if body.state != "archived" else m.entity_row(m.need(ref)["id"]))

    @app.post("/v1/memory/entities/{ref:path}/merge", summary="Merge an entity into another: its facts, names and anchors move")
    def merge(ref: str, body: MergeIn, request: Request) -> dict:
        return M(request).merge(ref, body.into)

    @app.get("/v1/memory/facts", summary="Facts: ?state=proposed|active|retired|rejected, ?entity=, ?q= (words), ?current=true")
    def facts(request: Request, state: str | None = None, entity: str | None = None, q: str | None = None,
              current: bool | None = None, limit: int = 200) -> list:
        return M(request).facts(state, entity, q, current, min(limit, 1000))

    @app.post("/v1/memory/facts", status_code=201, summary="Remember a fact about entities (the user when none); replaces retires an older one")
    def add(body: FactIn, request: Request) -> dict:
        return M(request).add_fact(body.text, body.about, body.kind, body.valid_from, body.valid_until, body.source,
                                   evidence=body.evidence, replaces=body.replaces)

    @app.patch("/v1/memory/facts/{fid}", summary="Correct a fact, or approve, reject, retire or bring it back (state)")
    def patch(fid: str, body: FactPatch, request: Request) -> dict:
        m = M(request)
        sent = body.model_fields_set
        if sent & {"text", "about", "kind", "valid_from", "valid_until"}:
            m.update_fact(fid, body.text, body.about, body.kind, body.valid_from if "valid_from" in sent else "",
                          body.valid_until if "valid_until" in sent else "")
        if body.state is not None:
            return m.set_fact_state(fid, body.state)
        return m.fact_public(m.need_fact(fid))

    @app.delete("/v1/memory/facts/{fid}", summary="Forget a fact for real (the log keeps only that one was forgotten)")
    def forget(fid: str, request: Request) -> dict:
        return M(request).forget(fid)

    @app.post("/v1/memory/undo/{log_id}", summary="Undo one change to memory")
    def undo(log_id: int, request: Request) -> dict:
        return M(request).undo(log_id)

    # ---- the agent's own memory tools (structured-memory 3.2; `[tools]` in service.toml, mcp = false) -----------

    @app.post("/v1/memory/save", summary="Remember a fact the user told you, about them or a project, person, place, tool or topic")
    def tool_save(body: SaveIn, request: Request) -> dict:
        m = M(request)
        tid = origin_thread(request)
        f = m.add_fact(body.text, body.about, body.kind, body.valid_from, body.valid_until, "stated",
                       evidence=[{"thread": tid}] if tid else [], replaces=body.replaces, by="agent")
        ents = [e["id"] for e in f["entities"]]
        related = [x for x in m.facts(current=True, limit=200) if x["id"] != f["id"] and {e["id"] for e in x["entities"]} & set(ents)][:3]
        out = {"saved": {"id": f["id"], "text": f["text"], "about": [e["path"] for e in f["entities"]], "seen": f["seen"]}}
        if body.replaces:
            out["replaced"] = body.replaces
        if related and not body.replaces:
            out["related"] = [{"id": x["id"], "text": x["text"]} for x in related]
            out["note"] = ("if the new fact makes one of these out of date, save it again with replaces=<that id> "
                           "(the old one is kept as history)")
        return out

    @app.post("/v1/memory/entity", summary="Make, rename, re-parent or describe an entry in memory (a project, person, place, tool, topic)")
    def tool_entity(body: EntityToolIn, request: Request) -> dict:
        m = M(request)
        e = m.resolve(body.entity)
        if e is None:
            if body.kind is None:
                raise MemoryError(404, "not_found", f"nothing in memory is called {body.entity!r}",
                                  "pass kind to make it, or memory_search to find what it's called")
            parts = [p for p in body.entity.split("/") if p]
            pe = m.resolve(body.parent) if body.parent else (m.resolve("/".join(parts[:-1])) if len(parts) > 1 else None)
            made = m.create_entity(body.kind, parts[-1], pe["id"] if pe else None, body.summary or "", body.aliases, by="agent")
            return {"made": made}
        p = m.update_entity(e["id"], body.rename, (m.need(body.parent)["id"] if body.parent else ""), body.summary,
                            aliases_add=body.aliases, by="agent")
        return {"changed": p}

    @app.post("/v1/memory/forget", summary="Forget a fact for good, when the user asks you to (memory_search finds its id)")
    def tool_forget(body: ForgetIn, request: Request) -> dict:
        return M(request).forget(body.fact, by="agent")

    @app.post("/v1/memory/learn", summary="Learn from the chats that went quiet now, instead of at the next pass; ?thread= one chat")
    async def learn_now(request: Request, thread: str | None = None) -> Any:
        ml = getattr(request.app.state.agent, "memory_learner", None)
        if ml is None:
            return JSONResponse({"detail": "the memory learner isn't running", "code": "unavailable"}, 503)
        if thread:
            return {"proposed": await ml.learn(thread)}
        return {"proposed": await ml.check()}

    @app.post("/v1/memory/tidy", summary="Tidy memory now instead of at night: ended facts, duplicate entries, summaries, fading")
    async def tidy_now(request: Request) -> Any:
        from .memory import tidy
        return await tidy.run(request.app.state.agent)

    @app.post("/v1/memory/reindex", summary="Send every current fact and entity to the embed mod's memory collection again")
    async def reindex(request: Request) -> Any:
        idx = getattr(request.app.state.agent, "memory_index", None)
        if idx is None:
            return JSONResponse({"detail": "the memory index isn't running", "code": "unavailable"}, 503)
        try:
            return {"sent": await idx.reindex()}
        except Exception as e:  # noqa: BLE001: the embed mod is away
            return JSONResponse({"detail": f"the embed mod didn't answer: {e}", "code": "unavailable",
                                 "fix": "start the Embeddings mod, then try again"}, 503)

    @app.get("/v1/memory/log", summary="Changes to memory, newest first; ?target= one entity's or fact's")
    def log(request: Request, target: str | None = None, limit: int = 100) -> list:
        return M(request).log(target, min(limit, 500))
