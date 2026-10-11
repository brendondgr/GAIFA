"""Options and presets of the image engines (plan 17.3): one model per engine with every setting the
lab measured (services/gen3d/runtime/lab/RESULTS.md, the report's "Every setting"). Field defaults are
the engine's **fast** preset, which is what a job without a preset gets; `base` is the model's stock
configuration. `target_faces` (0 = keep the raw mesh) reduces the result: fast-simplification in the
worker for Hunyuan3D and SAM 3D Objects, TRELLIS.2's own remesh + decimate for TRELLIS.2.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

MAX_FACES = 2_000_000
FACES = Field(0, ge=0, le=MAX_FACES, description="reduce the mesh to about this many faces; 0 = keep the raw mesh")


class Hunyuan21Options(BaseModel):
    steps: int = Field(30, ge=5, le=100, description="diffusion steps (~2.45 s each)")
    guidance: float = Field(5.0, ge=0, le=15, description="image guidance (CFG)")
    octree: Literal[256, 384, 512] = Field(384, description="decode grid: 256 halves the faces, 512 doubles them")
    num_chunks: int = Field(200_000, ge=1000, le=1_000_000, description="query points per decoder pass (speed only)")
    flashvdm: bool = Field(True, description="hierarchical volume decoding: decode 191 s → 9–14 s, same shape")
    flashvdm_topk: Literal["mean", "merge"] = Field("mean", description="FlashVDM's key selection")
    box_v: float = Field(1.01, ge=1.0, le=1.2, description="decode bounds half-extent")
    mc_level: float = Field(0.0, ge=-0.1, le=0.1, description="iso level of the surface")
    seed: int = Field(1234, ge=0, le=2**31 - 1)
    remove_floaters: bool = Field(True, description="drop small loose pieces")
    remove_degenerate: bool = Field(True, description="drop zero-area faces")
    target_faces: int = FACES


class Trellis2Options(BaseModel):
    resolution: Literal[512, 1024, 1536] = Field(1024, description="1024 = the cascade (512 → 1024); 512 = draft, no cascade; "
                                                                    "1536 = finer, ~3x the refine time")
    structure_steps: int = Field(12, ge=1, le=50, description="sparse-structure sampler steps")
    shape_steps: int = Field(12, ge=1, le=50, description="512 shape sampler steps")
    refine_steps: int = Field(6, ge=1, le=50, description="1024 refine sampler steps: the slow one, cost grows with the "
                                                          "object's surface area")
    guidance: float = Field(7.5, ge=0, le=20, description="CFG of the three samplers")
    seed: int = Field(42, ge=0, le=2**31 - 1)
    target_faces: int = FACES
    remesh_resolution: Literal[256, 384, 512, 768] = Field(512, description="remesh grid before decimating (only with "
                                                                           "target_faces): 512 is clean down to 50 k faces")


class Sam3dObjectsOptions(BaseModel):
    distill: bool = Field(True, description="shortcut sampling for both stages (CFG off): ~1.5x faster; fine for objects, "
                                            "loses detail on characters")
    ss_steps: int = Field(25, ge=1, le=100, description="stage 1 (sparse structure) steps")
    ss_cfg_strength: float = Field(7.0, ge=0, le=20)
    ss_rescale_t: float = Field(3.0, ge=0.1, le=10)
    slat_steps: int = Field(25, ge=1, le=100, description="stage 2 (structured latent) steps")
    slat_cfg_strength: float = Field(1.0, ge=0, le=20)
    slat_rescale_t: float = Field(1.0, ge=0.1, le=10)
    seed: int = Field(42, ge=0, le=2**31 - 1)
    target_faces: int = FACES


class Sam3dBodyOptions(BaseModel):
    hand_refinement: bool = Field(False, description="refine both hands with their own decoders (+0.4 s)")
    fov: float = Field(0.0, ge=0, le=170, description="camera field of view in degrees; 0 = estimate it")


IMAGE_OPTIONS: dict[str, type[BaseModel]] = {
    "hunyuan21": Hunyuan21Options, "trellis2": Trellis2Options,
    "sam3d_objects": Sam3dObjectsOptions, "sam3d_body": Sam3dBodyOptions,
}

# label/help, then the values that differ from the field defaults (the fast preset)
IMAGE_PRESETS: dict[str, dict[str, dict]] = {
    "hunyuan21": {
        "fast": {"label": "Fast", "help": "30 steps + FlashVDM: ~85 s warm, same shape as base (F 0.976–0.989)"},
        "base": {"label": "Base", "help": "Tencent's defaults: 50 steps, plain decoding (~320 s warm)",
                 "values": {"steps": 50, "flashvdm": False, "num_chunks": 8000}},
    },
    "trellis2": {
        "fast": {"label": "Fast", "help": "shape 12 + refine 6 steps: ~75 s on a character, ~220 s on a round object"},
        "base": {"label": "Base", "help": "ComfyUI's template: shape 20 + refine 12 steps (~120 s / ~430 s)",
                 "values": {"shape_steps": 20, "refine_steps": 12}},
        "draft": {"label": "Draft", "help": "512 only, no refine: ~16–55 s, softer with more pinholes",
                  "values": {"resolution": 512}},
    },
    "sam3d_objects": {
        "fast": {"label": "Fast", "help": "distilled sampling: ~35–50 s warm; objects only (characters lose detail)"},
        "base": {"label": "Base", "help": "Meta's config, 25 + 25 steps: ~50–77 s warm", "values": {"distill": False}},
    },
    "sam3d_body": {
        "fast": {"label": "Fast", "help": "body decoder only (~0.5 s warm)"},
        "base": {"label": "Base", "help": "with hand refinement (~0.9 s warm)", "values": {"hand_refinement": True}},
    },
}
DEFAULT_IMAGE_PRESET = "fast"


def preset_values(engine: str, name: str) -> dict:
    return dict((IMAGE_PRESETS.get(engine, {}).get(name) or {}).get("values") or {})


LABELS: dict[str, dict[str, str]] = {
    "hunyuan21": {"steps": "Steps", "guidance": "Guidance", "octree": "Octree resolution", "num_chunks": "Decoder chunk",
                  "flashvdm": "FlashVDM decoding", "flashvdm_topk": "FlashVDM key selection", "box_v": "Bounds",
                  "mc_level": "Iso level", "seed": "Seed", "remove_floaters": "Remove floaters",
                  "remove_degenerate": "Remove degenerate faces", "target_faces": "Face budget"},
    "trellis2": {"resolution": "Resolution", "structure_steps": "Structure steps", "shape_steps": "Shape steps",
                 "refine_steps": "Refine steps", "guidance": "Guidance", "seed": "Seed", "target_faces": "Face budget",
                 "remesh_resolution": "Remesh grid"},
    "sam3d_objects": {"distill": "Distilled sampling", "ss_steps": "Stage 1 steps", "ss_cfg_strength": "Stage 1 guidance",
                      "ss_rescale_t": "Stage 1 time rescale", "slat_steps": "Stage 2 steps",
                      "slat_cfg_strength": "Stage 2 guidance", "slat_rescale_t": "Stage 2 time rescale",
                      "seed": "Seed", "target_faces": "Face budget"},
    "sam3d_body": {"hand_refinement": "Hand refinement", "fov": "Field of view"},
}


def image_fields(engine: str) -> list[dict]:
    """The settings menu of one image engine, straight from its model."""
    model = IMAGE_OPTIONS[engine]
    out = []
    for name, f in model.model_fields.items():
        ann = f.annotation
        choices = list(getattr(ann, "__args__", ())) if getattr(ann, "__origin__", None) is Literal else None
        kind = "choice" if choices else {bool: "boolean", int: "integer", float: "number"}.get(ann, "string")
        meta = {"group": engine, "key": name, "label": LABELS[engine].get(name, name), "type": kind,
                "default": f.get_default(call_default_factory=True), "help": f.description or ""}
        if choices:
            meta["choices"] = choices
        for m in f.metadata:
            for attr, key in (("ge", "min"), ("gt", "min"), ("le", "max"), ("lt", "max")):
                if getattr(m, attr, None) is not None:
                    meta[key] = getattr(m, attr)
        if name == "target_faces":
            meta.update(step=1000, shortcuts=[0, 200_000, 100_000, 50_000], null_label="raw mesh")
        out.append(meta)
    return out
