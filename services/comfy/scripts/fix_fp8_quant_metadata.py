#!/usr/bin/env python3
"""Add ComfyUI's `_quantization_metadata` to a scaled-FP8 safetensors file that lacks it.

Some FP8 exports (abenzerps/Qwen-Image-2.1-Turbo-Quantized's turbo-fp8) mix the two formats:
the legacy `scaled_fp8` marker with the new `<layer>.weight_scale` names and no per-layer
metadata. ComfyUI's `convert_old_quants` only maps the legacy `.scale_weight` names, so it finds
no quantized layers and runs the raw FP8 values unscaled: the image is noise. Writing the
metadata ComfyUI's own exports carry ({"layers": {<layer>: {"format": "float8_e4m3fn"}}}) fixes
it. Tensor data is copied unchanged; only the header grows.

    fix_fp8_quant_metadata.py SRC DEST     (standard library only)
"""
import json
import shutil
import struct
import sys
from pathlib import Path


def read_header(path: Path) -> tuple[dict, int]:
    with path.open("rb") as f:
        n = struct.unpack("<Q", f.read(8))[0]
        return json.loads(f.read(n)), 8 + n


def fix(src: Path, dest: Path) -> int:
    header, data_start = read_header(src)
    meta = dict(header.pop("__metadata__", {}))
    if "_quantization_metadata" in meta:
        print(f"{src.name}: already has _quantization_metadata; nothing to do")
        return 0
    layers = {k[:-len(".weight_scale")]: {"format": "float8_e4m3fn"}
              for k in header
              if k.endswith(".weight_scale") and header.get(k[:-len("_scale")], {}).get("dtype") == "F8_E4M3"}
    if not layers:
        sys.exit(f"{src.name}: no F8_E4M3 weights with a weight_scale; not a scaled-FP8 file")
    meta["_quantization_metadata"] = json.dumps({"layers": layers})
    out = json.dumps({"__metadata__": meta, **header}, separators=(",", ":")).encode()
    out += b" " * (-len(out) % 8)                          # safetensors pads the header to 8 bytes
    part = dest.with_name(dest.name + ".part")
    with src.open("rb") as fi, part.open("wb") as fo:
        fo.write(struct.pack("<Q", len(out)) + out)
        fi.seek(data_start)
        shutil.copyfileobj(fi, fo, 64 << 20)
    part.replace(dest)
    print(f"{dest.name}: {len(layers)} FP8 layers described; tensor data unchanged")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    sys.exit(fix(Path(sys.argv[1]), Path(sys.argv[2])))
