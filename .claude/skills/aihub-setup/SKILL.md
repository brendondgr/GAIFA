---
name: aihub-setup
description: Use when asked to set up, install or bootstrap AIHub, or some of its mods, on a machine ("set up AIHub for me", "install the speech and chat mods", "get this running", "add llama.cpp to my install"), or when `aihub setup` stopped and needs finishing. Drives `aihub setup` for the person: the same steps and questions they'd see, with their answers, never root.
---

# Setting up AIHub for someone

`aihub setup` is the one setup process. A person runs it and answers as it goes; you run the same steps with `--plan --json`, ask the person the same questions, pass their answers, and read one JSON report. Everything a mod needs is declared in its setup doc (`services/<id>/setup/*.md`, the `aihub-setup` block); the guide is [docs/setup/README.md](../../../docs/setup/README.md). From a bare clone use `bin/aihub` (it works before `uv sync`); later `aihub` is on `PATH`.

## The procedure

1. **What they want.** `bin/aihub setup --json` lists every setup id with a one-line summary, GPU or not, and disk. Ask which they want, in their words ("chat and speech" → relay, agent, tts, stt). Mention what a choice brings along (`after`) and that GPU mods need the Strix Halo setup in [host.md](../../../docs/setup/host.md).
2. **The host.** `bin/aihub setup host --json`. For every failed check, give the person its `fix`. **Never run a fix that `needs_root`** (`sudo grubby`, `usermod`, `dnf`): show the exact command, let them run it (a reboot or a new login may follow), then check again. Non-root fixes (uv, OpenCode's installer, `loginctl enable-linger`) you may run once they agree.
3. **The plan.** `bin/aihub setup --plan --json <ids>`. Show them: the steps, the disk (environments plus required models), the hub stage if the hub isn't installed yet, and every question:
   - `yes-no` (a licence, third-party code): **their** answer, never yours. Quote the question and its link.
   - `models`: the suggestions with sizes and licences; required ones are needed for the engine to run. Their own models are added later per the doc's Choosing models.
   - `value` (the agent's model): asked after install, from the relay's models. If they have no local LLM, ask for a hosted provider (base URL, key, model names: services/relay/setup/relay.md, "Adding a hosted provider").
4. **The answers file.** Write `data/state/setup/answers.json` (inside the project; never put a key anywhere else, never echo it back):
   `{"yes": true, "accept": [...], "decline": [...], "models": {"<setup id>": ["<name>", ...]}, "values": {"services.agent.env.AGENT_MODEL": "<name>"}, "providers": [{"name": "...", "base_url": "...", "key": "...", "models": ["..."]}]}`
5. **The run.** `bin/aihub setup --json --answers data/state/setup/answers.json <ids>`, in the background: GPU mods take 10–30 minutes each. Progress lines arrive on stderr; stdout is one JSON object at the end. One mod at a time is fine and easier to follow.
6. **When it stops** (exit 2, or `"stage": "stopped"`):
   - `question`: ask the person (its `text`, `choices`), add the answer, run again. It resumes; finished steps are skipped.
   - `interactive`: a step that prompts (a login). Give the person its `run` and `cwd`; once they've run it, run again with `--done <id>`.
   - `failed`: read the failure's `doc` (What to look for, Known gaps), fix what you can, tell them what you can't, run again.
   - `host`: back to step 2.
7. **Done.** Report what's installed, what was skipped (a declined question skips its setup and what needs it), every `next` item (models to add, values left unset), and run `aihub doctor`.

## Rules
- **Root is the person's.** Print root commands; never run them, not even with their password.
- **Licences and third-party code are the person's choice.** Never `--accept` a question they didn't answer.
- **Nothing on the GPU beyond the mods' own installers and checks.** No custom kernels, no HIP graphs, no tuning experiments: this machine family lost files to stray GPU writes (host.md). Keep the IOMMU on.
- **Keys stay in the answers file and the relay;** don't paste them into chat output, commits or docs, and delete the answers file once the run is done if it holds one.
- **Don't change a mod's setup doc to make a step pass;** if a doc is wrong, say so (and fix it as a separate change, with the user's OK).
