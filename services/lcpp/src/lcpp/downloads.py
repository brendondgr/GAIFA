"""GGUF downloads from Hugging Face into ``models/<dir>/``.

Two inputs: a repo id (``owner/name``, or its huggingface.co URL) and a link
to one file (``…/resolve/<rev>/<path>``). Either is resolved against the Hub
API into GGUF *choices*: one per quant, with split parts grouped, plus the
repo's projector (``mmproj-*``) and draft (``mtp-*``) sidecars. A repo with no
GGUF is reported by what it holds instead (safetensors, AWQ, GPTQ, …), since
llama-server can only run GGUF.

A download streams each file to ``<name>.part`` (hashed on the way through
against the LFS sha256), then renames it into place. A ``.part`` left by a
failure, a cancelled retry or a daemon restart is resumed with a Range
request. Jobs run one at a time and exist only while something is queued or
downloading; finished jobs are records in memory until dismissed.

Daemon-only: this imports httpx, so the CLI must never import it.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import re
import shutil
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import quote, unquote, urlsplit

import httpx

from lcpp import gaifa

from lcpp.catalog import QUANT_SUFFIX_RE, SIDECAR_RE, SPLIT_RE, Catalog, suggest_id
from lcpp.instances import LcppError
from lcpp.paths import Paths

HF = "https://huggingface.co"
HOSTS = {"huggingface.co", "www.huggingface.co", "hf.co"}
REPO_RE = re.compile(r"^[A-Za-z0-9][\w.-]*/[\w.-]+$")
DIR_RE = re.compile(r"^[A-Za-z0-9][\w.+-]{0,127}$")
CHUNK = 1 << 20
ACTIVE = ("queued", "downloading")


def parse_input(text: str) -> tuple[str, str, str | None]:
    """``(repo, revision, file-or-None)`` from a repo id or a huggingface.co URL."""
    raw = (text or "").strip()
    if REPO_RE.match(raw):
        return raw, "main", None
    url = urlsplit(raw if "://" in raw else "https://" + raw)
    if url.hostname not in HOSTS:
        raise LcppError("invalid_param", "Enter a Hugging Face repo (owner/name) or a huggingface.co link")
    parts = [unquote(p) for p in url.path.split("/") if p]
    if parts and parts[0] == "models":  # huggingface.co/models/owner/name is not a thing, but be lenient
        parts = parts[1:]
    if len(parts) < 2 or not REPO_RE.match(f"{parts[0]}/{parts[1]}"):
        raise LcppError("invalid_param", "That link does not name a Hugging Face repo")
    repo = f"{parts[0]}/{parts[1]}"
    if len(parts) >= 4 and parts[2] in ("resolve", "blob"):
        return repo, parts[3], "/".join(parts[4:]) or None
    if len(parts) >= 4 and parts[2] == "tree":
        return repo, parts[3], None
    return repo, "main", None


def hf_token() -> str | None:
    """The token ``hf auth login`` saved, read fresh each time so a login
    takes effect without restarting the daemon."""
    if os.environ.get("HF_TOKEN"):
        return os.environ["HF_TOKEN"].strip()
    home = Path(os.environ.get("HF_HOME") or Path.home() / ".cache/huggingface")
    try:
        return (home / "token").read_text().strip() or None
    except OSError:
        return None


def _quant(path: str) -> str | None:
    stem = re.sub(r"(-\d+-of-\d+)?\.gguf$", "", path.rsplit("/", 1)[-1], flags=re.IGNORECASE)
    m = QUANT_SUFFIX_RE.search(stem)
    if m:
        return m.group(2).upper()
    folder = path.rsplit("/", 2)[-2] if "/" in path else ""
    m = QUANT_SUFFIX_RE.fullmatch(folder)
    return m.group(2).upper() if m else None


def _file(s: dict[str, Any]) -> dict[str, Any]:
    lfs = s.get("lfs") or {}
    return {"path": s["rfilename"], "size_bytes": int(s.get("size") or lfs.get("size") or 0),
            "sha256": lfs.get("sha256")}


def gguf_choices(siblings: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Group a repo's GGUFs into model choices (split parts together) and sidecars."""
    files = [_file(s) for s in siblings if s["rfilename"].lower().endswith(".gguf")]
    choices: dict[str, dict[str, Any]] = {}
    mmproj: list[dict[str, Any]] = []
    drafts: list[dict[str, Any]] = []
    for f in sorted(files, key=lambda f: f["path"]):
        name = f["path"].rsplit("/", 1)[-1]
        side = SIDECAR_RE.match(name)
        if side:
            (mmproj if side.group(1).lower() == "mmproj" else drafts).append(f)
            continue
        m = SPLIT_RE.match(name)
        key = f["path"][: len(f["path"]) - len(name)] + (f"{m.group('prefix')}*-of-{m.group('total')}" if m else name)
        c = choices.setdefault(key, {"id": f["path"], "label": re.sub(r"-\d+-of-\d+(?=\.gguf$)", "", name),
                                     "quant": _quant(f["path"]), "files": [], "size_bytes": 0})
        c["files"].append(f)
        c["size_bytes"] += f["size_bytes"]
    out = []
    for c in choices.values():
        c["id"] = c["files"][0]["path"]  # part 1 sorts first
        c["suggested_id"] = suggest_id(c["id"].rsplit("/", 1)[-1])
        m = SPLIT_RE.match(c["id"].rsplit("/", 1)[-1])
        c["complete"] = not m or (int(m.group("index")) == 1 and len(c["files"]) == int(m.group("total")))
        out.append(c)
    return {"choices": sorted(out, key=lambda c: c["size_bytes"]), "mmproj": mmproj, "drafts": drafts}


