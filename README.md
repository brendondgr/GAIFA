# LLMs

Repo-local helpers for running a JSON-configured llama.cpp router server. This
tooling lives in `~/Models/LLMs` alongside the GGUF weights it serves (e.g.
`Gemma4-26B/`).

## LlamaCPP

Edit `llamacpp.json` to add or remove GGUF models. Model `path` values may be
relative to this directory (`Gemma4-26B/...`) or absolute (`~/Models/...`), and
the server listens on port `7070`.

Server-level llama.cpp flags go under `server.params`. Shared per-model runtime
flags go under `model_defaults`, and per-model overrides go under each model's
`params` object.

Multimodal and speculative-decoding files are per-model `params`:

- `mmproj` — path to the multimodal projector (resolved like `path`).
- `model-draft` + `spec-type` — a draft model for speculative decoding; use
  `"spec-type": "draft-mtp"` for an MTP head.

Example server params:

```json
{
  "server": {
    "params": { "threads-http": 16, "cont-batching": true }
  }
}
```

Common commands from the repo root:

```bash
make llama-render
make llama-install-user
make llama-install-commands
make llama-start
make llama-status
make llama-models
```

After `make llama-install-commands`, these commands are available from any
shell:

```bash
llamacpp-start
llamacpp-start gemma4-E4B
llamacpp-restart gemma4-26B
llamacpp-stop
llamacpp-status
llamacpp-models
llamacpp-logs
```

For a foreground run instead of systemd:

```bash
make llama-run
```

The systemd service installed by `make llama-install-user` is a user service:
`llamacpp-router.service`.
