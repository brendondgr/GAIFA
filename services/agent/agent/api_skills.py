"""Your own skills (plan skill-sources 3.1): upload one, copy one from a workspace folder, switch it off, delete it.

Skills live in `data/agent/skills/<name>/` (SKILL.md and its files). `.gaifa.json` beside them says where one came
from, whether it is on, and what the screening found. An upload or a copy is checked by the hub's fixed patterns
(`POST /api/screen`: hidden characters, chat-template tokens, phrases aimed at an AI); one with findings, or one the
hub couldn't check, is saved turned off with the reason, and the user turns it on. A deleted skill moves to
`data/agent/skills/.trash/<name>-<date>/`.

    POST   /v1/skills         {files: [{path, data}] | zip, replace?}    data and zip are base64
    POST   /v1/skills/copy    {id, environment?, thread?, replace?}      a workspace skill (<folder>:<skill>)
    PATCH  /v1/skills/{name}  {enabled}
    DELETE /v1/skills/{name}
"""

from __future__ import annotations

import base64
import binascii
import io
import json
import secrets
import shutil
import stat
import time
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from . import skillfmt
from .hubapi import HubCallError

MAX_BYTES = 2 * 1024 * 1024
MAX_FILES = 100
META = ".gaifa.json"


class SkillFileIn(BaseModel):
    path: str = Field(min_length=1, max_length=500, description="The file's path inside the skill (or with the skill's folder first)")
    data: str = Field(description="The file's bytes, base64")


class SkillUpload(BaseModel):
    files: list[SkillFileIn] = Field(default_factory=list, max_length=MAX_FILES + 50)
    zip: str | None = Field(None, description="A zip of one skill folder, base64")
    replace: bool = False


class SkillCopy(BaseModel):
    id: str = Field(min_length=3, max_length=200, description="The workspace skill: <folder>:<skill>")
    environment: str | None = None
    thread: str | None = None
    replace: bool = False


class SkillPatch(BaseModel):
    enabled: bool


class SkillError(Exception):
    def __init__(self, status: int, code: str, detail: str, fix: str | None = None) -> None:
        super().__init__(detail)
        self.status, self.code, self.detail, self.fix = status, code, detail, fix


def meta_of(folder: Path) -> dict[str, Any]:
    try:
        return json.loads((folder / META).read_text())
    except (OSError, ValueError):
        return {}


def enabled(folder: Path) -> bool:
    return meta_of(folder).get("enabled", True) is not False


def _clean(path: str) -> str:
    rel = PurePosixPath(path.replace("\\", "/").strip())
    if not path.strip() or rel.is_absolute() or any(p in ("..", "", ".") for p in rel.parts) or ":" in rel.parts[0]:
        raise SkillError(422, "bad_path", f"{path!r} isn't a path inside the skill")
    if any(p.startswith(".") for p in rel.parts):
        raise SkillError(422, "bad_path", f"{path!r}: hidden files aren't kept in a skill")
    return rel.as_posix()


def from_upload(body: SkillUpload) -> dict[str, bytes]:
    """The uploaded files by their path inside the skill: one SKILL.md at the top, after a shared top folder."""
    files: dict[str, bytes] = {}
    if body.zip:
        try:
            z = zipfile.ZipFile(io.BytesIO(base64.b64decode(body.zip, validate=True)))
        except (binascii.Error, zipfile.BadZipFile, ValueError) as e:
            raise SkillError(422, "bad_zip", f"not a zip file ({e})") from None
        for info in z.infolist():
            if info.is_dir() or info.filename.startswith("__MACOSX/") or PurePosixPath(info.filename).name.startswith("."):
                continue
            if stat.S_ISLNK(info.external_attr >> 16):
                raise SkillError(422, "bad_path", f"{info.filename} is a symlink: a skill holds files only")
            if info.file_size > MAX_BYTES:
                raise SkillError(413, "too_big", f"{info.filename} is over {MAX_BYTES // 1024 // 1024} MB")
            files[_clean(info.filename)] = z.read(info)
    for f in body.files:
        try:
            files[_clean(f.path)] = base64.b64decode(f.data, validate=True)
        except (binascii.Error, ValueError):
            raise SkillError(422, "bad_data", f"{f.path}: the data isn't base64") from None
    if len(files) == 1 and next(iter(files)).lower().endswith(".md") and "/" not in next(iter(files)):
        files = {"SKILL.md": next(iter(files.values()))}                 # one Markdown file: the skill itself
    tops = {p.split("/", 1)[0] for p in files}
    if "SKILL.md" not in files and len(tops) == 1 and all("/" in p for p in files):
        top = tops.pop()                                                # a folder: strip its name
        files = {p[len(top) + 1:]: b for p, b in files.items()}
    return files


