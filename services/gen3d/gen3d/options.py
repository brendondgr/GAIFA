"""Job request schema, the option catalogue the UI builds its settings menu from, and presets.

A job is a pipeline of stages, each optional:

    shape    Cube3D v0.5: text prompt -> mesh            (needs a prompt)
    parts    CubePart: mesh -> up to 8 named part meshes (needs a mesh: this job's shape, the parent
             job's, or an uploaded one)
    rig      parts -> articulated GLB with joint/slide nodes per limb (needs parts)
    preview  Blender 4-view render of the newest result
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

Stage = Literal["shape", "parts", "rig", "preview"]
STAGE_ORDER: tuple[Stage, ...] = ("shape", "parts", "rig", "preview")
MAX_PARTS = 8  # CubePart always denoises 8 part slots


class ShapeOptions(BaseModel):
    seed: int = Field(0, ge=0, le=2**31 - 1, description="sampling seed (only matters with top_p)")
    top_p: float | None = Field(0.9, gt=0, le=1, description="nucleus sampling; null = deterministic argmax")
    guidance_scale: float = Field(3.0, ge=0, le=10, description="text guidance strength")
    bbox: tuple[float, float, float] | None = Field(None, description="aspect ratio W H D (Y up); null = model decides")
    resolution_base: float = Field(8.0, ge=5.0, le=9.5, description="mesh decode resolution (2^n grid)")
    target_faces: int | None = Field(None, ge=100, le=1_000_000,
                                     description="decimate the mesh to about this many faces; null = full detail")
    fast_engine: bool = Field(False, description="CUDA/HIP-graph engine: same output, 2x memory, not faster on gfx1151")

    @field_validator("bbox")
    @classmethod
    def _bbox(cls, v):
        if v is not None and min(v) <= 0:
            raise ValueError("bbox values must be > 0")
        return v


class PartsOptions(BaseModel):
    parts: list[str] = Field(default_factory=list, description=f"1-{MAX_PARTS} part names")
    steps: int = Field(50, ge=5, le=150, description="diffusion steps (~2.45 s each)")
    guidance_scale: float = Field(7.5, ge=0, le=20)
    resolution_base: float = Field(8.5, ge=6.0, le=9.5, description="part mesh decode resolution (min 6: CubePart samples a fixed 64³ coarse grid)")
    target_faces: int | None = Field(None, ge=100, le=2_000_000,
                                     description="one face budget for all parts together, split by surface area; null = full detail")
    scheduler: Literal["dpm_solver", "euler", "heun"] = "dpm_solver"
    timeshift: float = Field(4.0, ge=0.5, le=10)
    seed: int = Field(0, ge=0, le=2**31 - 1)
    num_samples: int = Field(128_000, ge=16_000, le=256_000, description="surface points sampled from the input mesh")

    @field_validator("parts")
    @classmethod
    def _parts(cls, v: list[str]):
        v = [p.strip() for p in v if p and p.strip()]
        if len(v) > MAX_PARTS:
            raise ValueError(f"CubePart supports at most {MAX_PARTS} parts (got {len(v)})")
        if any(len(p) > 60 for p in v):
            raise ValueError("part names must be 60 characters or fewer")
        return v


class RigOptions(BaseModel):
    height_m: float | None = Field(1.8, gt=0, le=50, description="scale the rigged asset to this height; null = keep units")
    faces_per_part: int = Field(12_000, ge=20, le=200_000, description="decimation cap per part (parts already under it are kept)")
    target_faces: int | None = Field(None, ge=100, le=2_000_000,
                                     description="face budget for the whole rigged asset (the limb split adds faces); null = no cap")


class JobRequest(BaseModel):
    prompt: str = Field("", max_length=1000, description="what to make (needed for the shape stage)")
    stages: list[Stage] = Field(default_factory=lambda: ["shape", "preview"])
    preset: Literal["lowpoly", "fast", "balanced", "quality"] | None = Field(None, description="applied under explicit options")
    shape: ShapeOptions = Field(default_factory=ShapeOptions)
    parts: PartsOptions = Field(default_factory=PartsOptions)
    rig: RigOptions = Field(default_factory=RigOptions)
    chat_id: str | None = None
    parent_id: str | None = Field(None, description="continue from this job's mesh / parts")
    title: str | None = Field(None, max_length=120)

    @field_validator("stages")
    @classmethod
    def _stages(cls, v: list[str]):
        if not v:
            raise ValueError("choose at least one stage")
        return [s for s in STAGE_ORDER if s in set(v)]  # dedupe + canonical order

    @model_validator(mode="after")
    def _consistent(self):
        if "shape" in self.stages and not self.prompt.strip():
            raise ValueError("the shape stage needs a prompt")
        if "parts" in self.stages and not self.parts.parts:
            raise ValueError("the parts stage needs at least one part name")
        return self


PRESETS: dict[str, dict] = {
    "fast": {"label": "Fast", "help": "coarser meshes, 25 CubePart steps (~1 min shape, ~1.8 min parts)",
             "shape": {"resolution_base": 7.5, "target_faces": None},
             "parts": {"steps": 25, "resolution_base": 8.0, "target_faces": None}, "rig": {"target_faces": None}},
    "balanced": {"label": "Balanced", "help": "the upstream defaults (~1.5 min shape, ~3.2 min parts)",
                 "shape": {"resolution_base": 8.0, "target_faces": None},
                 "parts": {"steps": 50, "resolution_base": 8.5, "target_faces": None}, "rig": {"target_faces": None}},
    "lowpoly": {"label": "Low-poly", "help": "about 1,000 faces for the whole asset: coarse decode, then decimation",
                "shape": {"resolution_base": 7.0, "target_faces": 1000},
                "parts": {"steps": 25, "resolution_base": 7.0, "target_faces": 1000},
                "rig": {"target_faces": 1000}},
    "quality": {"label": "Quality", "help": "finer meshes (~2.5 min shape, ~3.7 min parts, 52 GB peak)",
                "shape": {"resolution_base": 8.5, "target_faces": None},
                "parts": {"steps": 50, "resolution_base": 9.0, "target_faces": None}, "rig": {"target_faces": None}},
}

PART_TEMPLATES: dict[str, list[str]] = {
    "Chair": ["seat", "backrest", "legs", "armrests"],
    "Character": ["head", "torso", "left arm", "right arm", "left leg", "right leg"],
    "Vehicle": ["body", "front left wheel", "front right wheel", "rear left wheel", "rear right wheel", "windows"],
    "Weapon": ["blade", "guard", "grip", "pommel"],
    "Creature": ["head", "body", "tail", "wings", "legs"],
}


def apply_preset(raw: dict) -> dict:
    """Merge a preset under the explicit options in a raw request dict (explicit values win)."""
    name = raw.get("preset")
    if not name or name not in PRESETS:
        return raw
    out = dict(raw)
    for group in ("shape", "parts", "rig"):
        merged = dict(PRESETS[name].get(group, {}))
        merged.update(raw.get(group) or {})
        out[group] = merged
    return out


def parse_request(raw: dict) -> JobRequest:
    return JobRequest.model_validate(apply_preset(raw))


def _field(group: str, name: str, model: type[BaseModel], label: str, kind: str, **extra) -> dict:
    f = model.model_fields[name]
    meta = {"group": group, "key": name, "label": label, "type": kind,
            "default": f.get_default(call_default_factory=True), "help": f.description or ""}
    for m in f.metadata:  # ge/le/gt bounds
        for attr, key in (("ge", "min"), ("gt", "min"), ("le", "max"), ("lt", "max")):
            if getattr(m, attr, None) is not None:
                meta[key] = getattr(m, attr)
    meta.update(extra)
    return meta


def catalogue() -> dict:
    """Everything the UI needs to render the settings menu, straight from the schema."""
    return {
        "stages": [
            {"key": "shape", "label": "Generate shape", "help": "Cube3D v0.5 turns the prompt into a mesh"},
            {"key": "parts", "label": "Split into parts", "help": "CubePart separates the mesh into named parts"},
            {"key": "rig", "label": "Rig for games", "help": "joint + telescoping slide per limb, glTF extras"},
            {"key": "preview", "label": "Preview render", "help": "Blender 4-view contact sheet"},
        ],
        "fields": [
            _field("shape", "resolution_base", ShapeOptions, "Mesh resolution", "number", step=0.5,
                   choices=[5.0, 6.0, 6.5, 7.0, 7.5, 8.0, 8.5, 9.0]),
            _field("shape", "target_faces", ShapeOptions, "Face budget", "integer", step=100, nullable=True,
                   null_label="full detail"),
            _field("shape", "top_p", ShapeOptions, "Top-p", "number", step=0.05, nullable=True,
                   null_label="deterministic"),
            _field("shape", "seed", ShapeOptions, "Seed", "integer"),
            _field("shape", "guidance_scale", ShapeOptions, "Guidance", "number", step=0.5),
            _field("shape", "bbox", ShapeOptions, "Bounding box", "bbox", nullable=True),
            _field("shape", "fast_engine", ShapeOptions, "Graph engine", "boolean"),
            _field("parts", "parts", PartsOptions, "Parts", "parts", max_items=MAX_PARTS),
            _field("parts", "steps", PartsOptions, "Steps", "integer"),
            _field("parts", "resolution_base", PartsOptions, "Part resolution", "number", step=0.5,
                   choices=[6.0, 6.5, 7.0, 7.5, 8.0, 8.5, 9.0]),
            _field("parts", "target_faces", PartsOptions, "Face budget (all parts)", "integer", step=100, nullable=True,
                   null_label="full detail"),
            _field("parts", "guidance_scale", PartsOptions, "Guidance", "number", step=0.5),
            _field("parts", "seed", PartsOptions, "Seed", "integer"),
            _field("parts", "scheduler", PartsOptions, "Scheduler", "choice", choices=["dpm_solver", "euler", "heun"]),
            _field("parts", "timeshift", PartsOptions, "Timeshift", "number", step=0.5),
            _field("parts", "num_samples", PartsOptions, "Surface samples", "integer", step=16000),
            _field("rig", "height_m", RigOptions, "Height (m)", "number", step=0.1, nullable=True,
                   null_label="keep units"),
            _field("rig", "faces_per_part", RigOptions, "Faces per part", "integer", step=1000),
            _field("rig", "target_faces", RigOptions, "Face budget (rigged)", "integer", step=100, nullable=True,
                   null_label="no cap"),
        ],
        "presets": PRESETS,
        "part_templates": PART_TEMPLATES,
        "bbox_presets": {"Cube": [1, 1, 1], "Tall": [1, 2, 1], "Wide": [2, 1, 1], "Chair": [1, 1.4, 1],
                         "Flat": [2, 0.5, 2]},
        "max_parts": MAX_PARTS,
        "defaults": JobRequest(prompt="x").model_dump(exclude={"prompt", "chat_id", "parent_id", "title", "preset"}),
    }
