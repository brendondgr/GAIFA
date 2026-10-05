"""The memory manager (architecture §7, plan Phase 5).

- `source.py`: where the numbers come from (`ProcSource`: /proc, the backend, systemd, podman)
- `planner.py`: the load rule as a pure function (`make_plan`, the brief's `MakeRoomPlan`)
- `manager.py`: `MemoryManager`: sampling, events, peaks, the alert, `ensure_room`, make-room, reservations
- `triggers.py`: the proxy hook for `[memory] triggers`
"""

from utils.memory.manager import MemoryManager
from utils.memory.planner import make_plan

__all__ = ["MemoryManager", "make_plan"]
