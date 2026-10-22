# Platforms: what AIHub runs on

AIHub was built on one machine (Fedora, AMD Strix Halo). Stage N (plan [plans/portability.md](plans/portability.md)) makes it run on others. This page records what's supported, what was tested where, and what isn't done.

## Targets

| System | GPUs | How | Checked |
| --- | --- | --- | --- |
| Linux (Fedora, Ubuntu, Arch, openSUSE) | AMD (ROCm, Vulkan), NVIDIA (CUDA, Vulkan), Intel (XPU, Vulkan), none (CPU) | systemd user services | this machine (AMD Strix Halo); others through the field test (plan 40.5) |
| Windows 11 through WSL2 (Ubuntu) | NVIDIA (CUDA), Intel (XPU); AMD only where ROCm on WSL supports the card, else CPU | WSL2 with systemd on | the field test (plan 40.6) |
| macOS on Apple Silicon | Apple GPU (MPS, Metal) | launchd agent, or `aihub start`; detached mods | CI only (no Mac to test on) |
| Native Windows | — | not built (below) | — |

`aihub hardware` shows what AIHub finds on a machine, and `aihub setup` picks each mod's variant from it (plan 38). The support matrix per mod is in [Mods by machine](#mods-by-machine).

## Mods by machine

Filled in by plan 40.4 from each setup doc's variants.

## Native Windows

Not planned (the user's answer, 2026-10-21): Windows users run AIHub in WSL2. This is what a native port would have to change, as the survey found it, so the work isn't lost:

- **Python environments:** venvs are `.venv\Scripts\python.exe`, not `.venv/bin/python`. That path is hard-coded in `utils/cli.py` (`cmd_doctor`), `utils/cli_setup.py`, `utils/cli_platform.py`, `bin/aihub` (a bash script) and every mod's `service.toml` (`command = [".venv/bin/python", …]`, starting with `services/_template/service.toml`).
- **Installers:** every setup step and `install.sh` is bash (`utils/cli_setup_run.py` `Runner.run` runs `bash -c`). Windows would need PowerShell versions, or steps written as Python. `services/tts/engines/install.ps1` is the only one that exists, and it was never run.
- **Supervising mods:** there are no process groups or `os.killpg` (`utils/backends/subprocess.py`, `detached.py`) and no SIGTERM, SIGCONT or SIGKILL semantics. A Windows backend would use job objects and `CTRL_BREAK_EVENT`.
- **The hub as a service:** there's no systemd or launchd. It would need a scheduled task at logon, or a Windows service.
- **Atomic replace over an open file** fails on Windows. Affected: `utils/logfiles.py` (`os.replace` while a reader has the log open), `utils/tools/results.py` (`Path.rename`) and `paths.write_atomic` when the target is open.
- **Sockets:** `SO_REUSEADDR` in `app.py` lets another process take the port on Windows; there it should be `SO_EXCLUSIVEADDRUSE`.
- **Paths:**
  - `utils/manifest.py` `resolve_arg` treats only a leading `/` as absolute, and `ModelsSpec` the same.
  - `utils/doctor.py` `PATHLIKE` splits values on `:` and only knows `/` and `~`, so `C:\…` is misread.
  - The registry compares folders with `startswith(folder + "/")`.
- **The judge:** `utils/tools/shell.py`, `judge_commands.py` and `judge_rules.py` parse POSIX shell. PowerShell or cmd commands would get no meaningful verdict, so a native workspace would need its own rules.
- **Dependencies:** `uvicorn[standard]` has no uvloop on Windows (it falls back to asyncio, which is fine). The containers in the workspace sandbox and the GPU mods would need Docker Desktop, whose GPU support covers only NVIDIA through WSL2 anyway.
- **What already works:** the hub's own code avoids `fcntl`, `fork` and `resource`. `os.getuid` is guarded (`utils/doctor.py`). Memory and process reads fall back to psutil (`utils/proc_portable.py`). `utils/hardware/` has no Windows reader yet (its `Machine.os` allows `windows`).
