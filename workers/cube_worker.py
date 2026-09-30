"""GPU worker: runs inside the ROCm container, keeps Cube3D / CubePart loaded, does one task at a time.

Protocol (JSON lines):
  stdin   {"cmd": "load", "models": ["shape", "parts"]}
          {"cmd": "run", "task": {"stage", "job_dir", "request", "inputs"}}
          {"cmd": "quit"}
  stdout  {"event": "ready", ...}                      once, after imports
          {"event": "sub", "sub": "shape.gpt", "total": 1024}
          {"event": "progress", "step": 312, "total": 1024}
          {"event": "sub_done", "sub": "shape.gpt", "seconds": 57.9}
          {"event": "loaded", "models": [...]}          reply to load
          {"event": "result", "result": {...}}          reply to run
          {"event": "error", "message": "...", "trace": "..."}
Everything else anything prints goes to stderr (the server log): the real stdout is reserved.
"""

from __future__ import annotations

import colorsys
import json
import os
import sys
import tempfile
import time
import traceback
from pathlib import Path

_OUT = os.fdopen(os.dup(sys.stdout.fileno()), "w", buffering=1)
os.dup2(sys.stderr.fileno(), sys.stdout.fileno())  # C-level prints too
sys.stdout = sys.stderr

CUBEART = Path(os.environ["GEN3D_CUBEART"])
W = CUBEART / "weights"


def emit(event: str, **data) -> None:
    _OUT.write(json.dumps({"event": event, **data}) + "\n")
    _OUT.flush()


class Sub:
    """Context manager: announce a substage, report its duration."""

    def __init__(self, name: str, total: int | None = None):
        self.name, self.total = name, total

    def __enter__(self):
        self.t0 = time.time()
        emit("sub", sub=self.name, total=self.total)
        return self

    def __exit__(self, exc_type, *_):
        if exc_type is None:
            import torch
            if torch.cuda.is_available():
                torch.cuda.synchronize()
            emit("sub_done", sub=self.name, seconds=round(time.time() - self.t0, 2))


class ProgressTqdm:
    """Drop-in for `tqdm(iterable, ...)` that reports steps over the protocol (~4 times a second)."""

    def __init__(self, iterable=None, *args, total=None, **kwargs):
        self.iterable = iterable
        try:
            self.total = total or len(iterable)
        except TypeError:
            self.total = None

    def __iter__(self):
        last = 0.0
        for i, item in enumerate(self.iterable, 1):
            yield item
            now = time.monotonic()
            if now - last > 0.25 or i == self.total:
                emit("progress", step=i, total=self.total)
                last = now

    def update(self, *a, **k):
        pass

    def close(self):
        pass


def palette(n: int):
    return [[int(c * 255) for c in colorsys.hsv_to_rgb(i / max(n, 1), 0.55, 0.95)] for i in range(n)]


