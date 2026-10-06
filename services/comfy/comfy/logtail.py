"""Copy ComfyUI's log file (data/comfyui.log, written inside the toolbox) to this process's
stdout, so it shows in AIHub's Logs tab (journald) next to the adapter's own lines."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

PREFIX = "[comfyui] "


async def follow(path: Path, out=None, interval: float = 0.5, from_end: bool = True) -> None:
    """Print new lines as they're appended. A truncated or replaced file (each start empties it)
    is read again from the top."""
    out = out or sys.stdout
    pos, inode = None, None
    while True:
        try:
            st = path.stat()
            if inode != st.st_ino or pos is None or st.st_size < pos:
                pos = st.st_size if (pos is None and from_end) else 0
                inode = st.st_ino
            if st.st_size > pos:
                with path.open("rb") as f:
                    f.seek(pos)
                    chunk = f.read()
                end = chunk.rfind(b"\n") + 1          # only whole lines; the rest waits
                if end:
                    for line in chunk[:end].decode("utf-8", "replace").splitlines():
                        out.write(PREFIX + line + "\n")
                    out.flush()
                    pos += end
        except FileNotFoundError:
            pos = 0 if pos is not None else None
        await asyncio.sleep(interval)
