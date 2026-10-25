"""Job request schema, the option catalogue the UI builds its settings menu from, and presets.

A job is a pipeline of stages, each optional:

    shape    Cube3D v0.5: text prompt -> mesh            (needs a prompt)
    parts    CubePart: mesh -> up to 8 named part meshes (needs a mesh: this job's shape, the parent
             job's, or an uploaded one)
    rig      parts -> articulated GLB with joint/slide nodes per limb (needs parts)
    preview  Blender 4-view render of the newest result

`engine` picks what makes the mesh in the shape stage: Cube3D from the prompt, or an image engine
(Hunyuan3D 2.1, TRELLIS.2, SAM 3D Objects, SAM 3D Body) from `image` (plan 17; gen3d/image_options.py).
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from .engines import ENGINES, IMAGE_ENGINES
from .image_options import (DEFAULT_IMAGE_PRESET, IMAGE_OPTIONS, IMAGE_PRESETS, Hunyuan21Options, Sam3dBodyOptions,
                            Sam3dObjectsOptions, Trellis2Options, image_fields, preset_values)

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


EngineId = Literal["cube3d", "hunyuan21", "trellis2", "sam3d_objects", "sam3d_body"]
DEFAULT_IMAGE_ENGINE = "trellis2"
IMAGE_REF = re.compile(r"^(output:[A-Za-z0-9_.:-]{1,120}|upload)$")
BARE_OUTPUT = re.compile(r"^[0-9a-f]{12}$")              # the hub's output ids


class Refusal(ValueError):
    """A request that can't run as asked, with what to do instead (sent as the 422's `fix`)."""

    def __init__(self, detail: str, fix: str) -> None:
        super().__init__(detail)
        self.fix = fix


PresetId = Literal["lowpoly", "fast", "balanced", "quality", "base", "draft"]
PRESET_LABELS = {"lowpoly": "Low-poly", "fast": "Fast", "balanced": "Balanced", "quality": "Quality", "base": "Base", "draft": "Draft"}


def engine_options(schema: dict) -> None:
    """`x-options` for `engine` (plan 20.2): which engines take text and which a picture, the default
    for each, and their presets. Built from ENGINES when the schema is made."""
    opts = {}
    for eid, e in ENGINES.items():
        o: dict = {"label": e.label, "good_for": e.help, "speed": e.speed,
                   "allows": {"preset": list(PRESETS) if e.input == "text" else list(IMAGE_PRESETS[eid])}}
        if e.input == "text":
            o.update(excludes=["image"], default=True)
        else:
            o["needs"] = ["image"]
            if eid == DEFAULT_IMAGE_ENGINE:
                o["default"] = True
        opts[eid] = o
    schema["x-options"] = opts


def preset_options(schema: dict) -> None:
    schema["x-depends-on"] = "engine"
    schema["x-options"] = {k: {"label": v} for k, v in PRESET_LABELS.items()}


class JobRequest(BaseModel):
    prompt: str = Field("", max_length=1000, description="what to make (Cube3D's shape stage)")
    engine: EngineId | None = Field(None, description="what makes the mesh: Cube3D from `prompt`, or an image engine from `image` "
                                                      "(pick by what the picture shows). Left out: cube3d, or trellis2 with a picture",
                                    json_schema_extra=engine_options)
    image: str | None = Field(None, description="the picture for an image engine: output:<id> of an image (a GAIFA output)",
                              json_schema_extra={"format": "gaifa-file", "x-kind": "image"})
    stages: list[Stage] = Field(default_factory=lambda: ["shape", "preview"])
    preset: PresetId | None = Field(None, description="applied under explicit options; each engine has its own presets "
                                                      "(image engines use fast unless you pass base)",
                                    json_schema_extra=preset_options)
    shape: ShapeOptions = Field(default_factory=ShapeOptions)
    hunyuan21: Hunyuan21Options = Field(default_factory=Hunyuan21Options)
    trellis2: Trellis2Options = Field(default_factory=Trellis2Options)
    sam3d_objects: Sam3dObjectsOptions = Field(default_factory=Sam3dObjectsOptions)
    sam3d_body: Sam3dBodyOptions = Field(default_factory=Sam3dBodyOptions)
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

    @model_validator(mode="before")
    @classmethod
    def _engine_from_image(cls, raw):
        """A picture without an engine: TRELLIS.2, the most faithful general one (lab, 2026-10-10)."""
        if isinstance(raw, dict) and isinstance(raw.get("image"), str) and BARE_OUTPUT.match(raw["image"]):
            raw = {**raw, "image": f"output:{raw['image']}"}          # an output id without its prefix
        if isinstance(raw, dict) and not raw.get("engine"):
            raw = {**raw, "engine": DEFAULT_IMAGE_ENGINE if raw.get("image") else "cube3d"}
        return raw

    @field_validator("image")
    @classmethod
    def _image(cls, v: str | None):
        if v is not None and not IMAGE_REF.match(v):
            raise ValueError("image must be output:<id> (a GAIFA output) or a file sent to POST /v1/jobs/image")
        return v

    @model_validator(mode="after")
    def _consistent(self):
        engine = self.engine = self.engine or "cube3d"
        names = PRESETS if engine == "cube3d" else IMAGE_PRESETS[engine]
        if self.preset is not None and self.preset not in names:
            raise Refusal(f"{engine} has no preset {self.preset!r}", f"use one of: {', '.join(names)}")
        if engine == "cube3d" and self.image:
            raise Refusal("Cube3D makes a mesh from text and can't use a picture",
                          "for a picture use an image engine: " + "; ".join(f"{k} ({ENGINES[k].help})" for k in IMAGE_ENGINES)
                          + "; or leave out `image` to make it from the prompt")
        if "shape" in self.stages and engine == "cube3d" and not self.prompt.strip():
            raise Refusal("the shape stage needs a prompt", "add `prompt`: what to make")
        if "shape" in self.stages and engine != "cube3d" and not self.image:
            raise Refusal(f"{ENGINES[engine].label} makes the mesh from a picture: give `image`",
                          "pass `image` (output:<id> of a picture); with only text, use cube3d, or make a picture first with "
                          "comfy_generate_image (one object on a plain background) and pass it as `image`")
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
    """Merge a preset under the explicit options in a raw request dict (explicit values win). An image
    engine without a preset gets its fast preset."""
    engine = raw.get("engine") or (DEFAULT_IMAGE_ENGINE if raw.get("image") else "cube3d")
    if engine in IMAGE_ENGINES:
        name = raw.get("preset") or DEFAULT_IMAGE_PRESET
        if name not in IMAGE_PRESETS[engine]:
            return raw                                   # the validator names the engine's presets
        return {**raw, "preset": name, engine: {**preset_values(engine, name), **(raw.get(engine) or {})}}
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
        "engines": [engine_entry(eid) for eid in ENGINES],
        "part_templates": PART_TEMPLATES,
        "bbox_presets": {"Cube": [1, 1, 1], "Tall": [1, 2, 1], "Wide": [2, 1, 1], "Chair": [1, 1.4, 1],
                         "Flat": [2, 0.5, 2]},
        "max_parts": MAX_PARTS,
        "defaults": JobRequest(prompt="x").model_dump(exclude={"prompt", "chat_id", "parent_id", "title", "preset", "image",
                                                               "engine"}),
    }


def engine_entry(eid: str) -> dict:
    """One engine for the picker: what it takes, its licence, readiness, presets and settings."""
    from .engines import missing
    e = ENGINES[eid]
    out = {"id": eid, "label": e.label, "input": e.input, "help": e.help, "license": e.license,
           "runs_in": "gen3d" if e.local else "comfy", "missing": missing(eid)}
    if eid == "cube3d":
        out.update(presets=list(PRESETS), default_preset=None)
    else:
        out.update(presets={k: {"label": v["label"], "help": v["help"], "values": v.get("values", {})}
                            for k, v in IMAGE_PRESETS[eid].items()},
                   default_preset=DEFAULT_IMAGE_PRESET, fields=image_fields(eid))
    return out
