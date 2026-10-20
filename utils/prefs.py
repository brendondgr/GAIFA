"""Preferences (plan 21.2–21.3): what the user wants, as data the hub applies to every caller's card.

A preference sets one argument of one tool (`scope = "tool"`), or is a prose fact for the agent
(`scope = "agent"`, no tool: what `remember` writes), or holds for one chat only (`scope = "thread"`,
`source = "carried"`: a card edit carried to the next card of that tool in the same chat).

- `when`: conditions on the other arguments, `{"image": "present"}`, `{"engine": "trellis2"}`, so a
  preference only applies where it can (a picture engine only with a picture). Checked against the
  tool's schema and `x-options` when saved.
- `source`: `stated` (the user said it), `inferred` (the miner saw it twice in two chats), `carried`.
- `state`: `proposed` (waiting for the user), `active`, `retired` (faded or contradicted), `rejected`.
- `apply()` fills only arguments the caller left out or left at the capability default: an explicit
  value wins, and so does every card edit. Each filled field is recorded (`pref:<id>`).
- `[learning] enabled = false` stops applying and every write here.
"""

from __future__ import annotations

import json
import secrets
import time
from typing import TYPE_CHECKING, Any

from utils.tools import options
from utils.tools.schema import _errors as schema_errors

if TYPE_CHECKING:
    from utils.server import Hub

SCOPES = ("tool", "agent", "thread")
SOURCES = ("stated", "inferred", "carried")
STATES = ("proposed", "active", "retired", "rejected")
JSON_COLS = ("value", "when", "evidence")


class PrefError(Exception):
    def __init__(self, status: int, code: str, detail: str) -> None:
        super().__init__(detail)
        self.status, self.code, self.detail = status, code, detail


def _row(r: Any) -> dict[str, Any] | None:
    if r is None:
        return None
    out = dict(r)
    for k in JSON_COLS:
        if out.get(k) is not None:
            out[k] = json.loads(out[k])
    out["when"] = out.get("when") or {}
    out["evidence"] = out.get("evidence") or []
    return out


def matches(when: dict[str, Any], args: dict[str, Any]) -> bool:
    for k, want in (when or {}).items():
        if want == "present":
            if not options.present(args, k):
                return False
        elif want == "absent":
            if options.present(args, k):
                return False
        elif args.get(k) != want:
            return False
    return True


def when_for(tool: Any, field: str, value: Any) -> dict[str, str]:
    """The conditions a choice needs to apply (from its `x-options`): engine=trellis2 → {image: present}."""
    o = options.options((tool.parameters.get("properties") or {}).get(field)) or {}
    opt = o.get(str(value)) or {}
    return {**{n: "present" for n in opt.get("needs") or []}, **{n: "absent" for n in opt.get("excludes") or []}}


def _sample(when: dict[str, Any]) -> dict[str, Any]:
    """Arguments that satisfy `when`, to check a preference against the tool's choices."""
    return {k: ("output:000000000000" if v == "present" else v) for k, v in (when or {}).items() if v != "absent"}


