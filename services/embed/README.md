# Embeddings (`embed`)

EmbeddingGemma 2 as an AIHub mod (plan Phase 28): text, code, images, audio and video in one 768-d space, for search by meaning. Setup, versions and measurements: [setup/embed.md](setup/embed.md).

```
POST /v1/embed  {"inputs": [{"text": "…", "title": "…"} | {"image": "output:<id>"} | {"audio": "output:<id>"} | {"video": "output:<id>"}],
                 "dim": 768 | 512 | 256 | 128, "task": "query" | "document"}
             →  {"vectors": [[…]], "inputs": [{kind, output?, seconds?, frames?, …}], "dim", "device", "dtype", "ms"}
```

Vectors are unit length (cosine = dot product), in input order. Media are AIHub outputs, read through the hub. A video's soundtrack can be embedded as `{"audio": <video output>}`. Also `POST /v1/load {"kinds": […]}`, `POST /v1/unload`, `GET /v1/info`, `GET /v1/status`.

| File | What it does |
|---|---|
| `embed/server.py` | the API, the idle unloader, model registration at start |
| `embed/encoder.py` | `Encoder` (one lock, which encoders are loaded, prompts, Matryoshka truncation, measured memory), `GemmaBackend` (sentence-transformers), `FakeBackend` (tests) |
| `embed/worker.py` | `WorkerBackend`: the model in a spawned process; unload ends it, a crash ends only it |
| `embed/media.py` | images to RGB, audio to 16 kHz mono, video to frames at 1 fps (ffmpeg) |
| `embed/hubclient.py` | outputs, memory acquire and the models registry over HTTP |
| `locks/embed.txt` | the exact packages (ROCm torch for gfx1151) that `install.sh` installs |

```bash
.venv/bin/python -m pytest -q        # unit tests, fake backend
.venv/bin/python -m pytest -q -m gpu # the real model
```
