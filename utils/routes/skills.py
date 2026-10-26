"""Mods' agent skills (plan 14.9): `GET /api/skills`, `GET /api/skills/{mod}/{name}`, and a skill's other files
(skill-sources 1.2): `GET /api/skills/{mod}/{name}/files/{path}`.

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


class SkillFile(BaseModel):
    path: str
    size: int


class Skill(SkillInfo):
    body: str
    files: list[SkillFile] = []


class SkillFileText(BaseModel):
    path: str
    text: str



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

    folder = _folder(request, mod, name)
    if folder is None:
        raise HubError(404, "not_found", f"no skill {mod}/{name}")
    s = skillfmt.parse((folder / "SKILL.md").read_text())
    return {"mod": mod, "name": name, "description": s["description"], "body": s["body"], "files": skillfmt.files(folder)}


@router.get("/api/skills/{mod}/{name}/files/{path:path}", summary="One of a skill's other files, as text",
            response_model=SkillFileText)
async def get_skill_file(mod: str, name: str, path: str, request: Request) -> dict[str, Any]:
    from utils.server import HubError

    folder = _folder(request, mod, name)
    if folder is None:
        raise HubError(404, "not_found", f"no skill {mod}/{name}")
    try:
        return {"path": path, "text": skillfmt.read_file(folder, path)}
    except skillfmt.SkillFileError as e:
        raise HubError(404 if e.code == "not_found" else 422, e.code, e.detail) from None


def _folder(request: Request, mod: str, name: str) -> Path | None:
    if NAME.match(name):
        for m, d in _dirs(request):
            if m == mod and (d / name / "SKILL.md").is_file():
                return d / name
    return None
