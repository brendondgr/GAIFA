#!/usr/bin/env bash
# Qwen-Image 2.1 Turbo model pull (into GAIFA's data/models/comfyui), for the qwen21-turbo-* packs.
# The official Turbo weights (Qwen/Qwen-Image-2.1-Turbo), quantized like the base packs' files:
# Q8_0 GGUF (default) and FP8 (the packs' switch). The text encoder and VAE are the base model's,
# so run download_qwen_image_2.1.sh first if those are missing.
# Resumable: re-run to continue. Downloads to *.part, checks sha256, renames on success.
set -u
M="${COMFY_MODELS:-$(cd "$(dirname "$0")/../../.." && pwd)/data/models/comfyui}"
HF=https://huggingface.co
TQ=$HF/abenzerps/Qwen-Image-2.1-Turbo-Quantized/resolve
get() {  # url dest sha256
  local url=$1 dest=$2 sum=$3
  [ -f "$dest" ] && { echo "skip (exists) $dest"; return; }
  for i in 1 2 3 4 5; do
    if curl -fL --retry 5 --retry-delay 3 -C - -s -S -o "$dest.part" "$url"; then
      if echo "$sum  $dest.part" | sha256sum -c --quiet -; then
        mv "$dest.part" "$dest" && { echo "OK   $(date +%T) $dest"; return; }
      fi
      echo "sha256 mismatch, starting over: $dest"; rm -f "$dest.part"
    fi
    echo "retry $i $dest"; sleep 5
  done
  echo "FAILED $dest"
}
# Diffusion models: official Turbo, quantized (sums from the repo's SHA256SUMS)
get $TQ/main/qwen-image-2.1-turbo-Q8_0.gguf        $M/diffusion_models/qwen-image-2.1-turbo-Q8_0.gguf \
    9c2fd9b645811ae5f2b41e60adee832510a23929bc05bd6f8cc48d34a17b079e &
# The FP8 export lacks the per-layer metadata ComfyUI needs (it would run unscaled: noise), so it's
# fetched as .upstream and rewritten by fix_fp8_quant_metadata.py (header only; tensor data unchanged).
fp8() {
  local d=$M/diffusion_models/qwen-image-2.1-turbo-fp8.safetensors
  [ -f "$d" ] && { echo "skip (exists) $d"; return; }
  get $TQ/main/qwen-image-2.1-turbo-fp8.safetensors "$d.upstream" \
      024e1befc5f7557e250489839582166daf5994dc4449f01e7d12912cb300e21b
  [ -f "$d.upstream" ] && python3 "$(dirname "$0")/fix_fp8_quant_metadata.py" "$d.upstream" "$d" && rm -f "$d.upstream"
}
fp8 &
wait
echo ">>> $(date +%T) ALL DONE"
