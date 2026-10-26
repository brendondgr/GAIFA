"""Instructions, skills and memory (plan 14.9), all files under `data/agent/`:

    AGENT.md                     standing instructions, re-read every turn (first 200 lines)
    memory/MEMORY.md             the memory index (in every prompt, first 200 lines)
    memory/<topic>.md            topic files, read on demand (read_skill("memory:<topic>"))
    skills/<name>/SKILL.md       your own skills (YAML frontmatter `name`, `description`: skillfmt.py)

Mods' skills come from the hub (`GET /api/skills`, `GET /api/skills/{mod}/{name}`).
"""

from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Any

from . import skillfmt
from .hubapi import HubAPI, HubCallError

MAX_LINES = 200
NAME = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")



def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:40] or "notes"


class Knowledge:
    def __init__(self, data: Path | None, hub: HubAPI | None, tree: dict[str, str] | None = None, memory: Any = None) -> None:
        self.data = Path(data) if data else Path("data/agent")
        self.hub = hub
        self.memory = memory            # the structured memory (plan structured-memory), when the caller has it
        self._tree = tree               # the chat's harness files (plan 22.1); None: the active version

    @property
    def tree(self) -> dict[str, str]:
        if self._tree is None:
            from .harness import Harness
            self._tree = Harness(self.data).tree()
        return self._tree

    def _head(self, p: Path) -> str:
        try:
            return "\n".join(p.read_text().splitlines()[:MAX_LINES])
        except OSError:
            return ""

    def agent_md(self) -> str:
        return self._head(self.data / "AGENT.md")

    def memory_index(self) -> str:
        """What the prompt's Memory section lists: the current facts, newest first (structured-memory 1.3; Phase 3
        makes this a profile and recall), else the old MEMORY.md."""
        if self.memory is None:
            return self._head(self.data / "memory" / "MEMORY.md")
        from .memory.model import norm
        lines, known = [], set()
        for f in self.memory.facts(current=True, limit=MAX_LINES):
            where = ", ".join(e["path"] for e in f["entities"] if e["id"] != "user")
            lines.append(f"- {f['text']}" + (f" ({where})" if where else ""))
            known.add(norm(f["text"]))
        for line in self._head(self.data / "memory" / "MEMORY.md").splitlines():   # Settings' editor, until Phase 5
            text = re.sub(r"\s*\(\d{4}-\d{2}-\d{2}\)\s*$", "", line.lstrip("-* ").strip())
            if text and not text.startswith("#") and norm(text) not in known:
                lines.append(f"- {text}")
        return "\n".join(lines[:MAX_LINES])

    def user_skills(self) -> list[dict[str, str]]:
        from .harness import skills as harness_skills
        out = harness_skills(self.tree)                 # the harness's skills (plan 22.1), then data/agent/skills/
        from .api_skills import enabled
        for f in sorted((self.data / "skills").glob("*/SKILL.md")):
            if not NAME.match(f.parent.name):                           # .trash, .incoming-…
                continue
            s = skillfmt.load(f.read_text(), f.parent.name)
            out.append({"name": s["name"] or f.parent.name, "description": s["description"], "source": "user",
                        "id": f"user/{f.parent.name}", "enabled": enabled(f.parent), "problems": s["problems"]})
        return out

    async def skills(self) -> list[dict[str, str]]:
        mods = await self.hub.skills() if self.hub else []
        return [*({"name": s["name"], "description": s.get("description", ""), "source": s["mod"], "id": f"{s['mod']}/{s['name']}"}
                  for s in mods), *self.user_skills()]

    async def skill_list(self, off: set[str] | frozenset[str] = frozenset(), ws: dict[str, Any] | None = None) -> str:
        """The skills, without those of mods turned off in this chat (their tools can't be used). Each description
        is one line; the harness's (which the learner writes) and your own at most SKILL_DESC_MAX characters.
        `ws`: the chat's workspace skills and instruction files (skill-sources 2.2), grouped by folder."""
        from .harness import SKILL_DESC_MAX

        def desc(s: dict[str, Any], cap: int) -> str:
            d = re.sub(r"\s+", " ", s.get("description") or "").strip()
            return d if len(d) <= cap else d[: cap - 1] + "…"
        out = "\n".join(f"- {s['id']}: {desc(s, SKILL_DESC_MAX if s['source'] in ('harness', 'user') else 2 * SKILL_DESC_MAX)}"
                        for s in await self.skills() if s["source"] not in off and s.get("enabled", True))
        return out + workspace_list(ws, lambda s: desc(s, 2 * SKILL_DESC_MAX))

    async def read(self, name: str, tid: str | None = None, environment: str | None = None) -> str | None:
        """A skill's body (followed by its other files' names), one of those files (`<id>/<path>`, skill-sources
        1.2; skillfmt.SkillFileError when it can't be read), or a memory topic. None: no such skill."""
        name = name.strip().strip("/")
        if name.startswith("memory:"):
            topic = slug(name[7:])
            p = self.data / "memory" / f"{topic}.md"
            return p.read_text() if p.is_file() else None
        if ":" in name.split("/", 1)[0]:                 # a workspace folder's skill (skill-sources 2.2)
            return await self.read_workspace(name, tid, environment)
        if "/" in name:
            src, n, path = (name.split("/", 2) + [""])[:3]
        else:
            matches = [s for s in await self.skills() if s["name"] == name or s["id"].endswith("/" + name)]
            if not matches:
                return None
            (src, n), path = matches[0]["id"].split("/", 1), ""
        if not NAME.match(n) or not NAME.match(src):
            return None
        sid = f"{src}/{n}"
        if src == "user":
            from .harness import skill_body
            body = skill_body(self.tree, n)
            if body is not None and not path:
                return body
            folder = self.data / "skills" / n
            if not (folder / "SKILL.md").is_file():
                return None
            from .api_skills import enabled
            if not enabled(folder):
                raise skillfmt.SkillFileError("disabled", f"the skill {n} is turned off (Settings → Agent → Skills)")
            if path:
                return skillfmt.read_file(folder, path)
            return skillfmt.parse((folder / "SKILL.md").read_text())["body"] + skillfmt.files_note(sid, skillfmt.files(folder))
        if not self.hub:
            return None
        if path:
            try:
                return (await self.hub.skill_file(src, n, path))["text"]
            except HubCallError as e:
                raise skillfmt.SkillFileError(e.code or "not_found", e.detail) from None
        try:
            s = await self.hub.skill(src, n)
            return s["body"] + skillfmt.files_note(sid, s.get("files") or [])
        except Exception:  # noqa: BLE001
            return None

    async def read_workspace(self, sid: str, tid: str | None, environment: str | None) -> str | None:
        """`<folder>:<skill>` (with its files named after the body), `…/<path>`, or `<folder>:AGENTS.md`."""
        if not self.hub or not tid:
            return None
        try:
            r = await self.hub.chat_skill_read(tid, environment, sid)
        except HubCallError as e:
            raise skillfmt.SkillFileError(e.code or "not_found", e.detail) from None
        return r["text"] + (skillfmt.files_note(sid, r.get("files") or []) if r.get("kind") == "skill" else "")

    async def preferences(self, loaded: set[str], thread: str | None = None) -> str:
        """The user's preferences for the prompt (plan 21.4): tool preferences only for the tools loaded in this chat,
        so they cost nothing elsewhere, and this chat's own. The agent-scoped ones moved to memory (structured-memory
        1.3); one made since by another client moves at the agent's next start."""
        if not self.hub:
            return ""
        try:
            rows = await self.hub.prefs(state="active")
        except Exception:  # noqa: BLE001: the prompt never fails over preferences
            return ""
        lines = []
        for r in rows:
            if r["scope"] == "thread" and not r.get("tool") and thread and r.get("thread") == thread:
                lines.append(f"- {r['value']}")
            elif r["scope"] == "tool" and r.get("tool") in loaded:
                cond = ", ".join(f"{k} {v}" if v in ("present", "absent") else f"{k}={v}" for k, v in (r.get("when") or {}).items())
                lines.append(f"- {r['tool']}: {r['field']} = {r['value']!r}" + (f" (when {cond})" if cond else "")
                             + (f": {r['cue']}" if r.get("cue") else "") + " (the hub fills it in)")
        return "\n".join(lines[:60])

    async def import_memory(self) -> int:
        """Once: lines of the old memory files become agent preferences (plan 21.4). The files stay."""
        mem = self.data / "memory"
        mark = mem / ".imported"
        if not self.hub or mark.exists() or not mem.is_dir():
            return 0
        n = 0
        for f in sorted(mem.glob("*.md")):
            for line in f.read_text().splitlines():
                text = re.sub(r"\s*\(\d{4}-\d{2}-\d{2}\)\s*$", "", line.lstrip("- ").strip())
                if not text or text.startswith("[") and "](" in text:      # index lines point at topic files
                    continue
                await self.hub.create_pref({"value": text, "cue": f.stem if f.name != "MEMORY.md" else "",
                                            "evidence": [{"kind": "memory", "ref": f.name}]})
                n += 1
        mark.write_text(time.strftime("%Y-%m-%d %H:%M"))
        return n

    def remember(self, text: str, topic: str | None = None) -> str | None:
        mem = self.data / "memory"
        mem.mkdir(parents=True, exist_ok=True)
        index = mem / "MEMORY.md"
        day = time.strftime("%Y-%m-%d")
        if topic:
            t = slug(topic)
            f = mem / f"{t}.md"
            with f.open("a") as fh:
                fh.write(f"- {text} ({day})\n")
            lines = index.read_text().splitlines() if index.exists() else []
            if not any(f"({t}.md)" in ln for ln in lines):
                with index.open("a") as fh:
                    fh.write(f"- [{topic}]({t}.md): {text[:100]}\n")
            return t
        with index.open("a") as fh:
            fh.write(f"- {text} ({day})\n")
        return None

    # ---- settings (Settings → Agent) ---------------------------------------------------------

    def files(self) -> dict[str, Any]:
        mem = self.data / "memory"
        return {"agent_md": (self.data / "AGENT.md").read_text() if (self.data / "AGENT.md").exists() else "",
                "memory": (mem / "MEMORY.md").read_text() if (mem / "MEMORY.md").exists() else "",
                "topics": sorted(p.stem for p in mem.glob("*.md") if p.name != "MEMORY.md") if mem.exists() else []}

    def save(self, agent_md: str | None = None, memory: str | None = None) -> None:
        self.data.mkdir(parents=True, exist_ok=True)
        if agent_md is not None:
            _write(self.data / "AGENT.md", agent_md)
        if memory is not None:
            (self.data / "memory").mkdir(exist_ok=True)
            _write(self.data / "memory" / "MEMORY.md", memory)


def _write(p: Path, text: str) -> None:
    tmp = p.with_name(p.name + ".part")
    tmp.write_text(text)
    tmp.replace(p)


def workspace_list(ws: dict[str, Any] | None, desc: Any) -> str:
    """The chat's workspace skills under their folder, and the instruction files to read before working there."""
    if not ws:
        return ""
    folders: dict[str, dict[str, Any]] = {}
    for s in ws.get("skills") or []:
        if s.get("model_invocable", True):
            folders.setdefault(s["folder"]["id"], {"f": s["folder"], "skills": [], "docs": []})["skills"].append(s)
    for d in ws.get("instructions") or []:
        folders.setdefault(d["folder"]["id"], {"f": d["folder"], "skills": [], "docs": []})["docs"].append(d)
    out = ""
    for g in folders.values():
        out += f"\nFrom the workspace folder {g['f']['name']} ({g['f']['path']}):"
        out += "".join(f"\n- {s['id']}: {desc(s)}" for s in g["skills"])
        if g["docs"]:
            out += (f"\nBefore working in {g['f']['name']}, read its instructions with read_skill: "
                    + ", ".join(d["id"] for d in g["docs"]))
    return out