def save(data: Path, files: dict[str, bytes], origin: dict[str, Any], findings: list[dict[str, Any]], checked: bool,
         replace: bool) -> dict[str, Any]:
    """Check `files` as one skill and write it to `data/agent/skills/<name>/`; returns its row."""
    if "SKILL.md" not in files:
        raise SkillError(422, "no_skill", "there's no SKILL.md at the top of the skill", "upload the skill's folder, a zip of it, or its SKILL.md")
    if len(files) > MAX_FILES or sum(len(b) for b in files.values()) > MAX_BYTES:
        raise SkillError(413, "too_big", f"a skill holds at most {MAX_FILES} files and {MAX_BYTES // 1024 // 1024} MB")
    try:
        text = files["SKILL.md"].decode("utf-8")
    except UnicodeDecodeError:
        raise SkillError(422, "bad_skill", "SKILL.md isn't UTF-8 text") from None
    s = skillfmt.parse(text)
    name = s["name"]
    if not name or not skillfmt.NAME.match(name) or len(name) > skillfmt.NAME_MAX:
        raise SkillError(422, "bad_name", f"the skill's name {name!r} isn't valid",
                         "the frontmatter needs name: lower-case letters, digits and single hyphens (pdf-forms)")
    if not s["description"]:
        raise SkillError(422, "bad_skill", "the skill has no description", "add description: what it does and when to use it")
    root = data / "skills"
    dest = root / name
    if dest.exists() and not replace:
        raise SkillError(409, "exists", f"you already have a skill named {name}", "replace it, or rename the new one")
    tmp = root / f".incoming-{secrets.token_hex(4)}"
    for rel, b in files.items():
        p = tmp / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b)
    on = checked and not findings
    meta = {"enabled": on, **origin, "added": time.strftime("%Y-%m-%d %H:%M"), "screening": {
        "checked": checked, "findings": findings,
        "note": "" if on else ("the hub couldn't check it: look it over, then turn it on" if not checked else
                               "the screening found text that may be aimed at an AI: look it over, then turn it on")}}
    (tmp / META).write_text(json.dumps(meta, indent=1))
    if dest.exists():
        trash(data, name)
    tmp.rename(dest)
    return row(dest)


def trash(data: Path, name: str) -> Path:
    t = data / "skills" / ".trash"
    t.mkdir(parents=True, exist_ok=True)
    to = t / f"{name}-{time.strftime('%Y%m%d-%H%M%S')}"
    shutil.move(str(data / "skills" / name), to)
    return to


def row(folder: Path) -> dict[str, Any]:
    s = skillfmt.load((folder / "SKILL.md").read_text(), folder.name)
    m = meta_of(folder)
    return {"name": folder.name, "id": f"user/{folder.name}", "description": s["description"], "source": "user",
            "enabled": m.get("enabled", True) is not False, "problems": s["problems"], "files": skillfmt.files(folder),
            "from": m.get("from"), "added": m.get("added"), "screening": m.get("screening")}


async def screened(hub: Any, files: dict[str, bytes]) -> tuple[list[dict[str, Any]], bool]:
    """The hub's pattern screening over the skill's text files: (findings with their file, checked)."""
    out: list[dict[str, Any]] = []
    try:
        for rel, b in files.items():
            try:
                text = b.decode("utf-8")
            except UnicodeDecodeError:
                continue
            r = await hub._json("POST", "/api/screen", json={"text": text})
            out += [{"file": rel, **f} for f in r.get("findings") or []]
    except (HubCallError, OSError, ValueError) as e:
        return [{"file": "", "why": f"not checked: {e}"}], False
    except Exception as e:  # noqa: BLE001: httpx errors; the skill is saved off
        return [{"file": "", "why": f"not checked: {e}"}], False
    return out, True


def add_routes(app: FastAPI) -> None:
    def A(request: Request) -> Any:
        return request.app.state.agent

    def fail(e: SkillError) -> JSONResponse:
        return JSONResponse({"detail": e.detail, "code": e.code, **({"fix": e.fix} if e.fix else {})}, e.status)

    @app.post("/v1/skills", status_code=201, summary="Add a skill of your own: its folder's files, a zip of it, or its SKILL.md")
    async def upload(body: SkillUpload, request: Request) -> Any:
        agent = A(request)
        try:
            files = from_upload(body)
            findings, checked = await screened(agent.hub, files)
            return save(agent.cfg.data, files, {"from": {"kind": "upload"}}, findings, checked, body.replace)
        except SkillError as e:
            return fail(e)

    @app.post("/v1/skills/copy", status_code=201, summary="Copy a workspace folder's skill (<folder>:<skill>) into your own")
    async def copy(body: SkillCopy, request: Request) -> Any:
        agent = A(request)
        try:
            r = await agent.hub.chat_skill_read(body.thread or "", body.environment, body.id, raw=True)
            if r.get("kind") != "skill":
                raise SkillError(422, "not_a_skill", f"{body.id} isn't a skill")
            files = {"SKILL.md": r["text"].encode()}
            for f in r.get("files") or []:
                got = await agent.hub.chat_skill_read(body.thread or "", body.environment, f"{body.id}/{f['path']}")
                files[_clean(f["path"])] = got["text"].encode()
            findings, checked = await screened(agent.hub, files)
            return save(agent.cfg.data, files, {"from": {"kind": "workspace", "id": body.id}}, findings, checked, body.replace)
        except SkillError as e:
            return fail(e)
        except HubCallError as e:
            return JSONResponse({"detail": e.detail, "code": e.code}, e.status if 400 <= e.status < 500 else 502)

    @app.patch("/v1/skills/{name}", summary="Turn one of your skills on or off")
    def patch(name: str, body: SkillPatch, request: Request) -> Any:
        folder = A(request).cfg.data / "skills" / name
        if not skillfmt.NAME.match(name) or not (folder / "SKILL.md").is_file():
            return JSONResponse({"detail": f"you have no skill {name!r}", "code": "not_found"}, 404)
        m = meta_of(folder)
        m["enabled"] = body.enabled
        (folder / META).write_text(json.dumps(m, indent=1))
        return row(folder)

    @app.delete("/v1/skills/{name}", summary="Delete one of your skills (it moves to data/agent/skills/.trash/)")
    def delete(name: str, request: Request) -> Any:
        data = A(request).cfg.data
        if not skillfmt.NAME.match(name) or not (data / "skills" / name / "SKILL.md").is_file():
            return JSONResponse({"detail": f"you have no skill {name!r}", "code": "not_found"}, 404)
        return {"deleted": name, "trash": str(trash(data, name))}
