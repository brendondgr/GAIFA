# Plan: AIHub on other machines (NVIDIA, Intel, Apple; WSL2 and macOS)

Asked for on 2026-10-21: people with other hardware and other systems should be able to use AIHub, from NVIDIA to AMD to Intel GPUs, on Linux, macOS and Windows. Answers from the user the same day: **Windows through WSL2 first** (native Windows isn't planned); this stage runs **after Phase 23** (the setup), and makes `aihub setup` choose backends; the plan lives here, with one stage row in `backend-plan.md`. Machines to check on: **this one** (Linux, AMD Strix Halo), **a Linux machine with an NVIDIA GPU** (now), **a Windows PC with an Intel GPU** (later, through WSL2). There is no Mac: macOS is checked by CI only.

Today AIHub runs on one kind of machine. The surveys (2026-10-21) found:
- **The hub** needs systemd for its own unit and for running mods (`utils/backends/systemd.py`; the subprocess backend is for tests and `--dev`: mods die with the hub). Memory is read from `/proc` and **AMD's sysfs only** (`utils/proc.py:57-100`), as **one unified pool** (`utils/memory/manager.py:238`). On macOS `MemAvailable` reads as 0, so every load answers `needs_room`. `utils/doctor.py:35` calls `os.getuid()` at import time. `aihub setup host` (`utils/cli_setup_host.py`) checks Fedora, GTT kernel parameters, the IOMMU and the `video`/`render` groups. The GPU queue (`utils/gpu.py`) is vendor-neutral but has one slot.
- **The mods:**
  - **Tied to ROCm on gfx1151:** comfy, gen3d and vllm through kyuz0's images; tts and stt through AMD wheel indexes and a ROCm CTranslate2 wheel; embed and decide through the AMD nightly index with a `--cpu` fallback.
  - **Device strings:** they are "cuda or cpu" everywhere. ROCm reports as `torch.cuda`, and gen3d hard-codes `"cuda"`.
  - **Container GPU flags:** podman gets `/dev/kfd` and `/dev/dri` (comfy, gen3d, vllm).
  - **Already portable:**
    - lcpp runs on Vulkan, and llama.cpp builds for every vendor and OS.
    - ComfyUI, Kokoro, sentence-transformers and torch/transformers run everywhere.
    - `services/tts/engines/probe.py` already detects NVIDIA, AMD, Apple and CPU and picks a torch index.
  - **Not portable:** vLLM is Linux with CUDA or ROCm. CTranslate2 has no Metal. gen3d's SAM 3D needs CUDA-only extensions (spconv, gsplat, kaolin).
- **The setup schema:** `gpu` is a yes/no field (`utils/setupdocs/block.py:44`), every step is bash, and the docs' "What to look for" is about gfx1151.

The approach:
1. The hub learns what machine it is on (Phase 35).
2. It budgets memory in pools, so a card with its own VRAM counts separately from RAM (Phase 36).
3. It runs without this machine's systemd, Fedora and AMD setup (Phase 37).
4. Mods declare **variants**, one per accelerator, and the setup picks the one that fits (Phase 38).
5. The mods are ported in order of how portable their engines are (Phase 39).
6. Each target machine is checked for real (Phase 40).

**This machine must behave exactly as it does today** at every step. Its detection is recorded as a test fixture, and every step's tests include it.

Touches: architecture §2 (decisions: running mods, memory), §4.3–4.4 (manifest, placeholders, environment), §7 (memory manager, GPU queue), §9 (`config.toml`), §12; brief §6/§11.7 (`/api/system`, `/api/memory`, `/api/gpu` shapes); `docs/mods.md` §9; `docs/setup/`; Phase 23's setup block and wizard; Phase 31's GPU queue.

## Gaps & unanswered questions

- **Native Windows.** *Answered:* not planned. Windows users run AIHub in WSL2 (Ubuntu), which is Linux with systemd; the browser on Windows reaches `127.0.0.1:7000` through WSL's localhost forwarding. A native-Windows stage can be planned later; the Windows-specific code this plan avoids (PowerShell installers, a Windows supervisor, `.venv\Scripts`) is listed in 37.6 so it isn't lost.
- **macOS.** No Mac to test on. *Assumption:* Apple Silicon only. The hub and the no-GPU mods are checked in CI. A mod's `mps` or `metal` variant ships marked `tested = false`, and the setup says "untested on this machine" before it installs one. Intel Macs aren't targeted.
- **AMD on WSL2.** ROCm on WSL supports only some Radeon cards, and Vulkan on WSL2 goes through Mesa's D3D12 layer (dzn), which is slow and incomplete. *Assumption:* AMD on WSL2 gets the CPU variants, plus a `rocm` variant marked untested where a mod already has one.
- **Containers on NVIDIA.** *Assumption:* podman with the NVIDIA Container Toolkit's CDI (`--device nvidia.com/gpu=all`), and docker with `--gpus all` supported by the same helper. On WSL2, `/dev/dxg` and `/usr/lib/wsl` are mounted.
- **Partial offload on a discrete GPU.** On a card with its own VRAM, llama.cpp splits a model between VRAM and RAM (`-ngl`). *Assumption:* lcpp acquires both pools in one call (36.2), and its catalog gains a per-model `ngl` that defaults to "all that fits".
- **Workflow packs and weights that differ per backend** (fp8 runs on CUDA but not on gfx1151; some custom nodes need CUDA). *Assumption:* a pack declares `requires = ["cuda"]` and similar in `workflow.toml`. Phase 20's `x-options` hides packs that don't fit, as it already does for engines.
- **Files written outside the project root on macOS.** The launchd agent `~/Library/LaunchAgents/com.aihub.hub.plist` does the job of the systemd unit, so it would join the 12.4 allowlist. **Needs a human answer** before 37.2 is built. Until then, macOS runs the hub in the foreground (`uv run python app.py`).
- **The NVIDIA box.** Its GPU, VRAM, distro and driver aren't known yet, and the user approves the clone and install there. *Assumption:* asked at the start of 40.1. Its detection is recorded as a fixture then.
- **The Intel GPU on the Windows PC** (an Arc card or an integrated GPU). It decides between one pool and two. *Assumption:* detection handles both, and 40.2 records which one it is.

## How to work this plan

The same rules as `backend-plan.md`: one commit per step after `uv run pytest` passes, `AIHub (<phase>.<step>): <sentence>`, docs in the same commit. Tests that need Linux-only files are marked `linux` (`pyproject.toml` markers), like `systemd` today. Fake hardware lives in `utils/tests/hardware/fixtures/<machine>/` as recorded trees: sysfs, `/proc` snippets, `nvidia-smi` and NVML output, `sysctl` output, WSL markers. There is one fixture per machine: `strix-halo` (this one), `linux-nvidia-1gpu`, `linux-nvidia-2gpu`, `linux-intel-arc`, `wsl2-nvidia`, `wsl2-intel`, `macos-m3`, `linux-cpu`.

---

## Phase 35 — Know the machine: hardware detection (M)

- [ ] **35.1 `utils/hardware/`: what this machine has.**
  - **Model:** `Machine {os: "linux"|"darwin", wsl: bool, arch, cpu, ram_bytes, gpus: [Gpu], accels: [str]}`. Each `Gpu` is `{index, vendor: "amd"|"nvidia"|"intel"|"apple", name, arch (gfx1151, sm_89, xe2, m3), memory: "unified"|"dedicated", vram_bytes, driver, runtimes: {rocm?, cuda?, level_zero?, vulkan?, metal?}}`. `accels` is the ordered list of what can run here, from `rocm`, `cuda`, `xpu`, `vulkan`, `mps` and `cpu`. `cpu` is always last.
  - **Readers:** one file per source, each a pure function over a root path so fixtures can stand in:
    - `amd.py`: amdgpu sysfs, plus the KFD topology for the gfx id (the logic of `services/tts/engines/probe.py` moves here; the mod keeps its copy, since mods don't import the hub).
    - `nvidia.py`: NVML through an optional `nvidia-ml-py` import, else `nvidia-smi --query-gpu=… --format=csv`.
    - `intel.py`: i915/xe sysfs; on WSL2, `/dev/dxg` and the Level Zero loader.
    - `apple.py`: `sysctl hw.memsize machdep.cpu.brand_string`.
    - `wsl.py`: `/proc/version` contains "microsoft", `/dev/dxg`, `/usr/lib/wsl/lib`.
  - **Calling it:** `detect(root="/")` is cached, and `refresh()` reads again. Nothing runs at import.
  - **Why:** every later step decides from `Machine`, never from probing `/dev/kfd` itself.
  *Done when:* `utils/tests/hardware/test_detect.py` gives the expected `Machine` for every fixture, and this machine's live `detect()` equals the `strix-halo` fixture (marked `linux`).

- [ ] **35.2 Show it: `GET /api/system/hardware`, `aihub hardware`, Settings → About.**
  - The route returns `Machine`. `aihub hardware [--json]` prints it, and `aihub doctor` adds a Hardware section. Settings → About gets a Hardware card listing each GPU's vendor, arch, memory, runtimes and the accelerators found (`web/PATCHES.md` entry).
  - Brief §6/§11.7 gain the route and its type. The contract test covers it.
  *Done when:* `utils/tests/hardware/test_routes_hardware.py` covers the route; `utils/tests/core/test_cli.py` covers `aihub hardware --json`; the card is checked in a browser on a `--demo-mods` hub with the `linux-nvidia-2gpu` fixture (`AIHUB_HARDWARE_FIXTURE`, dev only).

- [ ] **35.3 Process and memory reads without `/proc`: `utils/proc.py` split.**
  - **The Linux file:** `utils/proc_linux.py` keeps today's reads: PSS from `smaps_rollup`, DRM fdinfo, cgroups, `/proc/net/tcp`.
  - **The fallback:** `utils/proc_portable.py` uses `psutil` (a new hub dependency) for memory totals, RSS, the process tree, a port's owner and the command line.
  - **Choosing one:** `utils/proc.py` stays the facade, with the same function names. It picks the Linux file when `/proc` is present and the portable one otherwise. The hub's own RSS (`utils/routes/system.py:40`) goes through it.
  - **Bugs fixed on the way:**
    - `utils/doctor.py:35` reads the uid lazily, so there's no work at import (an invariant).
    - `paths.write_atomic` skips the directory fsync where the OS doesn't allow it.
  *Done when:* `utils/tests/memory/test_proc.py` runs both implementations, with the portable one on the real machine and the Linux one on fixtures; the suite passes on macOS in CI (37.5); this machine's `/api/memory` numbers match before and after within a sample's noise.

**Checks & deliverables — Phase 35**
- [ ] On this machine, `aihub hardware` shows one AMD GPU, gfx1151, unified memory, and `rocm, vulkan, cpu`.
- [ ] Delivered: `utils/hardware/`, `utils/proc_linux.py`, `utils/proc_portable.py`, the route, the CLI command, the About card, the fixtures.

---

## Phase 36 — Memory in pools (M–L)

- [ ] **36.1 Pools: `utils/memory/pools.py`.**
  - **What a pool is:** `Pool {id: "system"|"gpu:<i>", total, used, available, unified_with?}`. A machine with unified memory (this one, Apple Silicon, an integrated Intel GPU) has **one pool**, `system`, and GPU use counts against it, as today. Each dedicated GPU adds a `gpu:<i>` pool.
  - **Sampling**, through `utils/hardware` readers, every 2 s as now:
    - **VRAM totals and use:** NVML, amdgpu `mem_info_vram_*` or xe/i915 sysfs.
    - **GPU memory per process:** the NVML process list on native Linux; DRM fdinfo for amdgpu and Intel. On WSL2 and macOS a process's GPU memory isn't readable, so it's **unknown**. A mod's share then comes from what it acquired (36.2), or its estimate.
  *Done when:* `utils/tests/memory/test_pools.py` builds the right pools for every fixture, with the `strix-halo` fixture giving exactly today's single-pool numbers.

- [ ] **36.2 Making room per pool: manifest, acquire, planner.**
  - **Manifest:** `[memory] estimate_gb` stays the system estimate, and `vram_gb` is added (`utils/manifest.py` `MemorySpec`). On a unified machine the two add up.
  - **Acquire:** `POST /api/memory/acquire` takes `{needs_bytes, vram_bytes?, device?}`.
  - **Planner:** `utils/memory/planner.py` covers each pool's gap. A candidate frees what it holds in each pool. `409 needs_room` names the pool that's short ("needs 6 GB more on GPU 0").
  - **Peaks:** learned peaks are stored per pool, through a `hub.db` migration whose existing rows become `system`.
  - **Docs:** architecture §7; brief §11.7 (`needs_room`'s `data.pool`).
  *Done when:* `utils/tests/memory/test_planner_pools.py` covers:
  - a VRAM gap freed by unloading a GPU mod while RAM is plentiful;
  - a RAM-only mod that never gets unloaded for VRAM;
  - two GPUs;
  - the unified case unchanged.

  The existing memory tests pass unchanged.

- [ ] **36.3 Which GPU a mod uses: devices and the GPU queue.**
  - **Choosing a GPU:** `config.toml [services.<id>] gpu = "auto" | <index>`. With `auto`, the mod gets the GPU with the most free VRAM when it loads.
  - **The environment:** the hub sets `AIHUB_GPU_INDEX` plus the vendor's visible-devices variable: `CUDA_VISIBLE_DEVICES`, `HIP_VISIBLE_DEVICES`, or `ONEAPI_DEVICE_SELECTOR`/`ZE_AFFINITY_MASK`.
  - **The queue:** `utils/gpu.py` keeps **one slot per device**, keyed by `device`. The leases, classes and groups work as in Phase 31. On a single-GPU machine, nothing changes.
  - **Docs:** architecture §4.4 (environment), §7 (the GPU queue), §9.
  *Done when:* `utils/tests/gpu/test_queue_devices.py` (two devices: two jobs run at once, one per device; a nested lease stays on its parent's device) and `utils/tests/services/test_env.py` (the visible-devices variable per vendor) pass; the Phase 31 tests pass unchanged.

- [ ] **36.4 The API and UI per pool.**
  - **The API:** `Gpu` in `utils/api_models.py` becomes vendor-neutral: `{index, vendor, name, memory: "unified"|"dedicated", total, used}`. The AMD-only `gtt_*` fields go away, and the UI (`web/api.js`) and the contract test change in the same step.
  - **Metrics:** the series become `gpu.<i>.mem_used`. A `hub.db` migration renames this machine's `gpu.gtt_used` history to `gpu.0.mem_used`, so its charts keep their history.
  - **The UI:** the header's memory section and the Overview's memory widget show one bar per pool. On this machine that's one bar, as today. A `web/PATCHES.md` entry and brief §11.5 cover the change.
  *Done when:* the contract test and `utils/tests/web/` pass; checked in a browser on a `--demo-mods` hub with the `linux-nvidia-2gpu` fixture (three bars) and on this machine (one bar, the same numbers as before).

**Checks & deliverables — Phase 36**
- [ ] On this machine: a comfy load still makes room as before (one pool), and the GPU queue still serializes jobs.
- [ ] Delivered: `utils/memory/pools.py`, the planner and acquire changes, per-device queue slots, the migrated metrics, the per-pool UI.

---

## Phase 37 — Running without this machine's setup (M)

- [ ] **37.1 A supervisor that outlives the hub without systemd: `utils/backends/detached.py`.**
  - **Starting a mod:** in its own session, with its output appended to `data/logs/<id>.log` (the shipper already reads it). A pidfile `data/state/hub/pids/<id>.json` holds `{pid, create_time, port, command_hash}`.
  - **After a hub restart:** a pidfile is adopted when the pid's create time and command still match; otherwise it's stale and is removed.
  - **Stopping, pids and logs:** stop sends SIGTERM to the process group, then SIGKILL after `timeout`. `pids` uses psutil's process tree. `logs` and `follow` read the file.
  - **Choosing the backend:** `config.toml [hub] backend = "auto" | "systemd" | "detached" | "subprocess"`. `auto` is systemd when available, else detached, and `--dev` stays subprocess (`utils/server.py` `default_backend`; architecture §2 and §5).
  *Done when:* `utils/tests/services/test_backend_detached.py` covers start, stop, a hub restart that adopts a running mod, a stale pidfile, a mod that ignores SIGTERM, and logs; the fake-mod suite runs under `detached` too.

- [ ] **37.2 The CLI on every target: `utils/cli.py`.**
  - **Opening and logs:**
    - `aihub open` uses `webbrowser`. On WSL2 it opens the Windows browser (`wslview`, else `explorer.exe`).
    - `aihub logs` follows the file in Python instead of `tail -F`.
  - **Installing the hub as a service:**
    - **systemd:** as today. On WSL2, `aihub install` first checks that systemd is on (`/etc/wsl.conf [boot] systemd=true`) and prints the fix if it isn't.
    - **launchd on macOS:** behind the answer to the launchd gap; until then, macOS runs the hub in the foreground.
  - **`start`, `stop` and `status` without a unit:** they work through the detached backend's pidfile for the hub itself.
  - **Docs:** `docs/setup/hub.md`.
  *Done when:* `utils/tests/core/test_cli.py` covers `open` (WSL and not), `logs`, and `install` on WSL with systemd off; the macOS CI job runs `aihub status` against a foreground hub.

- [ ] **37.3 Host checks per machine: `utils/setup_host/`.**
  - **Layout:** `utils/cli_setup_host.py` becomes a package with one file per kind of host, each a list of `Check {id, applies(machine), run(), fix}`:
    - `linux_amd.py`: today's checks, unchanged.
    - `linux_nvidia.py`: the driver loads; NVML answers; the CUDA runtime the variants need is new enough for the driver; the NVIDIA Container Toolkit's CDI spec exists when a chosen mod uses containers.
    - `linux_intel.py`: the `render` group; the compute runtime and Level Zero loader.
    - `wsl.py`: systemd on; the clone not under `/mnt/c` (slow); `/dev/dxg`; the Windows driver version, read from `/usr/lib/wsl`.
    - `macos.py`: Apple Silicon; the Xcode command line tools; Homebrew.
  - **Packages:** they're printed for the detected package manager (`dnf`, `apt`, `zypper`, `pacman`, `brew`), from one table of package names per tool (espeak-ng, ffmpeg, podman, git, Node).
  - **Kept from Phase 23:** fixes that need root are printed and never run.
  *Done when:* `utils/tests/core/test_setup_host.py` runs every fixture through the checks: the right checks apply, the fixes are printed for the right package manager, and nothing runs as root; on this machine `aihub setup host` prints exactly what it prints today.

- [ ] **37.4 The GPU in containers: `services/_template/containers.py`.**
  - A mod-side helper, copied into mods the way `gpu_slot.py` is. `gpu_args(machine, runtime)` returns the GPU flags:
    - **AMD:** `--device /dev/kfd --device /dev/dri --group-add keep-groups`.
    - **NVIDIA:** `--device nvidia.com/gpu=all` (podman CDI) or `--gpus all` (docker).
    - **Intel:** `--device /dev/dri`.
    - **WSL2:** `--device /dev/dxg -v /usr/lib/wsl:/usr/lib/wsl:ro`.
  - SELinux's `label=disable` is added only where SELinux is enforcing. The mod reads the machine from `GET /api/system/hardware` (the HTTP-only rule).
  - The runtime comes from `config.toml [containers] runtime = "podman" | "docker"` (default: whichever is installed, podman first), passed to mods as `AIHUB_CONTAINER_RUNTIME`.
  - **Docs:** `docs/mods.md` (containers), architecture §4.4.
  *Done when:* `services/_template/tests/test_containers.py` gives the right flags for every fixture and both runtimes; `aihub check` passes for the template.

- [ ] **37.5 CI: `.github/workflows/tests.yml`.**
  - `uv run pytest` runs on `ubuntu-latest` and `macos-latest`, with `linux` and `systemd` tests skipped on macOS. The Node tests use plain `node` (`setup-node`); the `flatpak-spawn` fallback stays for this machine's toolbox.
  - Tests that assume POSIX shell commands or Linux paths **by design** (the judge's) stay as they are, and are skipped nowhere.
  - **Needs the user's OK** to push the workflow (it's a public action on the repo).
  *Done when:* both jobs are green on a pushed branch.

- [ ] **37.6 What native Windows would need, written down: `docs/platforms.md` §Windows.**
  - The list, from the survey:
    - the Windows `.venv\Scripts` layout;
    - PowerShell installers;
    - a supervisor without process groups;
    - renaming over a file another process has open;
    - `SO_REUSEADDR`;
    - the `/`-only path checks in `utils/manifest.py` `resolve_arg`, `utils/doctor.py` `PATHLIKE` and the registry;
    - the judge's POSIX-only shell rules;
    - no uvloop.
  - Nothing is built for it.
  *Done when:* the section exists and names files and lines.

**Checks & deliverables — Phase 37**
- [ ] On this machine: `aihub restart`, `aihub logs -f`, `aihub setup host` and every mod behave as before (systemd backend).
- [ ] On this machine, with `[hub] backend = "detached"` on a second hub (port 7077): mods start, survive a hub restart, and stop.
- [ ] Delivered: `utils/backends/detached.py`, the CLI changes, `utils/setup_host/`, `services/_template/containers.py`, the CI workflow, `docs/platforms.md`.

---

## Phase 38 — Mods choose a backend (M)

- [ ] **38.1 Variants in the setup block, version 3: `utils/setupdocs/block.py`.**
  - A setup doc's block gains `[[variant]]` entries:
    ```toml
    [[variant]]
    accel = "cuda"              # rocm | cuda | xpu | vulkan | mps | metal | sycl | cpu
    os = ["linux", "wsl"]       # where it runs
    arch = ["sm_75+"]           # optional: GPU archs it needs
    tested = true               # false: the setup warns before installing it
    steps = [...]               # as version 2's [[steps]], run for this variant
    check = "..."
    ```
  - A block without variants is one `cpu` variant if `gpu = false`, and one variant for this machine (`rocm` or `vulkan`, from the doc) if `gpu = true`. Existing docs keep working.
  - `gpu` is derived from the variants. The mods index (`docs/setup/README.md`) shows a "Runs on" column (for example "CUDA · ROCm · CPU").
  - **Docs:** `docs/mods.md` §9.
  *Done when:* `utils/tests/docs/test_setup_block.py` covers parsing, the defaults for version 2 blocks, bad accels and archs, and the index column; `aihub docs --check` is clean.

- [ ] **38.2 The setup picks a variant: `utils/cli_setup.py`.**
  - **Picking:** for each chosen mod, the first of its variants whose `accel` is in `Machine.accels` and whose `os` and `arch` match. A mod with none is listed as "not available on this machine" with the reason ("needs CUDA or ROCm"), and choosing it is refused. A variant with `tested = false` is named as untested in the plan.
  - **Choosing another:** `--accel <id>=<accel>` picks a different one (for example `stt=cpu`).
  - **Recording the choice:** `config.toml [services.<id>] accel` (through `config.save`, keeping comments). The plan's JSON includes it.
  - **Docs:** Phase 23.9's description and `docs/setup/README.md`.
  *Done when:* `utils/tests/core/test_cli_setup.py` covers choosing per fixture, the override, an unavailable mod, an untested variant, and the recorded choice; `aihub setup --plan --json` on this machine picks today's backends for every mod.

- [ ] **38.3 The hub passes the choice to the mod: environment and manifest.**
  - **The environment:**
    - `AIHUB_ACCEL` is the chosen variant.
    - `AIHUB_DEVICE` is the torch device string: `cuda` for both CUDA and ROCm, then `xpu`, `mps` or `cpu`.
    - `AIHUB_GPU_ARCH` is the GPU's arch.
  - **Per-variant settings:** the manifest gains `[run.variants.<accel>] env = {…}` and an optional `command`, merged over `[run]` (`utils/manifest.py`; architecture §4.3–4.4).
  - **When the variant doesn't fit:** a mod whose recorded variant is missing from `Machine.accels` shows the state **unavailable**, with the reason, instead of failing to start. Brief §6/§11.7 gain the state, and the services list and mod card show it, plus a small badge with the variant ("CUDA", "ROCm", "CPU") (a `web/PATCHES.md` entry).
  *Done when:* `utils/tests/services/test_variants.py` (the environment, the merge and the unavailable state) and the contract test pass; the badge is checked in a browser on a `--demo-mods` hub.

- [ ] **38.4 The template and the docs.**
  - **The template:** `services/_template/` gains `device.py`, which reads `AIHUB_DEVICE` and falls back from `cuda` to `xpu`, `mps` and `cpu`. It also gains `torch_index.py`, which maps an accel and runtime version to a PyTorch wheel index, using the table from `services/tts/engines/probe.py`. Its `install.sh` takes `--accel`.
  - **The host docs:** `docs/setup/host.md` becomes an index of `host-linux-amd.md` (today's text), `host-linux-nvidia.md`, `host-linux-intel.md`, `host-wsl2.md` and `host-macos.md`.
  - **Wording:** "What to look for" becomes per variant in `docs/mods.md` §9.
  *Done when:* `aihub new demo` gives a mod whose `install.sh --accel cpu` and `aihub check demo` pass; `aihub docs --check` passes; `utils/tests/services/test_new.py` covers `device.py`.

**Checks & deliverables — Phase 38**
- [ ] On this machine: every installed mod shows its variant badge (ROCm or Vulkan), and nothing restarts differently.
- [ ] Delivered: setup block v3, the variant choice in `aihub setup`, `AIHUB_ACCEL`/`AIHUB_DEVICE`, the unavailable state, the template's helpers, the per-host docs.

---

## Phase 39 — The mods on other machines (L)

Each step:
- adds the mod's variants to its setup doc, one lock file per variant (`services/<id>/locks/<name>-<accel>.txt`) and `[run.variants]`;
- replaces hard-coded `"cuda"` and ROCm env with `AIHUB_DEVICE` and per-variant env;
- runs the mod's tests with fake hardware.

Variants for CUDA are checked live on the NVIDIA box in Phase 40. Until then they ship with `tested = false`. The expected result:

| Mod | rocm | cuda | xpu / sycl | vulkan | mps / metal | cpu |
| --- | --- | --- | --- | --- | --- | --- |
| agent, relay, web, searxng, opencode, workspace | — | — | — | — | — | yes (no GPU) |
| lcpp | — | yes | sycl | yes (today) | metal | yes |
| embed, decide | yes (today) | yes | xpu | — | mps | yes |
| tts (Kokoro) | yes (today) | yes | xpu | — | mps | yes |
| tts (Breeze) | yes (today) | yes | — | — | — | slow |
| stt | yes (today) | yes | — | — | — | yes (macOS, Intel) |
| comfy | yes (today, toolbox) | yes (native) | xpu (native) | — | mps (native) | slow |
| gen3d | yes (today) | yes | — | — | — | — |
| vllm | yes (parked) | yes | — | — | — | — |

- [ ] **39.1 The mods without GPU work: agent, relay, web, searxng, opencode, workspace.**
  - Their setup docs declare `os = ["linux", "wsl", "darwin"]`.
  - **The workspace sandbox:** it uses `--userns=keep-id` and `--network=pasta` only with rootless podman on Linux. With docker, and with podman on macOS (a VM), it uses their equivalents, and same-path mounts become `-v <dir>:<dir>` (`services/workspace/sandbox.py`).
  - **The opencode binary:** the setup step installs it for the OS.
  *Done when:* each mod's tests pass in the macOS CI job; `services/workspace/tests/test_sandbox.py` covers the flags per runtime.

- [ ] **39.2 lcpp: llama.cpp per accel.**
  - **Getting the binary:** the setup step fetches ggml-org's release asset for the OS and accel when one exists; otherwise it builds from source into `runtime/llama.cpp/bin/` with `-DGGML_CUDA=ON`, `-DGGML_SYCL=ON` or `-DGGML_METAL=ON`. The sha256 of each fetched asset is recorded in the doc.
  - **Running instances:** they keep the systemd backend on Linux and WSL2, and use lcpp's subprocess backend on macOS (`LCPP_BACKEND`, `services/lcpp/service.toml`).
  - **Memory:** the catalog's per-model `ngl` (the gap above), and acquire with `vram_bytes` (36.2).
  *Done when:* lcpp's tests cover choosing the asset per fixture and the two pools in acquire.

- [ ] **39.3 embed and decide: torch per accel.**
  - Locks for `cuda` (a cu12x index), `xpu`, `mps` (PyPI's macOS wheel) and `cpu`, next to today's ROCm lock.
  - `embed/encoder.py` and `decide/models/d3_lite.py` take the device from `AIHUB_DEVICE`. `DECIDE_DEVICE`/`EMBED_DEVICE` gain `xpu` and `mps`.
  - d3's `d3_fast.py` ROCm path is used only when `AIHUB_ACCEL = rocm`.
  *Done when:* both mods' tests cover choosing the device per accel, with a fake torch.

- [ ] **39.4 tts: the multi-backend planner becomes the install.**
  - **The install:** `scripts/install-runtime.sh` takes `--accel` and follows `engines/probe.py`'s plan instead of the hard-coded gfx1151 indexes.
  - **The engines:** Kokoro runs on every accel. Breeze has `rocm` (tested), `cuda` (untested until 40.1) and `cpu` behind `--allow-cpu-breeze`.
  - **Packages:** `espeak-ng` and `ffmpeg` come from 37.3's package table.
  *Done when:* tts's tests cover the plan per fixture; `install-runtime.sh --accel cpu --dry-run` prints a CPU-only plan.

- [ ] **39.5 stt: CTranslate2 per accel.**
  - **Variants:**
    - `cuda`: PyPI's wheel plus the cuBLAS/cuDNN pip packages.
    - `rocm`: today's overlay.
    - `cpu`: everywhere, and the only variant on macOS and Intel.
  - **Detection:** `stt/asr/acceleration.py` reads `AIHUB_ACCEL` instead of probing `/dev/kfd`. The gfx1151 int8 guard applies only to that arch.
  - **Docs:** the setup doc notes that whisper.cpp or MLX would give macOS a GPU path, as a later idea.
  *Done when:* stt's tests cover the device and compute type per accel.

- [ ] **39.6 comfy: a native ComfyUI next to the toolbox.**
  - **The native install:** `bin/comfyui` gains a native mode. It's a venv in `services/comfy/runtime/ComfyUI/` at a pinned commit, with the five custom nodes at pinned commits and torch per accel (`cuda`, `xpu`, `mps`, `cpu`).
  - **This machine:** the `rocm` variant is today's toolbox, unchanged.
  - **The workarounds:** the gfx1151 ones in `nodes/aihub_nodes` apply only when `AIHUB_GPU_ARCH = gfx1151`.
  - **Packs:** packs gain an optional `requires` (the gap above), and the tool's `x-options` drop packs the machine can't run.
  - **Docs:** `docs/workflows.md`, the `comfy-workflow` skill.
  *Done when:* comfy's tests cover the native launch command per accel, `requires` filtering, and the workarounds gated on the arch; `comfyui workflows check` passes on this machine.

- [ ] **39.7 gen3d: a CUDA image for the workers.**
  - **The image:** a `cuda` variant runs the workers in a pinned PyTorch CUDA image, with real spconv, gsplat and kaolin wheels instead of the shims.
  - **The workers:** `workers/cube_worker.py`, `hunyuan_worker.py` and `sam3do_worker.py` take `AIHUB_DEVICE`. The ROCm env in `gen3d/worker.py` is set only for `rocm`, and the container flags come from 37.4's helper.
  - **Engines that can't run:** an engine with no variant for the machine is reported through Phase 20's `x-options`, so it's never offered.
  *Done when:* gen3d's tests cover the worker command per accel and the engines offered per fixture.

- [ ] **39.8 vllm: a CUDA image (parked mod; declaration only).**
  - A `cuda` variant uses `vllm/vllm-openai` pinned by digest, with the attention backends per accel (`services/vllm/vllm_mod/profiles.py`) and the container flags from 37.4. The mod stays parked on this machine.
  *Done when:* vllm's tests cover the container command and the profiles' attention choices per accel.

**Checks & deliverables — Phase 39**
- [ ] On this machine: every mod still runs its ROCm or Vulkan variant, and one smoke per mod passes: an image, speech, a transcript, an embedding search, a chat on lcpp, a 3D model.
- [ ] Delivered: the variants, locks and setup docs for every mod; the native ComfyUI path; gen3d's CUDA image.

---

## Phase 40 — Checking on real machines (M)

- [ ] **40.1 Linux with NVIDIA** (the user's machine; needs the user's OK to clone and install there).
  - Record its detection as a fixture.
  - Run `aihub setup` from a fresh clone with the mods the user picks, and run every chosen mod's `check`.
  - Run the smokes from 39's checks.
  - Check making room on VRAM: two GPU mods whose VRAM doesn't fit together.
  - Flip each variant that passes to `tested = true`, and record its "Tested with" (driver, CUDA, torch).
  *Done when:* the results table in `docs/platforms.md` has a row per mod for this machine.

- [ ] **40.2 Windows 11, WSL2 and an Intel GPU** (when the PC is available; needs the user's OK).
  - Set up WSL2 and Ubuntu following `docs/setup/host-wsl2.md`, and record the detection.
  - Run `aihub setup` (xpu and sycl variants), open the UI from the Windows browser, and run the smokes for the mods with an Intel variant.
  - Record whether the GPU is one pool or two.
  *Done when:* as 40.1.

- [ ] **40.3 The support matrix.**
  - `docs/platforms.md` lists each OS and accelerator: tested (on which machine and when), CI only, or untested. The setup README's generated index takes "Runs on" from the variants.
  - The README's and `docs/setup/README.md`'s "macOS and Windows aren't supported" become the matrix. CLAUDE.md's status line is updated.
  *Done when:* `aihub docs --check` passes; the matrix agrees with every variant's `tested` flag.

**Checks & deliverables — Phase 40**
- [ ] A person on a Linux machine with an NVIDIA GPU can go from a clone to a working hub with lcpp, comfy, tts and stt by following `docs/setup/README.md`.
- [ ] Delivered: `docs/platforms.md`, the per-host docs checked on real machines, the fixtures from both machines.

---

## Deliverables

| Deliverable | Description | Location |
| --- | --- | --- |
| Hardware detection | what the machine has: OS, WSL, GPUs, memory kind, runtimes, accels | `utils/hardware/` |
| Portable process reads | psutil fallback next to the Linux `/proc` reads | `utils/proc_linux.py`, `utils/proc_portable.py` |
| Memory pools | system RAM and each dedicated GPU's VRAM as separate budgets | `utils/memory/pools.py`, `planner.py` |
| Per-device GPU queue | one slot per GPU | `utils/gpu.py` |
| Detached backend | mods that outlive the hub without systemd | `utils/backends/detached.py` |
| Host checks | per host kind, fixes printed per package manager | `utils/setup_host/` |
| Container GPU flags | per vendor and runtime, for mods | `services/_template/containers.py` |
| Variants | setup block v3, the choice in `aihub setup`, `AIHUB_ACCEL`/`AIHUB_DEVICE` | `utils/setupdocs/block.py`, `utils/cli_setup.py`, `utils/manifest.py` |
| Template helpers | the torch device and the wheel index per accel | `services/_template/device.py`, `torch_index.py` |
| Per-host docs | AMD, NVIDIA, Intel, WSL2, macOS | `docs/setup/host-*.md` |
| Support matrix | what runs where, and what was tested | `docs/platforms.md` |
| CI | Linux and macOS test jobs | `.github/workflows/tests.yml` |
| Tests | hardware fixtures per machine; detection, pools, devices, backends, variants, host checks | `utils/tests/hardware/`, `utils/tests/memory/`, `utils/tests/gpu/`, `utils/tests/services/`, `utils/tests/core/`, each mod's `tests/` |
