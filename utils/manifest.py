"""Mod manifests: `services/<id>/service.toml` (architecture §4.3–4.5).

- `discover(dirs)` finds every mod folder and parses its manifest. A broken
  manifest never raises: the mod is still listed, with `errors`, so the UI
  can show what is wrong and the hub keeps running.
- `effective(mod, cfg)` merges `[services.<id>]` from config.toml over the
  manifest defaults (port, env, enabled, autostart, ...).
- `launch_spec(mod, cfg, paths, hub_port)` expands placeholders and builds the
  environment: what a backend needs to start the mod.

Nothing here starts processes or touches the network.
"""

from __future__ import annotations

import os
import re
import shutil
import shlex
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import AfterValidator, BaseModel, BeforeValidator, ConfigDict, Field, ValidationError, field_validator, model_validator

from utils.config import Config
from utils.paths import Paths

MANIFEST = "service.toml"
SERVICE_ID = re.compile(r"^[a-z][a-z0-9-]{1,31}$")
OP = re.compile(r"^(GET|POST|PUT|PATCH|DELETE) /\S*$")
PLACEHOLDER = re.compile(r"\{([a-z_]+)\}")
PLACEHOLDERS = ("root", "service_dir", "port", "models", "outputs", "databases", "hf_home", "hub_url")
TOOL_NAME = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
WIDGET_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
DEFAULT_PRIORITY = 100

ResponseKind = Literal["json", "audio", "image", "video", "model3d", "file", "stream", "empty"]
OutputKind = Literal["audio", "image", "video", "model3d", "text", "archive", "other"]


class ManifestError(ValueError):
    """A problem found while building a mod's launch spec (bad placeholder, unreadable env_file)."""


def _env_value(v: Any) -> Any:
    # TOML numbers and booleans in `env` are written as strings, the way a shell would see them.
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(v)
    return v


EnvValue = Annotated[str, BeforeValidator(_env_value)]


def _op(v: str) -> str:
    if not OP.match(v):
        raise ValueError(f"{v!r} is not an operation; write it as \"METHOD /path\", e.g. \"POST /v1/load\"")
    return v


Op = Annotated[str, AfterValidator(_op)]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RunVariant(_Strict):
    """`[run.variants.<accel>]` (plan 38.3): what changes when the mod runs that variant."""
    env: dict[str, EnvValue] = {}


class RunSpec(_Strict):
    kind: Literal["process", "external"] = "process"
    command: list[str] = []
    cwd: str = "."
    port: int = Field(ge=1, le=65535)
    health: str = "/health"
    status: str | None = None
    openapi: str | None = "/openapi.json"
    env: dict[str, EnvValue] = {}
    env_file: str | None = None
    start_timeout_s: float = Field(60, gt=0, le=3600)
    stop_timeout_s: float = Field(30, gt=0, le=3600)
    restart: Literal["no", "on-failure"] = "on-failure"
    after: list[str] = []
    install: str | None = None
    installed: list[str] = []   # what exists once the mod is set up: paths (~/… or in the mod folder) or commands, any one; default: the command's first word
    variants: dict[Literal["rocm", "cuda", "xpu", "mps", "vulkan", "cpu"], RunVariant] = {}   # plan 38.3: env per accel, over [run].env

    @field_validator("installed", mode="before")
    @classmethod
    def _one_or_more(cls, v: Any) -> Any:
        return [v] if isinstance(v, str) else v

    @field_validator("command", mode="before")
    @classmethod
    def _split(cls, v: Any) -> Any:
        return shlex.split(v) if isinstance(v, str) else v

    @field_validator("health")
    @classmethod
    def _health(cls, v: str) -> str:
        if v != "tcp" and not v.startswith("/"):
            raise ValueError('must be a path starting with "/" or "tcp"')
        return v

    @field_validator("status", "openapi")
    @classmethod
    def _route(cls, v: str | None) -> str | None:
        if v == "":
            return None  # TOML has no null: "" means "this mod has none"
        if v is not None and not v.startswith("/"):
            raise ValueError('must be a path starting with "/"')
        return v

    @field_validator("env")
    @classmethod
    def _env_names(cls, v: dict[str, str]) -> dict[str, str]:
        for k in v:
            if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", k):
                raise ValueError(f"{k!r} is not a valid environment variable name")
        return v

    @model_validator(mode="after")
    def _needs_command(self) -> RunSpec:
        if self.kind == "process" and not self.command:
            raise ValueError('[run].command is required (or set kind = "external")')
        return self


