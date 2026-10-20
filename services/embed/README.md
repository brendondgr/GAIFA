# Embeddings (`embed`)

EmbeddingGemma 2 as an AIHub mod (plan Phase 28): text, code, images, audio and video in one 768-d space, for search by meaning. Setup, versions and measurements: [setup/embed.md](setup/embed.md).

```
POST /v1/embed  {"inputs": [{"text": "…", "title": "…"} | {"image": "output:<id>"} | {"audio": "output:<id>"} | {"video": "output:<id>"}],
                 "dim": 768 | 512 | 256 | 128, "task": "query" | "document"}
             →  {"vectors": [[…]], "inputs": [{kind, output?, seconds?, frames?, …}], "dim", "device", "dtype", "ms"}
```

The library indexes every output in AIHub when the GPU is idle (`GET /v1/library`; collections at `/v1/collections`).

Vectors are unit length (cosine = dot product), in input order. Media are AIHub outputs, read through the hub. A video's soundtrack can be embedded as `{"audio": <video output>}`. Also `POST /v1/load {"kinds": […]}`, `POST /v1/unload`, `GET /v1/info`, `GET /v1/status`.

| File | What it does |
|---|---|
| `embed/server.py` | the API, the idle unloader, model registration at start |
| `embed/encoder.py` | `Encoder` (one lock, which encoders are loaded, prompts, Matryoshka truncation, measured memory), `GemmaBackend` (sentence-transformers), `FakeBackend` (tests) |
| `embed/worker.py` | `WorkerBackend`: the model in a spawned process; unload ends it, a crash ends only it |
| `embed/media.py` | images to RGB, audio to 16 kHz mono (and 30 s windows), video to frames at 1 fps (ffmpeg) |
| `embed/library.py` | the library: follows the hub's outputs and events, chunks and embeds each output when the GPU is idle |
| `embed/store.py` | `embed.db`: indexed outputs, chunks with float16 vectors, collections; the vector matrix for search |
| `embed/chunks.py` | ~800-token chunks with 100 of overlap, keeping offset, page and line |
| `embed/gpu.py` | when the GPU is free: other processes' DRM engine time, or `gpu_busy_percent` |
| `embed/api_library.py` | `/v1/library`, `/v1/library/reindex`, `/v1/collections` |
| `embed/hubclient.py` | outputs, memory acquire and the models registry over HTTP |
| `locks/embed.txt` | the exact packages (ROCm torch for gfx1151) that `install.sh` installs |

```bash
.venv/bin/python -m pytest -q        # unit tests, fake backend
.venv/bin/python -m pytest -q -m gpu # the real model
```
