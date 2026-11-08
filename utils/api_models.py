"""Pydantic models for the service routes: the brief's §6.4 types, used as response models
so `/api/openapi.json` documents them and responses are checked against them."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from utils.config import command_patterns, mic_labels, tool_globs

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
    stage: str | None = Field(None, description='"waiting_gpu" while it waits for the GPU slot (plan 31.3)')
    ahead: list[dict[str, Any]] | None = Field(None, description="waiting_gpu: what runs before it ({service, label, eta_s})")
    eta_s: float | None = Field(None, description="waiting_gpu: seconds until it starts, when known")
    live: dict[str, Any] | None = Field(None, description="Live progress (plan 44.2): stage, stages, step, steps, eta_s, preview {url, seq, w, h}, lines, audio; paths on the hub")


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
    logo_url: str | None = Field(description="The mod's logo (`[ui] logo`, else `ui/logo.svg`), or null: the UI draws a monogram")
    chat_url: str | None = Field(None, description="The mod's chat module (`[ui] chat`, plan 44.1), loaded by the Chat page; null without one")
    has_outputs: bool
    native_ui: str | None
    enabled: bool
    autostart: bool
    last_error: str | None
    manifest_errors: list[str]
    accel: str | None = Field(None, description="The variant installed (plan 38.3): rocm, cuda, xpu, mps, vulkan, cpu; null: not recorded")
    unavailable: str | None = Field(None, description="Why it can't start on this machine (its variant's accel isn't here), else null")


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
    accel: str | None = Field(None, description="The variant installed (rocm, cuda, xpu, mps, vulkan, cpu; plan 38.2); null: not recorded")


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
    accel: Literal["rocm", "cuda", "xpu", "mps", "vulkan", "cpu"] | None = None


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

OutputKind = Literal["audio", "image", "video", "model3d", "text", "document", "archive", "other"]


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
    subtype: str | None = Field(None, description='Text and documents: "markdown", "plain", "code:python", "config:toml", "web:html", "data:csv", "subtitles", "notebook", "pdf", "docx", …')
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
    hidden: bool | None = Field(None, description="Set (true) for an output kept out of the lists people see: the sidecar's `hidden` (the web mod's saved pages)")


class OutputTotals(_Model):
    count: int
    size_bytes: int
    by_kind: dict[str, int] = Field(description="Counts with every filter except kind")
    by_service: dict[str, int] = Field(description="Counts with every filter except service")
    hidden: int = Field(0, description="Hidden outputs with these filters (listed only with `include_hidden=true`)")


class OutputPage(_Model):
    items: list[Output]
    next_cursor: str | None
    totals: OutputTotals


class OutlineItem(_Model):
    level: int
    title: str
    offset: int
    line: int
    page: int | None = None


class OutputText(_Model):
    text: str
    offset: int
    next_offset: int | None = Field(description="Where the next read starts; null at the end")
    total_chars: int
    tokens: int = Field(description="The whole text's token estimate (chars / 4)")
    pages: int = Field(description="Page count (PDFs); 0 for text without pages")
    lines: int
    page_of_offset: int | None
    outline: list[OutlineItem]
    scanned: list[int] = Field(description="PDF pages with almost no text (scans): look at them with the page image")
    truncated: bool = Field(description="The text was cut at 4 M characters")
    notes: list[str]


class SearchHit(_Model):
    page: int | None = None
    line: int
    offset: int
    text: str = Field(description="The line with one line of context on each side")


class OutputSearch(_Model):
    hits: list[SearchHit]
    total: int
    capped: bool | None = Field(None, description="true when more than 5,000 matches were found: `total` counts the first 5,000")


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
    gpu_busy_pct: float | None = Field(None, description="How busy the mod kept the GPU since the last sample: its "
                                       "busiest engine's share of the time, 0–100 (DRM fdinfo; absent until two samples)")
    vram_bytes: int | None = Field(None, description="Its VRAM on dedicated GPUs (plan 36.1; only on machines that have one)")


class MemoryPool(_Model):
    """A memory budget (plan 36.1): `system`, and `gpu:<index>` for each dedicated GPU."""

    id: str
    name: str
    total_bytes: int
    used_bytes: int
    available_bytes: int


class SystemMemory(_Model):
    """The brief's `Memory` (named apart from ServiceSummary's `Memory`)."""

    total_bytes: int
    used_bytes: int
    available_bytes: int
    reserve_bytes: int
    gpu: Gpu | None
    by_service: list[ServiceMemory]
    other_bytes: int = Field(description="OS, desktop, browser: anything GAIFA doesn't own")
    pools: list[MemoryPool] = Field(description="system first, then each dedicated GPU's VRAM (one pool where every GPU shares the system's memory)")


class PlanStep(_Model):
    id: str
    frees_bytes: int
    reason: str
    pool: str | None = Field(None, description="Set when the step frees a GPU's pool (its VRAM), not system memory")


class PlanPool(_Model):
    pool: str
    name: str
    needs_bytes: int
    available_bytes: int
    enough: bool


class MakeRoomPlan(_Model):
    service: str
    needs_bytes: int
    available_bytes: int
    unload: list[PlanStep]
    enough: bool
    pool: str = Field("system", description="The pool that's short (system or gpu:<index>)")
    pools: list[PlanPool] = Field(default_factory=list, description="Each pool the load needs: system, and its GPU's when it has dedicated VRAM")


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
    logs: str     # data/logs: mod and hub logs (plan 16.1)
    state: str    # data/state: mods' runtime state (plan 16.2)


class Usage(_Model):
    models_bytes: int
    databases_bytes: int
    outputs_bytes: int
    logs_bytes: int
    state_bytes: int


class SystemInfo(_Model):
    """The brief's `System`."""

    hub: HubProcess
    paths: SystemPaths
    usage: Usage
    disk: Disk