def weights_kind(info: dict[str, Any], names: list[str]) -> str:
    """What a repo without GGUFs holds: awq, gptq, … (its quant_method), else
    safetensors / pytorch / unknown."""
    qc = (info.get("config") or {}).get("quantization_config") or {}
    if qc.get("quant_method"):
        return str(qc["quant_method"]).lower()
    lower = info.get("id", "").lower()
    for q in ("awq", "gptq", "exl2", "mlx"):
        if q in lower:
            return q
    if any(n.endswith(".safetensors") for n in names):
        return "safetensors"
    if any(n.endswith((".bin", ".pt", ".pth")) for n in names):
        return "pytorch"
    return "unknown"


KIND_LABEL = {"safetensors": "full-precision safetensors weights", "awq": "AWQ-quantized weights",
              "gptq": "GPTQ-quantized weights", "pytorch": "PyTorch weights", "exl2": "EXL2 weights",
              "mlx": "MLX weights", "unknown": "no GGUF files"}


def suggest_dir(repo: str) -> str:
    name = re.sub(r"[-_.]?gguf$", "", repo.split("/", 1)[1], flags=re.IGNORECASE)
    return re.sub(r"[^\w.+-]+", "-", name).strip("-.") or "model"


# ---- jobs --------------------------------------------------------------
@dataclass
class FileJob:
    path: str  # in the repo
    dest: Path
    size: int
    sha256: str | None
    done: int = 0
    state: str = "queued"  # queued | downloading | verifying | done | failed
    created: bool = False  # this job put it there (cancel removes it)

    @property
    def part(self) -> Path:
        return self.dest.with_name(self.dest.name + ".part")


@dataclass
class Job:
    id: str
    repo: str
    revision: str
    label: str
    dest_dir: Path
    files: list[FileJob]
    model: dict[str, Any] | None  # ModelInput to add to the catalog when done
    state: str = "queued"  # queued | downloading | done | failed | cancelled
    error: str | None = None
    warning: str | None = None
    created_ts: float = field(default_factory=time.time)
    finished_ts: float | None = None
    samples: list[tuple[float, int]] = field(default_factory=list)
    task: asyncio.Task | None = None

    @property
    def done_bytes(self) -> int:
        return sum(f.done for f in self.files)

    @property
    def total_bytes(self) -> int:
        return sum(f.size for f in self.files)

    def speed(self) -> float:
        if self.state != "downloading" or len(self.samples) < 2:
            return 0.0
        (t0, b0), (t1, b1) = self.samples[0], self.samples[-1]
        return (b1 - b0) / (t1 - t0) if t1 > t0 else 0.0


