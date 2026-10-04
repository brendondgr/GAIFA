"""The registry's stored shape (architecture §8) and its validation.

`registry.json` is `{"version": 1, "models": {<id>: Entry}}`. Paths are relative
to `data/models/`. Unknown keys in an entry or a file are kept as they are, so a
newer hub's fields survive an older hub's save.
"""

from __future__ import annotations

import posixpath
import re
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

VERSION = 1
KINDS = ("llm", "tts", "stt", "voice", "3d", "image", "video", "text-encoder", "vae", "lora", "vision", "upscale", "other")
STATUSES = ("ok", "missing", "partial", "unverified", "checksum_mismatch", "verifying")
ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
SERVICE_RE = re.compile(r"^[a-z][a-z0-9-]{1,31}$")
SHA_RE = re.compile(r"^[0-9a-f]{64}$")

Kind = Literal["llm", "tts", "stt", "voice", "3d", "image", "video", "text-encoder", "vae", "lora", "vision", "upscale", "other"]


class RegistryError(Exception):
    """Turned into the error envelope: `{detail, code, data?}` with an HTTP status."""

    def __init__(self, status: int, code: str, detail: str, data: dict[str, Any] | None = None) -> None:
        super().__init__(detail)
        self.status, self.code, self.detail, self.data = status, code, detail, data


def rel_path(v: str) -> str:
    """A clean path inside data/models: relative, '/'-separated, no `..`, no trailing slash."""
    if not isinstance(v, str) or not v.strip():
        raise ValueError("must be a non-empty path relative to data/models")
    v = v.strip().replace("\\", "/")
    if v.startswith("/") or "\0" in v:
        raise ValueError(f"{v!r} must be relative to data/models")
    norm = posixpath.normpath(v)
    if norm in (".", "") or norm == ".." or norm.startswith("../"):
        raise ValueError(f"{v!r} must be inside data/models")
    return norm


class Source(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["huggingface", "url", "local", "created"]
    repo: str | None = None
    revision: str | None = None
    url: str | None = None
    note: str | None = None


class FileEntry(BaseModel):
    model_config = ConfigDict(extra="allow")
    path: str
    role: str = "weights"
    size_bytes: int | None = Field(None, ge=0)
    sha256: str | None = None
    verified_at: str | None = None
    actual_sha256: str | None = None  # set by verify when the file no longer matches `sha256`

    @field_validator("path")
    @classmethod
    def _path(cls, v: str) -> str:
        return rel_path(v)

    @field_validator("sha256", "actual_sha256")
    @classmethod
    def _sha(cls, v: str | None) -> str | None:
        if v is not None and not SHA_RE.match(v.lower()):
            raise ValueError("must be 64 hex characters")
        return v.lower() if v else v

    @field_validator("verified_at")
    @classmethod
    def _when(cls, v: str | None) -> str | None:
        if v is not None:
            datetime.fromisoformat(v)
        return v


class Entry(BaseModel):
    model_config = ConfigDict(extra="allow")
    name: str = Field(min_length=1, max_length=200)
    kind: Kind
    format: str = ""
    path: str
    files: list[FileEntry] = []
    services: list[str] = []
    source: Source | None = None
    added: str = Field(default_factory=lambda: now_iso())
    tags: list[str] = []
    notes: str = ""

    @field_validator("path")
    @classmethod
    def _path(cls, v: str) -> str:
        return rel_path(v)

    @field_validator("services")
    @classmethod
    def _services(cls, v: list[str]) -> list[str]:
        for s in v:
            if not SERVICE_RE.match(s):
                raise ValueError(f"{s!r} is not a mod id")
        return list(dict.fromkeys(v))

    @field_validator("tags")
    @classmethod
    def _tags(cls, v: list[str]) -> list[str]:
        return list(dict.fromkeys(t.strip() for t in v if t.strip()))

    @field_validator("added")
    @classmethod
    def _added(cls, v: str) -> str:
        datetime.fromisoformat(v)
        return v

    @field_validator("files")
    @classmethod
    def _unique(cls, v: list[FileEntry]) -> list[FileEntry]:
        seen: set[str] = set()
        for f in v:
            if f.path in seen:
                raise ValueError(f"{f.path} is listed twice")
            seen.add(f.path)
        return v

    def dump(self) -> dict[str, Any]:
        """The stored form: unset optional source fields and `actual_sha256` are left out."""
        out = self.model_dump(exclude={"files", "source"})
        out["source"] = self.source.model_dump(exclude_none=True) if self.source else None
        out["files"] = []
        for f in self.files:
            d = f.model_dump()
            if d.get("actual_sha256") is None:
                d.pop("actual_sha256", None)
            out["files"].append(d)
        return out


class Patch(BaseModel):
    """`PUT /api/models/{id}` (brief `ModelPatch`)."""

    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(None, min_length=1, max_length=200)
    kind: Kind | None = None
    services: list[str] | None = None
    source: Source | None = None
    tags: list[str] | None = None
    notes: str | None = None


def now_iso() -> str:
    return datetime.now().astimezone().replace(microsecond=0).isoformat()


def iso_ts(v: str | None) -> float | None:
    if not v:
        return None
    try:
        d = datetime.fromisoformat(v)
    except ValueError:
        return None
    if d.tzinfo is None:
        d = d.astimezone()
    return d.timestamp()


def first_error(e: Exception) -> str:
    """A pydantic ValidationError as one line: `files.0.path: must be inside data/models`."""
    errors = getattr(e, "errors", None)
    if not callable(errors):
        return str(e)
    items = []
    for x in errors():
        loc = ".".join(str(p) for p in x.get("loc", ()))
        msg = str(x.get("msg", "")).removeprefix("Value error, ")
        items.append(f"{loc}: {msg}" if loc else msg)
    return "; ".join(items)
