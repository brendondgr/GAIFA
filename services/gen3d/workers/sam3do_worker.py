"""SAM 3D Objects (geometry only) in the ROCm container, venv runtime/sam3do (plan 17.8). Protocol: proto.py.

Ported from the lab's sam3do_run.py, which runs the real weights on gfx1151:
- the pipeline is built from the checkpoint's yamls (patched copies in runtime/sam3do/config/);
- DINOv2's code comes from a local clone with `pretrained: false` (its weights are in the checkpoints);
- MoGe v1 is loaded from data/models/3d/moge-vitl/model.pt;
- the 4-Gaussian decoder, torch.compile and MIOpen are off, as is mesh post-processing (its hole filling
  needs a CUDA rasteriser);
- spconv, gsplat, kaolin and open3d come from workers/shims (first on PYTHONPATH).
A task reads the job's `input_rgba.png` (RGB + its alpha as the mask) and writes `mesh.glb`, geometry
only (the model's vertex colours are dropped: texturing happens elsewhere).
"""

from __future__ import annotations

import os
from pathlib import Path

from proto import Subs, peak_gb, reduce_mesh, serve

RT = Path(os.environ["GEN3D_RUNTIME"])
W = Path(os.environ["GEN3D_WEIGHTS"])
CKPTS = W / "sam-3d-objects" / "checkpoints"
MOGE = W / "moge-vitl" / "model.pt"
CFG = RT / "sam3do" / "config"
PIPE = None
SUBS: Subs | None = None
STAGES = {"compute_pointmap": "sam3do.pointmap", "sample_sparse_structure": "sam3do.stage1",
          "sample_slat": "sam3do.stage2", "decode_slat": "sam3do.decode"}


def _configs() -> None:
    """Patched copies of the checkpoint's yamls (local DINOv2 code, no pretrained download) + linked ckpts."""
    from omegaconf import OmegaConf

    def patch(node):
        if isinstance(node, dict):
            if str(node.get("_target_", "")).endswith("embedder.dino.Dino"):
                node.update(repo_or_dir=str(RT / "sam3do" / "dinov2"), source="local", backbone_kwargs={"pretrained": False})
            for v in node.values():
                patch(v)
        elif isinstance(node, list):
            for v in node:
                patch(v)

    CFG.mkdir(parents=True, exist_ok=True)
    for f in os.listdir(CKPTS):
        src, dst = CKPTS / f, CFG / f
        if f.endswith(".yaml") and f != "pipeline.yaml":
            c = OmegaConf.to_container(OmegaConf.load(src))
            patch(c)
            OmegaConf.save(OmegaConf.create(c), dst)
        elif f.endswith(".ckpt") and not dst.exists():
            dst.symlink_to(src)


def load(models: list[str]) -> list[str]:
    global PIPE
    if PIPE is None:
        import torch
        from hydra.utils import instantiate
        from omegaconf import OmegaConf
        torch.backends.cudnn.enabled = False                   # MIOpen off, as ComfyUI on gfx1151
        _configs()
        cfg = OmegaConf.load(CKPTS / "pipeline.yaml")
        cfg.rendering_engine, cfg.compile_model, cfg.workspace_dir = "pytorch3d", False, str(CFG)
        cfg.slat_decoder_gs_4_config_path = cfg.slat_decoder_gs_4_ckpt_path = None
        cfg.depth_model.model.pretrained_model_name_or_path = str(MOGE)
        PIPE = instantiate(cfg)
        for name, sub in STAGES.items():                       # announce the pipeline's parts as substages
            f = getattr(PIPE, name)

            def wrapped(*a, _f=f, _sub=sub, **k):
                if SUBS is not None:
                    SUBS.next(_sub)
                return _f(*a, **k)
            setattr(PIPE, name, wrapped)
    return ["sam3d_objects"]


def run(task: dict) -> tuple[dict, list[str]]:
    global SUBS
    import numpy as np
    import trimesh
    from PIL import Image

    o, jdir = task["request"]["sam3d_objects"], Path(task["job_dir"])
    SUBS = Subs()
    try:
        if PIPE is None:
            SUBS.next("load.sam3d_objects")
            load([])
        PIPE.override_ss_generator_cfg_config(PIPE.models["ss_generator"], cfg_strength=o["ss_cfg_strength"],
                                              inference_steps=o["ss_steps"], rescale_t=o["ss_rescale_t"])
        PIPE.override_slat_generator_cfg_config(PIPE.models["slat_generator"], cfg_strength=o["slat_cfg_strength"],
                                                inference_steps=o["slat_steps"], rescale_t=o["slat_rescale_t"])
        rgba = np.asarray(Image.open(task["inputs"]["image"]).convert("RGBA"))
        mask = rgba[..., 3] > 127
        if not mask.any():
            raise RuntimeError("the picture's cut-out is empty")
        rgba = np.concatenate([rgba[..., :3], (mask.astype(np.uint8) * 255)[..., None]], -1)
        out = PIPE.run(rgba, None, o["seed"], stage1_only=False, with_mesh_postprocess=False, with_texture_baking=False,
                       with_layout_postprocess=False, use_vertex_color=True, stage1_inference_steps=o["ss_steps"],
                       stage2_inference_steps=o["slat_steps"], use_stage1_distillation=o["distill"],
                       use_stage2_distillation=o["distill"], decode_formats=["mesh", "gaussian"])
        SUBS.next("sam3do.post")
        glb = out.get("glb")
        if glb is None:
            raise RuntimeError("SAM 3D Objects returned no mesh")
        mesh = trimesh.Trimesh(np.asarray(glb.vertices), np.asarray(glb.faces), process=False)   # geometry only
        res = {"mesh": "mesh.glb", "raw_faces": len(mesh.faces), "engine": "sam3d_objects",
               "voxels": int(out["coords"].shape[0]) if "coords" in out else None}
        if o["target_faces"] and len(mesh.faces) > o["target_faces"]:
            mesh.export(jdir / "mesh_raw.glb")
            mesh = reduce_mesh(mesh, o["target_faces"])
            res["raw"] = "mesh_raw.glb"
        mesh.export(jdir / "mesh.glb")
        SUBS.done()
    finally:
        SUBS = None
    res.update(faces=len(mesh.faces), vertices=len(mesh.vertices), peak_gpu_gb=peak_gb())
    return res, ["sam3d_objects"]


if __name__ == "__main__":
    serve(load, run, {"engine": "sam3d_objects"})
