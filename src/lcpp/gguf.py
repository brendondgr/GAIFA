"""Just enough of the GGUF format to estimate a model's KV-cache size.

Reads the metadata key/value section at the head of the file and stops as
soon as the tokenizer keys start (those arrays run to megabytes and come after
the architecture keys in every GGUF writer in use). Results are cached by
path + size + mtime, so repeated preflight checks cost nothing.
"""

from __future__ import annotations

import functools
import struct
from pathlib import Path
from typing import Any, BinaryIO

_SCALARS = {0: "<B", 1: "<b", 2: "<H", 3: "<h", 4: "<I", 5: "<i", 6: "<f", 7: "<?",
            10: "<Q", 11: "<q", 12: "<d"}
_STRING, _ARRAY = 8, 9
# Bytes per element for each KV cache type (block formats include their scales).
CACHE_BYTES = {"f32": 4.0, "f16": 2.0, "bf16": 2.0, "q8_0": 34 / 32, "q5_1": 24 / 32,
               "q5_0": 22 / 32, "q4_1": 20 / 32, "q4_0": 18 / 32, "iq4_nl": 18 / 32}


def _read(f: BinaryIO, fmt: str) -> Any:
    size = struct.calcsize(fmt)
    data = f.read(size)
    if len(data) != size:
        raise EOFError
    return struct.unpack(fmt, data)[0]


def _string(f: BinaryIO) -> str:
    n = _read(f, "<Q")
    return f.read(n).decode("utf-8", errors="replace")


def _value(f: BinaryIO, vtype: int) -> Any:
    if vtype in _SCALARS:
        return _read(f, _SCALARS[vtype])
    if vtype == _STRING:
        return _string(f)
    if vtype == _ARRAY:
        itype = _read(f, "<I")
        count = _read(f, "<Q")
        if itype in _SCALARS:
            fmt = _SCALARS[itype]
            size = struct.calcsize(fmt)
            raw = f.read(size * count)
            return list(struct.unpack(f"<{count}{fmt[1]}", raw))
        return [_value(f, itype) for _ in range(count)]
    raise ValueError(f"unknown GGUF value type {vtype}")


def read_metadata(path: Path) -> dict[str, Any]:
    st = path.stat()
    return _cached(str(path), st.st_size, st.st_mtime_ns)


@functools.lru_cache(maxsize=64)
def _cached(path: str, _size: int, _mtime: int) -> dict[str, Any]:
    meta: dict[str, Any] = {}
    with open(path, "rb") as f:
        if f.read(4) != b"GGUF":
            raise ValueError(f"{path} is not a GGUF file")
        version = _read(f, "<I")
        if version < 2:
            raise ValueError(f"GGUF v{version} is not supported")
        _read(f, "<Q")  # tensor count
        kv_count = _read(f, "<Q")
        for _ in range(kv_count):
            key = _string(f)
            if key.startswith("tokenizer.") and "general.architecture" in meta:
                break
            meta[key] = _value(f, _read(f, "<I"))
    return meta


def _per_layer(value: Any, n_layer: int) -> list[int]:
    if isinstance(value, list):
        return [int(v) for v in value[:n_layer]] + [0] * max(0, n_layer - len(value))
    return [int(value or 0)] * n_layer


def kv_cache_bytes(meta: dict[str, Any], ctx: int, cache_k: str = "f16",
                   cache_v: str = "f16", parallel: int = 1) -> int | None:
    """Estimate llama.cpp's KV cache for ``ctx`` tokens. None when unknown.

    Sliding-window layers only hold ``sliding_window`` tokens (llama.cpp's
    default without --swa-full), which matters a lot for Gemma-style models.
    Recurrent/SSM layers (head_count_kv 0, or off the full-attention interval)
    and shared-KV tail layers hold no KV of their own.
    """
    arch = meta.get("general.architecture")
    if not arch:
        return None
    n_layer = int(meta.get(f"{arch}.block_count") or 0)
    if not n_layer:
        return None
    heads = meta.get(f"{arch}.attention.head_count") or 0
    kv_heads = _per_layer(meta.get(f"{arch}.attention.head_count_kv", heads), n_layer)
    embd = int(meta.get(f"{arch}.embedding_length") or 0)
    head_dim = embd // int(heads if not isinstance(heads, list) else max(heads) or 1) if embd else 0
    k_len = int(meta.get(f"{arch}.attention.key_length") or head_dim)
    v_len = int(meta.get(f"{arch}.attention.value_length") or k_len)
    k_len_swa = int(meta.get(f"{arch}.attention.key_length_swa") or k_len)
    v_len_swa = int(meta.get(f"{arch}.attention.value_length_swa") or v_len)
    window = int(meta.get(f"{arch}.attention.sliding_window") or 0)
    pattern = meta.get(f"{arch}.attention.sliding_window_pattern")
    if isinstance(pattern, list):
        swa = [bool(p) for p in pattern[:n_layer]] + [False] * max(0, n_layer - len(pattern))
    elif isinstance(pattern, int) and pattern > 1 and window:
        swa = [(i + 1) % pattern != 0 for i in range(n_layer)]
    else:
        swa = [False] * n_layer
    # Hybrid models: only every Nth layer is full attention (the rest are
    # recurrent with a fixed-size state), and some models reuse the KV of
    # earlier layers for their last N layers.
    interval = int(meta.get(f"{arch}.full_attention_interval") or 0)
    shared = int(meta.get(f"{arch}.attention.shared_kv_layers") or 0)
    kb = CACHE_BYTES.get(cache_k, 2.0)
    vb = CACHE_BYTES.get(cache_v, 2.0)
    total = 0.0
    for i in range(n_layer):
        if not kv_heads[i] or i >= n_layer - shared:
            continue
        if interval > 1 and (i + 1) % interval != 0:
            continue
        if swa[i] and window:
            tokens = min(ctx, window * max(1, parallel) + 256)
            per_tok = kv_heads[i] * (k_len_swa * kb + v_len_swa * vb)
        else:
            tokens = ctx
            per_tok = kv_heads[i] * (k_len * kb + v_len * vb)
        total += tokens * per_tok
    return int(total)