class Downloads:
    def __init__(self, paths: Paths, catalog: Catalog):
        self.paths = paths
        self.catalog = catalog
        self.jobs: dict[str, Job] = {}
        self.transport: httpx.AsyncBaseTransport | None = None  # tests swap in a MockTransport
        self._slot = asyncio.Semaphore(1)

    @property
    def models_dir(self) -> Path:
        return self.paths.models_dir

    def _client(self) -> httpx.AsyncClient:
        token = hf_token()
        return httpx.AsyncClient(
            transport=self.transport, follow_redirects=True,
            timeout=httpx.Timeout(30.0, read=120.0),
            # httpx drops Authorization on a redirect to another origin (the CDN).
            headers={"Authorization": f"Bearer {token}"} if token else {})

    # ---- resolve -------------------------------------------------------
    async def _info(self, c: httpx.AsyncClient, repo: str, revision: str) -> dict[str, Any]:
        path = f"/api/models/{repo}" + (f"/revision/{quote(revision, safe='')}" if revision != "main" else "")
        try:
            r = await c.get(HF + path, params={"blobs": "true"})
        except httpx.HTTPError as e:
            raise LcppError("hf_unreachable", f"Hugging Face is unreachable: {e}", 502) from e
        if r.status_code in (401, 404):
            hint = "" if hf_token() else " If it is private, log in with `hf auth login`."
            raise LcppError("hf_not_found", f"Repo {repo} (revision {revision}) was not found on Hugging Face.{hint}", 404)
        if r.status_code >= 400:
            raise LcppError("hf_unreachable", f"Hugging Face answered {r.status_code} for {repo}", 502)
        return r.json()

    async def resolve(self, text: str) -> dict[str, Any]:
        repo, revision, want = parse_input(text)
        async with self._client() as c:
            info = await self._info(c, repo, revision)
        siblings = info.get("siblings") or []
        names = [s["rfilename"] for s in siblings]
        groups = gguf_choices(siblings)
        out: dict[str, Any] = {
            "repo": info.get("id") or repo, "revision": revision, "sha": info.get("sha"),
            "gated": info.get("gated") or False, "kind": "gguf", "message": None, "search_url": None,
            **groups, "selected": None, "suggested_dir": suggest_dir(repo), "suggested_id": None,
            "free_bytes": shutil.disk_usage(self._existing(self.models_dir)).free,
        }
        if want is not None:
            if want not in names:
                raise LcppError("hf_not_found", f"{want} is not in {repo} at {revision}", 404)
            if not want.lower().endswith(".gguf"):
                raise LcppError("not_gguf", f"{want} is not a GGUF file; llama-server can only run GGUF", 400)
            sel = next((ch for ch in groups["choices"] if any(f["path"] == want for f in ch["files"])), None)
            if sel is None:
                raise LcppError("invalid_param", f"{want} is a projector/draft sidecar, not a model. "
                                "Link the model GGUF; its sidecars are offered alongside it.")
            out["selected"] = sel["id"]
        elif len(groups["choices"]) == 1:
            out["selected"] = groups["choices"][0]["id"]
        if not groups["choices"]:
            kind = weights_kind(info, names)
            out["kind"] = kind
            base = repo.split("/", 1)[1]
            out["search_url"] = f"{HF}/models?search={quote(base)}%20gguf"
            out["message"] = (f"{repo} has {KIND_LABEL.get(kind, kind + ' weights')}, not GGUF. "
                              "llama-server can only run GGUF, so look for a GGUF conversion of it.")
        if out["selected"]:
            out["suggested_id"] = next(ch["suggested_id"] for ch in groups["choices"] if ch["id"] == out["selected"])
        return out

    @staticmethod
    def _existing(p: Path) -> Path:
        while not p.exists() and p != p.parent:
            p = p.parent
        return p

    # ---- start ---------------------------------------------------------
    async def start(self, body: dict[str, Any]) -> dict[str, Any]:
        repo = str(body.get("repo") or "")
        revision = str(body.get("revision") or "main")
        choice = str(body.get("choice") or "")
        if not REPO_RE.match(repo):
            raise LcppError("invalid_param", "repo must be owner/name")
        folder = str(body.get("dir") or suggest_dir(repo)).strip()
        if not DIR_RE.match(folder) or folder in (".", ".."):
            raise LcppError("invalid_param", "folder must be one name (letters, digits, . _ + -), no slashes", field="dir")
        async with self._client() as c:
            info = await self._info(c, repo, revision)
        groups = gguf_choices(info.get("siblings") or [])
        pick = next((ch for ch in groups["choices"] if ch["id"] == choice), None)
        if pick is None:
            raise LcppError("invalid_param", f"{choice or 'no file'} is not a GGUF model in {repo}", field="choice")
        if not pick["complete"]:
            raise LcppError("invalid_param", f"{pick['label']}: split set is incomplete in the repo")
        wanted = list(pick["files"])
        side: dict[str, str | None] = {}
        for key, pool in (("mmproj", groups["mmproj"]), ("draft", groups["drafts"])):
            name = body.get(key) or None
            f = next((x for x in pool if x["path"] == name), None) if name else None
            if name and f is None:
                raise LcppError("invalid_param", f"{name} is not a {key} file in {repo}", field=key)
            if f:
                wanted.append(f)
            side[key] = f
        dest_dir = self.models_dir / folder
        files = [FileJob(path=f["path"], dest=dest_dir / f["path"].rsplit("/", 1)[-1],
                         size=f["size_bytes"], sha256=f["sha256"]) for f in wanted]
        if len({f.dest for f in files}) != len(files):
            raise LcppError("invalid_param", "two selected files have the same name")
        busy = {f.dest for j in self.jobs.values() if j.state in ACTIVE for f in j.files}
        clash = next((f for f in files if f.dest in busy), None)
        if clash:
            raise LcppError("name_taken", f"{self.paths.display(clash.dest)} is already being downloaded", 409)

        model = None
        if body.get("add_to_catalog", True):
            mid = str(body.get("model_id") or suggest_id(pick["id"].rsplit("/", 1)[-1]))
            nicknames = [str(n).strip() for n in body.get("nicknames") or [] if str(n).strip()]
            errors = self.catalog.name_errors(mid, nicknames)
            if self.catalog.get(mid) is not None:
                errors.insert(0, f'"{mid}" is already in the catalog')
            queued = {j.model["id"] for j in self.jobs.values() if j.state in ACTIVE and j.model}
            if mid in queued:
                errors.insert(0, f'"{mid}" is already being downloaded')
            if errors:
                raise LcppError("invalid_param", errors[0], field="model_id")
            model = {"id": mid, "nicknames": nicknames, "path": self.paths.display_model(files[0].dest),
                     "mmproj": self.paths.display_model(dest_dir / side["mmproj"]["path"].rsplit("/", 1)[-1]) if side["mmproj"] else None,
                     "draft": self.paths.display_model(dest_dir / side["draft"]["path"].rsplit("/", 1)[-1]) if side["draft"] else None,
                     "spec_type": "draft-mtp" if side["draft"] else None, "overrides": {}}

        need = sum(f.size - self._have(f) for f in files)
        free = shutil.disk_usage(self._existing(dest_dir)).free
        if need > free:
            raise LcppError("disk_full", f"Needs {need / 1024**3:.1f} GB, only {free / 1024**3:.1f} GB free "
                            f"in {self.paths.display(self._existing(dest_dir))}", 507)

        job = Job(id=uuid.uuid4().hex[:8], repo=repo, revision=revision, label=pick["label"],
                  dest_dir=dest_dir, files=files, model=model)
        self.jobs[job.id] = job
        job.task = asyncio.create_task(self._run(job))
        return self.view(job)

    @staticmethod
    def _have(f: FileJob) -> int:
        """Bytes of ``f`` already on disk (a finished file or a resumable part)."""
        try:
            if f.dest.stat().st_size == f.size:
                return f.size
        except OSError:
            pass
        try:
            return min(f.part.stat().st_size, f.size)
        except OSError:
            return 0

    # ---- run -----------------------------------------------------------
    async def _run(self, job: Job) -> None:
        try:
            async with self._slot:
                job.state = "downloading"
                job.dest_dir.mkdir(parents=True, exist_ok=True)
                async with self._client() as c:
                    for f in job.files:
                        await self._fetch(c, job, f)
                if job.model:
                    job.warning = await asyncio.to_thread(self._register, job.model)
                hub = await gaifa.register_download(
                    job.dest_dir, model_id=job.model["id"] if job.model else None,
                    name=job.model["id"] if job.model else job.label, repo=job.repo, revision=job.revision,
                    files=[(f.dest, f.sha256) for f in job.files])
                job.warning = "; ".join(w for w in (job.warning, hub) if w) or None
                job.state = "done"
        except asyncio.CancelledError:
            job.state = "cancelled"
            raise
        except LcppError as e:
            job.state, job.error = "failed", e.detail
        except httpx.HTTPError as e:
            job.state, job.error = "failed", f"network error: {e}"
        except OSError as e:
            job.state, job.error = "failed", f"{e.strerror or e}: {e.filename or ''}".strip(": ")
        finally:
            job.finished_ts = time.time()
            job.samples.clear()
            for f in job.files:
                if f.state in ("downloading", "verifying"):
                    f.state = "failed" if job.state == "failed" else "queued"

    def _register(self, model: dict[str, Any]) -> str | None:
        if self.catalog.get(model["id"]) is not None:
            return f'"{model["id"]}" was added to the catalog meanwhile; add this one from Discovered GGUFs'
        try:
            self.catalog.upsert(self.catalog.entry_from_input(model))
        except Exception as e:  # noqa: BLE001 — the files are fine; say why the entry is not
            return f"downloaded, but not added to the catalog: {e}"
        return None

    async def _fetch(self, c: httpx.AsyncClient, job: Job, f: FileJob) -> None:
        if f.dest.exists() and f.dest.stat().st_size == f.size:
            f.done, f.state = f.size, "done"
            return
        f.state = "downloading"
        start = f.part.stat().st_size if f.part.exists() else 0
        if start > f.size:
            start = 0
        digest = hashlib.sha256() if f.sha256 else None
        if digest and start:
            await asyncio.to_thread(_hash_prefix, f.part, start, digest)
        f.done = start
        url = f"{HF}/{job.repo}/resolve/{quote(job.revision, safe='')}/{quote(f.path)}"
        headers = {"Range": f"bytes={start}-"} if start else {}
        async with c.stream("GET", url, headers=headers) as r:
            if r.status_code == 416 and start == f.size:
                pass  # the part is already whole
            elif r.status_code in (401, 403):
                raise LcppError("hf_gated", f"{job.repo} is gated: accept its license on huggingface.co, "
                                "then log in with `hf auth login`", 403)
            elif r.status_code >= 400:
                raise LcppError("hf_unreachable", f"{f.path}: Hugging Face answered {r.status_code}", 502)
            else:
                if r.status_code == 200 and start:  # server ignored Range: start over
                    start = f.done = 0
                    digest = hashlib.sha256() if f.sha256 else None
                f.created = f.created or not f.dest.exists()
                with open(f.part, "ab" if start else "wb") as out:
                    async for chunk in r.aiter_bytes(CHUNK):
                        await asyncio.to_thread(_write, out, chunk, digest)
                        f.done += len(chunk)
                        now = time.monotonic()
                        job.samples.append((now, job.done_bytes))
                        while len(job.samples) > 2 and now - job.samples[0][0] > 5:
                            job.samples.pop(0)
        size = f.part.stat().st_size
        if size != f.size:
            raise LcppError("daemon_error", f"{f.path}: got {size} of {f.size} bytes; retry to resume", 502)
        if digest:
            f.state = "verifying"
            if digest.hexdigest() != f.sha256:
                f.part.unlink(missing_ok=True)
                f.done = 0
                raise LcppError("daemon_error", f"{f.path}: checksum mismatch (the partial file was removed)", 502)
        os.replace(f.part, f.dest)
        f.created = True
        f.state = "done"

    # ---- manage --------------------------------------------------------
    def need(self, job_id: str) -> Job:
        job = self.jobs.get(job_id)
        if job is None:
            raise LcppError("download_not_found", f"Download {job_id} not found", 404)
        return job

    async def cancel(self, job_id: str) -> dict[str, Any]:
        """Stop a download and remove what it wrote (finished files it created too)."""
        job = self.need(job_id)
        if job.state not in ACTIVE:
            return self.view(job)
        if job.task:
            job.task.cancel()
            try:
                await job.task
            except asyncio.CancelledError:
                pass
        for f in job.files:
            f.part.unlink(missing_ok=True)
            if f.created:
                f.dest.unlink(missing_ok=True)
            f.done, f.state, f.created = 0, "queued", False
        job.state = "cancelled"
        return self.view(job)

    async def retry(self, job_id: str) -> dict[str, Any]:
        job = self.need(job_id)
        if job.state in ACTIVE:
            return self.view(job)
        if job.state == "done":
            raise LcppError("invalid_param", "That download already finished")
        job.state, job.error, job.warning, job.finished_ts = "queued", None, None, None
        for f in job.files:
            if f.state != "done":
                f.state = "queued"
        job.task = asyncio.create_task(self._run(job))
        return self.view(job)

    async def dismiss(self, job_id: str) -> None:
        job = self.need(job_id)
        if job.state in ACTIVE:
            await self.cancel(job_id)
        self.jobs.pop(job_id, None)

    def list(self) -> list[dict[str, Any]]:
        return [self.view(j) for j in sorted(self.jobs.values(), key=lambda j: j.created_ts, reverse=True)]

    def view(self, job: Job) -> dict[str, Any]:
        speed = job.speed()
        left = job.total_bytes - job.done_bytes
        return {
            "id": job.id, "repo": job.repo, "revision": job.revision, "label": job.label,
            "dir": self.paths.display(job.dest_dir), "state": job.state, "error": job.error,
            "warning": job.warning, "model_id": job.model["id"] if job.model else None,
            "bytes_total": job.total_bytes, "bytes_done": job.done_bytes,
            "speed_bps": round(speed), "eta_s": round(left / speed) if speed > 0 else None,
            "created_ts": job.created_ts, "finished_ts": job.finished_ts,
            "files": [{"path": f.path, "name": f.dest.name, "size_bytes": f.size, "done_bytes": f.done,
                       "state": f.state} for f in job.files],
        }

    async def close(self) -> None:
        """Daemon shutdown: stop tasks but keep ``.part`` files for a resume."""
        tasks = [j.task for j in self.jobs.values() if j.task and not j.task.done()]
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


def _write(out, chunk: bytes, digest) -> None:
    out.write(chunk)
    if digest is not None:
        digest.update(chunk)


def _hash_prefix(path: Path, length: int, digest) -> None:
    with open(path, "rb") as f:
        left = length
        while left > 0:
            b = f.read(min(CHUNK * 8, left))
            if not b:
                break
            digest.update(b)
            left -= len(b)
