#!/usr/bin/env bash
# Qwen-Image 2.1 model pull (into AIHub's data/models/comfyui; moved from ~/Models/ComfyUI/models).
# Resumable: re-run to continue. Downloads to *.part, renames on success.
set -u
M="${COMFY_MODELS:-$(cd "$(dirname "$0")/../../.." && pwd)/data/models/comfyui}"
HF=https://huggingface.co
UC=$HF/abenzerps/Qwen-Image-2.1-Uncensored-GGUF/resolve
CO=$HF/Comfy-Org/Qwen-Image-2.1/resolve
get() {  # url dest
  local url=$1 dest=$2
  [ -f "$dest" ] && { echo "skip (exists) $dest"; return; }
  for i in 1 2 3 4 5; do
    curl -fL --retry 5 --retry-delay 3 -C - -s -S -o "$dest.part" "$url" && mv "$dest.part" "$dest" && { echo "OK   $(date +%T) $dest"; return; }
    echo "retry $i $dest"; sleep 5
  done
  echo "FAILED $dest"
}
# Diffusion models — uncensored (preferred)
get $UC/main/qwen-image-2.1-UC-Q8_0.gguf                       $M/diffusion_models/qwen-image-2.1-UC-Q8_0.gguf &
get $UC/main/qwen-image-2.1-UC-fp8.safetensors                 $M/diffusion_models/qwen-image-2.1-UC-fp8.safetensors &
# Diffusion models — non-censored base
get $UC/base/qwen-image-2.1-Q8_0.gguf                          $M/diffusion_models/qwen-image-2.1-Q8_0.gguf &
get $CO/main/diffusion_models/qwen_image_2.1_int8_convrot.safetensors $M/diffusion_models/qwen_image_2.1_int8_convrot.safetensors &
# Text encoders + VAE (identical hashes across repos -> single copy)
get $CO/main/text_encoders/qwen3vl_8b_bf16.safetensors         $M/text_encoders/qwen3vl_8b_bf16.safetensors &
get $CO/main/text_encoders/qwen3vl_8b_int8_convrot.safetensors $M/text_encoders/qwen3vl_8b_int8_convrot.safetensors &
get $CO/main/vae/qwen_image_2.1_vae_bf16.safetensors           $M/vae/qwen_image_2.1_vae_bf16.safetensors &
# Prompt enhancers (optional; TextGenerate node)
get $CO/main/text_encoders/qwen3.5_9b_qwen_image_2.1_pe_t2i.int8_convrot.safetensors $M/text_encoders/qwen3.5_9b_qwen_image_2.1_pe_t2i.int8_convrot.safetensors &
get $CO/main/text_encoders/qwen3.5_9b_qwen_image_2.1_pe_i2i.int8_convrot.safetensors $M/text_encoders/qwen3.5_9b_qwen_image_2.1_pe_i2i.int8_convrot.safetensors &
wait
echo ">>> $(date +%T) ALL DONE"
