"""`gaifa hardware` (plan 35.2): what this machine has, without the hub. Standard library only.

`--snapshot <file>` writes the recording detection read (a fixture, or part of a field report);
`--from <file>` replays one, so another machine's detection can be read here.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

if __package__:
    from utils import hardware
else:                    # loaded by bin/gaifa's cli.py as a script: utils/ itself is on sys.path
    import hardware  # type: ignore[no-redef]

GIB = 2**30


def summary(m: hardware.Machine) -> list[str]:
    os_ = m.distro.get("name") or m.os
    lines = [f"Machine   {os_}{' (WSL2)' if m.wsl else ''} · kernel {m.kernel} · {m.arch} · {m.cpus} CPUs · {m.ram_bytes / GIB:.1f} GiB"
             + (f" · package manager {m.pkg}" if m.pkg else "") + (f" · inside {m.container}" if m.container else "")]
    if m.cpu:
        lines.append(f"CPU       {m.cpu}")
    for g in m.gpus:
        mem = {"unified": f"unified, up to {g.vram_bytes / GIB:.1f} GiB", "dedicated": f"{g.vram_bytes / GIB:.1f} GiB VRAM" if g.vram_bytes else "its own VRAM (size unknown)"}.get(g.memory, "memory unknown")
        rt = ", ".join(k + ("" if v == "yes" else " " + v) for k, v in g.runtimes.items())
        lines.append(f"GPU {g.index}     {g.name}{f' ({g.arch})' if g.arch else ''} · {mem}" + (f" · {g.driver}" if g.driver else "") + (f" · {rt}" if rt else ""))
        lines.append(f"          runs: {', '.join(g.accels) or 'nothing GAIFA can use yet'}")
        lines += [f"          problem: {p}" for p in g.problems]
    if not m.gpus:
        lines.append("GPU       none found: everything runs on the CPU")
    lines.append(f"Accels    {', '.join(m.accels)}")
    return lines


def cmd_hardware(args: argparse.Namespace) -> int:
    if args.from_file:
        m = hardware.from_snapshot(json.loads(Path(args.from_file).read_text()))
    elif args.snapshot:
        m, data = hardware.record()
        text = json.dumps(data, indent=1, sort_keys=True) + "\n"
        if args.snapshot == "-":
            print(text, end="")
            return 0
        Path(args.snapshot).write_text(text)
    else:
        m = hardware.detect()
    if args.json:
        print(json.dumps(m.to_dict(), indent=1))
    else:
        print("\n".join(summary(m)))
        if args.snapshot:
            print(f"\nsnapshot written to {args.snapshot}")
    return 0


def add_parser(sub: Any) -> None:
    p = sub.add_parser("hardware", help="what this machine has: OS, GPUs, memory, runtimes, and the accelerators GAIFA can use")
    p.add_argument("--json", action="store_true", help="the same as GET /api/system/hardware")
    p.add_argument("--snapshot", metavar="FILE", help="also write everything detection read, to replay elsewhere ('-' prints it instead)")
    p.add_argument("--from", dest="from_file", metavar="FILE", help="replay a snapshot instead of reading this machine")
    p.set_defaults(fn=cmd_hardware)