class HardwareGpu(_Model):
    """One GPU (plan 35.2): `utils.hardware.Gpu`."""

    vendor: Literal["amd", "nvidia", "intel", "apple"]
    name: str
    memory: Literal["unified", "dedicated", "unknown"] = Field(description="unified: shares the system's RAM; dedicated: its own VRAM")
    vram_bytes: int = Field(description="dedicated: its VRAM; unified: what it may address")
    arch: str = Field(description="gfx1151, sm_89, m3, … (empty when unknown)")
    driver: str
    pci: str
    index: int
    vendor_index: int = Field(description="Its place among this vendor's GPUs (what CUDA_VISIBLE_DEVICES and the like count)")
    runtimes: dict[str, str]
    accels: list[str] = Field(description="What can run on it here: rocm, cuda, xpu, mps, vulkan")
    problems: list[str] = Field(description="Why an accel it could have isn't usable")


class Hardware(_Model):
    """What this machine has (plan 35.2): `utils.hardware.Machine`."""

    os: Literal["linux", "darwin", "windows"]
    arch: str
    wsl: bool
    container: str = Field(description="toolbox, podman or docker when the hub runs inside one")
    distro: dict[str, str]
    kernel: str
    cpu: str
    cpus: int
    ram_bytes: int
    pkg: str = Field(description="The package manager found: dnf, apt, zypper, pacman, brew")
    gpus: list[HardwareGpu]
    accels: list[str] = Field(description="Every accel usable here, best first; cpu last")
    unified: bool = Field(description="One memory pool: every GPU shares the system's RAM (or there's none)")


class DoctorCheck(_Model):
    area: Literal["models", "manifests", "paths", "ports", "units", "disk", "offline", "repos"]
    level: Literal["ok", "note", "warn", "fail"]
    title: str
    detail: str
    fix: str | None = None


class DoctorCounts(_Model):
    ok: int
    note: int
    warn: int
    fail: int


class Doctor(_Model):
    """`gaifa doctor`'s report (plan 12.4)."""

    ts: float
    ok: bool
    counts: DoctorCounts
    checks: list[DoctorCheck]


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


class NavSettings(_Model):
    """`[ui.nav]`: the sidebar (plan 33.2)."""
    collapsed: bool = Field(False, description="The sidebar is the thin rail")
    services: Literal["list", "button", "counts"] = Field("list", description="Services as a list, one button, or a button with counts")
    hidden: list[str] = Field([], description="Mod ids left out of the sidebar's list")
    folded: bool = Field(False, description="The list is folded under its header")


class ChatListSettings(_Model):
    """`[ui.chat.list]`: the chat list's View menu."""
    group: Literal["environment", "none"] = "environment"
    env_order: Literal["activity", "name", "created"] = "activity"
    chat_order: Literal["updated", "title", "created"] = "updated"
    collapsed: list[str] = Field([], description="Environment ids whose section is folded")


