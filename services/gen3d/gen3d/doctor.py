"""Check that the pieces the GPU worker needs are in place. `python -m gen3d.doctor`."""

from __future__ import annotations

import shutil
import subprocess
import sys

from .config import settings

REQUIRED = {
    "Cube3D GPT": "cube3d-v0.5/shape_gpt.safetensors",
    "Cube3D shape tokenizer": "cube3d-v0.5/shape_tokenizer.safetensors",
    "CLIP-L text encoder": "clip-vit-large-patch14/model.safetensors",
    "CubePart DiT": "cubepart/multi_part_dit.safetensors",
    "CubePart shape VAE": "cubepart/vae.safetensors",
    "Qwen3-VL-4B text encoder": "Qwen3-VL-4B-Instruct/model.safetensors.index.json",
    "Qwen-Image transformer config": "Qwen-Image/transformer/config.json",
}


def checks() -> list[tuple[str, bool, str]]:
    out = []
    for label, rel in REQUIRED.items():
        p = settings.weights / rel
        out.append((label, p.exists(), str(p)))
    for label, rel in {"upstream clone (cube/)": "cube/cube3d", "CubePart code": "cube/cubepart/cube_part",
                       "worker venv (.venv)": ".venv/bin/activate"}.items():
        p = settings.cubeart / rel
        out.append((label, p.exists(), str(p)))
    podman = shutil.which(settings.podman)
    out.append(("podman", bool(podman), podman or f"{settings.podman} not on PATH"))
    if podman:
        r = subprocess.run([podman, "image", "exists", settings.image], capture_output=True)
        out.append(("ROCm image", r.returncode == 0, settings.image))
    blender = shutil.which(settings.blender) if settings.blender else None
    out.append(("Blender (previews, optional)", bool(blender), blender or "not found: previews are skipped"))
    return out


def main() -> int:
    bad = 0
    for label, ok, detail in checks():
        optional = "optional" in label
        print(f"  {'ok     ' if ok else ('skip   ' if optional else 'MISSING')} {label:32s} {detail}")
        bad += (not ok and not optional)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
