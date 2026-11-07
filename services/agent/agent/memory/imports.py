"""Importing another assistant's memory (plan memory-import 1.2–1.4).

1. **Read.** `sources.read_lines` splits the pasted answer into entries, with their section and date, without a model.
2. **Interpret.** The agent's background model reads 20 entries at a time (`READ`): the facts each one says, in the
   third person (instructions stay rules for the assistant, with the user as "the user"), their kind, what they are
   about (the user, a project, a topic…), whether they are sensitive, and for a project its entry (name, old names,
   a summary). A fact still in the first person is reworded once (`wording.reword`).
3. **Compare.** An entry already imported before is `same` without asking; the rest go through the learner's compare
   step (`compare.py`): `same`, `replaces`, `adds` or `skip`.
4. **Preview.** Each fact gets a choice: `save` when `auto.decide_import` passes, else `review` with the reason (it
   would wait in Review), `skip` for what the model found not worth keeping. Nothing is saved yet.
5. **Save** with the person's choices: imported facts dated by their entry (`valid_from`, the evidence's `ts`), their
   evidence naming the import and the entry; `same` adds the entry to the held fact's evidence; entries are made
   or gain the old names as aliases. Every change is logged `by="import"`.
6. **Undo** reverses the import's changes through the log, newest first; a fact changed since is left as it is.

Imports live in `mem_imports` (one row each: its lines, its preview as `result`, and the log ids it made).
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from typing import Any

from ..learn.loop import _json
from . import auto, profile
from .compare import compare
from .learn import clean_about
from .model import FACT_KINDS, FOLDERS, MemoryError, kind_of, norm
from .sources import MAX_BYTES, MAX_LINES, NotAnExport, read_file, read_lines
from .store import MemoryStore, new_id
from .wording import first_person, reword

log = logging.getLogger("agent.memory.imports")
SCHEMA = ("CREATE TABLE IF NOT EXISTS mem_imports (id TEXT PRIMARY KEY, made REAL NOT NULL, source TEXT NOT NULL, "
          "lines INTEGER NOT NULL DEFAULT 0, state TEXT NOT NULL, done INTEGER NOT NULL DEFAULT 0, result TEXT, error TEXT, "
          "logs TEXT, saved TEXT, undone TEXT)")
FROM = ("chatgpt", "claude", "gemini", "other")
BATCH = 20
MAX_FACTS = 4                 # per entry: a long project line may say a few things, one of them sensitive
CHOICES = ("save", "review", "skip")
YOURS = ("identity", "career", "preferences")
FOLDER_WORDS = {*FOLDERS.values(), *FOLDERS}
# A preference said about someone ("The user prefers…", "Sam likes…") rather than a rule to the assistant ("Never push…").
_ABOUT = re.compile(r"^(?:The user|Their|They|[A-Z][\w'’-]*(?: [A-Z][\w'’-]*)?)(?:'s)? (?:\w+ )?(?:prefers|likes|loves|dislikes|hates|wants|values|enjoys|"
                    r"uses|tends|is|has|avoids|finds|cares|considers|trusts|notices|keeps|reads|shares|runs)\b")

READ = """You are moving a user's memory from another AI assistant into a new one. Below are entries the other assistant wrote, numbered, each under the section it was in (instructions, identity, career, projects, preferences, or none).

For each entry, write the facts it says, so the new assistant can keep them:
- Instructions are rules the user gave the assistant. Keep each one as a rule addressed to the assistant, in the imperative, in its own words: only "me", "my" and "I" become "the user", "their" and "the user" ("Never run sudo for me" → "Never run sudo for the user"); add no other words. Kind "preference". "about": ["you"] when it applies to any work; when it is only for one kind of work or one project, the topic or project instead ("topics/Cover letters", "projects/Ariadne"), not "you".
- Identity, career and preferences are about the user: one sentence in the third person each, starting "The user" even where the entry uses their name ("Sam is a PhD student at FSU" → "The user is a PhD student at FSU."; the name itself is a fact: "The user's name is Sam."). Kinds: "preference" for tastes and working style, "interest" for what they are into or learning these days, "fact" for lasting facts, "event" for something that happened on a date.
- Projects: the entry's first words name the project. Give "entity": {{"name": "the project's name", "kind": "project", "aliases": [former or other names it is called, from "(formerly X)" or "(X)"], "summary": "what it is, under 120 characters"}}. Each fact starts with the project's name ("Mycelium is an open-source research assistant…") and is about "projects/<name>".
- One fact per entry is usual. Split a long entry into at most 4 facts, each a sentence that stands on its own, so that a sensitive part (money, health, family) is its own fact.
- Keep every detail, date and name. Copy the user's quoted words exactly, inside their double quotation marks ("…"). Add nothing. Never write "I", "me", "my", "we" or "our" outside quotation marks.
- "sensitive": true when the fact is about health, money or finances, legal matters, relationships or family, religion, politics, sexuality, or another private person.
- "confidence": 0 to 1, how sure you are the facts say what the entry means.
- "ends": what the entry says the user no longer does or uses, by name, else [].

