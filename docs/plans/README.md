# Plans

Each piece of work GAIFA builds has its own plan here: one file per plan, `docs/plans/<slug>.md`, with its phases, steps, checks and deliverables. The `plan` skill writes them; the format is in `.claude/skills/plan/planner.md`.

- **A new feature, mod or fix gets a new file.** It doesn't extend another plan or [backend-plan.md](../backend-plan.md).
- **Phases and steps are numbered inside the plan**, from 1. Commits name the plan: `GAIFA (<slug> 2.3): <what was done>`.
- **Keep the table current:** add a row when a plan is written, and change its status as its steps land.

[backend-plan.md](../backend-plan.md) is the original build plan, Phases 0–51 (2026-10-04 to 2026-10-25). It's closed: read it for history and the reasons behind what exists, and refer to its steps by number ("plan 23.6"), but don't add to it. Steps still open in it (in Phases 12, 15–18, 31–34 and 43) may be finished and ticked there; anything beyond them is a new plan.

| Plan | What | Status |
| --- | --- | --- |
| [backend-plan.md](../backend-plan.md) | The original build plan, Phases 0–51: the hub, the mods, chat and the agent, setup, other machines | Closed (2026-10-25) |
| [comfy-qwen21-turbo.md](comfy-qwen21-turbo.md) | The Qwen-Image 2.1 Turbo workflow packs | Done |
| [chat-uploads-and-fast-presets.md](chat-uploads-and-fast-presets.md) | `fast`/`draft` presets the agent can use, and uploading images in Chat | Done |
| [capabilities-and-learning.md](capabilities-and-learning.md) | Stage H (Phases 20–22); a pointer, moved into backend-plan | Done |
| [portability.md](portability.md) | Stage N (Phases 35–40): other GPUs and systems | In progress: the field tests (40.5, 40.6) are the user's |
| [chat-cards.md](chat-cards.md) | Stage P (Phases 44–49): mods' chat cards, live progress, `show`, @-mentions, Save to…, voice | Done |
| [gaifa-rename.md](gaifa-rename.md) | Stage Q (Phase 50): AIHub becomes GAIFA | Done |
| [settings-redesign.md](settings-redesign.md) | The Settings page in `web/settings/`: eight regrouped sections, a sticky section list, search with highlighting, keys, defaults and Reset on every row | Done (2026-10-25) |
