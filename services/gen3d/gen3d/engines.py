"""The engines that make a mesh in the `shape` stage (plan 17).

`cube3d` turns a prompt into a mesh; the image engines turn one picture into a mesh. Local engines run
in gen3d's own worker container, each with its venv and code under runtime/ (scripts/install-runtime.sh);
delegated engines run as workflow packs in the comfy mod, through the hub.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .config import ROOT, settings


@dataclass(frozen=True)
class Engine:
    id: str
    label: str
    input: str                          # "text" | "image"
    help: str
    license: str
    local: bool                         # True: gen3d's worker container; False: a comfy pack
    worker: str = ""                    # the worker family a local engine runs in (one container at a time)
    weights: tuple[str, ...] = ()       # under data/models/3d (local) or data/models/comfyui (delegated)
    code: tuple[str, ...] = ()          # under runtime/
    venv: str = ""                      # under runtime/
    packs: tuple[str, ...] = field(default_factory=tuple)


ENGINES: dict[str, Engine] = {e.id: e for e in (
    Engine("cube3d", "Cube3D", "text", "Text to mesh, then optional named parts and a game rig", "Cube3D Research-Only RAIL-MS",
           local=True, worker="cube"),
    Engine("hunyuan21", "Hunyuan3D 2.1", "image", "Characters: the cleanest, watertight surface",
           "Tencent Hunyuan 3D 2.1 Community Licence (excludes the EU, UK and South Korea)", local=True, worker="img3d",
           weights=("Hunyuan3D-2.1/hunyuan3d-dit-v2-1/model.fp16.ckpt", "Hunyuan3D-2.1/hunyuan3d-vae-v2-1/model.fp16.ckpt"),
           code=("hunyuan3d-2.1/hy3dshape/hy3dshape",), venv="img3d"),
    Engine("trellis2", "TRELLIS.2", "image", "Objects: the most faithful detail (runs in Images & Video)", "MIT",
           local=False, weights=("diffusion_models/trellis_2_bf16.safetensors", "vae/trellis_2_shape_vae_bf16.safetensors",
                                 "clip_vision/dino_v3_vit_l.safetensors"),
           packs=("trellis2-shape", "trellis2-lowpoly", "trellis2-draft")),
    Engine("sam3d_objects", "SAM 3D Objects", "image", "Quickest full shape; rougher surface", "SAM Licence",
           local=True, worker="sam3do",
           weights=("sam-3d-objects/checkpoints/pipeline.yaml", "sam-3d-objects/checkpoints/ss_generator.ckpt",
                    "sam-3d-objects/checkpoints/slat_generator.ckpt", "sam-3d-objects/checkpoints/slat_decoder_mesh.ckpt",
                    "moge-vitl/model.pt"),
           code=("sam3d-objects/sam3d_objects", "sam3do/dinov2/dinov2"), venv="sam3do"),
    Engine("sam3d_body", "SAM 3D Body", "image", "A person's body (no clothes) as a rigged mesh (runs in Images & Video)",
           "SAM Licence", local=False,
           weights=("detection/sam_3d_body_dinov3_bf16.safetensors",), packs=("sam3d-body",)),
)}
IMAGE_ENGINES = tuple(k for k, e in ENGINES.items() if e.input == "image")
SHIMS = ROOT / "workers" / "shims"


def missing(eid: str) -> list[str]:
    """What a local engine still needs on disk (empty = ready). Delegated engines are checked by comfy."""
    e = ENGINES[eid]
    if eid == "cube3d" or not e.local:
        return []
    out = [f"runtime/{c}" for c in e.code if not (settings.runtime / c).exists()]
    if e.venv and not (settings.runtime / e.venv / ".venv" / "bin" / "activate").exists():
        out.append(f"runtime/{e.venv}/.venv")
    out += [f"models/3d/{w}" for w in e.weights if not (settings.weights / w).exists()]
    return out