class Prefs:
    def __init__(self, hub: Hub) -> None:
        self.hub = hub

    @property
    def on(self) -> bool:
        return bool(self.hub.config.learning.enabled)

    # ---- reading -------------------------------------------------------------------------------

    async def list(self, state: str | None = None, tool: str | None = None, scope: str | None = None,
                   thread: str | None = None, limit: int = 500) -> list[dict[str, Any]]:
        sql, args = "SELECT * FROM prefs WHERE 1=1", []
        for col, v in (("state", state), ("tool", tool), ("scope", scope), ("thread", thread)):
            if v:
                sql += f" AND {col} = ?"
                args.append(v)
        sql += " ORDER BY updated_ts DESC LIMIT ?"
        args.append(limit)
        return [_row(r) for r in await self.hub.db.fetchall(sql, args)]  # type: ignore[misc]

    async def get(self, pid: str) -> dict[str, Any]:
        p = _row(await self.hub.db.fetchone("SELECT * FROM prefs WHERE id = ?", (pid,)))
        if p is None:
            raise PrefError(404, "not_found", f"no preference {pid!r}")
        return p

    # ---- writing -------------------------------------------------------------------------------

    async def _check(self, p: dict[str, Any]) -> None:
        if p["scope"] not in SCOPES or p["source"] not in SOURCES or p["state"] not in STATES:
            raise PrefError(422, "invalid_pref", f"scope, source and state must be one of {SCOPES}, {SOURCES}, {STATES}")
        if p["scope"] == "agent" or (p["scope"] == "thread" and not p.get("tool")):   # a sentence (for one chat: thread)
            if not isinstance(p.get("value"), str) or not p["value"].strip():
                raise PrefError(422, "invalid_pref", "an agent preference is a sentence: give `value` as text")
            if p["scope"] == "thread" and not p.get("thread"):
                raise PrefError(422, "invalid_pref", "a thread preference needs `thread`")
            return
        if not p.get("tool") or not p.get("field"):
            raise PrefError(422, "invalid_pref", "a tool preference needs `tool` and `field`")
        if p["scope"] == "thread" and not p.get("thread"):
            raise PrefError(422, "invalid_pref", "a thread preference needs `thread`")
        tool = await self.hub.tools.get(p["tool"]) if self.hub.tools else None
        if tool is None:
            raise PrefError(422, "unknown_tool", f"there is no tool {p['tool']!r}")
        prop = (tool.parameters.get("properties") or {}).get(p["field"])
        if prop is None:
            raise PrefError(422, "invalid_pref", f"{p['tool']} has no parameter {p['field']!r}")
        errs = schema_errors(prop, p["value"], p["field"])
        args = {**_sample(p.get("when") or {}), p["field"]: p["value"]}
        errs += [e for e in options.problems(tool.parameters, args) if e["field"] == p["field"]]
        if errs:
            raise PrefError(422, "invalid_pref", f"{errs[0]['detail']}; {errs[0]['fix']}")

    async def create(self, body: dict[str, Any]) -> dict[str, Any]:
        if not self.on:
            raise PrefError(409, "learning_off", "learning is turned off (Settings → Learning)")
        now = time.time()
        p = {"id": "pref_" + secrets.token_hex(6), "scope": body.get("scope") or ("agent" if not body.get("tool") else "tool"),
             "tool": body.get("tool"), "field": body.get("field"), "thread": body.get("thread"), "value": body.get("value"),
             "when": body.get("when") or {}, "cue": body.get("cue") or "", "source": body.get("source") or "stated",
             "state": body.get("state") or ("proposed" if body.get("source") == "inferred" else "active"),
             "confidence": float(body.get("confidence") if body.get("confidence") is not None else 1.0),
             "evidence": body.get("evidence") or [], "seen": int(body.get("seen") or 1), "contradicted": 0,
             "note": body.get("note") or "", "created_ts": now, "updated_ts": now, "last_used_ts": None}
        if p["scope"] != "agent" and not p["when"] and p.get("tool") and self.hub.tools:
            tool = await self.hub.tools.get(p["tool"])
            if tool is not None and p.get("field"):
                p["when"] = when_for(tool, p["field"], p["value"])      # a choice applies only where it can
        await self._check(p)
        same = await self._same(p)
        if same:                                      # the same preference again: one row, more evidence
            return await self.update(same["id"], {"value": p["value"], "seen": same["seen"] + 1,
                                                  "evidence": (same["evidence"] + p["evidence"])[-20:],
                                                  **({"state": "active"} if p["source"] == "stated" else {}),
                                                  **({"source": "stated"} if p["source"] == "stated" else {})})
        await self.hub.db.execute(
            "INSERT INTO prefs (id, scope, tool, field, thread, value, \"when\", cue, source, state, confidence, evidence, seen, "
            "contradicted, note, created_ts, updated_ts) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (p["id"], p["scope"], p["tool"], p["field"], p["thread"], json.dumps(p["value"]), json.dumps(p["when"]), p["cue"],
             p["source"], p["state"], p["confidence"], json.dumps(p["evidence"]), p["seen"], 0, p["note"], now, now))
        return await self._changed(p["id"])

    async def _same(self, p: dict[str, Any]) -> dict[str, Any] | None:
        if p["scope"] == "agent":
            rows = await self.list(scope="agent")
            return next((r for r in rows if r["value"] == p["value"] and r["state"] in ("active", "proposed")), None)
        rows = await self.list(tool=p["tool"], scope=p["scope"])
        return next((r for r in rows if r["field"] == p["field"] and r["when"] == p["when"] and r.get("thread") == p.get("thread")
                     and r["state"] in ("active", "proposed")), None)

    async def update(self, pid: str, patch: dict[str, Any]) -> dict[str, Any]:
        p = {**await self.get(pid), **{k: v for k, v in patch.items() if v is not None}}
        if {"value", "when", "tool", "field", "scope"} & set(patch):
            await self._check(p)
        cols = ("value", "when", "cue", "source", "state", "confidence", "evidence", "seen", "contradicted", "note", "last_used_ts")
        sets = [f'"{c}" = ?' for c in cols if c in patch]
        vals = [json.dumps(p[c]) if c in JSON_COLS else p[c] for c in cols if c in patch]
        if sets:
            await self.hub.db.execute(f"UPDATE prefs SET {', '.join(sets)}, updated_ts = ? WHERE id = ?", (*vals, time.time(), pid))
        return await self._changed(pid)

    async def delete(self, pid: str) -> None:
        await self.get(pid)
        await self.hub.db.execute("DELETE FROM prefs WHERE id = ?", (pid,))
        self.hub.bus.publish({"type": "pref", "pref": {"id": pid, "deleted": True}})

    async def decide(self, pid: str, approve: bool) -> dict[str, Any]:
        return await self.update(pid, {"state": "active" if approve else "rejected"})

    async def _changed(self, pid: str) -> dict[str, Any]:
        p = await self.get(pid)
        self.hub.bus.publish({"type": "pref", "pref": p})
        return p

    # ---- the call path (21.3) --------------------------------------------------------------------

    async def apply(self, tool: Any, args: dict[str, Any], origin: dict[str, Any] | None,
                    defaulted: list[str]) -> tuple[dict[str, Any], dict[str, str]]:
        """`args` with active preferences filled in where the caller left a field out or at its
        capability default; returns the fields filled (field → "pref:<id>" | "carried")."""
        if not self.on or (origin or {}).get("no_learn"):
            return args, {}
        rows = [r for r in await self.list(tool=tool.name, state="active") if r["scope"] in ("tool", "thread")]
        thread = (origin or {}).get("thread")
        rows = [r for r in rows if r["scope"] == "tool" or (thread and r.get("thread") == thread)]
        rows.sort(key=lambda r: (r["scope"] != "thread", r["source"] != "stated", -(r["updated_ts"] or 0)))   # this chat, then stated
        out, filled, used = dict(args), {}, []
        for r in rows:
            f = r["field"]
            if f in filled or (options.present(out, f) and f not in defaulted) or not matches(r["when"], out):
                continue
            trial = {**out, f: r["value"]}
            if options.problems(tool.parameters, trial) or schema_errors((tool.parameters.get("properties") or {}).get(f) or {}, r["value"], f):
                continue
            out = trial
            filled[f] = "carried" if r["source"] == "carried" else f"pref:{r['id']}"
            used.append(r["id"])
        if used:
            now = time.time()
            await self.hub.db.executemany("UPDATE prefs SET last_used_ts = ? WHERE id = ?", [(now, u) for u in used])
        return out, filled

    async def after_decision(self, tool: Any, origin: dict[str, Any], final: dict[str, Any], edited: list[str],
                             filled: dict[str, str]) -> None:
        """A card was approved: carry its edits to this chat's next card of the tool, and count
        edits away from a preference's value against it."""
        if not self.on or origin.get("no_learn"):
            return
        for f in edited:
            how = filled.get(f) or ""
            if how.startswith("pref:") and not origin.get("dry_run"):     # an eval never counts against a preference
                try:
                    p = await self.get(how[5:])
                except PrefError:
                    continue
                n = p["contradicted"] + 1
                retire = p["source"] == "inferred" and n >= 2
                await self.update(p["id"], {"contradicted": n, **({"state": "retired"} if retire else {}),
                                            **({"note": "contradicted on a card"} if not retire and p["source"] == "stated" else {})})
            if origin.get("thread") and f in final:
                await self.create({"scope": "thread", "thread": origin["thread"], "tool": tool.name, "field": f, "value": final[f],
                                   "source": "carried", "state": "active",
                                   "evidence": [{"kind": "approval", "ref": origin.get("approval_id") or ""}]})
