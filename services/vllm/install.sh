#!/usr/bin/env bash
# Builds .venv/ for the vllm adapter (run by `gaifa install vllm`), and pulls the vLLM image named in
# service.toml (VLLM_IMAGE) when podman doesn't have it yet. vLLM itself runs inside that image.
set -euo pipefail
cd "$(dirname "$0")"
uv venv --quiet --allow-existing --python 3.12 --python-preference only-managed .venv
uv pip install --quiet --python .venv/bin/python -r requirements-dev.txt
image=$(.venv/bin/python -c 'import tomllib; print(tomllib.load(open("service.toml","rb"))["run"]["env"]["VLLM_IMAGE"])')
if ! podman image exists "$image"; then
  echo "pulling $image (about 3.3 GB)"
  podman pull "$image"
fi
echo "installed vllm into .venv"
