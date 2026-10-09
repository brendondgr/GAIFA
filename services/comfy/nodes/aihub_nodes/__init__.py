"""AIHub's own ComfyUI nodes and fixes (loaded through extra_model_paths.yaml; tracked in git).

- Qwen-VL vision patch-embed as a matmul: the Qwen2.5-VL / Qwen3-VL / Qwen3.5 vision towers embed
  patches with a Conv3d whose kernel equals its stride, which is one matrix multiply over the
  patches. ROCm (MIOpen) runs that Conv3d about 100x slower than the matmul on gfx1151 (17.5 s of a
  33 s Qwen3-VL text encode for one 1024x1024 image); the result is the same to rounding (1e-5).
- AIHubTextEncodeQwenImage21: TextEncodeQwenImage21 that can skip the negative encode. The core
  node runs the whole prompt + reference images through Qwen3-VL twice (positive and negative),
  but at CFG 1 (Qwen-Image 2.1 Turbo, and the base packs) the sampler never uses the negative.

Guide: docs/workflows.md; measurements: docs/comfy-transfer-report.md.
"""
import logging
import math

import torch
import torch.nn.functional as F
from typing_extensions import override

import comfy.model_management
import comfy.ops
import comfy.utils
import node_helpers
from comfy_api.latest import ComfyExtension, io
from comfy_extras.nodes_qwen import TextEncodeQwenImage21


def _patch_embed_forward(self, x: torch.Tensor) -> torch.Tensor:
    """VisionPatchEmbed.forward with the stride == kernel Conv3d done as F.linear (same casting as
    comfy.ops' Conv3d, so offloaded and manual-cast weights behave the same)."""
    x = x.reshape(-1, self.in_channels * self.temporal_patch_size * self.patch_size * self.patch_size)
    p = self.proj
    if getattr(p, "comfy_cast_weights", False) or getattr(p, "weight_function", None) or getattr(p, "bias_function", None):
        with comfy.ops.CastBiasWeightContext(p, x, offloadable=True) as (w, b):
            return F.linear(x, w.reshape(w.shape[0], -1), b).view(-1, self.embed_dim)
    return F.linear(x, p.weight.reshape(p.weight.shape[0], -1), p.bias).view(-1, self.embed_dim)


def patch_vision_embeds() -> list[str]:
    patched = []
    for mod, cls in (("comfy.text_encoders.qwen_vl", "VisionPatchEmbed"),
                     ("comfy.text_encoders.qwen35", "Qwen35VisionPatchEmbed")):
        try:
            klass = getattr(__import__(mod, fromlist=[cls]), cls)
        except (ImportError, AttributeError):
            continue                                    # this ComfyUI doesn't have it
        if getattr(klass.forward, "_aihub", False):
            continue
        klass.forward = _patch_embed_forward
        klass.forward._aihub = True
        patched.append(f"{mod}.{cls}")
    return patched


_patch_embed_forward._aihub = True


def _zeroed(conditioning):
    """ConditioningZeroOut that keeps reference_latents (only read when cfg > 1)."""
    out = []
    for c, d in conditioning:
        d = dict(d)
        if d.get("pooled_output") is not None:
            d["pooled_output"] = torch.zeros_like(d["pooled_output"])
        out.append([torch.zeros_like(c), d])
    return out


class AIHubTextEncodeQwenImage21(TextEncodeQwenImage21):
    @classmethod
    def define_schema(cls):
        s = super().define_schema()
        s.node_id = "AIHubTextEncodeQwenImage21"
        s.display_name = "Text Encode Qwen Image 2.1 (AIHub, encode once)"
        s.category = "AIHub"
        s.inputs.append(io.Boolean.Input(
            "encode_negative", default=False,
            tooltip="Off: encode only the prompt (the negative is unused at cfg 1, so the output is identical "
                    "and the reference images are read once instead of twice). Turn on when cfg > 1."))
        return s

    @classmethod
    def execute(cls, clip, prompt, negative_prompt, vae=None, resolution=1024, images=None,
                encode_negative=False) -> io.NodeOutput:
        if encode_negative:
            return super().execute(clip, prompt, negative_prompt, vae=vae, resolution=resolution, images=images)
        # The core node's steps (comfy_extras/nodes_qwen.py), with one encode instead of two.
        ref_latents, images_vl = [], []
        latent_w = latent_h = resolution or 1024
        images = images or {}
        for name in sorted(images, key=lambda n: int(n.rsplit("_", 1)[-1])):
            image = images[name]
            if image is None:
                continue
            samples = image[:1].movedim(-1, 1)
            if resolution > 0:
                ratio = samples.shape[3] / samples.shape[2]
                width = round(math.sqrt(resolution * resolution * ratio) / 32) * 32
                height = round(math.sqrt(resolution * resolution / ratio) / 32) * 32
            else:
                width, height = round(samples.shape[3] / 32) * 32, round(samples.shape[2] / 32) * 32
            width, height = max(32, width), max(32, height)
            if (width, height) == (samples.shape[3], samples.shape[2]):
                s = image[:1]
            else:
                s = comfy.utils.common_upscale(samples, width, height, "lanczos", "disabled").movedim(1, -1)
            if not images_vl:
                latent_w, latent_h = width, height
            rgb = s[:, :, :, :3]
            if s.shape[-1] > 3:
                rgb = rgb * s[:, :, :, 3:] + (1.0 - s[:, :, :, 3:])
            images_vl.append(rgb)
            if vae is not None:
                ref_latents.append(vae.encode(s))
        keep_vision = len(ref_latents) == 0
        positive = clip.encode_from_tokens_scheduled(
            clip.tokenize(prompt, images=images_vl, keep_vision=keep_vision, prevent_empty_text=True))
        negative = _zeroed(positive)
        if ref_latents:
            positive = node_helpers.conditioning_set_values(positive, {"reference_latents": ref_latents}, append=True)
            negative = node_helpers.conditioning_set_values(negative, {"reference_latents": ref_latents}, append=True)
        latent = torch.zeros([1, 64, latent_h // 16, latent_w // 16], device=comfy.model_management.intermediate_device())
        return io.NodeOutput(positive, negative, {"samples": latent})


class AIHubExtension(ComfyExtension):
    @override
    async def get_node_list(self) -> list[type[io.ComfyNode]]:
        return [AIHubTextEncodeQwenImage21]


async def comfy_entrypoint() -> AIHubExtension:
    patched = patch_vision_embeds()
    logging.info("[aihub_nodes] vision patch-embed as matmul: %s", ", ".join(patched) or "nothing to patch")
    return AIHubExtension()
