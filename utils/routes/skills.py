"""Mods' agent skills (plan 14.9): `GET /api/skills`, `GET /api/skills/{mod}/{name}`.

A mod declares `[agent] skills = "skills"`; each `skills/<name>/SKILL.md` starts with YAML frontmatter
(`name`, `description`; `utils/skillfmt.py`). The agent lists the descriptions in its prompt and reads a body when needed.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel

from utils import skillfmt

router = APIRouter(tags=["tools"])
NAME = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


class SkillInfo(BaseModel):
    mod: str
    name: str
    description: str


class Skill(SkillInfo):
    body: str



def _dirs(request: Request) -> list[tuple[str, Path]]:
    hub = request.app.state.hub
    out = []
    for s in hub.services.list() if hub.services else []:
        if s.m is None or s.errors or not s.eff.enabled or not s.m.agent.skills:
            continue
        d = (s.mod.dir / s.m.agent.skills).resolve()
        if d.is_dir() and d.is_relative_to(s.mod.dir.resolve()):
            out.append((s.id, d))
    return out


@router.get("/api/skills", summary="The mods' agent skills: name and description", response_model=list[SkillInfo])
async def list_skills(request: Request) -> list[dict[str, Any]]:
    out = []
    for mod, d in _dirs(request):
        for f in sorted(d.glob("*/SKILL.md")):
            if not NAME.match(f.parent.name):
                continue
            out.append({"mod": mod, "name": f.parent.name, "description": skillfmt.parse(f.read_text())["description"]})
    return out


@router.get("/api/skills/{mod}/{name}", summary="One skill with its body", response_model=Skill)
async def get_skill(mod: str, name: str, request: Request) -> dict[str, Any]:
    from utils.server import HubError

    if NAME.match(name):
        for m, d in _dirs(request):
            f = d / name / "SKILL.md"
            if m == mod and f.is_file():
                s = skillfmt.parse(f.read_text())
                return {"mod": mod, "name": name, "description": s["description"], "body": s["body"]}
    raise HubError(404, "not_found", f"no skill {mod}/{name}")