class MemorySpec(_Strict):
    estimate_gb: float | None = Field(None, ge=0)
    vram_gb: float | None = Field(None, ge=0)   # plan 36.2: VRAM on a dedicated GPU (on a unified machine, added to estimate_gb)
    load: Op | None = None
    unload: Op | None = None
    triggers: list[Op] = []
    extra_units: list[str] = []
    containers: list[str] = []
    idle_unload_s: int | None = Field(None, ge=0)  # the default; config.toml may override (0 = never)
    idle_unload_env: str | None = None  # the env variable the mod reads it from, e.g. LOCALTTS_IDLE_UNLOAD_S

    @field_validator("idle_unload_env")
    @classmethod
    def _env_name(cls, v: str | None) -> str | None:
        if v is not None and not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", v):
            raise ValueError(f"{v!r} is not an environment variable name")
        return v


class GpuSpec(_Strict):
    """[gpu] (plan 31.2): the mod takes the GPU slot around its GPU work (`POST /api/gpu/acquire`). The
    defaults for its leases; a lease can override both."""
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    cls: Literal["interactive", "job", "background"] = Field("job", alias="class")
    group: str | None = Field(None, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$")   # default: the mod id


class ModelsSpec(_Strict):
    dirs: list[str] = []

    @field_validator("dirs")
    @classmethod
    def _inside(cls, v: list[str]) -> list[str]:
        for d in v:
            if d.startswith("/") or ".." in Path(d).parts:
                raise ValueError(f"{d!r} must be a folder inside data/models")
        return v


LOGO_TYPES = (".svg", ".png", ".webp")


class OutputsSpec(_Strict):
    kinds: list[OutputKind] = []


class WidgetSpec(_Strict):
    id: str
    title: str
    kind: Literal["line", "area", "bar", "donut", "number", "table"]
    source: Op
    ranges: list[str] = []
    span: Literal[3, 4, 6, 12] = 4

    @field_validator("id")
    @classmethod
    def _id(cls, v: str) -> str:
        if not WIDGET_ID.match(v):
            raise ValueError(f"{v!r}: use lowercase letters, digits, - and _")
        return v


class UiSpec(_Strict):
    page: str | None = None
    native: str | None = None
    logo: str | None = None   # plan 33.1: unset = ui/logo.svg when that file exists
    chat: str | None = None   # plan 44.1: a chat module (`export default function setup(chat)`) inside ui/
    widgets: list[WidgetSpec] = []

    @field_validator("chat")
    @classmethod
    def _chat(cls, v: str | None) -> str | None:
        if v is None:
            return v
        p = Path(v)
        if p.is_absolute() or ".." in p.parts or p.parts[:1] != ("ui",) or p.suffix != ".js":
            raise ValueError(f"{v!r} must be a .js file inside the mod's ui/ folder")
        return v

    @field_validator("logo")
    @classmethod
    def _logo(cls, v: str | None) -> str | None:
        if v is None:
            return v
        p = Path(v)
        if p.is_absolute() or ".." in p.parts or p.parts[:1] != ("ui",) or len(p.parts) < 2:
            raise ValueError(f"{v!r} must be a file inside the mod's ui/ folder")
        if p.suffix.lower() not in LOGO_TYPES:
            raise ValueError(f"{v!r} must be an .svg, .png or .webp image")
        return v

    @field_validator("page")
    @classmethod
    def _page(cls, v: str | None) -> str | None:
        if v is None:
            return v
        p = Path(v)
        if p.is_absolute() or ".." in p.parts or p.parts[:1] != ("ui",):
            raise ValueError(f"{v!r} must be a file inside the mod's ui/ folder")
        if p.suffix != ".js" and not v.endswith(".dc.html"):
            raise ValueError(f"{v!r} must be a .js page module or a .dc.html component")
        return v

    @field_validator("native")
    @classmethod
    def _native(cls, v: str | None) -> str | None:
        if v is not None and not (v.startswith("/") or v.startswith(("http://", "https://"))):
            raise ValueError('must be a path on the mod ("/ui/") or a full http(s) URL')
        return v

    @field_validator("widgets")
    @classmethod
    def _unique(cls, v: list[WidgetSpec]) -> list[WidgetSpec]:
        ids = [w.id for w in v]
        dup = {i for i in ids if ids.count(i) > 1}
        if dup:
            raise ValueError(f"duplicate widget id {sorted(dup)[0]!r}")
        return v


class ApiSpec(_Strict):
    hide: list[str] = []
    responses: dict[str, ResponseKind] = {}

    @field_validator("responses")
    @classmethod
    def _ops(cls, v: dict[str, str]) -> dict[str, str]:
        for k in v:
            _op(k)
        return v


Risk = Literal["read", "write", "generate", "network", "execute", "destructive"]


class ToolSpec(_Strict):
    op: Op
    description: str = ""
    confirm: bool = False         # the same as risk = "destructive"
    risk: Risk | None = None      # default: read for GET, destructive for DELETE or confirm, else write (plan 13.1)
    grant_key: str | None = None  # plan 25.2: what one "allow" covers ("url:host", "arg:<name>", "const:<word>")
    dry_run: bool = False         # the mod answers dry runs (the agent eval) itself: `dry_run` in X-AIHub-Origin (plan 26.2)
    ask: list[str] = []           # inputs the user chooses: editable on the parameter card
    examples: list[dict[str, Any]] = []
    core: bool = False            # always loaded in the chat (plan 14.6)
    hide: list[str] = []          # parameters the agent doesn't see (the mod's default applies)
    fixed: dict[str, Any] = {}    # values always sent, hidden from the agent (e.g. stream = false)
    view: dict[str, Any] | None = None   # plan 46.1: how its result draws in Chat (utils/tools/views.py)
    job: bool = False             # the call returns a job id; the agent API waits for the job (plan 13.2)
    job_status: Op | None = None  # "GET /v1/jobs/{id}": `{id}` (or any one placeholder) is the job id
    job_cancel: Op | None = None
    cap_kb: int | None = Field(None, ge=1, le=256)  # results kept whole up to this many KB (default 8; plan 27.2)

    @field_validator("grant_key")
    @classmethod
    def _grant_key(cls, v: str | None) -> str | None:
        from utils.tools.grants import GRANT_KEY

        if v is not None and not GRANT_KEY.match(v):
            raise ValueError(f"grant_key {v!r} must be \"url:host\", \"arg:<parameter>\" or \"const:<word>\"")
        return v

    @model_validator(mode="after")
    def _job(self) -> ToolSpec:
        if self.job and not self.job_status:
            raise ValueError("job = true needs job_status (the operation that reports the job, e.g. \"GET /v1/jobs/{id}\")")
        return self


class AgentSpec(_Strict):
    """[agent]: tools a mod lists at runtime (comfy's task tools), read by the tool catalog (plan 13.1),
    and the mod's skills folder (plan 14.9)."""
    tools_source: Op | None = None
    skills: str | None = None     # a folder inside the mod: skills/<name>/SKILL.md
    limits: Op | None = None      # plan 27.4: "POST /v1/limits", the preflight the hub asks before deciding a call

    @field_validator("skills")
    @classmethod
    def _skills(cls, v: str | None) -> str | None:
        if v is not None and (v.startswith("/") or ".." in Path(v).parts):
            raise ValueError(f"{v!r} must be a folder inside the mod")
        return v


class Manifest(_Strict):
    id: str
    name: str = ""
    description: str = ""
    icon: str = "box"
    version: str | None = None
    run: RunSpec
    memory: MemorySpec | None = None
    gpu: GpuSpec | None = None
    models: ModelsSpec = ModelsSpec()
    outputs: OutputsSpec | None = None
    ui: UiSpec = UiSpec()
    api: ApiSpec = ApiSpec()
    tools: dict[str, ToolSpec] = {}
    agent: AgentSpec = AgentSpec()

    @field_validator("id")
    @classmethod
    def _id(cls, v: str) -> str:
        if not SERVICE_ID.match(v):
            raise ValueError(f"{v!r} must match [a-z][a-z0-9-]{{1,31}} (lowercase, digits and -, 2–32 characters)")
        return v

    @field_validator("version", mode="before")
    @classmethod
    def _version(cls, v: Any) -> Any:
        return str(v) if isinstance(v, (int, float)) else v

    @field_validator("tools")
    @classmethod
    def _tools(cls, v: dict[str, ToolSpec]) -> dict[str, ToolSpec]:
        for k in v:
            if not TOOL_NAME.match(k):
                raise ValueError(f"tool name {k!r}: use lowercase letters, digits and _")
        return v

    @model_validator(mode="after")
    def _defaults(self) -> Manifest:
        if not self.name:
            self.name = self.id
        return self


@dataclass
class Mod:
    """One folder under `services/`. `manifest` is None when it couldn't be parsed."""

    id: str  # the folder name (always set, even when the manifest is broken)
    dir: Path
    manifest: Manifest | None
    raw: dict[str, Any] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.manifest is not None and not self.errors

    @property
    def name(self) -> str:
        if self.manifest:
            return self.manifest.name
        name = self.raw.get("name")
        return name if isinstance(name, str) and name else self.id

    @property
    def manifest_port(self) -> int:
        """The manifest's port, or 0 when it has none (broken manifests)."""
        if self.manifest:
            return self.manifest.run.port
        port = (self.raw.get("run") or {}).get("port") if isinstance(self.raw.get("run"), dict) else None
        return port if isinstance(port, int) and not isinstance(port, bool) else 0


@dataclass
class Effective:
    """A mod's settings after `[services.<id>]` in config.toml is applied (brief `ServiceConfig`)."""

    enabled: bool
    autostart: bool
    port: int
    idle_unload_s: int | None
    auto_unload: bool
    priority: int
    env: dict[str, str]
    accel: str | None = None   # plan 38.2: the variant `aihub setup` installed ([services.<id>] accel)

    def as_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)


