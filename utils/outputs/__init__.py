"""The outputs index (architecture §4.7, plan Phase 4): everything mods write to `outputs/`.

- `entries.py`: which files and folders are outputs (`walk`, `scope_for`)
- `describe.py`: one output → its `outputs` row (sidecar, title, kind, main file, media details)
- `media.py`: durations, sizes and previews (`wave`, Pillow, ffprobe/ffmpeg)
- `index.py`: `Outputs`, the table kept in step with the disk; list/get/delete/files
- `watch.py`: `Watcher`, live updates via `watchfiles`, the startup rescan, trash purging
- `trash.py`: deletes go to `outputs/.trash/<date>/`, purged after 30 days
- `announce.py`: batched activity items for new outputs
"""

from utils.outputs.entries import KINDS
from utils.outputs.index import OutputError, Outputs

__all__ = ["KINDS", "OutputError", "Outputs"]
