---
name: aihub-setup
description: Use when asked to set up, install or bootstrap AIHub, or some of its mods, on a machine ("set up AIHub for me", "install the speech and chat mods", "get this running", "add llama.cpp to my install"), or when `aihub setup` stopped and needs finishing. Drives `aihub setup` for the person: the same steps and questions they'd see, with their answers, never root.
---

# Setting up AIHub for someone

`aihub setup` is the one setup process. A person runs it and answers as it goes; you run the same steps with `--plan --json`, ask the person the same questions, pass their answers, and read one JSON report. Everything a mod needs is declared in its setup doc (`services/<id>/setup/*.md`, the `aihub-setup` block); the guide is [docs/setup/README.md](../../../docs/setup/README.md). From a bare clone use `bin/aihub` (it works before `uv sync`); later `aihub` is on `PATH`.

## The procedure

1. **What they want.** `bin/aihub setup --json` lists every setup id with a one-line summary, GPU or not, disk and `after`. Ask which they want, in their words ("chat and speech" → relay, agent, tts, stt). Mention what a choice brings along (`after`) and that GPU mods need the Strix Halo setup in [host.md](../../../docs/setup/host.md). Two things to ask early:
   - **Where Chat's LLM comes from**, since the agent's model question lists only what the relay serves: a **local** model (`lcpp`: setup downloads the GGUF they pick and launches it on the relay; needs the GPU), a **hosted provider** (an OpenAI-compatible base URL, a key and model names, added to the relay: `"providers"` in the answers), or **OpenCode Zen**'s free hosted models (`opencode`, with their Zen key at its login step and a folder for it to work in). No GPU: one of the last two.
   - **A mod id takes all its setups; a setup id takes one.** `tts` is Kokoro **and** Breeze TTS 2 (Breeze is research / non-commercial only, asked as a licence question); `tts-kokoro` is Kokoro alone. `gen3d` is 3D Generate's base (server, image, runtimes) **and** its engines `gen3d-cubeart`, `gen3d-img3d`, `gen3d-sam3do`, each with its own licence question (a "no" skips only that engine; the base alone, with ComfyUI, still runs TRELLIS.2 and SAM 3D Body); an engine's id brings the base along. Check the `choose` list's ids before naming one.
2. **The host.** `bin/aihub setup host --json`. For every failed check, give the person its `fix`. **Never run a fix that `needs_root`** (`sudo grubby`, `usermod`, `dnf`): show the exact command, let them run it (a reboot or a new login may follow), then check again. Non-root fixes (uv, OpenCode's installer, `loginctl enable-linger`) you may run once they agree.
3. **The plan.** `bin/aihub setup --plan --json <ids>`. Show them: the steps, the disk (environments plus required models), the hub stage if the hub isn't installed yet, each setup's **variant** (`variants`: the accel picked for this machine, `untested` when it hasn't run on this kind of machine) and what's **unavailable** here with why (`unavailable`), and every question. If they'd rather use another variant (the CPU instead of an untested GPU path), pass `--accel <setup or mod>=<accel>`. `--smoke` adds each setup's smoke after the checks:
   - `yes-no` (a licence, third-party code): **their** answer, never yours. Quote the question and its link.
   - `models`: the suggestions with sizes and licences; required ones are needed for the engine to run (leaving one out is allowed, but its check fails and the report says so). Their own models are added later per the doc's Choosing models.
   - `value`: asked after install, since the choices exist only then, and saved through the hub so the running mod gets it (folders and lists first; the relay's models last, since OpenCode's folder brings Zen's). The agent's model and the Auto judge's come from the relay's models; if they have no local LLM, ask for a hosted provider (base URL, key, model names: services/relay/setup/relay.md, "Adding a hosted provider"). A folder (`choices = "folder"`, such as OpenCode's `OPENCODE_PROJECT_DIR`) is an absolute path outside AIHub that they pick; it's created if missing.
   - A step marked `optional` (ComfyUI's custom nodes): a "no" skips only that step, not the whole setup; say which packs then won't run (the question says).
4. **The answers file.** Write `data/state/setup/answers.json` (inside the project; never put a key anywhere else, never echo it back):
   `{"yes": true, "accept": [...], "decline": [...], "models": {"<setup id>": ["<name>", ...]}, "values": {"services.agent.env.AGENT_MODEL": "<name>"}, "providers": [{"name": "...", "base_url": "...", "key": "...", "models": ["..."]}]}`
5. **The run.** `bin/aihub setup --json --answers data/state/setup/answers.json <ids>`, in the background: GPU mods take 10–30 minutes each. Progress lines arrive on stderr; stdout is one JSON object at the end. One mod at a time is fine and easier to follow.
6. **When it stops** (exit 2 for a question or an interactive step, else exit 1; `"stage": "stopped"` with a `reason`). Answers already given are kept in `data/state/setup/run.json`, so a resumed run doesn't ask them again, and finished steps are skipped:
   - `question`, by its `kind`:
     - `yes-no`: a licence or third-party code (or `plan`: "Run this plan?", answered with `--yes`). Quote its `text`; their answer goes in `accept` or `decline` (`--accept <id>` / `--decline <id>`).
     - `models`: which suggestions for one setup (`choices`, with the `required` ones); `--models "<setup id>=<names>"`, or `none`.
     - `value`: a setting after install (`choices`: the relay's models, a list, or `"folder"`); `--set "<id>=<value>"`. When the relay has **no chat models yet**, the `answer_with` hint says where one comes from: set up `lcpp` with a model (setup launches it), add a hosted provider (`"providers"` in the answers), or set up `opencode`. Don't invent a name.
   - `interactive`: a step that prompts (a login). Give the person its `run` and `cwd`; once they've run it, run again with `--done <id>`. (A step whose `skip_if` passes, such as an existing login, never stops here.)
   - `failed`: a step, a download, a model launch or a config write failed; read the failure's `doc` (What to look for, Known gaps), its `source` (the doc line the command comes from), its `output` and its whole `log` (`data/state/setup/logs/`), fix what you can, tell them what you can't, run again.
   - `host`: a blocking host check failed: back to step 2.
   - `unavailable`: nothing they chose runs on this machine (`unavailable` says why: no such accel here, or another OS). Offer another variant with `--accel`, or other mods.
   - `unknown`: a setup or mod id that has no setup doc (a typo, or a mod that isn't in this clone); its `choices` lists the real ids. Ask which they meant.
   - `unknown-model`: a model name that isn't one of that setup's suggestions; use a name from `choices` exactly (their own models are added later, per the doc's Choosing models).
   - `unknown-value`: a value that isn't one of the `choices` (a model the relay doesn't serve), or a folder that isn't absolute or is inside AIHub. Ask again with the real choices.
   - `cycle`: setup docs whose `after` lists loop (`ids` shows the loop). That's a doc bug, not the person's: report it, don't edit around it.
7. **Done.** Report what's installed, what was skipped (a declined question skips its setup and what needs it), every `next` item (models to add, values left unset), and run `aihub doctor`.

## Rules
- **Root is the person's.** Print root commands; never run them, not even with their password.
- **Licences and third-party code are the person's choice.** Never `--accept` a question they didn't answer.
- **Nothing on the GPU beyond the mods' own installers and checks.** No custom kernels, no HIP graphs, no tuning experiments: this machine family lost files to stray GPU writes (host.md). Keep the IOMMU on.
- **Keys stay in the answers file and the relay;** don't paste them into chat output, commits or docs, and delete the answers file once the run is done if it holds one.
- **Don't change a mod's setup doc to make a step pass;** if a doc is wrong, say so (and fix it as a separate change, with the user's OK).
