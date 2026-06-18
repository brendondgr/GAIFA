# LLMs

Repo-local helpers for running a YAML-configured llama.cpp router server.

## LlamaCPP

Edit `llamacpp.yaml` to add or remove GGUF models. The current config uses the
available model in `~/Models` and forces the server to listen on port `9090`.

Common commands from the repo root:

```bash
make llama-render
make llama-install-user
make llama-start
make llama-status
make llama-models
```

For a foreground run instead of systemd:

```bash
make llama-run
```

The systemd service installed by `make llama-install-user` is a user service:
`llamacpp-router.service`.
