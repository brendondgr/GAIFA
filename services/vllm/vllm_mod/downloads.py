"""Downloading a profile's model into the Hugging Face cache (HF_HOME = data/models/hf-cache) before
the engine starts, then registering it in GAIFA's models registry (plan 18.3). The engine itself runs
offline (HF_HUB_OFFLINE=1), so a start never downloads inside the container, and download time never
holds a memory grant."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .hubclient import Hub
from .profiles import Profile
from .settings import Settings

log = logging.getLogger("vllm")
ALLOW = ["*.safetensors", "*.json", "*.txt", "*.model", "*.jinja", "*.tiktoken", "*.py", "tokenizer*"]


@dataclass
class Download:
    profile: str
    repo: str
    revision: str
    state: str = "running"            # running | done | failed
    bytes: int = 0
    total: int | None = None
    error: str | None = None
    commit: str | None = None
    registered: str | None = None
    started: float = field(default_factory=time.time)
    finished: float | None = None

    @property
    def progress(self) -> float | None:
        return min(1.0, self.bytes / self.total) if self.total else None

    def view(self) -> dict[str, Any]:
        return {**asdict(self), "progress": self.progress}


def repo_dir(hf_home: Path, repo: str) -> Path:
    return hf_home / "hub" / ("models--" + repo.replace("/", "--"))


def role_of(name: str) -> str:
    if name.endswith(".safetensors"):
        return "weights"
    if name.startswith("tokenizer") or name in ("vocab.json", "merges.txt") or name.endswith((".model", ".tiktoken")):
        return "tokenizer"
    if name.endswith(".json") or name.endswith(".jinja"):
        return "config"
    return "other"


class Downloads:
    """`fetch(repo, revision, folder, progress)` is huggingface_hub's snapshot_download by default;
    tests swap it, and `remote_size` (the repo's total of the allowed files)."""

    def __init__(self, settings: Settings, hub: Hub, fetch: Callable[..., str] | None = None,
                 remote_size: Callable[[str, str], int | None] | None = None):
        self.s = settings
        self.hub = hub
        self.fetch = fetch or _snapshot_download
        self.remote_size = remote_size or _remote_size
        self.jobs: dict[str, Download] = {}
        self._tasks: dict[str, asyncio.Task] = {}

    @property
    def _done_file(self) -> Path:
        return self.s.state_dir / "downloads.json"

    def _done(self) -> dict[str, str]:
        try:
            return json.loads(self._done_file.read_text())
        except (OSError, ValueError):
            return {}

    def local_commit(self, p: Profile) -> str | None:
        """The commit downloaded for the profile's repo and revision, if its snapshot is still there."""
        commit = self._done().get(f"{p.model}@{p.revision}")
        if commit and (repo_dir(self.s.hf_home, p.model) / "snapshots" / commit).is_dir():
            return commit
        return None

    def local_bytes(self, p: Profile) -> int:
        d = repo_dir(self.s.hf_home, p.model) / "blobs"
        return sum(f.stat().st_size for f in d.glob("*") if f.is_file()) if d.is_dir() else 0

    async def ensure(self, p: Profile) -> None:
        """Before a start: download if needed (or wait for the running download); raise if it fails."""
        if self.local_commit(p):
            return
        job = await self.start(p)
        await self._tasks[p.id]
        if job.state != "done":
            raise RuntimeError(f"download of {p.model} failed: {job.error}")

    async def start(self, p: Profile) -> Download:
        cur = self.jobs.get(p.id)
        if cur and cur.state == "running":
            return cur
        job = self.jobs[p.id] = Download(p.id, p.model, p.revision)
        self._tasks[p.id] = asyncio.create_task(self._run(p, job))
        return job

    async def _run(self, p: Profile, job: Download) -> None:
        log.info("downloading %s@%s", p.model, p.revision)
        try:
            job.total = await asyncio.to_thread(self.remote_size, p.model, p.revision)
        except Exception as e:  # noqa: BLE001  (sizes are only for the progress bar)
            log.warning("no size for %s: %s", p.model, e)
        watcher = asyncio.create_task(self._watch(p, job))
        try:
            path = await asyncio.to_thread(self.fetch, p.model, p.revision, self.s.hf_home / "hub")
            job.commit = Path(path).name
            job.bytes = self.local_bytes(p)
            done = self._done()
            done[f"{p.model}@{p.revision}"] = job.commit
            self.s.state_dir.mkdir(parents=True, exist_ok=True)
            self._done_file.write_text(json.dumps(done, indent=1))
            job.registered = await self.register(p, Path(path))
            job.state = "done"
            log.info("downloaded %s (%s); registry: %s", p.model, job.commit[:12], job.registered)
        except Exception as e:  # noqa: BLE001
            job.state, job.error = "failed", str(e) or type(e).__name__
            log.error("download of %s failed: %s", p.model, job.error)
        finally:
            job.finished = time.time()
            watcher.cancel()

    async def _watch(self, p: Profile, job: Download) -> None:
        while True:
            job.bytes = self.local_bytes(p)
            await asyncio.sleep(1.0)

    async def register(self, p: Profile, snapshot: Path) -> str:
        models = self.s.hf_home.parent         # data/models
        try:
            base = repo_dir(self.s.hf_home, p.model).relative_to(models).as_posix()
        except ValueError:
            return "outside data/models"
        files = [{"path": f.relative_to(models).as_posix(), "role": role_of(f.name)}
                 for f in sorted(snapshot.rglob("*")) if f.is_file()]
        entry = {"path": base, "kind": "llm", "format": "hf-dir", "name": f"{p.model} (vLLM)", "services": ["vllm"],
                 "source": {"type": "huggingface", "repo": p.model, "revision": snapshot.name}, "files": files,
                 "notes": f"Downloaded by the vllm mod for the profile {p.id}."}
        return await self.hub.register_model(entry)

    def views(self) -> list[dict[str, Any]]:
        return [j.view() for j in self.jobs.values()]


def _snapshot_download(repo: str, revision: str, cache_dir: Path) -> str:
    from huggingface_hub import snapshot_download

    return snapshot_download(repo, revision=revision, cache_dir=str(cache_dir), allow_patterns=ALLOW)


def _remote_size(repo: str, revision: str) -> int | None:
    from fnmatch import fnmatch

    from huggingface_hub import HfApi

    info = HfApi().model_info(repo, revision=revision, files_metadata=True)
    sizes = [s.size or 0 for s in info.siblings or [] if any(fnmatch(s.rfilename.split("/")[-1], a) for a in ALLOW)]
    return sum(sizes) or None