@dataclass
class LaunchSpec:
    """Everything a backend needs to start a mod."""

    id: str
    argv: list[str]
    cwd: Path
    env: dict[str, str]
    port: int
    stop_timeout_s: float
    outputs: Path


# --- discovery -----------------------------------------------------------------


def discover(dirs: list[Path], hub_port: int = 7000) -> list[Mod]:
    """Every mod in `dirs` (sorted by id). Folders starting with `_` or `.` are skipped.

    Later dirs can't redefine an id from an earlier one; the duplicate is listed with an error.
    """
    mods: list[Mod] = []
    seen: dict[str, Mod] = {}
    for base in dirs:
        if not base.is_dir():
            continue
        for d in sorted(p for p in base.iterdir() if p.is_dir()):
            if d.name.startswith(("_", ".")) or not (d / MANIFEST).exists():
                continue
            mod = parse(d)
            if mod.id in seen:
                mod.errors.append(f"{MANIFEST}: id {mod.id!r} is already used by {seen[mod.id].dir}")
            else:
                seen[mod.id] = mod
            mods.append(mod)
    _check_ports(mods, hub_port)
    return sorted(mods, key=lambda m: m.id)


def parse(folder: Path) -> Mod:
    folder_id = folder.name
    mod = Mod(id=folder_id, dir=folder.resolve(), manifest=None)
    if not SERVICE_ID.match(folder_id):
        mod.errors.append(f"folder name {folder_id!r} is not a valid mod id (lowercase letters, digits and -, 2–32 characters)")
    try:
        mod.raw = tomllib.loads((folder / MANIFEST).read_text())
    except tomllib.TOMLDecodeError as e:
        mod.errors.append(f"{MANIFEST}: not valid TOML: {e}")
        return mod
    except (OSError, UnicodeDecodeError) as e:
        mod.errors.append(f"{MANIFEST}: can't read it: {e}")
        return mod
    try:
        mod.manifest = Manifest.model_validate(mod.raw)
    except ValidationError as e:
        mod.errors.extend(describe(e))
        # Whole-model rules don't run once a field fails; report the common one anyway,
        # so every problem shows at once.
        run = mod.raw.get("run")
        missing = '[run].command is required (or set kind = "external")'
        if isinstance(run, dict) and run.get("kind", "process") == "process" and not run.get("command") and not any(missing in x for x in mod.errors):
            mod.errors.append(f"{MANIFEST}: {missing}")
        return mod
    if mod.manifest.id != folder_id:
        mod.errors.append(f"{MANIFEST}: id {mod.manifest.id!r} must equal the folder name {folder_id!r}")
    return mod


