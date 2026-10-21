"""Hidden outputs that pile up (plan 30.9): every page the agent reads is saved by the web mod as a hidden
output, so the reading tools and citations can open it later. `[outputs] hidden_keep_days` (config.toml)
moves hidden outputs older than that to the outputs trash, which is emptied after its own 30 days, so a
page stays recoverable for a while. `0` (the default) keeps them forever. The watcher's housekeeping runs
it at startup and every 6 hours, next to the trash purge.
"""

from __future__ import annotations

import asyncio
import logging
import time
from pathlib import PurePosixPath
from typing import TYPE_CHECKING

from utils.outputs import trash

if TYPE_CHECKING:
    from utils.outputs.index import Outputs

log = logging.getLogger("aihub.outputs")


async def expire_hidden(outs: Outputs, keep_days: float, now: float | None = None) -> int:
    """Move hidden outputs created more than `keep_days` ago to the trash. Returns how many went."""
    if keep_days <= 0:
        return 0
    cutoff = (time.time() if now is None else now) - keep_days * 86400
    gone: list[str] = []
    async with outs.lock:
        rows = await outs.db.fetchall("SELECT id, path, is_dir FROM outputs WHERE hidden = 1 AND created_ts < ?", (cutoff,))
        for r in rows:
            target, parts = outs.dir / r["path"], PurePosixPath(r["path"]).parts
            if len(parts) < 2 or ".." in parts or not target.resolve().is_relative_to(outs.dir.resolve()):
                continue    # a symlink out of outputs/: never touched (as a delete from the UI refuses it)
            try:
                if target.exists() or target.is_symlink():
                    await asyncio.to_thread(trash.move, outs.dir, r["path"], bool(r["is_dir"]))
            except OSError as e:
                log.warning("outputs: couldn't move %s to the trash: %s", r["path"], e)
                continue
            gone.append(r["id"])
        if gone:
            await outs.db.write(lambda c: outs._apply(c, [], gone))
    for oid in gone:
        outs.bus.publish({"type": "output_deleted", "id": oid})
    if gone:
        log.info("outputs: moved %d hidden outputs older than %g days to the trash", len(gone), keep_days)
        if outs.activity:
            await outs.activity.add(f"Moved {len(gone)} saved web page{'s' if len(gone) != 1 else ''} older than "
                                    f"{keep_days:g} days to the outputs trash", None, "info")
    return len(gone)
