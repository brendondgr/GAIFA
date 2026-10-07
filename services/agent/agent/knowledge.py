"""Instructions, skills and memory (plan 14.9), all files under `data/agent/`:

    AGENT.md                     standing instructions, re-read every turn (first 200 lines)
    memory/MEMORY.md             the memory index (in every prompt, first 200 lines)
    memory/<topic>.md            topic files, read on demand (read_skill("memory:<topic>"))
    skills/<name>/SKILL.md       your own skills (frontmatter `name`, `description`)

Mods' skills come from the hub (`GET /api/skills`, `GET /api/skills/{mod}/{name}`).
"""

from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Any

from .hubapi import HubAPI

MAX_LINES = 200
NAME = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


def frontmatter(text: str) -> tuple[dict[str, str], str]:
    if not text.startswith("---"):
        return {}, text
    end = text.find("\n---", 3)
    if end < 0:
        return {}, text
    meta = {}
    for line in text[3:end].strip().splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            meta[k.strip()] = v.strip().strip('"').strip("'")
    return meta, text[end + 4:].lstrip("\n")


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:40] or "notes"


class Knowledge:
    def __init__(self, data: Path | None, hub: HubAPI | None) -> None:
        self.data = Path(data) if data else Path("data/agent")
        self.hub = hub

    def _head(self, p: Path) -> str:
        try:
            return "\n".join(p.read_text().splitlines()[:MAX_LINES])
        except OSError:
            return ""

    def agent_md(self) -> str:
        return self._head(self.data / "AGENT.md")

    def memory_index(self) -> str:
        return self._head(self.data / "memory" / "MEMORY.md")

    def user_skills(self) -> list[dict[str, str]]:
        out = []
        for f in sorted((self.data / "skills").glob("*/SKILL.md")):
            meta, _ = frontmatter(f.read_text())
            out.append({"name": meta.get("name") or f.parent.name, "description": meta.get("description", ""),
                        "source": "user", "id": f"user/{f.parent.name}"})
        return out

    async def skills(self) -> list[dict[str, str]]:
        mods = await self.hub.skills() if self.hub else []
        return [*({"name": s["name"], "description": s.get("description", ""), "source": s["mod"], "id": f"{s['mod']}/{s['name']}"}
                  for s in mods), *self.user_skills()]

    async def skill_list(self) -> str:
        return "\n".join(f"- {s['id']}: {s['description']}" for s in await self.skills())

    async def read(self, name: str) -> str | None:
        name = name.strip().strip("/")
        if name.startswith("memory:"):
            topic = slug(name[7:])
            p = self.data / "memory" / f"{topic}.md"
            return p.read_text() if p.is_file() else None
        if "/" in name:
            src, n = name.split("/", 1)
        else:
            matches = [s for s in await self.skills() if s["name"] == name or s["id"].endswith("/" + name)]
            if not matches:
                return None
            src, n = matches[0]["id"].split("/", 1)
        if not NAME.match(n) or not NAME.match(src):
            return None
        if src == "user":
            p = self.data / "skills" / n / "SKILL.md"
            return frontmatter(p.read_text())[1] if p.is_file() else None
        if not self.hub:
            return None
        try:
            return (await self.hub.skill(src, n))["body"]
        except Exception:  # noqa: BLE001
            return None

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