def describe(err: ValidationError) -> list[str]:
    """Pydantic errors as `service.toml: [run].port: Field required`."""
    out = []
    for e in err.errors():
        loc = [str(p) for p in e["loc"]]
        if len(loc) > 1:
            where = f"[{loc[0]}].{'.'.join(loc[1:])}"
        elif loc:
            where = loc[0]
        else:
            where = "(top level)"
        msg = e["msg"].removeprefix("Value error, ")
        if e["type"] == "extra_forbidden":
            msg = "unknown key (check the spelling against architecture §4.3)"
        elif e["type"] == "missing":
            msg = "required"
        # Messages that name their own location ("[run].command is required") don't repeat it.
        out.append(f"{MANIFEST}: {msg}" if msg.startswith("[") else f"{MANIFEST}: {where}: {msg}")
    return out


def _check_ports(mods: list[Mod], hub_port: int) -> None:
    by_port: dict[int, Mod] = {}
    for m in sorted(mods, key=lambda m: m.id):
        if not m.manifest:
            continue
        port = m.manifest.run.port
        if port == hub_port:
            m.errors.append(f"{MANIFEST}: [run].port {port} is the hub's own port")
        elif port in by_port:
            m.errors.append(f"{MANIFEST}: [run].port {port} is already used by {by_port[port].id}")
        else:
            by_port[port] = m