Entries memory already knows (use these names when an entry is about one):
{entities}

THE ENTRIES:
{lines}

Answer with JSON only, one item per entry number:
{{"lines": [{{"n": 1, "entity": null, "facts": [{{"text": "…", "kind": "preference|interest|fact|event", "about": ["you"], "ends": [], "sensitive": false, "confidence": 0.9}}]}}]}}"""


def _noon(date: str | None) -> float | None:
    try:
        return time.mktime(time.strptime(f"{date} 12", "%Y-%m-%d %H")) if date else None
    except ValueError:
        return None


def _entity(raw: Any, section: str | None) -> dict[str, Any] | None:
    if not isinstance(raw, dict) or not isinstance(raw.get("name"), str) or not raw["name"].strip() or len(raw["name"]) > 120:
        return None
    given = raw["name"].strip()
    name = " ".join(given.replace("/", " ").split())        # "ProQuest/Pivot-RP scraper": a name, not a path
    aliases = [a.strip() for a in [*(raw.get("aliases") or []), given] if isinstance(a, str) and a.strip() and a.strip() != name][:10]
    return {"name": name, "kind": kind_of(raw.get("kind") or ("project" if section == "projects" else "topic")),
            "aliases": list(dict.fromkeys(aliases)), "summary": str(raw.get("summary") or "").strip()[:200]}


def cands_of(line: dict[str, Any], got: dict[str, Any]) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    """An entry's entity and facts from the model's item for it, cleaned: kinds, `about` paths, the user added where
    the section says the fact is theirs, numbers in range."""
    sec = line.get("section")
    ent = _entity(got.get("entity"), sec)
    path = f"{FOLDERS.get(ent['kind'], 'topics')}/{ent['name']}" if ent else None
    names = {norm(n) for n in [ent["name"], *ent["aliases"]]} if ent else set()

    def at(a: str) -> str:                                  # the entity by any of its names, as its path
        head, _, tail = a.partition("/")
        return path if path and (norm(a) in names or (tail and head.lower() in FOLDER_WORDS and norm(tail) in names)) else a
    out = []
    for f in (got.get("facts") or [])[:MAX_FACTS]:
        if not isinstance(f, dict) or not isinstance(f.get("text"), str) or not f["text"].strip():
            continue
        kind = f.get("kind") if f.get("kind") in FACT_KINDS else ("preference" if sec in ("instructions", "preferences") else "fact")
        about = [at(clean_about(a)) for a in f.get("about") or [] if isinstance(a, str) and a.strip()][:6]
        if path and not about:
            about = [path]
        if not about or (sec in YOURS and "you" not in about):
            about.append("you")
        try:
            conf = min(1.0, max(0.0, float(f.get("confidence", 0.9))))
        except (TypeError, ValueError):
            conf = 0.5
        out.append({"text": " ".join(f["text"].split())[:1000], "kind": kind, "about": list(dict.fromkeys(about)),
                    "sensitive": f.get("sensitive") is True, "confidence": conf, "line": line["text"],
                    "ends": [e for e in f.get("ends") or [] if isinstance(e, str)][:5]})
    return ent, out


class Importer:
    def __init__(self, agent: Any, clock: Any = time.time) -> None:
        self.agent, self.clock = agent, clock
        self.m: MemoryStore = agent.memory
        self.task: asyncio.Task[Any] | None = None
        with self.m.lock:
            self.m.c.execute(SCHEMA)
            self.m.c.execute("UPDATE mem_imports SET state = 'failed', error = 'the agent restarted while reading it' "
                             "WHERE state = 'reading'")

    # ---- rows --------------------------------------------------------------------------------------

    def _set(self, iid: str, **cols: Any) -> None:
        with self.m.lock:
            self.m.c.execute(f"UPDATE mem_imports SET {', '.join(f'{k} = ?' for k in cols)} WHERE id = ?",
                             [json.dumps(v) if k in ("result", "logs", "saved", "undone") and v is not None else v
                              for k, v in cols.items()] + [iid])

    def _need(self, iid: str) -> dict[str, Any]:
        r = self.m._row("SELECT * FROM mem_imports WHERE id = ?", (iid,))
        if r is None:
            raise MemoryError(404, "not_found", f"no import {iid!r}")
        for k in ("result", "logs", "saved", "undone"):
            r[k] = json.loads(r[k]) if r[k] else None
        return r

    def public(self, r: dict[str, Any], items: bool = True) -> dict[str, Any]:
        lines = r["result"] or []
        facts = [f for li in lines for f in li["facts"]]
        counts = {"lines": r["lines"], "facts": len(facts), "unread": sum(1 for li in lines if li.get("error")),
                  **{c: sum(1 for f in facts if f["choice"] == c and f["op"] != "same") for c in CHOICES},
                  "same": sum(1 for f in facts if f["op"] == "same")}
        out = {"id": r["id"], "made": r["made"], "source": r["source"], "state": r["state"], "done": r["done"],
               "total": r["lines"], "error": r["error"], "counts": counts, "saved": r["saved"], "undone": r["undone"]}
        return {**out, "lines": lines} if items else out

    def get(self, iid: str) -> dict[str, Any]:
        return self.public(self._need(iid))

    def list(self, limit: int = 50) -> list[dict[str, Any]]:
        return [self.public(self._need(r["id"]), items=False)
                for r in self.m._rows("SELECT id FROM mem_imports ORDER BY made DESC LIMIT ?", (limit,))]

    # ---- reading -----------------------------------------------------------------------------------

    def start(self, text: str, source: str) -> dict[str, Any]:
        """Read `text` (an assistant's memory export) into a preview in the background; the import's row."""
        if len((text or "").encode()) > MAX_BYTES:
            raise MemoryError(413, "too_big", f"an import is at most {MAX_BYTES // 1000} KB", "import it in parts")
        return self.start_lines(read_lines(text), source)

    def start_file(self, name: str, data: bytes, source: str = "claude") -> dict[str, Any]:
        """The same for a memory export file (Claude's zip or memories.json; sources.read_file)."""
        try:
            lines = read_file(name, data)
        except NotAnExport as e:
            raise MemoryError(422, "not_an_export", e.detail, e.fix) from None
        return self.start_lines(lines, source)

    def start_lines(self, lines: list[dict[str, Any]], source: str) -> dict[str, Any]:
        if source not in FROM:
            raise MemoryError(422, "bad_source", f"source is one of {', '.join(FROM)}")
        if not lines:
            raise MemoryError(422, "nothing_to_import", "no memories found in the text",
                              "paste the other assistant's answer: one memory per line")
        if len(lines) > MAX_LINES:
            raise MemoryError(413, "too_big", f"an import is at most {MAX_LINES} lines (this has {len(lines)})", "import it in parts")
        if self.task is not None and not self.task.done():
            raise MemoryError(409, "busy", "another import is being read", "wait until it is ready")
        iid = new_id("imp_")
        with self.m.lock:
            self.m.c.execute("INSERT INTO mem_imports (id, made, source, lines, state, result) VALUES (?, ?, ?, ?, 'reading', ?)",
                             (iid, self.clock(), source, len(lines),
                              json.dumps([{**li, "entity": None, "error": None, "facts": []} for li in lines])))
        self.task = asyncio.create_task(self._read(iid, lines))
        return self.get(iid)

    async def ask(self, model: str, prompt: str, key: str) -> dict[str, Any] | None:
        reply = await self.agent.llm.chat(model, [{"role": "user", "content": prompt}], stream=False)
        got = _json(reply.text or "")
        if got is None and not (reply.text or "").strip() and reply.thinking and f'{{"{key}"' in reply.thinking:
            got = _json(reply.thinking[reply.thinking.rfind(f'{{"{key}"'):])     # all of it went into the thinking
        if got is None:
            log.warning("memory import: the model's answer wasn't JSON: %r", (reply.text or "")[:300])
        return got

    def _entities(self) -> str:
        rows = [f"- {self.m.path(e)}" + (f" (also {', '.join(self.m.aliases(e['id']))})" if self.m.aliases(e["id"]) else "")
                for e in self.m.entities() if e["id"] != "user"]
        return "\n".join(rows)[:3000] or "(none yet)"

    async def interpret(self, model: str, lines: list[dict[str, Any]], progress: Any = None) -> dict[int, dict[str, Any]]:
        """n → {entity, facts} or {error}: the model's reading of each entry, BATCH at a time (a batch that isn't JSON
        is asked once more)."""
        out: dict[int, dict[str, Any]] = {}
        ents = self._entities()
        for start in range(0, len(lines), BATCH):
            part = lines[start:start + BATCH]
            text = "\n".join(f"{li['n']}. [{li['section'] or 'none'}] {li['text']}" for li in part)
            got = None
            for _ in range(2):
                got = await self.ask(model, READ.format(entities=ents, lines=text), "lines")
                if got is not None and isinstance(got.get("lines"), list):
                    break
            items = {}
            for it in (got or {}).get("lines") or []:
                try:
                    items[int(it.get("n"))] = it
                except (TypeError, ValueError, AttributeError):
                    continue
            for li in part:
                it = items.get(li["n"])
                ent, cands = cands_of(li, it) if isinstance(it, dict) else (None, [])
                out[li["n"]] = {"entity": ent, "facts": cands} if cands else {"error": "couldn't read this line"}
            if progress:
                progress(start + len(part))
        return out

    async def _read(self, iid: str, lines: list[dict[str, Any]]) -> None:
        try:
            model = await self.agent.llm.background_model(None, self.agent.cfg.model)
            if model is None:
                raise RuntimeError("no model to read it with: the agent's model isn't served (Settings → LLMs)")
            known = self._known_lines()
            fresh = [li for li in lines if norm(li["text"]) not in known]       # imported before: no need to read again
            read = await self.interpret(model, fresh, lambda n: self._set(iid, done=len(lines) - len(fresh) + n))
            result = await self.preview(model, lines, read, known)
            self._set(iid, state="ready", done=len(lines), result=result)
        except Exception as e:  # noqa: BLE001: the model went away; the person can paste it again
            log.warning("memory import %s failed: %s", iid, e)
            self._set(iid, state="failed", error=str(e)[:500])

    def _known_lines(self) -> dict[str, list[str]]:
        """Entries imported before (normalized) → the current facts they became; and a current fact's own text (GAIFA's
        export pasted back, 3.2) → that fact."""
        out: dict[str, list[str]] = {}
        for f in self.m._rows("SELECT id, text, source, evidence FROM mem_facts WHERE state IN ('active', 'proposed')"):
            out.setdefault(norm(f["text"]), []).append(f["id"])
            if f["source"] != "imported":
                continue
            for ev in json.loads(f["evidence"] or "[]"):
                if isinstance(ev, dict) and ev.get("import") and isinstance(ev.get("line"), str):
                    out.setdefault(norm(ev["line"]), []).append(f["id"])
        return out

    async def preview(self, model: str, lines: list[dict[str, Any]], read: dict[int, dict[str, Any]],
                      known: dict[str, list[str]]) -> list[dict[str, Any]]:
        """Each entry with its facts, what each would do (op, the held fact) and the default choice with its reason.
        An entry imported before (`known`) is the facts it became, each `same`."""
        flat = [c for li in lines for c in read.get(li["n"], {}).get("facts", [])]
        bad = [c for c in flat if first_person(c["text"])]
        for c, t in zip(bad, await reword(self.agent.llm, model, [c["text"] for c in bad])):
            c["text"] = t
            c["first_person"] = first_person(t)
        ops = await compare(self.m, self.agent.hub, lambda p: self.ask(model, p, "decisions"), flat, meaning_wait=3, batch=BATCH)
        op_of = {id(c): o for c, o in zip(flat, ops)}
        cfg = auto.settings(profile.settings(self.agent.cfg.data))
        out = []
        for li in lines:
            held_line = [f for f in (self.m.fact_row(x) for x in dict.fromkeys(known.get(norm(li["text"]), []))) if f]
            if held_line:
                out.append({**li, "entity": None, "error": None, "facts": [
                    {"key": f"{li['n']}.{k}", "text": f["text"], "kind": f["kind"], "about": [], "op": "same",
                     "held": {"id": f["id"], "text": f["text"]}, "choice": "save", "why": "already known", "sensitive": False,
                     "confidence": f["confidence"]} for k, f in enumerate(held_line, 1)]})
                continue
            r = read.get(li["n"], {"error": "couldn't read this line"})
            facts = []
            for k, c in enumerate(r.get("facts", []), 1):
                op, fid = op_of.get(id(c), ("adds", None))
                held = self.m.fact_row(fid) if fid else None
                if op in ("same", "replaces") and held is None:
                    op, fid = "adds", None
                if op == "same":
                    choice, why = "save", "already known"
                elif op == "skip":
                    choice, why = "skip", "not worth keeping"
                else:
                    ok, why = auto.decide_import(c, held if op == "replaces" else None, cfg)
                    choice = "save" if ok else "review"
                facts.append({"key": f"{li['n']}.{k}", "text": c["text"], "kind": c["kind"], "about": c["about"], "op": op,
                              "held": {"id": held["id"], "text": held["text"]} if held else None, "choice": choice, "why": why,
                              "sensitive": c["sensitive"], "confidence": c["confidence"]})
            out.append({**li, "entity": r.get("entity"), "error": r.get("error"), "facts": facts})
        return out

    # ---- saving and undoing ------------------------------------------------------------------------

    def _make_entity(self, ent: dict[str, Any], active: bool) -> str:
        """The entry a project line is about: the one memory holds by that name or an old one (gaining the other
        names as aliases and a summary when it has none), else a new one. Its id."""
        e = self.m.resolve(ent["name"]) or next((x for x in (self.m.resolve(a) for a in ent["aliases"]) if x), None) \
            or self.m._row("SELECT * FROM mem_entities WHERE state = 'proposed' AND norm = ?", (norm(ent["name"]),))
        names = [n for n in [ent["name"], *ent["aliases"]] if not self.m._taken(norm(n))]
        if e is None:
            return self.m.create_entity(ent["kind"], ent["name"], summary=ent["summary"], aliases=[a for a in names if a != ent["name"]],
                                        source="imported", state="active" if active else "proposed", by="import")["id"]
        have = {e["norm"], *(norm(a) for a in self.m.aliases(e["id"]))}
        new = [n for n in names if norm(n) not in have]
        if new or (ent["summary"] and not e["summary"]):
            try:
                self.m.update_entity(e["id"], aliases_add=new, summary=ent["summary"] if not e["summary"] else None, by="import")
            except MemoryError as err:
                log.info("memory import: %s: %s", ent["name"], err.detail)
        return e["id"]

    def save(self, iid: str, choices: dict[str, str] | None = None) -> dict[str, Any]:
        """Save a ready import with the person's `choices` ("<n>.<k>" → save|review|skip; the preview's otherwise)."""
        r = self._need(iid)
        if r["state"] != "ready":
            raise MemoryError(409, "not_ready", f"the import is {r['state']}", "wait until it is ready" if r["state"] == "reading" else None)
        bad = {k: v for k, v in (choices or {}).items() if v not in CHOICES}
        if bad:
            raise MemoryError(422, "bad_choice", f"a choice is one of {', '.join(CHOICES)}")
        lo = (self.m._row("SELECT MAX(id) AS id FROM mem_log") or {}).get("id") or 0
        counts = {"saved": 0, "review": 0, "same": 0, "skipped": 0, "failed": 0}
        for li in r["result"]:
            pick = {f["key"]: (choices or {}).get(f["key"], f["choice"]) for f in li["facts"]}
            ev = {"import": iid, "from": r["source"], "line": li["text"], **({"section": li["section"]} if li["section"] else {}),
                  "ts": round(_noon(li["date"]) or r["made"], 1)}
            eid = None
            if li.get("entity") and any(pick[f["key"]] != "skip" and f["op"] != "same" for f in li["facts"]):
                try:
                    eid = self._make_entity(li["entity"], any(pick[f["key"]] == "save" for f in li["facts"]))
                except MemoryError as err:
                    log.info("memory import: %s: %s", li["entity"]["name"], err.detail)
            for f in li["facts"]:
                c = pick[f["key"]]
                if c == "skip":
                    counts["skipped"] += 1
                    continue
                try:
                    if f["op"] == "same":
                        if self.m.fact_row(f["held"]["id"]) and self.m.fact_row(f["held"]["id"])["state"] in ("active", "proposed"):
                            self.m.saw(f["held"]["id"], [ev], by="import")
                        counts["same"] += 1
                        continue
                    about = list(f["about"])
                    if eid and li["entity"]:
                        names = {norm(n) for n in [li["entity"]["name"], *li["entity"]["aliases"]]}
                        about = [eid if norm(a.partition("/")[2] or a) in names else a for a in about]
                    old = f["held"]["id"] if f["op"] == "replaces" and f["held"] else None
                    if old and (self.m.fact_row(old) or {}).get("state") not in ("active", "proposed"):
                        old = None
                    self.m.add_fact(f["text"], about, f["kind"], li["date"], source="imported",
                                    state="active" if c == "save" else "proposed", confidence=f["confidence"], replaces=old,
                                    evidence=[{**ev, **({"why": f["why"]} if c == "review" and f["why"] else {})}], by="import")
                    counts["saved" if c == "save" else "review"] += 1
                except MemoryError as err:
                    log.info("memory import: %s: %s", f["text"][:80], err.detail)
                    counts["failed"] += 1
        logs = [x["id"] for x in self.m._rows("SELECT id FROM mem_log WHERE id > ? AND by = 'import' ORDER BY id", (lo,))]
        self._set(iid, state="saved", logs=logs, saved={**counts, "at": self.clock()})
        return self.get(iid)

    def undo(self, iid: str) -> dict[str, Any]:
        """Reverse a saved import's changes, newest first. A change whose facts or entries were changed since (by
        anything but this import) is left, and counted as kept."""
        r = self._need(iid)
        if r["state"] != "saved":
            raise MemoryError(409, "not_saved", f"the import is {r['state']}: only a saved one can be undone")
        mine = set(r["logs"] or [])
        undone, kept = 0, 0
        for lid in sorted(mine, reverse=True):
            row = self.m._row("SELECT op, before FROM mem_log WHERE id = ?", (lid,))
            if row is None or not row["before"]:
                continue
            ids = json.loads(row["before"])["ids"]
            later = any(x["id"] > lid and x["id"] not in mine for t in [*ids["entities"], *ids["facts"]] for x in self.m.log(t, 1000))
            if later:
                kept += row["op"] == "fact_add"
                continue
            try:
                mine.add(self.m.undo(lid, by="import")["log"])
                undone += row["op"] == "fact_add"
            except MemoryError:
                kept += row["op"] == "fact_add"
        self._set(iid, state="undone", undone={"undone": undone, "kept": kept, "at": self.clock()})
        return self.get(iid)

    # ---- export (3.2) -------------------------------------------------------------------------------

    def export(self) -> dict[str, Any]:
        """GAIFA's current memory in the export prompt's format: five sections, "[YYYY-MM-DD] - fact", oldest first.
        An imported preference goes back to the section it came from; otherwise the user's rules (a preference not
        written about someone: "Never push…") are Instructions and their tastes ("The user prefers…") Preferences; the rest about them Identity; facts about projects Projects (a fact about the user and a
        project counts as the user's). Topics' and others' facts go under Other."""
        groups: dict[str, list[tuple[str, str]]] = {k: [] for k in ("Instructions", "Identity", "Projects", "Preferences", "Other")}
        for f in self.m.facts(state="active", current=True, limit=100000):
            kinds = {e["kind"] for e in f["entities"]}
            was = next((e.get("section") for e in f["evidence"] if isinstance(e, dict) and e.get("import")), None)
            if was in ("instructions", "preferences") and f["kind"] == "preference":
                sec = was.capitalize()                           # where the import found it
            elif "user" in kinds:
                sec = ("Preferences" if _ABOUT.match(f["text"]) else "Instructions") if f["kind"] == "preference" else "Identity"
            elif "project" in kinds:
                sec = "Projects"
            elif f["kind"] == "preference":
                sec = "Instructions"
            else:
                sec = "Other"
            date = f["valid_from"] or time.strftime("%Y-%m-%d", time.localtime(f["recorded"] or 0))
            groups[sec].append((date, f["text"]))
        parts = [f"## {sec}\n\n" + "\n".join(f"[{d}] - {t}" for d, t in sorted(rows)) for sec, rows in groups.items() if rows]
        return {"text": "\n\n".join(parts) + ("\n" if parts else ""), "count": sum(len(r) for r in groups.values())}
