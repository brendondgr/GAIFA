"""Pydantic models for the service routes: the brief's §6.4 types, used as response models
so `/api/openapi.json` documents them and responses are checked against them."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

ServiceState = Literal["stopped", "starting", "ready", "degraded", "stopping", "failed"]
LoadState = Literal["unloaded", "loading", "loaded", "unloading", "n/a"]


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Stat(_Model):
    label: str
    value: float | int | str
    unit: str | None = None
    hint: str | None = None
    reset: Literal["daily"] | None = None


class Memory(_Model):
    used_bytes: int
    estimate_bytes: int | None
    peak_bytes: int | None


class Job(_Model):
    id: str
    service: str
    label: str
    progress: float | None
    state: Literal["queued", "running", "done", "failed", "cancelled"]
    route: str | None = None


class ServiceSummary(_Model):
    id: str
    name: str
    description: str
    icon: str
    version: str | None
    kind: Literal["process", "external"]
    port: int
    url: str
    state: ServiceState
    state_since: float
    load: LoadState
    idle_s: float | None
    busy: bool
    memory: Memory
    stats: list[Stat]
    has_page: bool
    page_url: str | None
    has_outputs: bool
    native_ui: str | None
    enabled: bool
    autostart: bool
    last_error: str | None
    manifest_errors: list[str]


class Health(_Model):
    ok: bool
    latency_ms: float | None
    body: Any
    status: int | None = None


class ServiceConfig(_Model):
    enabled: bool
    autostart: bool
    port: int
    idle_unload_s: int | None
    auto_unload: bool
    priority: int
    env: dict[str, str]


class ServiceDetail(ServiceSummary):
    pid: int | None
    started_ts: float | None
    command: list[str]
    folder: str
    outputs_dir: str | None
    models: list[str]
    health: Health | None
    manifest: dict[str, Any]
    config: ServiceConfig
    jobs: list[Job]
    in_flight: int
    last_request_ts: float | None


class ServiceConfigPatch(_Model):
    """`PUT /api/services/{id}/config`: any subset of ServiceConfig. `idle_unload_s: null` means never."""

    enabled: bool | None = None
    autostart: bool | None = None
    port: int | None = Field(None, ge=1, le=65535)
    idle_unload_s: int | None = Field(None, ge=0)
    auto_unload: bool | None = None
    priority: int | None = None
    env: dict[str, str] | None = None


class SavedConfig(_Model):
    config: ServiceConfig
    restart_required: bool


class LogLine(_Model):
    ts: float
    text: str
    stream: Literal["stdout", "stderr"]


class Logs(_Model):
    lines: list[LogLine]


class Param(_Model):
    name: str
    in_: Literal["path", "query"] = Field(alias="in")
    required: bool
    schema_: dict[str, Any] = Field(alias="schema")
    description: str | None = None

    model_config = ConfigDict(extra="forbid", populate_by_name=True, serialize_by_alias=True)


class Body(_Model):
    content_type: Literal["application/json", "multipart/form-data"]
    schema_: dict[str, Any] = Field(alias="schema")

    model_config = ConfigDict(extra="forbid", populate_by_name=True, serialize_by_alias=True)


class Tool(_Model):
    name: str
    confirm: bool


class Operation(_Model):
    id: str
    method: Literal["GET", "POST", "PUT", "PATCH", "DELETE"]
    path: str
    summary: str
    description: str
    tag: str
    params: list[Param]
    body: Body | None
    response: Literal["json", "audio", "image", "video", "model3d", "file", "stream", "empty"]
    destructive: bool
    tool: Tool | None


# ---- models registry (Phase 3) ----

ModelKind = Literal["llm", "tts", "stt", "voice", "3d", "image", "video", "text-encoder", "vae", "lora", "vision", "upscale", "other"]
ModelStatus = Literal["ok", "missing", "partial", "unverified", "checksum_mismatch", "verifying"]


class ModelFile(_Model):
    path: str
    role: str
    size_bytes: int | None
    exists: bool
    sha256: str | None
    verified: bool


class ModelSource(_Model):
    type: Literal["huggingface", "url", "local", "created"]
    repo: str | None = None
    revision: str | None = None
    url: str | None = None
    note: str | None = None


class Model(_Model):
    id: str
    name: str
    kind: ModelKind
    format: str
    services: list[str]
    path: str
    files: list[ModelFile]
    size_bytes: int
    status: ModelStatus
    problems: list[str]
    source: ModelSource | None
    added_ts: float
    tags: list[str]
    notes: str
    progress: float | None = Field(None, description="0–1 while status is verifying")


class KindTotal(_Model):
    count: int
    size_bytes: int


class ModelTotals(_Model):
    size_bytes: int
    count: int
    by_kind: dict[str, KindTotal]


class Disk(_Model):
    free_bytes: int
    total_bytes: int


class ModelList(_Model):
    models: list[Model]
    totals: ModelTotals
    disk: Disk


# ---- outputs (Phase 4) ----

OutputKind = Literal["audio", "image", "video", "model3d", "text", "archive", "other"]


class OutputFile(_Model):
    path: str
    kind: OutputKind
    size_bytes: int
    role: str | None = None


class Dims(_Model):
    w: int
    h: int


class Output(_Model):
    id: str
    service: str
    kind: OutputKind
    title: str
    path: str = Field(description='"outputs/tts/2026-10-04/143012-good-morning.wav" (a file or a folder)')
    files: list[OutputFile]
    url: str = Field(description="The main file (supports Range)")
    preview: str | None = Field(description="Thumbnail or poster, if there is one")
    size_bytes: int
    created_ts: float
    duration_s: float | None = None
    dims: Dims | None = None
    meta: dict[str, Any] = Field(description="The sidecar's other fields: prompt, model, voice, seed, params, source, …; `excerpt` for text")


class OutputTotals(_Model):
    count: int
    size_bytes: int
    by_kind: dict[str, int] = Field(description="Counts with every filter except kind")
    by_service: dict[str, int] = Field(description="Counts with every filter except service")


class OutputPage(_Model):
    items: list[Output]
    next_cursor: str | None
    totals: OutputTotals