# --- config.toml overrides --------------------------------------------------------


def effective(mod: Mod, cfg: Config) -> Effective:
    """`[services.<id>]` over the manifest defaults. Unknown mods default to enabled + autostart."""
    defaults = {
        "enabled": True,
        "autostart": True,
        "port": mod.manifest_port,
        "idle_unload_s": mod.manifest.memory.idle_unload_s if mod.manifest and mod.manifest.memory else None,
        "auto_unload": True,
        "priority": cfg.memory.priority.index(mod.id) if mod.id in cfg.memory.priority else DEFAULT_PRIORITY,
        "env": {},
        "accel": None,
    }
    merged = cfg.service_override(mod.id, defaults)
    merged.pop("gpu", None)          # read by launch_spec and the memory manager, not part of ServiceConfig
    if merged["idle_unload_s"] == 0:
        merged["idle_unload_s"] = None  # config.toml writes "never" as 0 (TOML has no null)
    return Effective(**merged)


def check_effective_ports(mods: list[Mod], cfg: Config, hub_port: int) -> dict[str, str]:
    """Port clashes after overrides: {mod id: error}. Discovery only sees manifest ports."""
    clashes: dict[str, str] = {}
    by_port: dict[int, str] = {}
    for m in sorted(mods, key=lambda m: m.id):
        if not m.manifest:
            continue
        port = effective(m, cfg).port
        if port == hub_port:
            clashes[m.id] = f"port {port} is the hub's own port"
        elif port in by_port:
            clashes[m.id] = f"port {port} is already used by {by_port[port]}"
        else:
            by_port[port] = m.id
    return clashes


# --- placeholders and environment -------------------------------------------------------


