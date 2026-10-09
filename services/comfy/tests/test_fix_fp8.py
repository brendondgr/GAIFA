"""scripts/fix_fp8_quant_metadata.py: a hybrid scaled-FP8 file (legacy `scaled_fp8` marker, new
`.weight_scale` names, no metadata) gets ComfyUI's per-layer metadata; tensor data is unchanged."""

import importlib.util
import json
import struct
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "fix_fp8", Path(__file__).parents[1] / "scripts" / "fix_fp8_quant_metadata.py")
fix_fp8 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fix_fp8)


def write_st(path: Path, tensors: dict[str, tuple[str, list[int], bytes]], meta: dict | None = None):
    header, blob = {}, b""
    for name, (dtype, shape, data) in tensors.items():
        header[name] = {"dtype": dtype, "shape": shape, "data_offsets": [len(blob), len(blob) + len(data)]}
        blob += data
    if meta:
        header["__metadata__"] = meta
    h = json.dumps(header).encode()
    h += b" " * (-len(h) % 8)
    path.write_bytes(struct.pack("<Q", len(h)) + h + blob)


def read_st(path: Path) -> tuple[dict, bytes]:
    raw = path.read_bytes()
    n = struct.unpack("<Q", raw[:8])[0]
    return json.loads(raw[8:8 + n]), raw[8 + n:]


@pytest.fixture
def hybrid(tmp_path):
    src = tmp_path / "turbo-fp8.safetensors"
    write_st(src, {
        "scaled_fp8": ("F32", [1], struct.pack("<f", 0.0)),
        "blocks.0.attn.to_q.weight_scale": ("F32", [], struct.pack("<f", 0.002)),
        "blocks.0.attn.to_q.weight": ("F8_E4M3", [2, 2], bytes([1, 2, 3, 4])),
        "img_in.weight": ("BF16", [2], bytes(4)),                 # not quantized
    }, meta={"format": "pt"})
    return src


def test_adds_layer_metadata_and_keeps_data(hybrid, tmp_path):
    dest = tmp_path / "fixed.safetensors"
    assert fix_fp8.fix(hybrid, dest) == 0
    h_in, data_in = read_st(hybrid)
    h_out, data_out = read_st(dest)
    assert data_out == data_in
    meta = h_out.pop("__metadata__")
    assert meta["format"] == "pt"
    assert json.loads(meta["_quantization_metadata"]) == {"layers": {"blocks.0.attn.to_q": {"format": "float8_e4m3fn"}}}
    h_in.pop("__metadata__")
    assert h_out == h_in                                         # same tensors, same offsets
    assert (8 + struct.unpack("<Q", dest.read_bytes()[:8])[0]) % 8 == 0


def test_leaves_files_that_already_have_metadata(hybrid, tmp_path):
    fixed, again = tmp_path / "fixed.safetensors", tmp_path / "again.safetensors"
    fix_fp8.fix(hybrid, fixed)
    assert fix_fp8.fix(fixed, again) == 0
    assert not again.exists()
