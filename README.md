# LLMs

Repo-local helpers for running a YAML-configured llama.cpp router server.

## LlamaCPP

Edit `llamacpp.yaml` to add or remove GGUF models. The current config uses the
available models in `~/Models` and forces the server to listen on port `7070`.

Server-level llama.cpp flags go under `server.params`. Shared per-model runtime
flags go under `model_defaults`, and per-model overrides can go under each
model's `params` mapping.

Example server params:

```yaml
server:
  params:
    threads-http: 16
    cont-batching: true
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