def placeholders(mod: Mod, paths: Paths, port: int, hub_port: int) -> dict[str, str]:
    return {
        "root": str(paths.root),
        "service_dir": str(mod.dir),
        "port": str(port),
        "models": str(paths.models),
        "outputs": str(paths.outputs / mod.id),
        "databases": str(paths.databases),
        "hf_home": str(paths.models / "hf-cache"),
        "hub_url": f"http://127.0.0.1:{hub_port}",
    }


def expand(value: str, values: dict[str, str], where: str) -> str:
    """Replace `{name}` placeholders. An unknown `{lowercase_name}` is an error, so typos don't pass silently."""

    def sub(m: re.Match[str]) -> str:
        name = m.group(1)
        if name not in values:
            raise ManifestError(f"{where}: unknown placeholder {{{name}}} (known: {', '.join('{' + p + '}' for p in PLACEHOLDERS)})")
        return values[name]

    return PLACEHOLDER.sub(sub, value)


def read_env_file(path: Path) -> dict[str, str]:
    """A `.env` file: `KEY=value` lines, `#` comments, optional `export ` and quotes. No placeholders."""
    env: dict[str, str] = {}
    try:
        text = path.read_text()
    except OSError as e:
        raise ManifestError(f"env_file {path.name}: can't read it: {e.strerror}") from None
    for n, line in enumerate(text.splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        line = line.removeprefix("export ").lstrip()
        key, sep, value = line.partition("=")
        key = key.strip()
        if not sep or not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", key):
            raise ManifestError(f"env_file {path.name}:{n}: expected KEY=value")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        elif " #" in value:
            value = value.split(" #", 1)[0].rstrip()
        env[key] = value
    return env


def hub_env(mod: Mod, paths: Paths, port: int, hub_port: int) -> dict[str, str]:
    """The variables every mod gets (architecture §4.4)."""
    return {
        "AIHUB_URL": f"http://127.0.0.1:{hub_port}",
        "AIHUB_SERVICE_ID": mod.id,
        "AIHUB_PORT": str(port),
        "AIHUB_ROOT": str(paths.root),
        "AIHUB_MODELS": str(paths.models),
        "AIHUB_OUTPUTS": str(paths.outputs / mod.id),
        "AIHUB_DATABASES": str(paths.databases),
        "HF_HOME": str(paths.models / "hf-cache"),
        "PYTHONUNBUFFERED": "1",
    }


def resolve_arg(arg: str, base: Path, first: bool) -> str:
    """Relative paths in `command` resolve against the mod folder: the executable when it contains a `/`,
    any other argument when it starts with `./` or `../`. Bare names (`python3`) are looked up on PATH."""
    if arg.startswith("/"):
        return arg
    if (first and "/" in arg) or arg.startswith(("./", "../")):
        # normpath, not resolve(): a venv's bin/python is a symlink, and Python only finds
        # its venv when started through that link.
        return os.path.normpath(base / arg)
    return arg


def gpu_pin(mod_id: str, cfg: Config) -> int | str | None:
    """`[services.<id>] gpu`: an index, "auto", or None (plan 36.3)."""
    ov = cfg.services.overrides.get(mod_id)
    return ov.gpu if ov else None


def launch_spec(mod: Mod, cfg: Config, paths: Paths, hub_port: int, gpu_index: int | None = None, machine: Any = None) -> LaunchSpec:
    """What a backend starts: argv, cwd and env with placeholders expanded. Raises ManifestError.
    `gpu_index`: the GPU the hub picked for it ("auto" on a machine with more than one)."""
    if not mod.manifest or mod.errors:
        raise ManifestError("; ".join(mod.errors) or f"{mod.id}: no manifest")
    m = mod.manifest
    eff = effective(mod, cfg)
    values = placeholders(mod, paths, eff.port, hub_port)
    argv = [expand(a, values, f"[run].command[{i}]") for i, a in enumerate(m.run.command)]
    argv = [resolve_arg(a, mod.dir, i == 0) for i, a in enumerate(argv)]
    cwd_s = expand(m.run.cwd, values, "[run].cwd")
    cwd = Path(cwd_s) if Path(cwd_s).is_absolute() else (mod.dir / cwd_s)
    env = hub_env(mod, paths, eff.port, hub_port)
    if m.run.env_file:
        env_file = Path(expand(m.run.env_file, values, "[run].env_file"))
        env_file = env_file if env_file.is_absolute() else mod.dir / env_file
        if env_file.exists():  # optional: secrets that haven't been written yet
            env.update(read_env_file(env_file))
    env.update({k: expand(v, values, f"[run].env.{k}") for k, v in m.run.env.items()})
    if eff.accel:          # plan 38.3: the variant `aihub setup` installed ([services.<id>] accel)
        if machine is None:
            from utils import hardware
            machine = hardware.detect()
        from utils.hardware import DEVICE
        env["AIHUB_ACCEL"], env["AIHUB_DEVICE"] = eff.accel, DEVICE.get(eff.accel, "cpu")
        arch = next((g.arch for g in machine.gpus if eff.accel in g.accels and g.arch), "")
        if arch:
            env["AIHUB_GPU_ARCH"] = arch
        var = m.run.variants.get(eff.accel)
        if var:
            env.update({k: expand(v, values, f"[run.variants.{eff.accel}].env.{k}") for k, v in var.env.items()})
    if m.memory:  # idle unload stays inside the mod (plan 5.6): seconds, 0 = never
        idle = str(eff.idle_unload_s or 0)
        env["AIHUB_IDLE_UNLOAD_S"] = idle
        if m.memory.idle_unload_env:
            env[m.memory.idle_unload_env] = idle
    if m.gpu:  # plan 31.2: the defaults the mod's gpu_slot client reads
        env["AIHUB_GPU_CLASS"] = m.gpu.cls
        env["AIHUB_GPU_GROUP"] = m.gpu.group or mod.id
    rt = cfg.containers.runtime        # plan 37.4: the runtime a mod's containers use (services/_template/containers.py)
    if rt == "auto":
        rt = "podman" if shutil.which("podman") else "docker" if shutil.which("docker") else ""
    if rt:
        env["AIHUB_CONTAINER_RUNTIME"] = rt
    pin = gpu_pin(mod.id, cfg)
    index = pin if isinstance(pin, int) and not isinstance(pin, bool) else gpu_index
    if index is not None:          # plan 36.3: only on machines with more than one GPU to choose from
        if machine is None:
            from utils import hardware
            machine = hardware.detect()
        if len(machine.compute_gpus()) > 1:
            env.update(machine.visible_env(index))
    env.update({k: expand(v, values, f"config.toml [services.{mod.id}].env.{k}") for k, v in eff.env.items()})
    return LaunchSpec(
        id=mod.id,
        argv=argv,
        cwd=cwd.resolve(),
        env=env,
        port=eff.port,
        stop_timeout_s=m.run.stop_timeout_s,
        outputs=paths.outputs / mod.id,
    )


# --- ordering ------------------------------------------------------------------------------


def ordered(mods: list[Mod], order: list[str]) -> list[Mod]:
    """Config `[services] order` first, then the rest by id (the sidebar order)."""
    rank = {sid: i for i, sid in enumerate(order)}
    return sorted(mods, key=lambda m: (rank.get(m.id, len(rank)), m.id))


def start_order(mods: list[Mod], order: list[str]) -> list[Mod]:
    """Config order, adjusted so each mod comes after the mods in its `after` list.

    `after` is ordering only: unknown ids are ignored, and a cycle is broken at the
    mod that comes first in config order.
    """
    base = ordered(mods, order)
    by_id = {m.id: m for m in base}
    done: set[str] = set()
    out: list[Mod] = []

    def visit(m: Mod, stack: set[str]) -> None:
        if m.id in done or m.id in stack:
            return
        stack.add(m.id)
        for dep in (m.manifest.run.after if m.manifest else []):
            if dep in by_id:
                visit(by_id[dep], stack)
        stack.discard(m.id)
        if m.id not in done:
            done.add(m.id)
            out.append(m)

    for m in base:
        visit(m, set())
    return out
