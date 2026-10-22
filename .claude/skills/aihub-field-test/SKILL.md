---
name: aihub-field-test
description: Use when asked to test AIHub on a new or different machine ("try AIHub on this box", "field test the NVIDIA PC", "see what breaks on WSL", "build AIHub here and tell me what failed"), or to write a field report for whoever fixes AIHub. Runs `aihub setup` with its smokes, records every problem with `aihub report note`, and hands back one detailed markdown report. Changes no tracked file.
---

# Field-testing AIHub on another machine

The goal is a **report**, not a working install. A field test runs the same setup a person would (the `aihub-setup` skill's procedure), proves each GPU path with the smokes, and writes everything it saw into one file: `aihub report`. The person takes that file back to the AIHub repo, where each issue's setup doc line, command, log and likely cause make the fix a small edit. Plan: [docs/plans/portability.md](../../../docs/plans/portability.md) Phase 40. Guide: [docs/setup/README.md](../../../docs/setup/README.md), "Testing on another machine".

From a bare clone use `bin/aihub` (it works before `uv sync`).

## The procedure

1. **Record the machine.** `bin/aihub hardware`. Read it to the person: the GPUs, their drivers, the accels AIHub can use (`rocm`, `cuda`, `xpu`, `mps`, `vulkan`, `cpu`) and any GPU `problem` (a missing runtime, a group). If what it found is wrong (a GPU it missed, a wrong VRAM size), that is itself an issue: `bin/aihub report note "aihub hardware missed the second GPU" --cmd "lspci | grep -i vga" --severity major`.
2. **Which mods.** `bin/aihub setup --json` lists the setups. By default try **every mod that's available** here (the plan's `unavailable` names the rest and why); ask the person whether to leave any out (big downloads, licences they don't want, no time). Where Chat's LLM comes from is the same question as in `aihub-setup`.
3. **The host.** `bin/aihub setup host --json`. Hand the person every fix that `needs_root` (never run one); run the others once they agree. A host check that fails with no fix, or a fix that didn't work, is a note.
4. **The plan.** `bin/aihub setup --plan --json --smoke <ids>`. Show the steps, the disk, each setup's **variant** (and `untested` ones: most variants off this repo's own machine are; that's what the test is for) and every question. Licences and model choices are the person's, as in `aihub-setup`.
5. **The run.** `bin/aihub setup --json --smoke --answers data/state/setup/answers.json <ids>`, in the background; one mod at a time is easier to follow. Every step's, check's and smoke's whole output is kept in `data/state/setup/logs/`, and the run in `data/state/setup/last-run.json`; the report reads both, so a failure needs no copying.
6. **When something fails** (`"reason": "failed"`, a check or a smoke `ok: false`):
   - Read the failure's `doc` (its **What to look for** and **Known gaps**), its `source` (the doc line the command comes from) and its whole `log`.
   - **Try the documented fixes, at most ~15 minutes per failure**, and record every attempt as you go: `bin/aihub report note "<what you saw, in your words>" --setup <id> --cmd "<the command>" --output <a file with its output> --tried "<what you tried and what it did>" --severity blocker|major|minor`. Blocker: the mod can't run here. Major: it runs only after a workaround. Minor: a wrong message, a doc that's out of date.
   - **Change no tracked file** unless the person asks. If a local workaround is needed to go on (an env var in `config.toml`, an edit to a script), make it, note it, and keep it: the report's `git diff` carries it to the fixer, which is often the fix itself.
   - Then go on: rerun (it resumes after the last step that passed), or `--decline` that setup and continue with the rest. One failure shouldn't end the test.
7. **Also note** what isn't a failure but would trip a person: a step far slower or bigger than its doc says, a question that was confusing, a warning in a log, a page in the UI that looks wrong (`bin/aihub open`), a mod that starts but whose page errors.
8. **The doctor.** `bin/aihub doctor`. The report includes it, but read its warnings: one may explain a failure above.
9. **The report.** `bin/aihub report`. It writes `data/state/reports/<date>-<host>.md`, a `.json` with the same data and a `.hardware.json` recording of this machine. Give the person the paths and a three-line summary (what passed, what failed, what was worked around). They feed the `.md` to Claude in the AIHub repo; the recording becomes a test fixture when the fixes land.

## Rules
- **The report is the product.** A failure you fixed locally and didn't note is lost to the fixer. Note first, fix second.
- **Root is the person's**, licences and model choices are the person's, keys stay in the answers file and out of notes (the report redacts tokens, keys and the home folder anyway).
- **Change no tracked file unless asked**; never commit or push from a field test.
- **Nothing on the GPU beyond the mods' installers, checks and smokes:** no benchmarks, no custom kernels, no tuning. A GPU hang or reset (`journalctl -k`) is a blocker note and a reason to stop.
- **Never `git clean -x` / `-X`**: it deletes the downloaded models.
- `aihub report clear` forgets the notes; use it only between two separate test runs, after the person has the first report.
