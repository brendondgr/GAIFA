"""`config.toml`: load, validate and save (architecture §9).

A missing file means defaults. Each mod's own defaults live in its
`service.toml`; `[services.<id>]` here overrides them (`service_override`).
`save()` edits the file through tomlkit so comments and key order survive.
"""

from __future__ import annotations

import ipaddress
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

    @field_validator("host")
    @classmethod
    def _loopback(cls, v: str) -> str:
        if not is_loopback(v):
            raise ValueError(f"{v!r} is not loopback; AIHub only listens on 127.0.0.1, ::1 or localhost")
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


class PortsCfg(_Strict):
    new_mods: tuple[int, int] = (5100, 5199)

    @field_validator("new_mods")
    @classmethod
    def _range(cls, v: tuple[int, int]) -> tuple[int, int]:
        lo, hi = v
        if not (1 <= lo <= hi <= 65535):
            raise ValueError("must be [low, high] with 1 <= low <= high <= 65535")
        return v


class UiCfg(_Strict):
    theme: Literal["system", "light", "dark"] = "system"
    density: Literal["comfortable", "compact"] = "comfortable"


class ServiceOverride(_Strict):
    """`[services.<id>]`: per-mod values that win over the manifest. Unset = keep the manifest's."""

    port: int | None = Field(None, ge=1, le=65535)
    env: dict[str, str] = {}
    enabled: bool | None = None
    autostart: bool | None = None
    idle_unload_s: int | None = Field(None, ge=0)
    auto_unload: bool | None = None
    priority: int | None = None


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


class Config(_Strict):
    hub: HubCfg = HubCfg()
    paths: PathsCfg = PathsCfg()
    memory: MemoryCfg = MemoryCfg()
    ports: PortsCfg = PortsCfg()
    ui: UiCfg = UiCfg()
    services: ServicesCfg = ServicesCfg()

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


def load(path: Path) -> Config:
    """Read and validate `path`. A missing file gives the defaults."""
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
