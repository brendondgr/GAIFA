"""`config.toml`: load, validate and save (architecture §9).

A missing file means defaults. Each mod's own defaults live in its
`service.toml`; `[services.<id>]` here overrides them (`service_override`).
`save()` edits the file through tomlkit so comments and key order survive.
"""

from __future__ import annotations

import ipaddress
import re
import tomllib
from copy import deepcopy
from pathlib import Path
from typing import Any, Literal

import tomlkit
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from utils.paths import Paths, write_atomic

LOOPBACK_NAMES = {"localhost"}


class ConfigError(ValueError):
    """A bad `config.toml`. The message names the file and the key."""


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class HubCfg(_Strict):
    host: str = "127.0.0.1"
    port: int = Field(7000, ge=1, le=65535)
    backend: Literal["auto", "systemd", "detached", "subprocess"] = "auto"   # how mods run (plan 37.1)

    @field_validator("host")
    @classmethod
    def _loopback(cls, v: str) -> str:
        if not is_loopback(v):
            raise ValueError(f"{v!r} is not loopback; GAIFA only listens on 127.0.0.1, ::1 or localhost")
        return v


class PathsCfg(_Strict):
    models: str = "data/models"
    databases: str = "data/databases"
    outputs: str = "outputs"


class MemoryCfg(_Strict):
    reserve_gb: float = Field(12, ge=0)
    auto_make_room: bool = False
    never_unload: list[str] = ["lcpp"]
    priority: list[str] = ["comfy", "tts", "gen3d"]
    peak_days: float = Field(7, gt=0)   # a learned peak older than this stops counting; the next load learns a fresh one


class PortsCfg(_Strict):
    new_mods: tuple[int, int] = (5100, 5199)

    @field_validator("new_mods")
    @classmethod
    def _range(cls, v: tuple[int, int]) -> tuple[int, int]:
        lo, hi = v
        if not (1 <= lo <= hi <= 65535):
            raise ValueError("must be [low, high] with 1 <= low <= high <= 65535")
        return v


class DashboardCfg(_Strict):
    """`[ui.dashboard]`: the Overview dashboard's Customize choices (brief §11.5)."""

    order: list[str] = []
    hidden: list[str] = []
    ranges: dict[str, str] = {}


class NavCfg(_Strict):
    """`[ui.nav]`: the sidebar's choices (plan 33.2): the thin rail, how services are shown, which are left out."""

    collapsed: bool = False
    services: Literal["list", "button", "counts"] = "list"
    hidden: list[str] = []          # mod ids left out of the sidebar's list (new mods show)
    folded: bool = False            # the list folded under its SERVICES header


class ChatListCfg(_Strict):
    """`[ui.chat.list]`: the chat list's View menu (plan 41.2): grouping, both orders, the folded sections."""

    group: Literal["environment", "none"] = "environment"
    env_order: Literal["activity", "name", "created"] = "activity"
    chat_order: Literal["updated", "title", "created"] = "updated"
    collapsed: list[str] = []


class ChatUiCfg(_Strict):
    """`[ui.chat]` (settings-that-stick 3.1): the Chat page's choices, the same in every browser."""

    steps: Literal["fold", "split"] = "fold"     # Steps between messages: one fold per turn, or split at each message
    list: ChatListCfg = ChatListCfg()
    environment: str | None = None               # the environment a new chat starts in (the last one picked)


RANGES = Literal["1h", "6h", "24h", "7d"]


class OverviewCfg(_Strict):
    """`[ui.overview]` (settings-that-stick 3.1): the Overview's view and its charts' ranges."""

    view: Literal["dashboard", "services", "table", "timeline"] = "dashboard"
    timeline_range: RANGES = "24h"
    services_range: RANGES = "24h"               # a service's History charts


class UiCfg(_Strict):
    theme: Literal["system", "light", "dark"] = "system"
    density: Literal["comfortable", "compact"] = "compact"
    dashboard: DashboardCfg = DashboardCfg()
    nav: NavCfg = NavCfg()
    chat: ChatUiCfg = ChatUiCfg()
    overview: OverviewCfg = OverviewCfg()


