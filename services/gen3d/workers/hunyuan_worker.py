"""Hunyuan3D 2.1 (shape only) in the ROCm container, venv runtime/img3d (plan 17.4). Protocol: proto.py.

A task is the shape stage of a `hunyuan21` job: it reads the job's `input_rgba.png` and writes `mesh.glb`
(and `mesh_raw.glb` when `target_faces` reduced it). Substages: hunyuan.conditioning, hunyuan.diffusion
(one progress step per sampler step), hunyuan.decode (volume decode + marching cubes), hunyuan.post.
FlashVDM is switched through the VAE (`enable_flashvdm_decoder`): the pipeline's own `enable_flashvdm`
looks for a turbo VAE that 2.1 doesn't have (lab, 2026-10-10).
"""

from __future__ import annotations

import os
import time
from pathlib import Path

from proto import Subs, emit, peak_gb, reduce_mesh, serve

CKPT = Path(os.environ["GEN3D_WEIGHTS"]) / "Hunyuan3D-2.1" / "hunyuan3d-dit-v2-1"
PIPE = None


def load(models: list[str]) -> list[str]:
    global PIPE
    if PIPE is None:
        import torch
        from hy3dshape.pipelines import Hunyuan3DDiTFlowMatchingPipeline
        PIPE = Hunyuan3DDiTFlowMatchingPipeline.from_single_file(
            ckpt_path=str(CKPT / "model.fp16.ckpt"), config_path=str(CKPT / "config.yaml"), device="cuda", dtype=torch.float16)
    return ["hunyuan21"]


def run(task: dict) -> tuple[dict, list[str]]:
    import torch
    from PIL import Image
    from hy3dshape.postprocessors import DegenerateFaceRemover, FloaterRemover

    o, jdir = task["request"]["hunyuan21"], Path(task["job_dir"])
    subs = Subs()
    if PIPE is None:
        subs.next("load.hunyuan21")
        load([])
    pipe, vae = PIPE, PIPE.vae
    vae.enable_flashvdm_decoder(enabled=o["flashvdm"], adaptive_kv_selection=True, topk_mode=o["flashvdm_topk"], mc_algo="mc")

    # The pipeline is one call: announce its parts from the inside.
    enc, decode = pipe.encode_cond, vae.forward
    vol = vae.volume_decoder

    def enc_w(*a, **k):
        r = enc(*a, **k)
        subs.next("hunyuan.diffusion", total=o["steps"])
        return r

    def decode_w(*a, **k):                     # the latent → volume decoder starts after the last step
        subs.next("hunyuan.decode")
        return decode(*a, **k)

    last = [0.0]

    def on_step(i, _t, _out):
        now = time.monotonic()
        if now - last[0] > 0.25 or i + 1 == o["steps"]:
            emit("progress", step=i + 1, total=o["steps"])
            last[0] = now

    pipe.encode_cond, vae.forward = enc_w, decode_w
    try:
        subs.next("hunyuan.conditioning")
        image = Image.open(task["inputs"]["image"])
        mesh = pipe(image=image, num_inference_steps=o["steps"], guidance_scale=o["guidance"],
                    generator=torch.Generator("cuda").manual_seed(o["seed"]), box_v=o["box_v"],
                    octree_resolution=o["octree"], mc_level=o["mc_level"], mc_algo="mc", num_chunks=o["num_chunks"],
                    output_type="trimesh", enable_pbar=False, callback=on_step, callback_steps=1)[0]
    finally:
        pipe.encode_cond, vae.forward, vae.volume_decoder = enc, decode, vol
    if mesh is None:
        raise RuntimeError("no surface found: the picture may be empty or the object too thin")
    subs.next("hunyuan.post")
    raw_faces = len(mesh.faces)
    if o["remove_floaters"]:
        mesh = FloaterRemover()(mesh)
    if o["remove_degenerate"]:
        mesh = DegenerateFaceRemover()(mesh)
    out = {"mesh": "mesh.glb", "raw_faces": raw_faces, "engine": "hunyuan21"}
    if o["target_faces"] and len(mesh.faces) > o["target_faces"]:
        mesh.export(jdir / "mesh_raw.glb")
        mesh = reduce_mesh(mesh, o["target_faces"])
        out["raw"] = "mesh_raw.glb"
    mesh.export(jdir / "mesh.glb")
    subs.done()
    out.update(faces=len(mesh.faces), vertices=len(mesh.vertices), watertight=bool(mesh.is_watertight),
               peak_gpu_gb=peak_gb())
    return out, ["hunyuan21"]


if __name__ == "__main__":
    serve(load, run, {"engine": "hunyuan21"})
