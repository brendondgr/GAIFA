# Plan: AIHub on other machines (NVIDIA, Intel, Apple; WSL2 and macOS)

Asked for on 2026-10-21: people with other hardware and other systems should be able to use AIHub, from NVIDIA to AMD to Intel GPUs, on Linux, macOS and Windows. Answers from the user the same day:
- **Windows** goes through WSL2 first; native Windows isn't planned.
- **Order:** this stage runs **after Phase 23** (the setup), and makes `aihub setup` choose backends.
- **Where the plan lives:** here, with one stage row in `backend-plan.md`.
- **Machines to check on:** **this one** (Linux, AMD Strix Halo), **a Linux machine with an NVIDIA GPU**, and **a Windows PC with an Intel GPU** (through WSL2). There is no Mac, so macOS is checked by CI only.

**Revised the same evening** (the user: "update the plans, then build everything; commit after each step with full checks"). Phase 23 had finished in the meantime, which changes several things here:
- `aihub setup` runs from a bare clone and is **standard library only**. `utils/hardware/` must be standard library only too, so the setup can detect the machine before the hub's dependencies exist. `psutil` stays in the hub's process reads.
- `config.toml` is each machine's own (gitignored), made from the tracked `config.example.toml`. New defaults go in the example.
- The setup block grew `[[config]]` and steps with `skip_if`, `optional` and `interactive`.
- gen3d is a base setup plus one setup per engine, and stt runs on the CPU unless the host has ROCm.

The user also asked for **field reports**: an agent builds AIHub on another machine, records every problem it meets, and writes a markdown file detailed enough that the fixes are simple edits when the file is fed back here (Phase 40, 40.1–40.3). The user runs those builds on the other machines later.

Today AIHub runs on one kind of machine. The surveys (2026-10-21) found:
- **The hub:**
  - **systemd:** the hub needs it for its own unit and for running mods (`utils/backends/systemd.py`). The subprocess backend is for tests and `--dev`, so its mods die with the hub.
  - **Memory:** it's read from `/proc` and **AMD's sysfs only** (`utils/proc.py`), as **one unified pool** (`utils/memory/manager.py`). On macOS `MemAvailable` reads as 0, so every load answers `needs_room`.
  - **An import-time call:** `utils/doctor.py` calls `os.getuid()` at import time.
  - **Host checks:** `aihub setup host` (`utils/cli_setup_host.py`) checks GTT kernel parameters, the IOMMU, the `video`/`render` groups and Fedora packages.
  - **The GPU queue** (`utils/gpu.py`) is vendor-neutral but has one slot.
- **The mods:**
  - **Tied to ROCm on gfx1151:** comfy, gen3d and vllm through kyuz0's images; tts through AMD wheel indexes; stt through a ROCm CTranslate2 wheel; embed and decide through the AMD nightly index, with a `--cpu` fallback.
  - **Device strings** are "cuda or cpu" everywhere. ROCm reports as `torch.cuda`, and gen3d hard-codes `"cuda"`.
  - **Containers** get the GPU through podman with `/dev/kfd` and `/dev/dri`.
  - **Already portable engines:** lcpp runs on Vulkan, and llama.cpp builds for every vendor and OS. ComfyUI, Kokoro, sentence-transformers and torch/transformers run everywhere. `services/tts/engines/probe.py` already detects NVIDIA, AMD, Apple and CPU and picks a torch index.
  - **Not portable:** vLLM needs Linux with CUDA or ROCm. CTranslate2 has no Metal backend. gen3d's SAM 3D needs CUDA-only extensions.
- **The setup schema:** `gpu` is a yes/no, every step is bash, and the docs' "What to look for" is about gfx1151.

The approach:
1. The hub learns what machine it is on (Phase 35).
2. It budgets memory in pools, so a card's own VRAM counts apart from RAM (Phase 36).
3. It runs without this machine's systemd, Fedora and AMD setup (Phase 37).
4. Mods declare **variants**, one per accelerator, and the setup picks the one that fits (Phase 38).
5. The mods are ported in order of how portable their engines are (Phase 39).
6. Field reports from other machines come back here, and a support matrix records what was tested (Phase 40).

**This machine must behave exactly as it does today** at every step. Its detection is recorded as a test fixture, and every step's tests include it.

Touches:
- architecture §2 (decisions: running mods, memory), §4.3–4.4 (manifest, placeholders, environment), §7 (memory manager, GPU queue), §9 (`config.toml`) and §12;
- brief §6/§11.7 (`/api/system`, `/api/memory`, `/api/gpu` shapes);
- `docs/mods.md` §9 and `docs/setup/`;
- Phase 23's setup block and wizard, and Phase 31's GPU queue.

## Gaps & unanswered questions