class ChatUiSettings(_Model):
    """`[ui.chat]` (settings-that-stick 3.1)."""
    steps: Literal["fold", "split"] = Field("fold", description="Steps between messages: one fold per turn, or split at each message")
    list: ChatListSettings = ChatListSettings()
    environment: str | None = Field(None, description="The environment a new chat starts in (the last one picked)")


class OverviewSettings(_Model):
    """`[ui.overview]` (settings-that-stick 3.1)."""
    view: Literal["dashboard", "services", "table", "timeline"] = "dashboard"
    timeline_range: Literal["1h", "6h", "24h", "7d"] = "24h"
    services_range: Literal["1h", "6h", "24h", "7d"] = "24h"


class UiSettings(_Model):
    theme: Literal["system", "light", "dark"]
    density: Literal["comfortable", "compact"]
    dashboard: DashboardLayout
    nav: NavSettings = NavSettings()
    chat: ChatUiSettings = ChatUiSettings()
    overview: OverviewSettings = OverviewSettings()


class LearningSettings(_Model):
    enabled: bool
    nightly_at: str = Field(pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    idle_min: int = Field(ge=5)
    infer_after: int = Field(ge=1)
    fade_days: int = Field(ge=1)


class SpeechInputSettings(_Model):
    """Plan 29.4: dictation in Chat."""
    mics: list[str] = Field(description="Microphone labels, most preferred first; the first one present is used")
    language: str = Field(pattern=r"^([a-z]{2,3})?$", description="ISO code, or empty to detect")
    preset: Literal["fast", "balanced", "accurate", "best"]
    mode: Literal["both", "toggle", "hold"] = Field(description="Click to start and stop, hold to talk, or either")

    _labels = field_validator("mics")(lambda cls, v: mic_labels(v))


class JudgeSettings(_Model):
    """`[agent.judge]`: the Auto mode's judge (plan 30.3)."""
    backend: Literal["relay", "decide"]
    model: str = Field(min_length=1, max_length=200, description="A relay model name, or a decide model id")
    url: str = Field(min_length=1, max_length=500, description="The relay, or the decide mod")
    threshold: float = Field(gt=0, le=1, description="decide: every answer must clear it")
    timeout_s: float = Field(gt=0, le=60, description="Slower than this → ask")
    context: Literal["none", "trail", "full"] = Field("none", description="What it reads of the turn so far besides the "
                                                      "user's words: the agent's earlier calls (trail), or also their "
                                                      "results and its text, as untrusted data (full); judge_context.py")
    allow_commands: list[str] = Field([], description="Your rules: commands that run in Auto unless a fixed rule asks "
                                      "(`pytest *`; utils/tools/judge_user.py)")
    ask_commands: list[str] = Field([], description="Your rules: commands that always ask in Auto")

    _patterns = field_validator("allow_commands", "ask_commands")(lambda cls, v: command_patterns(v))


class PermissionsSettings(_Model):
    """`[agent.permissions]`: tool-name globs (plan 13.2, 25.1); the order they apply in is architecture §14.7."""
    deny: list[str]
    ask: list[str]
    allow: list[str] = Field(description="Ignored for `execute` tools: only a grant skips their card")

    _globs = field_validator("deny", "ask", "allow")(lambda cls, v: tool_globs(v))


class ScreenSettings(_Model):
    """`[agent.screen]`: screening fetched pages (and, when on, documents and transcripts) with the judge's model (plan 30.6)."""
    pages: bool
    documents: bool
    transcripts: bool
    timeout_s: float = Field(gt=0, le=600)
    window_chars: int = Field(ge=200, le=20000)
    backend: Literal["relay", "decide"] | None = Field(None, description="The screening model's backend; null: the judge's")
    model: str | None = Field(None, min_length=1, max_length=200, description="null: the judge's (or the backend's default)")
    url: str | None = Field(None, min_length=1, max_length=500, description="null: the judge's (or the backend's default)")
    threshold: float | None = Field(None, gt=0, le=1, description="decide: a passage is for a human reader at or above it")
    confirm: bool = Field(True, description="decide: what it flags is read again by the judge's chat model (relay)")
    parallel: int = Field(4, ge=1, le=32, description="Model calls at once for one text")


class WebReadSettings(_Model):
    """`[agent.web]`: how web_fetch returns a page longer than its max_chars (`utils/tools/webread.py`)."""
    relevance: Literal["auto", "decide", "lexical", "off"] = Field(description="Its passages most relevant to the question "
                                                                   "first: auto (the decide mod when it's up with its model "
                                                                   "loaded, else lexical), decide, lexical (words in common), "
                                                                   "off (the page's start)")
    model: str = Field(min_length=1, max_length=200, description="The decide model that scores passages")
    url: str = Field(min_length=1, max_length=500, description="The decide mod")
    candidates: int = Field(ge=4, le=200, description="decide re-ranks lexical's best this many passages")
    timeout_s: float = Field(gt=0, le=60, description="Slower than this: lexical's order")


class ReposSettings(_Model):
    """`[repos]` (plan mod-repos 3.5): the mods that are their own repositories."""
    fetch_every_h: float = Field(ge=0, le=720, description="How often the hub asks GitHub what's new; 0 = never")
    notify: Literal["warnings", "all", "off"] = Field(description="Alerts: warnings, all (updates too) or off")
    check_on_start: bool = Field(description="Read their state (local git) when the hub starts")


class OutputsSettings(_Model):
    """`[outputs]` (plan 30.9)."""
    hidden_keep_days: float = Field(ge=0, le=3650, description="Hidden outputs (the web mod's saved pages) older than this "
                                    "go to the outputs trash; 0 keeps them")


class SpeechOutputSettings(_Model):
    """Plan 49.1: reading replies aloud, and voice mode (49.2)."""
    voice: str = Field(description="A saved voice or a Kokoro voice; empty for the tts mod's default")
    engine: Literal["auto", "breeze", "kokoro"]
    speed: float = Field(ge=0.5, le=2.0, description="Kokoro only")
    auto_read: bool = Field(description="Read every reply aloud when it's finished")
    pause_ms: int = Field(ge=400, le=5000, description="Voice mode: the quiet that ends what you said")


class Settings(_Model):
    hub: HubSettings
    memory: MemorySettings
    services: ServicesSettings
    ui: UiSettings
    learning: LearningSettings
    speech_input: SpeechInputSettings
    speech_output: SpeechOutputSettings
    judge: JudgeSettings
    screen: ScreenSettings
    permissions: PermissionsSettings
    web: WebReadSettings
    outputs: OutputsSettings
    repos: ReposSettings


class SettingsPatch(_Model):
    """`PUT /api/settings`: the whole `Settings` or any part of it; what is left out stays as it is."""

    hub: dict[str, Any] | None = None
    memory: dict[str, Any] | None = None
    services: dict[str, Any] | None = None
    ui: dict[str, Any] | None = None
    learning: dict[str, Any] | None = None
    speech_input: dict[str, Any] | None = None
    speech_output: dict[str, Any] | None = None
    judge: dict[str, Any] | None = None
    screen: dict[str, Any] | None = None
    permissions: dict[str, Any] | None = None
    web: dict[str, Any] | None = None
    outputs: dict[str, Any] | None = None
    repos: dict[str, Any] | None = None
    base: dict[str, dict[str, Any]] | None = Field(None, description="What each changed key held when the writer loaded it (section → key → value): "
                                                     "lists and tables merge with what is saved now; a value changed on both sides is a 409 settings_conflict")


class SavedSettings(_Model):
    settings: Settings
    restart_required: bool


# ---- the rest of the hub's routes (plan 6.7: every route documents its response) ----


class Rescan(_Model):
    added: list[str]
    removed: list[str]
    changed: list[str]


class Check(_Model):
    name: str
    status: Literal["ok", "fail", "warn", "skip"]
    ok: bool
    detail: str


class CheckReport(_Model):
    """`gaifa check <id>`: the mod self-test."""

    ok: bool
    checks: list[Check]


class DiscoveredFile(_Model):
    path: str
    role: str
    size_bytes: int | None


class Discovered(_Model):
    path: str
    size_bytes: int
    suggested_kind: ModelKind
    suggested_name: str
    suggested_id: str
    format: str
    files: list[DiscoveredFile]
    source: ModelSource | None = None


class ScanResult(_Model):
    discovered: list[Discovered]


class Grant(_Model):
    granted: bool
    freed: list[str] = Field(description="Mods unloaded to make room")
    plan: MakeRoomPlan