class ServiceOverride(_Strict):
    """`[services.<id>]`: per-mod values that win over the manifest. Unset = keep the manifest's."""

    port: int | None = Field(None, ge=1, le=65535)
    env: dict[str, str] = {}
    enabled: bool | None = None
    autostart: bool | None = None
    idle_unload_s: int | None = Field(None, ge=0)
    auto_unload: bool | None = None
    priority: int | None = None
    gpu: int | Literal["auto"] | None = Field(None, description="Which GPU (hardware index) on a machine with more than one; auto: the freest at start (plan 36.3)")
    accel: Literal["rocm", "cuda", "xpu", "mps", "vulkan", "cpu"] | None = Field(None, description="The variant `gaifa setup` installed (plan 38.2): the mod gets GAIFA_ACCEL and GAIFA_DEVICE")

    @field_validator("gpu")
    @classmethod
    def _gpu_index(cls, v: Any) -> Any:
        if isinstance(v, int) and not isinstance(v, bool) and v < 0:
            raise ValueError("gpu is a GPU index (0, 1, …) or \"auto\"")
        return v


class ServicesCfg(BaseModel):
    """`order` plus one `[services.<id>]` table per mod."""

    model_config = ConfigDict(extra="forbid")
    order: list[str] = ["relay", "lcpp", "tts", "gen3d", "comfy", "opencode"]
    overrides: dict[str, ServiceOverride] = {}

    @model_validator(mode="before")
    @classmethod
    def _split(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        rest = {k: v for k, v in data.items() if k != "order"}
        out: dict[str, Any] = {"overrides": rest}
        if "order" in data:
            out["order"] = data["order"]
        return out


MAX_PATTERNS = 100
TOOL_GLOB = re.compile(r"[A-Za-z0-9_.*?!\[\]-]{1,100}")
COMMAND_BAD = re.compile(r"[;|&$`<>()\\'\"\x00-\x1f\x7f]")     # shell syntax: a rule names one simple command


def _unique(v: list[str]) -> list[str]:
    if len(v) > MAX_PATTERNS:
        raise ValueError(f"at most {MAX_PATTERNS} entries")
    return list(dict.fromkeys(v))


def tool_globs(v: list[str]) -> list[str]:
    """`[agent.permissions]` lists: tool-name globs (`comfy_*`), trimmed, each once."""
    v = [str(g).strip() for g in v]
    for g in v:
        if not TOOL_GLOB.fullmatch(g):
            raise ValueError(f"{g!r}: a tool name or glob (letters, digits, _ . - and * ? [ ]), 1-100 characters")
    return _unique(v)


def command_patterns(v: list[str]) -> list[str]:
    """`[agent.judge] allow_commands / ask_commands` (`utils/tools/judge_user.py`): a command and its words, with
    `*` globs (`pytest *`); spaces collapsed, each once. The first word is a plain command name (no `*`), and no
    shell syntax (; | & $ < > ( ), backticks, backslashes, quotes), newlines or control characters."""
    out = []
    for raw in v:
        if m := COMMAND_BAD.search(str(raw)):
            raise ValueError(f"{raw!r}: no shell syntax or control characters ({m.group(0)!r}); a rule is one command")
        p = " ".join(str(raw).split())
        if not p or len(p) > 200:
            raise ValueError("each command rule is 1-200 characters")
        if re.search(r"[*?\[]", p.split()[0]):
            raise ValueError(f"{p!r}: start with the command's name (no * in the first word)")
        out.append(p)
    return _unique(out)


class PermissionsCfg(_Strict):
    """Tool permissions (plan 13.2, 25.1): name globs; the order with modes and grants is in `utils/tools/approvals.py`."""
    deny: list[str] = []
    ask: list[str] = ["hub_set_preference", "agent_memory_save", "agent_memory_entity"]   # lasting: reaches every later chat, a card in every mode
    allow: list[str] = ["hub_start_service"]

    _globs = field_validator("deny", "ask", "allow")(lambda cls, v: tool_globs(v))


JUDGE_DECIDE = {"backend": "decide", "model": "d3-lite", "url": "http://127.0.0.1:7000/api/s/decide"}


class JudgeCfg(_Strict):
    """The Auto mode's judge (plan Phase 30, `utils/tools/judge.py`): only ever a decision model in the `decide` mod
    (plan web-approvals 1.1, the user's rule of 2026-11-08), never a chat model through the relay. An older
    `config.toml` with `backend = "relay"` loads with the decide defaults instead (`gaifa doctor` names the keys)."""
    backend: Literal["decide"] = "decide"
    model: str = JUDGE_DECIDE["model"]      # a decide model id
    url: str = JUDGE_DECIDE["url"]          # the decide mod, through the hub
    threshold: float = Field(0.35, gt=0, le=1)   # decide: the lowest "safe" probability of its three questions must reach it (judge.DECIDE_CUTOFF)
    timeout_s: float = Field(3.0, gt=0)     # slower → ask
    context: Literal["none", "trail", "full"] = "none"   # what it reads of the turn so far besides the user's words (judge_context.py)
    allow_commands: list[str] = []          # your rules (judge_user.py): these commands run in Auto, unless a rule asks
    ask_commands: list[str] = []            # … and these always ask

    _patterns = field_validator("allow_commands", "ask_commands")(lambda cls, v: command_patterns(v))

    @model_validator(mode="before")
    @classmethod
    def _decision_model_only(cls, v: Any) -> Any:
        """A chat-model judge (`backend = "relay"`, before web-approvals) is read as the decide defaults."""
        if isinstance(v, dict) and v.get("backend", "decide") != "decide":
            v = {**{k: x for k, x in v.items() if k not in JUDGE_DECIDE}, **JUDGE_DECIDE}
        return v


class ScreenCfg(_Strict):
    """Screening text for instructions aimed at an AI before the chat model reads it (plan 30.6, `utils/tools/screen.py`),
    with the judge's model. Pages are screened; your own documents and transcripts only when turned on."""
    pages: bool = True
    documents: bool = False
    transcripts: bool = False
    timeout_s: float = Field(30.0, gt=0)
    window_chars: int = Field(800, ge=200, le=20000)   # passages per model call: 800 for a small judge (MiniCPM5 2B), 6000 for a large one
    # The screening model, when it isn't the judge's (unset: [agent.judge]'s); screen.screen_config
    backend: Literal["relay", "decide"] | None = None
    model: str | None = None
    url: str | None = None
    threshold: float | None = Field(None, gt=0, le=1)
    confirm: bool = True            # decide: what it flags is read again by the judge's chat model (relay)
    parallel: int = Field(4, ge=1, le=32)   # model calls at once for one text


class WebReadCfg(_Strict):
    """How `web_fetch` returns a page longer than its `max_chars` (`utils/tools/webread.py`): its passages most relevant to
    the call's `focus` or the user's question first. `auto`: the decide mod when it's up with its model loaded, else
    lexical (words in common); `off`: the page's start, as fetched."""
    relevance: Literal["auto", "decide", "lexical", "off"] = "auto"
    model: str = "d3-lite"                                  # the decide model that scores passages
    url: str = "http://127.0.0.1:7000/api/s/decide"
    candidates: int = Field(24, ge=4, le=200)               # decide re-ranks lexical's best this many
    timeout_s: float = Field(8.0, gt=0)                     # slower → lexical's order


class AgentCfg(_Strict):
    permissions: PermissionsCfg = PermissionsCfg()
    judge: JudgeCfg = JudgeCfg()
    screen: ScreenCfg = ScreenCfg()
    web: WebReadCfg = WebReadCfg()
    make_room: bool = True          # tool calls unload idle mods when a model needs room
    approval_ttl_h: float = Field(24, gt=0)


class SessionsCfg(_Strict):
    restore_on_boot: bool = False
    autosave_s: int = Field(300, ge=0)   # 0 = no auto-save


class LearningCfg(_Strict):
    """Plan 21–22: preferences on the cards and the learner. Off: nothing is filled or learned."""
    enabled: bool = True
    nightly_at: str = Field("03:00", pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    idle_min: int = Field(60, ge=5)
    infer_after: int = Field(2, ge=1)       # an inferred preference needs this many times, in as many chats
    fade_days: int = Field(60, ge=1)


def mic_labels(v: list[str]) -> list[str]:
    """Microphone labels: trimmed, not empty, each once, in the order given."""
    out: list[str] = []
    for label in v:
        label = str(label).strip()
        if not label or len(label) > 200:
            raise ValueError("each microphone is its label: 1-200 characters")
        if label not in out:
            out.append(label)
    return out


class SpeechInputCfg(_Strict):
    """Plan 29.4: dictation in Chat (the stt mod). Saved settings, not personal memory."""
    mics: list[str] = Field([], max_length=20)   # microphone labels, most preferred first (browsers change device ids)
    language: str = Field("", pattern=r"^([a-z]{2,3})?$")   # "" = detect
    preset: Literal["fast", "balanced", "accurate", "best"] = "balanced"
    mode: Literal["both", "toggle", "hold"] = "both"   # click to start/stop, hold to talk, or either

    _labels = field_validator("mics")(lambda cls, v: mic_labels(v))


class SpeechOutputCfg(_Strict):
    """Plan 49.1: reading replies aloud in Chat (the tts mod) and voice mode's answers."""
    voice: str = Field("", max_length=120)   # a saved voice or a Kokoro voice; "" = the tts mod's default
    engine: Literal["auto", "breeze", "kokoro"] = "auto"
    speed: float = Field(1.0, ge=0.5, le=2.0)   # Kokoro only
    auto_read: bool = False                     # read every reply aloud when it's finished
    pause_ms: int = Field(1200, ge=400, le=5000)   # voice mode: the quiet that ends what you said (plan 49.2)


class OutputsCfg(_Strict):
    """Plan 30.9: hidden outputs (the web mod's saved pages) older than this go to the outputs trash; 0 keeps them."""
    hidden_keep_days: float = Field(0, ge=0)


class GpuCfg(_Strict):
    """Plan 31.1: the GPU queue. Off: memory-only admission (every lease is granted at once)."""
    queue: bool = True
    lease_ttl_s: float = Field(60, ge=5, le=3600)   # a held lease not renewed for this long is dropped (the mod died)


class DocsCfg(_Strict):
    """Plan 23.3/23.6: the local model inventory (data/state/setup/models/) follows the registry.
    Off (the default): only `gaifa docs` writes it."""
    regenerate: bool = False



class ContainersCfg(_Strict):
    """`[containers]` (plan 37.4): the runtime mods run their engines' containers with."""

    runtime: Literal["auto", "podman", "docker"] = "auto"   # auto: podman if installed, else docker


class ReposCfg(_Strict):
    """`[repos]` (plan mod-repos 3.3): the mods that are their own repositories (relay, lcpp, tts, gen3d)."""

    fetch_every_h: float = Field(24, ge=0, le=24 * 30)   # how often the hub asks GitHub what's new; 0 = never
    notify: Literal["warnings", "all", "off"] = "warnings"   # all: updates and unpinned commits as alerts too
    check_on_start: bool = True                          # read their state (local git only) when the hub starts


class Config(_Strict):
    hub: HubCfg = HubCfg()
    paths: PathsCfg = PathsCfg()
    memory: MemoryCfg = MemoryCfg()
    ports: PortsCfg = PortsCfg()
    ui: UiCfg = UiCfg()
    services: ServicesCfg = ServicesCfg()
    agent: AgentCfg = AgentCfg()
    sessions: SessionsCfg = SessionsCfg()
    learning: LearningCfg = LearningCfg()
    speech_input: SpeechInputCfg = SpeechInputCfg()
    speech_output: SpeechOutputCfg = SpeechOutputCfg()
    docs: DocsCfg = DocsCfg()
    outputs: OutputsCfg = OutputsCfg()
    gpu: GpuCfg = GpuCfg()
    containers: ContainersCfg = ContainersCfg()
    repos: ReposCfg = ReposCfg()

    def service_override(self, service_id: str, defaults: dict[str, Any]) -> dict[str, Any]:
        """Merge `[services.<id>]` over a mod's manifest defaults.

        `env` is merged key by key; every other set key replaces the default.
        """
        merged = deepcopy(defaults)
        ov = self.services.overrides.get(service_id)
        if ov is None:
            return merged
        for key, value in ov.model_dump(exclude_unset=True).items():
            if key == "env":
                merged["env"] = {**merged.get("env", {}), **value}
            elif value is not None:
                merged[key] = value
        return merged


def is_loopback(host: str) -> bool:
    if host.lower() in LOOPBACK_NAMES:
        return True
    try:
        return ipaddress.ip_address(host.strip("[]")).is_loopback
    except ValueError:
        return False


def validate(data: dict[str, Any], source: str = "config.toml") -> Config:
    try:
        return Config.model_validate(data)
    except ValidationError as e:
        raise ConfigError(_describe(e, source)) from None


EXAMPLE = "config.example.toml"   # tracked: the defaults; config.toml itself is each machine's own (plan 23.11)


def ensure(path: Path) -> None:
    """A fresh clone has no config.toml: copy it from the tracked example next to it, once."""
    example = path.with_name(EXAMPLE)
    if not path.exists() and example.is_file():
        write_atomic(path, example.read_text())


def load(path: Path) -> Config:
    """Read and validate `path`, made from config.example.toml first when it's missing. With
    neither file, the defaults."""
    ensure(path)
    if not path.exists():
        return Config()
    try:
        data = tomllib.loads(path.read_text())
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"{path.name}: not valid TOML: {e}") from None
    return validate(data, path.name)


def save(path: Path, changes: dict[str, Any]) -> Config:
    """Apply the nested `changes` to the file, keeping comments and order.

    Only the keys given are touched; a `None` value removes its key, and
    `Replace(value)` sets a table as a whole instead of merging into it. The
    result is validated before it is written; on error the file is left
    unchanged and ConfigError is raised.
    """
    doc = tomlkit.parse(path.read_text()) if path.exists() else tomlkit.document()
    _merge(doc, changes)
    cfg = validate(doc.unwrap(), path.name)
    write_atomic(path, tomlkit.dumps(doc))
    return cfg


def build_paths(cfg: Config, root: Path | None = None) -> Paths:
    """The project paths, with `[paths]` resolved against the root (where config.toml lives)."""
    try:
        return Paths.build(root, cfg.paths.models, cfg.paths.databases, cfg.paths.outputs)
    except ValueError as e:
        raise ConfigError(f"config.toml: {e}") from None


class Replace:
    """In `save()` changes: set this value as a whole instead of merging into the existing table."""

    def __init__(self, value: Any) -> None:
        self.value = value


def _merge(table: Any, changes: dict[str, Any]) -> None:
    for key, value in changes.items():
        if value is None:  # None removes the key (TOML has no null)
            if key in table:
                del table[key]
        elif isinstance(value, Replace):
            if key in table:
                del table[key]
            if value.value is not None:
                table[key] = value.value
        elif isinstance(value, dict) and key in table and isinstance(table[key], dict):
            had = len(table[key])
            _merge(table[key], value)
            if had and not len(table[key]):  # this save removed its last key: drop the empty table
                del table[key]
        elif isinstance(value, dict) and key not in table:
            t = tomlkit.table()
            _merge(t, value)
            if len(t):  # don't create a table that would be empty
                table[key] = t
        else:
            table[key] = value


def _describe(err: ValidationError, source: str) -> str:
    parts = []
    for e in err.errors():
        loc = [str(p) for p in e["loc"] if p != "overrides"]
        parts.append(f"{'.'.join(loc) or '(root)'}: {e['msg']}")
    return f"{source}: " + "; ".join(parts)
