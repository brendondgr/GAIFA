"""Settings from the environment. GAIFA sets these in service.toml; standalone, each one
defaults to a folder inside this mod."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _path(env: dict, name: str, default: Path) -> Path:
    v = env.get(name, "")
    return Path(v).expanduser() if v else default


@dataclass(frozen=True)
class Settings:
    port: int
    comfy_url: str           # ComfyUI itself (8199)
    data: Path               # adapter state: the node-catalog cache
    db: Path                 # runs, statistics, per-task defaults
    outputs: Path            # ComfyUI's --output-directory
    workflows: Path          # the packs
    comfy_view: Path         # ComfyUI's own workflows folder (symlinks to the packs, drafts)
    models: Path             # ComfyUI's model folders (for memory estimates)
    input: Path              # ComfyUI's input folder (uploads and file inputs go in input/gaifa/)
    control: Path            # bin/comfyui
    hub_url: str             # "" when not under GAIFA
    load_timeout_s: float
    idle_unload_s: float     # 0 = never
    quit_on_exit: bool       # stop an idle ComfyUI when the adapter stops

    @classmethod
    def from_env(cls, env: dict | None = None) -> Settings:
        env = os.environ if env is None else env
        data = _path(env, "COMFY_DATA", ROOT / "data")
        return cls(
            port=int(env.get("GAIFA_PORT") or env.get("COMFY_PORT") or 5070),
            comfy_url=env.get("COMFY_URL", "http://127.0.0.1:8199").rstrip("/"),
            data=data,
            db=_path(env, "COMFY_DB", data / "comfy.db"),
            outputs=_path(env, "COMFY_OUTPUTS", ROOT / "output"),
            workflows=_path(env, "COMFY_WORKFLOWS", ROOT / "workflows"),
            comfy_view=_path(env, "COMFY_VIEW", ROOT / "user" / "default" / "workflows"),
            models=_path(env, "COMFY_MODELS", ROOT.parents[1] / "data" / "models" / "comfyui"),
            input=_path(env, "COMFY_INPUT", ROOT / "input"),
            control=_path(env, "COMFY_CONTROL", ROOT / "bin" / "comfyui"),
            hub_url=env.get("GAIFA_URL", "").rstrip("/"),
            load_timeout_s=float(env.get("COMFY_LOAD_TIMEOUT_S", "600")),
            idle_unload_s=float(env.get("COMFY_IDLE_UNLOAD_S") or 600),
            quit_on_exit=env.get("COMFY_QUIT_ON_EXIT", "1").lower() not in ("0", "false", "no", "off"),
        )