- **Native Windows.** *Answered:* not planned. Windows users run AIHub in WSL2 (Ubuntu), which is Linux with systemd; the browser on Windows reaches `127.0.0.1:7000` through WSL's localhost forwarding. 37.6 lists what native Windows would need, so it isn't lost.
- **macOS.** No Mac to test on. *Assumption:*
  - Apple Silicon only; Intel Macs aren't targeted.
  - The hub and the mods without GPU work are checked in CI.
  - A mod's `mps` variant ships `tested = false`, and the setup says "untested on this machine" before it installs one.
- **AMD on WSL2.** ROCm on WSL covers only some Radeon cards, and Vulkan on WSL2 goes through Mesa's D3D12 layer (dzn). *Assumption:* AMD on WSL2 gets the CPU variants, plus a `rocm` variant marked untested where a mod already has one.
- **Containers on NVIDIA.** *Assumption:* podman with the NVIDIA Container Toolkit's CDI (`--device nvidia.com/gpu=all`), and docker with `--gpus all`, both from the same helper. On WSL2, `/dev/dxg` and `/usr/lib/wsl` are mounted.
- **Partial offload on a discrete GPU** (llama.cpp's `-ngl`). *Assumption:* lcpp acquires both pools in one call (36.2), and its catalog's per-model `ngl` defaults to "all that fits".
- **Workflow packs and weights that differ per backend** (fp8, CUDA-only custom nodes). *Assumption:* a pack declares `requires = ["cuda"]` and similar in `workflow.toml`, and Phase 20's `x-options` hides packs that don't fit.
- **The launchd agent on macOS** would be written outside the project root. *Assumption* (decided while revising, so nothing is written outside the folder without asking): `aihub install` on macOS **prints** the plist and the `launchctl` command for the person to place, the way root fixes are printed. Until they do, the hub runs in the foreground.
- **Pushing the CI workflow** to GitHub is the user's call. *Assumption:* the workflow is committed and pushed with the next push the user asks for.
- **Field reports may contain private data** (paths, user names, tokens in the environment). *Assumption:* the report redacts known secret shapes (`hf_…`, `sk-…`, `ghp_…`, `*_TOKEN`/`*_KEY` values) and writes the home folder as `~`. It's written inside the project (`data/state/reports/`, gitignored) and goes nowhere by itself.
- **The NVIDIA box and the Intel PC.** Their details aren't known yet. *Assumption:* the user runs the field test there (40.5, 40.6), and each report's detection becomes a fixture when its fixes land.

## How to work this plan

The same rules as `backend-plan.md`: one commit per step after `uv run pytest` passes, `AIHub (<phase>.<step>): <sentence>`, with docs in the same commit and an *As built* note under the step. Tests that need Linux-only files are marked `linux` (`pyproject.toml` markers), like `systemd` today.

Fake hardware lives in `utils/tests/hardware/fixtures/<machine>/`. Each is a recorded tree: sysfs, `/proc` snippets, `nvidia-smi` output, `sysctl` output and WSL markers. There's one per machine: `strix-halo` (this one), `linux-nvidia-1gpu`, `linux-nvidia-2gpu`, `linux-intel-arc`, `wsl2-nvidia`, `wsl2-intel`, `macos-m3`, `linux-cpu`.

---

## Phase 35 — Know the machine: hardware detection (M)

- [ ] **35.1 `utils/hardware/`: what this machine has (standard library only).**
  - **Model:** `Machine {os: "linux"|"darwin", wsl: bool, distro, arch, cpu, ram_bytes, gpus: [Gpu], accels: [str]}`.
    - `Gpu {index, vendor: "amd"|"nvidia"|"intel"|"apple", name, arch (gfx1151, sm_89, xe2, m3), memory: "unified"|"dedicated", vram_bytes, driver, runtimes: {rocm?, cuda?, level_zero?, vulkan?, metal?}}`.
    - `accels` is the ordered list of what can run here, from `rocm`, `cuda`, `xpu`, `mps`, `vulkan` and `cpu`, best first; `cpu` is always last. Metal and SYCL aren't accels of their own: llama.cpp's Metal build is lcpp's `mps` variant, its SYCL build the `xpu` one.
    - `to_dict()` gives the JSON shape.
  - **Readers:** one file per source, each a pure function over a root path so fixtures can stand in.
    - `amd.py`: amdgpu sysfs, plus the KFD topology for the gfx id. The logic of `services/tts/engines/probe.py` is reimplemented here; the mod keeps its copy.
    - `nvidia.py`: `nvidia-smi --query-gpu=… --format=csv,noheader,nounits` through an injectable runner (no NVML binding: standard library only).
    - `intel.py`: i915/xe sysfs, and on WSL2 the Level Zero loader.
    - `apple.py`: `sysctl hw.memsize machdep.cpu.brand_string hw.optional.arm64`.
    - `wsl.py`: "microsoft" in `/proc/version`, `/dev/dxg`, `/usr/lib/wsl/lib`.
    - `osinfo.py`: `/etc/os-release` and `platform`.
  - **Calling it:** `detect(root="/", run=…)` is cached, and `refresh()` reads again. Nothing runs at import.
  - **Why:** every later step decides from `Machine`, never from probing `/dev/kfd` itself.
  *Done when:* `utils/tests/hardware/test_detect.py` gives the expected `Machine` for every fixture, and this machine's live `detect()` matches the `strix-halo` fixture's GPU and accels (marked `linux`).

- [ ] **35.2 Show it: `GET /api/system/hardware`, `aihub hardware`, Settings → About.**
  - The route returns `Machine`. `aihub hardware [--json]` prints it (standard library only, no hub needed), and `aihub doctor` adds a Hardware section.
  - Settings → About gets a Hardware card listing each GPU's vendor, arch, memory and runtimes, and the accelerators found (a `web/PATCHES.md` entry).
  - Brief §6/§11.7 gain the route and its type, and the contract test covers it. `AIHUB_HARDWARE_FIXTURE=<dir>` (dev only) makes the hub read a fixture instead of the machine.
  *Done when:* `utils/tests/hardware/test_routes_hardware.py` covers the route and the fixture override; `utils/tests/core/test_cli.py` covers `aihub hardware --json`; the card is checked in a browser on a `--demo-mods` hub with the `linux-nvidia-2gpu` fixture.

- [ ] **35.3 Process and memory reads without `/proc`: `utils/proc.py` split.**
  - **The Linux file:** `utils/proc_linux.py` keeps today's reads: PSS from `smaps_rollup`, DRM fdinfo, cgroups, `/proc/net/tcp`.
  - **The fallback:** `utils/proc_portable.py` uses `psutil` (a new hub dependency) for memory totals, RSS, the process tree, a port's owner and the command line.
  - **Choosing one:** `utils/proc.py` stays the facade, with the same function names. It picks the Linux file when `/proc/meminfo` is readable and the portable one otherwise. The hub's own RSS (`utils/routes/system.py`) goes through it.
  - **Fixed on the way:**
    - `utils/doctor.py` reads the uid lazily, so nothing runs at import (an invariant).
    - `paths.write_atomic` skips the directory fsync where the OS doesn't allow it.
  *Done when:* `utils/tests/memory/test_proc_portable.py` runs the portable reads on the real machine and agrees with the Linux ones within a sample's noise; the existing `/proc` tests pass unchanged.

**Checks & deliverables — Phase 35**
- [ ] On this machine, `aihub hardware` shows one AMD GPU, gfx1151, unified memory, and `rocm, vulkan, cpu`.
- [ ] Delivered: `utils/hardware/`, `utils/proc_linux.py`, `utils/proc_portable.py`, the route, the CLI command, the About card, the fixtures.

---

## Phase 36 — Memory in pools (M–L)

- [ ] **36.1 Pools: `utils/memory/pools.py`.**
  - **What a pool is:** `Pool {id: "system"|"gpu:<i>", total, used, available}`. A machine with unified memory (this one, Apple Silicon, an integrated Intel GPU) has **one pool**, `system`, and GPU use counts against it, as today. Each dedicated GPU adds a `gpu:<i>` pool.
  - **Sampling**, every 2 s as now:
    - **VRAM:** `nvidia-smi`, amdgpu `mem_info_vram_*` or xe/i915 sysfs.
    - **GPU memory per process:** `nvidia-smi --query-compute-apps` on native Linux, and DRM fdinfo for amdgpu and Intel.
    - **Where it can't be read** (WSL2, macOS): a process's GPU memory is **unknown**, and a mod's share comes from what it acquired (36.2) or its estimate.
  *Done when:* `utils/tests/memory/test_pools.py` builds the right pools for every fixture, with the `strix-halo` fixture giving exactly today's single-pool numbers.

- [ ] **36.2 Making room per pool: manifest, acquire, planner.**
  - **Manifest:** `[memory] estimate_gb` stays the system estimate, and `vram_gb` is added (`utils/manifest.py` `MemorySpec`). On a unified machine the two add up.
  - **Acquire:** `POST /api/memory/acquire` takes `{needs_bytes, vram_bytes?, device?}`.
  - **Planner:** `utils/memory/planner.py` covers each pool's gap. A candidate frees what it holds in each pool, and `409 needs_room` names the pool that's short.
  - **Peaks:** learned peaks are stored per pool. Existing rows are the `system` pool.
  - **Docs:** architecture §7, and brief §11.7 (`needs_room`'s `data.pool`).
  *Done when:* `utils/tests/memory/test_planner_pools.py` covers:
  - a VRAM gap freed by unloading a GPU mod while RAM is plentiful;
  - a RAM-only mod never unloaded for VRAM;
  - two GPUs;
  - the unified case unchanged.

  The existing memory tests pass unchanged.

- [ ] **36.3 Which GPU a mod uses: devices and the GPU queue.**
  - **Choosing a GPU:** `[services.<id>] gpu = "auto" | <index>`. With `auto`, the mod gets the GPU with the most free VRAM when it starts.
  - **The environment:** the hub sets `AIHUB_GPU_INDEX` plus the vendor's visible-devices variable (`CUDA_VISIBLE_DEVICES`, `HIP_VISIBLE_DEVICES`, or `ONEAPI_DEVICE_SELECTOR`), and only on machines with more than one GPU.
  - **The queue:** `utils/gpu.py` keeps **one slot per device**. On a single-GPU machine, nothing changes.
  - **Docs:** architecture §4.4 and §7, `config.example.toml`.
  *Done when:* `utils/tests/gpu/test_queue_devices.py` (two devices: two jobs at once, one per device; a nested lease stays on its parent's device) and the environment tests pass; the Phase 31 tests pass unchanged.

- [ ] **36.4 The API and UI per pool.**
  - **The API:** `GET /api/memory` gains `pools`, and the `Gpu` model gains `vendor`, `memory` and `index`. The AMD-only `gtt_*` fields stay for this release, so the UI and the contract keep working.
  - **Metrics:** for each dedicated pool, a `gpu.<i>.mem_used` series. This machine's series are unchanged.
  - **The UI:** the header's memory section and the Overview's memory widget show one bar per pool. On this machine that's one bar, as today (a `web/PATCHES.md` entry, brief §11.5).
  *Done when:* the contract test and `utils/tests/web/` pass; checked in a browser on a `--demo-mods` hub with the `linux-nvidia-2gpu` fixture (three bars) and on this machine (one bar, the same numbers as before).

**Checks & deliverables — Phase 36**
- [ ] On this machine: a load still makes room as before (one pool), and the GPU queue still serializes jobs.
- [ ] Delivered: `utils/memory/pools.py`, the planner and acquire changes, per-device queue slots, the per-pool UI.

---

## Phase 37 — Running without this machine's setup (M)

- [ ] **37.1 A supervisor that outlives the hub without systemd: `utils/backends/detached.py`.**
  - **Starting a mod:** in its own session, with its output appended to `data/logs/<id>.log`. A pidfile `data/state/hub/pids/<id>.json` holds `{pid, create_time, port, command_hash}`.
  - **After a hub restart:** a pidfile is adopted when the pid's start time and command still match; otherwise it's stale and is removed.
  - **Stopping:** SIGTERM to the process group, then SIGKILL after the timeout. `pids` walks the process tree.
  - **Choosing the backend:** `[hub] backend = "auto" | "systemd" | "detached" | "subprocess"` in `config.example.toml`. `auto` is systemd when available, else detached, and `--dev` stays subprocess (`utils/server.py` `default_backend`; architecture §2 and §5).
  *Done when:* `utils/tests/services/test_backend_detached.py` covers start, stop, a hub restart that adopts a running mod, a stale pidfile, a mod that ignores SIGTERM, and logs.

- [ ] **37.2 The CLI on every target: `utils/cli.py`.**
  - **`aihub open`** uses `webbrowser`. On WSL2 it opens the Windows browser (`wslview`, else `explorer.exe`).
  - **`aihub logs`** follows the file in Python instead of `tail -F`.
  - **`aihub install`:**
    - **Under WSL2:** it checks that systemd is on (`/etc/wsl.conf`) and prints the fix if it isn't.
    - **On macOS:** it prints the launchd plist and the `launchctl` command.
    - **Without systemd:** `start`, `stop` and `status` work through a pidfile for the hub itself.
  - **Docs:** `docs/setup/hub.md`.
  *Done when:* `utils/tests/core/test_cli.py` covers `open` (WSL and not), `logs`, `install` on WSL with systemd off, and the macOS plist.

- [ ] **37.3 Host checks per machine: `utils/cli_setup_gpu.py`, `utils/cli_setup_pkgs.py`.**
  - **The checks:** `utils/cli_setup_host.py` keeps `Probe`, `Check` and the common checks, and asks `cli_setup_gpu.py` for the GPU checks of the detected machine:
    - **AMD:** today's checks, unchanged.
    - **NVIDIA:** the driver answers `nvidia-smi`, and the NVIDIA Container Toolkit's CDI spec exists when a chosen mod uses containers.
    - **Intel:** the `render` group, and the compute runtime and Level Zero loader.
    - **WSL2:** systemd is on, the clone isn't under `/mnt/` (slow), and `/dev/dxg` exists.
    - **macOS:** Apple Silicon, and Homebrew.
  - **Packages:** they're printed for the detected package manager (`dnf`, `apt`, `zypper`, `pacman`, `brew`), from one table of package names per tool (`cli_setup_pkgs.py`).
  - **Kept from Phase 23:** fixes that need root are printed, never run.
  - **Docs:** the per-host docs (38.4).
  *Done when:* `utils/tests/core/test_setup_host.py` runs every fixture through the checks: the right ones apply, fixes are printed for the right package manager, and nothing runs as root; on this machine `aihub setup host` prints what it printed before.

- [ ] **37.4 The GPU in containers: `services/_template/containers.py`.**
  - A mod-side helper, copied into mods the way `gpu_slot.py` is. `gpu_args(machine, runtime)` returns the GPU flags:
    - **AMD:** `--device /dev/kfd --device /dev/dri --group-add keep-groups`.
    - **NVIDIA:** `--device nvidia.com/gpu=all` (podman CDI) or `--gpus all` (docker).
    - **Intel:** `--device /dev/dri`.
    - **WSL2:** `--device /dev/dxg -v /usr/lib/wsl:/usr/lib/wsl:ro`.
  - The mod reads the machine from `GET /api/system/hardware`.
  - **The runtime:** `[containers] runtime = "auto" | "podman" | "docker"`, passed to mods as `AIHUB_CONTAINER_RUNTIME`.
  - **Docs:** `docs/mods.md`, architecture §4.4.
  *Done when:* `services/_template/tests/test_containers.py` gives the right flags for every fixture and both runtimes.

- [ ] **37.5 CI: `.github/workflows/tests.yml`.**
  - `uv run pytest` runs on `ubuntu-latest` and `macos-latest`, with the `linux` and `systemd` tests skipped on macOS. The Node tests use plain `node`.
  *Done when:* the workflow file parses and the suite passes locally with `-m "not linux and not systemd"`; the jobs run on the user's next push.

- [ ] **37.6 What native Windows would need: `docs/platforms.md` §Windows.**
  - The list from the survey:
    - the `.venv\Scripts` layout;
    - PowerShell installers;
    - a supervisor without process groups;
    - renaming over a file that another process has open;
    - `SO_REUSEADDR`;
    - the `/`-only path checks in `utils/manifest.py` and `utils/doctor.py`;
    - the judge's POSIX-only shell rules;
    - no uvloop.
  *Done when:* the section exists and names files.

**Checks & deliverables — Phase 37**
- [ ] On this machine: `aihub status`, `aihub logs`, `aihub setup host` and every mod behave as before (systemd backend).
- [ ] On a second hub (port 7077) with `[hub] backend = "detached"`: mods start, survive a hub restart, and stop.
- [ ] Delivered: `utils/backends/detached.py`, the CLI changes, the host checks per machine, `services/_template/containers.py`, the CI workflow, `docs/platforms.md`.

---

## Phase 38 — Mods choose a backend (M)

- [ ] **38.1 Variants and smokes in the setup block, version 3: `utils/setupdocs/block.py`.**
  - **Variants:** a block may have `[[variants]]`:
    ```toml
    [[variants]]
    accel = "cuda"              # rocm | cuda | xpu | mps | vulkan | cpu
    os = ["linux", "wsl"]       # where it runs (linux | wsl | darwin)
    tested = true               # false: the setup warns before installing it
    env = { FOO = "1" }         # passed to the steps, the check and the mod (as [services.<id>.env])
    steps = [...]               # replaces the block's [[steps]] for this variant (optional)
    ```
  - **Defaults:** a block without variants is one variant: `cpu` if `gpu = false`, else this machine's accelerator. So version 2 docs keep working on this machine, and are "untested" elsewhere.
  - **Smokes:** `smoke` is a command that does real work (one image, one sentence spoken, one transcript). It runs with `aihub setup --smoke` and in the field test, never by default.
  - The mods index shows a "Runs on" column. **Docs:** `docs/mods.md` §9.
  *Done when:* `utils/tests/docs/test_setup_block.py` covers parsing, the defaults, bad accels and the smoke; `aihub docs --check --strict` is clean.

- [ ] **38.2 The setup picks a variant: `utils/cli_setup.py`.**
  - **Picking:** for each chosen setup, the first variant whose `accel` is in `Machine.accels` and whose `os` matches.
    - **None fits:** the setup is "not available on this machine" with the reason, and is left out like a declined one.
    - **Untested:** a variant with `tested = false` is named as untested in the plan.
  - **Overriding:** `--accel <setup>=<accel>` picks another (for example `stt=cpu`).
  - **Recording:** the choice goes to `[services.<mod>] accel` in `config.toml`, through the same careful edit as `[[config]]`. The plan's JSON includes it, and so do the steps' and the check's environment (`AIHUB_ACCEL`).
  - **Docs:** `docs/setup/README.md`, the `aihub-setup` skill.
  *Done when:* `utils/tests/core/test_cli_setup_variants.py` covers choosing per fixture, the override, an unavailable setup, an untested variant and the recorded choice; `aihub setup --plan --json` on this machine picks today's backends for every mod.

- [ ] **38.3 The hub passes the choice to the mod.**
  - **The environment:**
    - `AIHUB_ACCEL`: the chosen accel.
    - `AIHUB_DEVICE`: the torch device string (`cuda` for CUDA and ROCm, `xpu`, `mps` or `cpu`).
    - `AIHUB_GPU_ARCH`: the GPU's arch.
  - **The manifest:** it gains `[run.variants.<accel>] env = {…}`, merged over `[run] env` (`utils/manifest.py`; architecture §4.3–4.4).
  - **When the recorded accel isn't on this machine:** the mod shows **unavailable** with the reason, instead of failing to start. Brief §6/§11.7, the services list and the mod card show it, plus a small variant badge (a `web/PATCHES.md` entry).
  *Done when:* `utils/tests/services/test_variants.py` (the environment, the merge, the unavailable state) and the contract test pass; the badge is checked in a browser on a `--demo-mods` hub.

- [ ] **38.4 The template and the docs.**
  - **The template:** `services/_template/` gains `device.py` (`AIHUB_DEVICE`, falling back `cuda` → `xpu` → `mps` → `cpu`) and `torch_index.py` (accel and runtime → the PyTorch wheel index, the table from `services/tts/engines/probe.py`). Its `install.sh` takes `--accel`.
  - **The host docs:** `docs/setup/host.md` becomes an index of `host-linux-amd.md` (today's text), `host-linux-nvidia.md`, `host-linux-intel.md`, `host-wsl2.md` and `host-macos.md`.
  *Done when:* `aihub new demo` gives a mod whose `install.sh --accel cpu` and `aihub check demo` pass (in a test root); `aihub docs --check --strict` passes.

**Checks & deliverables — Phase 38**
- [ ] On this machine: every installed mod shows its variant badge, and nothing restarts differently.
- [ ] Delivered: setup block v3, the variant choice in `aihub setup`, `AIHUB_ACCEL`/`AIHUB_DEVICE`, the unavailable state, the template's helpers, the per-host docs.

---

## Phase 39 — The mods on other machines (L)

Each step:
- adds the mod's variants and a `smoke` to its setup docs;
- adds a lock or wheel index per variant where torch is involved;
- replaces hard-coded `"cuda"` and ROCm env with `AIHUB_DEVICE` and per-variant env;
- runs the mod's tests with fake hardware.

Variants not run on real hardware ship `tested = false`, until a field report (40.5, 40.6) says they work. The expected result:

| Mod | rocm | cuda | xpu / sycl | vulkan | mps / metal | cpu |
| --- | --- | --- | --- | --- | --- | --- |
| agent, relay, web, searxng, opencode, workspace | — | — | — | — | — | yes (no GPU) |
| lcpp | — | yes | sycl | yes (today) | metal | yes |
| embed, decide | yes (today) | yes | xpu | — | mps | yes |
| tts (Kokoro) | yes (today) | yes | xpu | — | mps | yes |
| tts (Breeze) | yes (today) | yes | — | — | — | slow |
| stt | yes (today) | yes | — | — | — | yes |
| comfy | yes (today, toolbox) | yes (native) | xpu (native) | — | mps (native) | slow |
| gen3d | yes (today) | yes | — | — | — | — |
| vllm | yes (parked) | yes | — | — | — | — |

- [ ] **39.1 The mods without GPU work: agent, relay, web, searxng, opencode, workspace.**
  - Their setup docs declare `os = ["linux", "wsl", "darwin"]`.
  - **The workspace sandbox:** `--userns=keep-id` and `--network=pasta` are used only with rootless podman on Linux; docker gets its own equivalents (`services/workspace/sandbox.py`).
  *Done when:* each mod's tests pass; `services/workspace/tests/` covers the flags per runtime.

- [ ] **39.2 lcpp: llama.cpp per accel.**
  - **The binary:** the setup step fetches ggml-org's release asset for the OS and accel when one exists (Vulkan and CPU on Linux, Metal on macOS). Otherwise it builds from source into `runtime/llama.cpp/bin/` with `-DGGML_CUDA=ON` or `-DGGML_SYCL=ON`.
  - **Instances:** they keep the systemd backend on Linux and WSL2, and use lcpp's subprocess backend on macOS.
  *Done when:* lcpp's tests pass; `aihub docs --check --strict` is clean; on this machine `aihub setup --plan lcpp` picks Vulkan.

- [ ] **39.3 embed and decide: torch per accel.**
  - **Wheels:** `cuda` (a cu12x index), `xpu`, `mps` and `cpu` next to today's ROCm lock.
  - **The device:** it comes from `AIHUB_DEVICE`, and `EMBED_DEVICE`/`DECIDE_DEVICE` gain `xpu` and `mps`. d3's ROCm fast path runs only when `AIHUB_ACCEL = rocm`.
  *Done when:* both mods' tests cover the device per accel with a fake torch.

- [ ] **39.4 tts: the multi-backend planner becomes the install.** `scripts/install-runtime.sh` takes `--accel` and follows `engines/probe.py`'s plan for indexes other than gfx1151's. Kokoro runs on every accel. Breeze has `rocm` (tested), `cuda` (untested) and `cpu` behind its flag.
  *Done when:* tts's tests cover the plan per accel; `install-runtime.sh --accel cpu --dry-run` prints a CPU-only plan.

- [ ] **39.5 stt: CTranslate2 per accel.**
  - **Variants:**
    - `cuda`: PyPI's wheel plus the cuBLAS/cuDNN pip packages.
    - `rocm`: today's overlay.
    - `cpu`: everywhere.
  - **Detection:** `stt/asr/acceleration.py` reads `AIHUB_ACCEL` first, before its own probe.
  *Done when:* stt's tests cover the device per accel.

- [ ] **39.6 comfy: a native ComfyUI next to the toolbox.**
  - **The native install:** `bin/comfyui` gains a native mode: a venv in `services/comfy/runtime/ComfyUI/` at a pinned commit, with torch per accel (`cuda`, `xpu`, `mps`, `cpu`).
  - **This machine:** the `rocm` variant is today's toolbox, unchanged.
  - **The workarounds:** the gfx1151 ones apply only when `AIHUB_GPU_ARCH = gfx1151`.
  - **Packs:** they gain an optional `requires`.
  *Done when:* comfy's tests cover the launch per mode, and `requires` filtering.

- [ ] **39.7 gen3d: a CUDA path for the workers.** A `cuda` variant runs the workers in a pinned PyTorch CUDA image, with real spconv, gsplat and kaolin instead of the shims. The workers take `AIHUB_DEVICE`; the ROCm environment is set only for `rocm`; the container flags come from 37.4's helper.
  *Done when:* gen3d's tests cover the worker command per accel.

- [ ] **39.8 vllm: a CUDA image (parked mod; declaration only).** A `cuda` variant uses `vllm/vllm-openai`, with the attention backends per accel and 37.4's flags.
  *Done when:* vllm's tests cover the container command per accel.

**Checks & deliverables — Phase 39**
- [ ] On this machine: every mod still runs its ROCm or Vulkan variant, and the smokes that fit pass.
- [ ] Delivered: the variants, smokes and setup docs for every mod; the native ComfyUI path; gen3d's CUDA path.

---

## Phase 40 — Field reports and the support matrix (M)

The user builds AIHub on the other machines later, with an agent. The agent follows a procedure, records every problem as it goes, and ends with one markdown file, written for a fixer working in this repo. That file says which file and line to change, with the exact command, output and versions behind each issue.

- [ ] **40.1 The setup keeps what it saw: full logs and the saved report.**
  - **Full logs:** `aihub setup` writes each step's, check's and smoke's full output to `data/state/setup/logs/<step-id>.log` (capped at 2 MB each), alongside the 4000-character tail it keeps today (`utils/cli_setup_run.py` `Runner.run`).
  - **The saved report:** every run saves its report, the plan and the chosen variants to `data/state/setup/last-run.json`, whether it ended done, failed or stopped.
  - **Where each failure comes from:** a failure item gains `log` (its log file) and `source`, the setup doc's path and the line of its step, read when the doc is parsed (`utils/setupdocs/envs.py`).
  *Done when:* `utils/tests/core/test_cli_setup.py` covers a failed step's log file, `source` line and the saved report.

- [ ] **40.2 `aihub report`: the field report (`utils/cli_report.py`, standard library only).**
  - **Notes:** `aihub report note "<what happened>" [--cmd "<command>"] [--output <file>] [--setup <id>] [--severity blocker|major|minor] [--tried "<what was tried>"]` appends an observation to `data/state/reports/notes.jsonl`.
  - **The report:** `aihub report [--out <file>]` writes `data/state/reports/<date>-<host>.md` (and `.json`). In order:
    1. **Summary:** counts by severity, and the stages that passed.
    2. **Machine:** `aihub hardware --json`, the OS, kernel, Python, uv, podman and docker versions, driver versions, WSL.
    3. **AIHub:** the commit, and `git status` and `git diff` of any local changes the agent made.
    4. **Host checks:** the failed ones, with their fixes.
    5. **The setup run:** the plan, the chosen variants and the last report.
    6. **Issues:** one section per failure and per note, with:
       - an id;
       - where (the setup, the step, `source`: doc path and line, the files the step runs);
       - the command and its working folder;
       - the environment (`AIHUB_*`);
       - the exit code;
       - the log's last 120 lines, plus its path;
       - a **likely cause**, from a table of known patterns (a missing wheel for the index, a CUDA/driver mismatch, a missing shared library, a permission on `/dev/*`, command not found, a port in use, out of memory, a container toolkit missing, a network failure);
       - what the agent tried.
    7. **Mods:** each mod's state, `aihub check <id>`'s output for the failing ones, and the last 80 lines of their logs.
    8. **The doctor's output.**
    9. **For the fixer:** how to reproduce each issue, and the files most likely to change.
  - **Redaction:** tokens and keys are redacted (`hf_…`, `sk-…`, `ghp_…`, values of `*_TOKEN`, `*_KEY`, `*_SECRET`), and the home folder is written as `~`.
  *Done when:* `utils/tests/core/test_cli_report.py` builds a report from a fake failed run, notes and fake hardware: every section is present, the patterns classify sample outputs, secrets are redacted, and the markdown is stable for a fixed input.

- [ ] **40.3 The field test, for an agent on another machine.**
  - **The skill:** `.claude/skills/aihub-field-test/SKILL.md`, plus a "Testing on another machine" section in `AGENTS.md` for other agents:
    1. Record the machine (`aihub hardware`).
    2. Ask the person which mods to try, by default all that are available.
    3. Show `aihub setup --plan`.
    4. Run it with `--smoke`.
    5. On each failure, read its doc's What to look for, try the documented fixes within a time limit, and record each attempt with `aihub report note`. Change no tracked file unless asked; if a local workaround is needed to go on, the report's `git diff` keeps it.
    6. Run `aihub doctor`.
    7. Write `aihub report` and give the person its path.
  - **Docs:** `docs/setup/README.md` (a short section).
  *Done when:* a dry run on this machine (with a mod made to fail on purpose, in a test root) produces a report whose issue names the doc line, the command and a likely cause.

- [ ] **40.4 The support matrix: `docs/platforms.md`.**
  - It lists, for each OS and accelerator, whether a mod is tested (where and when), CI only, or untested, from the variants' `tested` flags. `aihub docs` generates the table into it.
  - The README's and `docs/setup/README.md`'s "macOS and Windows aren't supported" become a pointer to the matrix, and CLAUDE.md's status line is updated.
  *Done when:* `aihub docs --check` passes, and the matrix agrees with every variant's `tested` flag.

- [ ] **40.5 Linux with NVIDIA: the field test** (the user, later). The report comes back here; its fixes land as follow-up steps, and passing variants flip to `tested = true`.

- [ ] **40.6 Windows 11, WSL2 and an Intel GPU: the field test** (the user, later). As 40.5.

**Checks & deliverables — Phase 40**
- [ ] On this machine, `aihub setup --plan` and `aihub report` work end to end, and the report reads cleanly.
- [ ] Delivered: full setup logs and the saved run, `aihub report`, the field-test skill, `docs/platforms.md`.

---

## Deliverables

| Deliverable | Description | Location |
| --- | --- | --- |
| Hardware detection | what the machine has: OS, WSL, GPUs, memory kind, runtimes, accels (standard library only) | `utils/hardware/` |
| Portable process reads | a psutil fallback next to the Linux `/proc` reads | `utils/proc_linux.py`, `utils/proc_portable.py` |
| Memory pools | system RAM and each dedicated GPU's VRAM as separate budgets | `utils/memory/pools.py`, `planner.py` |
| Per-device GPU queue | one slot per GPU | `utils/gpu.py` |
| Detached backend | mods that outlive the hub without systemd | `utils/backends/detached.py` |
| Host checks | per vendor and OS, fixes printed per package manager | `utils/cli_setup_gpu.py`, `utils/cli_setup_pkgs.py` |
| Container GPU flags | per vendor and runtime, for mods | `services/_template/containers.py` |
| Variants and smokes | setup block v3, the choice in `aihub setup`, `AIHUB_ACCEL`/`AIHUB_DEVICE` | `utils/setupdocs/block.py`, `utils/cli_setup.py`, `utils/manifest.py` |
| Template helpers | the torch device and the wheel index per accel | `services/_template/device.py`, `torch_index.py` |
| Per-host docs | AMD, NVIDIA, Intel, WSL2, macOS | `docs/setup/host-*.md` |
| Field reports | full setup logs, notes, a detailed markdown report for the fixer; the agent's procedure | `utils/cli_report.py`, `.claude/skills/aihub-field-test/` |
| Support matrix | what runs where, and what was tested | `docs/platforms.md` |
| CI | Linux and macOS test jobs | `.github/workflows/tests.yml` |
| Tests | hardware fixtures per machine; detection, pools, devices, backends, variants, host checks, reports | `utils/tests/hardware/`, `utils/tests/memory/`, `utils/tests/gpu/`, `utils/tests/services/`, `utils/tests/core/`, each mod's `tests/` |
