"""Settings changed on gen3d's page, kept in `<state>/settings.json` (under GAIFA `data/state/gen3d/`,
which `gaifa backup` saves; standalone, the data folder). Read on every use, so a change applies to the
next preview without a restart. Precedence: the saved value, else `GEN3D_PREVIEW_DEVICE`, else cpu."""

from __future__ import annotations

import contextlib
import json
import os
import tempfile
import threading
from pathlib import Path
from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field

from .config import settings

DEVICES = ("cpu", "gpu")
FILE = "settings.json"
MAX_BYTES = 64 * 1024
_lock = threading.Lock()
router = APIRouter()


def path() -> Path:
    return settings.state_path / FILE


def saved() -> dict:
    """The valid saved values; a missing, oversized or broken file counts as nothing saved."""
    try:
        p = path()
        if p.stat().st_size > MAX_BYTES:
            return {}
        doc = json.loads(p.read_text())
    except (OSError, ValueError):
        return {}
    if not isinstance(doc, dict):
        return {}
    return {"preview_device": doc["preview_device"]} if doc.get("preview_device") in DEVICES else {}


def preview_device() -> str:
    return saved().get("preview_device") or settings.preview_device


def view() -> dict:
    s = saved()
    return {"preview_device": s.get("preview_device") or settings.preview_device,
            "saved": "preview_device" in s, "default": settings.preview_device, "choices": list(DEVICES)}


def _write(doc: dict) -> None:
    p = path()
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".settings-", suffix=".json", dir=p.parent)
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(doc, f, indent=2)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, p)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


class SettingsChange(BaseModel):
    model_config = ConfigDict(extra="forbid")
    preview_device: Literal["cpu", "gpu"] | None = Field(
        None, description="Where Blender draws preview renders: cpu (Mesa llvmpipe, never the GPU; safer) or gpu "
                          "(faster). null forgets the saved choice (back to GEN3D_PREVIEW_DEVICE, else cpu).")


@router.get("/v1/settings")
def get_settings():
    """The page's settings: {preview_device, saved, default, choices}; `default` applies when nothing is saved."""
    return view()


@router.put("/v1/settings")
def put_settings(change: SettingsChange):
    """Change and save settings; they apply to the next preview, no restart."""
    if "preview_device" in change.model_fields_set:
        with _lock:
            doc = saved()
            if change.preview_device is None:
                doc.pop("preview_device", None)
            else:
                doc["preview_device"] = change.preview_device
            _write(doc)
    return view()
