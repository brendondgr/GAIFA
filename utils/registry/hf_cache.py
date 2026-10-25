"""Deleting a Hugging Face cache repo (`hf-cache/hub/models--org--name`) the way `hf cache rm` does.

huggingface_hub 2.x keeps Xet downloads in a cache-wide store: a snapshot file links to
`models--org--name/blobs/<etag>`, which links to `hf-cache/hub/blobs/<xx>/<hash>`, and a
`<hash>.refs` manifest beside it lists every repo blob that links there. Another repo may
share the same payload, so it can only be freed once no manifest entry is left. The hub
never touches that store by hand: huggingface_hub's own cache API plans the deletion (the
whole repo, every revision) and then sweeps each shared blob, freeing it only when nothing
else refers to it. The older per-repo `blobs/` layout goes the same way.

It is a hub dependency rather than a call to a mod's `hf` CLI: the hub can't rely on a
mod's folder or venv (deleting a mod removes it completely). It is imported on the first
delete, not at import time.
"""

from __future__ import annotations

import dataclasses
import logging
import re
from pathlib import Path

log = logging.getLogger("gaifa.registry")

REPO_RE = re.compile(r"hf-cache/hub/models--[^/]+")


def is_repo(rel: str) -> bool:
    """Whether a registry path is a whole repo in the shared Hugging Face cache."""
    return REPO_RE.fullmatch(rel.rstrip("/")) is not None


def delete_repo(repo: Path) -> list[str] | None:
    """Delete one cached repo through huggingface_hub. Returns what failed, or None when
    huggingface_hub doesn't list the repo (no cache, or a repo it reports as corrupted), so
    the caller deletes the recorded files itself."""
    from huggingface_hub import CacheNotFound, scan_cache_dir

    repo = repo.resolve()
    try:
        info = scan_cache_dir(repo.parent)
    except (CacheNotFound, ValueError, OSError) as x:
        log.warning("hf-cache: couldn't scan %s: %s", repo.parent, x)
        return None
    cached = next((r for r in info.repos if r.repo_path.resolve() == repo), None)
    if cached is None or not cached.revisions:
        log.warning("hf-cache: %s isn't a valid cached repo; deleting its recorded files instead", repo.name)
        return None
    # Only this repo in the plan: delete_revisions matches commit hashes, which two repos may share.
    strategy = dataclasses.replace(info, repos=frozenset({cached})).delete_revisions(*(r.commit_hash for r in cached.revisions))
    try:
        strategy.execute()
    except OSError as x:
        return [f"{repo.name}: {x.strerror or x}"]
    log.info("hf-cache: deleted %s, freed %s", repo.name, strategy.expected_freed_size_str)
    return [f"{repo.name}: couldn't remove the folder"] if repo.exists() else []
