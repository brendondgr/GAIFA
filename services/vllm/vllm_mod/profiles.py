"""Profiles: one TOML file per model setup in services/vllm/profiles/<id>.toml (plan 18.1), and the
`podman run` line that serves one."""

from __future__ import annotations

import logging
import re
import tomllib
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from .settings import Settings

log = logging.getLogger("vllm")
ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
NAME_PREFIX = "aihub-vllm-"
LABEL = "aihub.mod=vllm"
MAX_UTILIZATION = 0.95


class Profile(BaseModel):
    """A model and the flags vLLM serves it with. `memory_gb` is vLLM's whole budget (weights, KV cache
    and CUDA graphs), passed as --gpu-memory-utilization."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(description="The file name without .toml", json_schema_extra={"readOnly": True})
    name: str = Field(description="Shown on the page")
    model: str = Field(description="Hugging Face repo, e.g. Qwen/Qwen3-0.6B")
    revision: str = Field("main", description="Branch, tag or commit to download")
    served_name: str | None = Field(None, description="The model id clients send (default: the repo)")
    alias: str | None = Field(None, description="The relay's alias for this endpoint")
    memory_gb: float = Field(gt=0, description="vLLM's memory budget in GB: weights + KV cache + graphs")
    max_model_len: int = Field(gt=0, description="Context window in tokens")
    max_num_seqs: int = Field(4, gt=0, description="Requests served at once")
    attention_backend: str | None = Field("TRITON_ATTN", description="TRITON_ATTN, ROCM_ATTN or "
                                          "ROCM_AITER_UNIFIED_ATTN; empty = vLLM's choice")
    enforce_eager: bool = Field(False, description="Skip CUDA graphs (needed by some quantized models)")
    trust_remote_code: bool = Field(False, description="Run the repo's own model code")
    tool_parser: str | None = Field(None, description="--tool-call-parser (turns on auto tool choice)")
    reasoning_parser: str | None = Field(None, description="--reasoning-parser (thinking in `reasoning`)")
    env: dict[str, str] = Field(default_factory=dict, description="Extra environment for the engine")
    extra_args: list[str] = Field(default_factory=list, description="More `vllm serve` flags")
    notes: str = Field("", description="Free text")

    @field_validator("id")
    @classmethod
    def _id(cls, v: str) -> str:
        if not ID_RE.match(v):
            raise ValueError("lowercase letters, digits, '.', '_' and '-'; starts with a letter or digit")
        return v

    @field_validator("attention_backend", "tool_parser", "reasoning_parser", "served_name", "alias")
    @classmethod
    def _blank(cls, v: str | None) -> str | None:
        return v or None

    @property
    def served(self) -> str:
        return self.served_name or self.model

    @property
    def container(self) -> str:
        return NAME_PREFIX + self.id

    def file_data(self) -> dict:
        """What goes in the TOML file: everything but the id, without empty optional values."""
        return {k: v for k, v in self.model_dump(exclude={"id"}).items() if v not in (None, "", [], {})}


def load_profiles(folder: Path) -> tuple[dict[str, Profile], dict[str, str]]:
    """Every profile in the folder, plus a problem per file that doesn't parse."""
    found: dict[str, Profile] = {}
    problems: dict[str, str] = {}
    for f in sorted(folder.glob("*.toml")) if folder.is_dir() else []:
        try:
            data = tomllib.loads(f.read_text())
            if "id" in data and data["id"] != f.stem:
                raise ValueError(f"id {data['id']!r} doesn't match the file name")
            found[f.stem] = Profile(**{**data, "id": f.stem})
        except (OSError, tomllib.TOMLDecodeError, ValueError, ValidationError) as e:
            problems[f.name] = _problem(e)
    for name, why in problems.items():
        log.warning("profile %s: %s", name, why)
    return found, problems


def _problem(e: Exception) -> str:
    if isinstance(e, ValidationError):
        return "; ".join(f"{'.'.join(str(x) for x in err['loc'])}: {err['msg']}" for err in e.errors())
    return str(e)


def utilization(profile: Profile, gtt_total: int) -> float:
    u = profile.memory_gb * 1e9 / gtt_total
    if u > MAX_UTILIZATION:
        raise ValueError(f"{profile.memory_gb} GB is more than {MAX_UTILIZATION:.0%} of the GPU's "
                         f"{gtt_total / 1e9:.1f} GB")
    return round(max(u, 0.01), 4)


def serve_args(profile: Profile, port: int, gtt_total: int) -> list[str]:
    """`vllm serve …` for a profile, listening on 127.0.0.1:<port>."""
    args = ["vllm", "serve", profile.model, "--host", "127.0.0.1", "--port", str(port),
            "--served-model-name", profile.served, "--revision", profile.revision,
            "--gpu-memory-utilization", str(utilization(profile, gtt_total)),
            "--max-model-len", str(profile.max_model_len), "--max-num-seqs", str(profile.max_num_seqs)]
    if profile.attention_backend:
        args += ["--attention-backend", profile.attention_backend]
    if profile.enforce_eager:
        args.append("--enforce-eager")
    if profile.trust_remote_code:
        args.append("--trust-remote-code")
    if profile.tool_parser:
        args += ["--enable-auto-tool-choice", "--tool-call-parser", profile.tool_parser]
    if profile.reasoning_parser:
        args += ["--reasoning-parser", profile.reasoning_parser]
    return args + list(profile.extra_args)


def engine_env(profile: Profile, settings: Settings) -> dict[str, str]:
    cache = settings.cache_dir
    return {
        "HF_HOME": str(settings.hf_home), "HF_HUB_OFFLINE": "1",
        "TRITON_CACHE_DIR": f"{cache}/triton", "VLLM_CACHE_ROOT": f"{cache}/vllm",
        "XDG_CACHE_HOME": f"{cache}/xdg", "TORCHINDUCTOR_CACHE_DIR": f"{cache}/inductor",
        # kyuz0's safe baseline for every profile (models.py DEFAULT_MODEL_ENV).
        "VLLM_ROCM_USE_AITER": "0", "VLLM_ROCM_USE_AITER_LINEAR": "0",
        # rocprofiler-sdk attaches to every process and polls its queues; nothing here profiles.
        "ROCPROFILER_REGISTER_ENABLED": "0",
        "PYTHONUNBUFFERED": "1", **profile.env,
    }


def engine_command(profile: Profile, settings: Settings, gtt_total: int) -> list[str]:
    """The `podman run -d` line: host network (vLLM binds 127.0.0.1, nothing is published), the GPU
    devices, the HF cache and compile caches at the same paths inside, labels for adoption."""
    hf, cache = str(settings.hf_home), str(settings.cache_dir)
    cmd = [settings.podman, "run", "-d", "--name", profile.container,
           "--label", LABEL, "--label", f"aihub.profile={profile.id}",
           "--network", "host", "--ipc", "host",
           "--device", "/dev/kfd", "--device", "/dev/dri", "--group-add", "keep-groups",
           "--security-opt", "label=disable", "--security-opt", "seccomp=unconfined",
           "-v", f"{hf}:{hf}", "-v", f"{cache}:{cache}"]
    for k, v in engine_env(profile, settings).items():
        cmd += ["-e", f"{k}={v}"]
    return cmd + [settings.image] + serve_args(profile, settings.engine_port, gtt_total)
