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
    series: str | None = Field(None, description="The metric series a numeric stat is recorded as (`svc.<id>.stat.<slug>`), for sparklines")


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


# ---- memory (Phase 5) ----


class Gpu(_Model):
    name: str
    vram_total_bytes: int
    vram_used_bytes: int
    gtt_total_bytes: int
    gtt_used_bytes: int


class ServiceMemory(_Model):
    id: str
    used_bytes: int
    estimate_bytes: int | None
    load: LoadState
    idle_s: float | None
    auto_unload: bool
    priority: int


class SystemMemory(_Model):
    """The brief's `Memory` (named apart from ServiceSummary's `Memory`)."""

    total_bytes: int
    used_bytes: int
    available_bytes: int
    reserve_bytes: int
    gpu: Gpu | None
    by_service: list[ServiceMemory]
    other_bytes: int = Field(description="OS, desktop, browser: anything AIHub doesn't own")


class PlanStep(_Model):
    id: str
    frees_bytes: int
    reason: str


class MakeRoomPlan(_Model):
    service: str
    needs_bytes: int
    available_bytes: int
    unload: list[PlanStep]
    enough: bool


# ---- charts (Phase 6, brief §11.7) ----


class Metrics(_Model):
    range: str
    step_s: int
    t: list[int] = Field(description="Unix seconds, one per bucket, evenly spaced")
    series: dict[str, list[float | None]] = Field(description="One value per bucket; null = no sample (a gap)")


class SeriesInfo(_Model):
    name: str
    label: str
    unit: str = Field(description='"bytes", "count", "seconds", "ms", "ratio" or a mod\'s own unit')
    service: str | None = None
    reset: Literal["daily"] | None = None


class StateBand(_Model):
    from_: float = Field(alias="from")
    to: float
    state: ServiceState
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class Span(_Model):
    from_: float = Field(alias="from")
    to: float
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class JobBar(_Model):
    id: str
    label: str
    from_: float = Field(alias="from")
    to: float | None
    state: Literal["queued", "running", "done", "failed", "cancelled"]
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class OutputDot(_Model):
    ts: float
    id: str
    kind: OutputKind


class LaneEvent(_Model):
    ts: float
    level: Literal["warn", "error"]
    text: str


class Lane(_Model):
    service: str
    states: list[StateBand]
    loaded: list[Span]
    jobs: list[JobBar]
    outputs: list[OutputDot]
    events: list[LaneEvent]


class Timeline(_Model):
    from_: float = Field(alias="from")
    to: float
    lanes: list[Lane]
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class OutputBucket(_Model):
    key: str = Field(description="A local date (YYYY-MM-DD), a mod id or a kind")
    count: int
    size_bytes: int
    by_kind: dict[str, int]


class OutputStats(_Model):
    buckets: list[OutputBucket]


class ActivityCell(_Model):
    day: str
    hour: int
    count: int
    errors: int


class ActivityStats(_Model):
    cells: list[ActivityCell]


class JobServiceStats(_Model):
    service: str
    count: int
    failed: int
    p50_s: float
    p90_s: float
    max_s: float


class JobStats(_Model):
    by_service: list[JobServiceStats]


class WidgetInfo(_Model):
    service: str
    id: str
    title: str
    kind: Literal["line", "area", "bar", "donut", "number", "table"]
    ranges: list[str]
    span: Literal[3, 4, 6, 12]


class WidgetSeries(BaseModel):
    name: str
    values: list[float | None]
    axis: Literal["left", "right"] | None = None


class WidgetData(BaseModel):
    """A mod's widget data (extra keys a mod sends are passed through)."""

    unit: str | None = None
    t: list[float] | None = None
    categories: list[str] | None = None
    series: list[WidgetSeries] = []
    rows: list[dict[str, Any]] | None = None


# ---- system, overview and settings (Phase 6.3) ----


class HubProcess(_Model):
    version: str
    pid: int
    uptime_s: int
    rss_bytes: int
    port: int


class SystemPaths(_Model):
    root: str
    models: str
    databases: str
    outputs: str


class Usage(_Model):
    models_bytes: int
    databases_bytes: int
    outputs_bytes: int


class SystemInfo(_Model):
    """The brief's `System`."""

    hub: HubProcess
    paths: SystemPaths
    usage: Usage
    disk: Disk


class Activity(_Model):
    id: str
    ts: float
    service: str | None
    level: Literal["info", "warn", "error"]
    text: str
    route: str | None = None


class AlertAction(_Model):
    label: str
    route: str


class Alert(_Model):
    id: str
    level: Literal["warn", "error"]
    text: str
    service: str | None = None
    action: AlertAction | None = None


class Overview(_Model):
    services: list[ServiceSummary]
    memory: SystemMemory
    recent_outputs: list[Output]
    activity: list[Activity]
    alerts: list[Alert]
    jobs: list[Job]
    system: SystemInfo


class RecentEvents(_Model):
    activity: list[Activity]
    alerts: list[Alert]
    jobs: list[Job]


class HubSettings(_Model):
    port: int = Field(ge=1024, le=65535)


class MemorySettings(_Model):
    reserve_gb: float = Field(ge=0)
    auto_make_room: bool
    never_unload: list[str]
    priority: list[str] = Field(description="Unloaded first → last")


class ServicesSettings(_Model):
    order: list[str]
    enabled: dict[str, bool]
    autostart: dict[str, bool]


class DashboardLayout(_Model):
    order: list[str] = Field([], description="Widget keys in the order shown (missing ones follow in the default order)")
    hidden: list[str] = []
    ranges: dict[str, str] = Field({}, description="Widget key → its chosen range")


class UiSettings(_Model):
    theme: Literal["system", "light", "dark"]
    density: Literal["comfortable", "compact"]
    dashboard: DashboardLayout


class Settings(_Model):
    hub: HubSettings
    memory: MemorySettings
    services: ServicesSettings
    ui: UiSettings


class SettingsPatch(_Model):
    """`PUT /api/settings`: the whole `Settings` or any part of it; what is left out stays as it is."""

    hub: dict[str, Any] | None = None
    memory: dict[str, Any] | None = None
    services: dict[str, Any] | None = None
    ui: dict[str, Any] | None = None


class SavedSettings(_Model):
    settings: Settings
    restart_required: bool