class Worker:
    def __init__(self) -> None:
        self.engine = None      # Cube3D
        self.parts_pipe = None  # CubePart
        self.cfg_dir = Path(tempfile.mkdtemp(prefix="gen3d-cfg-"))

    @property
    def loaded(self) -> list[str]:
        return [n for n, v in (("shape", self.engine), ("parts", self.parts_pipe)) if v is not None]

    # ---- loading ------------------------------------------------------------------------------

    def load_shape(self) -> None:
        if self.engine is not None:
            return
        with Sub("load.shape"):
            import torch
            from omegaconf import OmegaConf
            import cube3d.inference.engine as eng
            eng.tqdm = ProgressTqdm
            c = OmegaConf.load(CUBEART / "cube/cube3d/configs/open_model_v0.5.yaml")
            c.text_model_pretrained_model_name_or_path = str(W / "clip-vit-large-patch14")
            cfg = self.cfg_dir / "open_model_v0.5.yaml"
            OmegaConf.save(c, cfg)
            self.engine = eng.Engine(str(cfg), str(W / "cube3d-v0.5/shape_gpt.safetensors"),
                                     str(W / "cube3d-v0.5/shape_tokenizer.safetensors"), device=torch.device("cuda"))
            self.fast_engine = None

    def load_parts(self) -> None:
        if self.parts_pipe is not None:
            return
        with Sub("load.parts"):
            from omegaconf import OmegaConf
            import cube_part.pipelines.shape_denoiser as sd
            sd.tqdm = ProgressTqdm
            c = OmegaConf.load(CUBEART / "cube/cubepart/configs/shape_denoiser_multimesh.yaml")
            c.system.base_model_path = str(W / "Qwen3-VL-4B-Instruct")
            c.system.diffusion_model_type = str(W / "Qwen-Image")
            cfg = self.cfg_dir / "shape_denoiser_multimesh.yaml"
            OmegaConf.save(c, cfg)
            self.parts_pipe = sd.PartShapeDenoiserPipeline(
                config_path=str(cfg), checkpoint_path=str(W / "cubepart/multi_part_dit.safetensors"),
                vae_checkpoint_path=str(W / "cubepart/vae.safetensors"),
                extract_geometry_fn_name="extract_geometry_coarse_to_fine")

    # ---- stages -------------------------------------------------------------------------------

    def shape(self, req: dict, jdir: Path) -> dict:
        import torch
        import trimesh
        from cube3d.inference.utils import normalize_bbox
        from cube3d.mesh_utils.postprocessing import (PYMESHLAB_AVAILABLE, create_pymeshset,
                                                      postprocess_mesh, save_mesh)
        self.load_shape()
        s = req["shape"]
        engine = self.engine
        if s.get("fast_engine"):
            if self.fast_engine is None:
                import cube3d.inference.engine as eng
                with Sub("load.shape_fast"):
                    self.fast_engine = eng.EngineFast(
                        str(self.cfg_dir / "open_model_v0.5.yaml"), str(W / "cube3d-v0.5/shape_gpt.safetensors"),
                        str(W / "cube3d-v0.5/shape_tokenizer.safetensors"), device=torch.device("cuda"))
            engine = self.fast_engine
        bbox = normalize_bbox(tuple(s["bbox"])) if s.get("bbox") else None
        torch.manual_seed(int(s.get("seed", 0)))
        with torch.inference_mode():
            with Sub("shape.gpt", total=engine.max_new_tokens):
                ids = engine.run_gpt([req["prompt"]], True, float(s["guidance_scale"]), s.get("top_p"), bbox)
            with Sub("shape.decode"):
                with torch.autocast("cuda", dtype=torch.bfloat16):
                    v, f = engine.run_shape_decode(ids, float(s["resolution_base"]))[0]
        with Sub("shape.post"):
            obj = jdir / "mesh.obj"
            if PYMESHLAB_AVAILABLE:
                ms = create_pymeshset(v, f)
                postprocess_mesh(ms, max(10000, int(f.shape[0] * 0.1)), str(obj))
                save_mesh(ms, str(obj))
            else:
                trimesh.Trimesh(v, f).export(obj)
            m = trimesh.load(obj, force="mesh")
            m.export(jdir / "mesh.glb")
            obj.unlink(missing_ok=True)
        return {"mesh": "mesh.glb", "faces": int(len(m.faces)), "raw_faces": int(f.shape[0]),
                "bounds": m.bounds.round(4).tolist()}

    def parts(self, req: dict, jdir: Path, inputs: dict) -> dict:
        import torch
        import trimesh
        from cube_part.pipelines import ShapeInput
        from cube_part.utils.mesh import load_mesh, sample_surface
        self.load_parts()
        p = req["parts"]
        names = p["parts"]
        pipe = self.parts_pipe
        with Sub("parts.encode"):
            mesh, center, scale = load_mesh(inputs["mesh"])
            surf = torch.from_numpy(sample_surface(mesh, num_samples=int(p["num_samples"]))).to(pipe.device)
            latents, _ = pipe.encode_shape(surf.unsqueeze(0).float())
        with Sub("parts.diffusion", total=int(p["steps"])):
            lat = pipe.input_to_part_shape(
                ShapeInput(prompt=[names], latents=latents), guidance_scale=float(p["guidance_scale"]),
                resolution_base=float(p["resolution_base"]), scheduler_type=p["scheduler"],
                timeshift=float(p["timeshift"]), num_inference_steps=int(p["steps"]), seed=int(p["seed"]),
                output_mesh=False)
        with Sub("parts.decode"):
            with torch.autocast("cuda", dtype=torch.bfloat16):
                meshes = pipe.decode_shape(lat.float(), resolution_base=float(p["resolution_base"]))
            pdir = jdir / "parts"
            pdir.mkdir(exist_ok=True)
            pal = palette(len(names))
            scene = trimesh.Scene()
            out = []
            for i, (v, f) in enumerate(meshes):
                name = names[i]
                if v is None or len(f) == 0:
                    out.append({"index": i, "name": name, "file": None, "faces": 0, "color": pal[i]})
                    continue
                safe = "".join(ch if ch.isalnum() else "_" for ch in name)
                fn = f"part_{i:02d}_{safe}.glb"
                m = trimesh.Trimesh(v, f)
                m.export(pdir / fn)
                cm = m.copy()
                cm.visual.face_colors = pal[i] + [255]
                scene.add_geometry(cm, geom_name=f"part_{i:02d}_{safe}", node_name=f"part_{i:02d}_{safe}")
                out.append({"index": i, "name": name, "file": fn, "faces": int(len(f)), "color": pal[i]})
            if scene.geometry:
                scene.export(jdir / "parts.glb")
            (pdir / "manifest.json").write_text(json.dumps(
                {"source_mesh": inputs["mesh"], "parts": out, "center": center.tolist(), "scale": float(scale)}, indent=2))
        empty = [o["name"] for o in out if not o["file"]]
        return {"dir": "parts", "scene": "parts.glb", "parts": out,
                **({"empty": empty} if empty else {})}

    def rig(self, req: dict, jdir: Path, inputs: dict) -> dict:
        import rig as rigmod  # vendored workers/rig.py
        r = req["rig"]
        with Sub("rig"):
            info = rigmod.rig(Path(inputs["parts_dir"]), jdir / "rigged", height=r.get("height_m"),
                              faces_per_part=int(r["faces_per_part"]))
            (jdir / "rigged.rig.json").replace(jdir / "rig.json")
        return {"glb": "rigged.glb", "rig": "rig.json", "joints": info["joints"], "missing": info["missing"]}

    def run(self, task: dict) -> dict:
        jdir = Path(task["job_dir"])
        req, inputs, stage = task["request"], task["inputs"], task["stage"]
        if stage == "shape":
            return self.shape(req, jdir)
        if stage == "parts":
            return self.parts(req, jdir, inputs)
        if stage == "rig":
            return self.rig(req, jdir, inputs)
        raise ValueError(f"unknown stage {stage!r}")


def main() -> None:
    import torch
    w = Worker()
    emit("ready", torch=torch.__version__, hip=torch.version.hip, cuda=torch.cuda.is_available(),
         device=torch.cuda.get_device_name(0) if torch.cuda.is_available() else "cpu")
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
            cmd = msg.get("cmd")
            if cmd == "quit":
                break
            if cmd == "load":
                for m in msg.get("models", []):
                    {"shape": w.load_shape, "parts": w.load_parts}[m]()
                emit("loaded", models=w.loaded)
            elif cmd == "run":
                result = w.run(msg["task"])
                if torch.cuda.is_available():
                    result["peak_gpu_gb"] = round(torch.cuda.max_memory_allocated() / 1e9, 2)
                    torch.cuda.reset_peak_memory_stats()
                emit("result", result=result, loaded=w.loaded)
            else:
                emit("error", message=f"unknown command {cmd!r}")
        except Exception as exc:  # report and keep serving; the models stay loaded
            emit("error", message=f"{type(exc).__name__}: {exc}", trace=traceback.format_exc(), loaded=w.loaded)


if __name__ == "__main__":
    main()
