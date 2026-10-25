---
name: plan
description: Use when asked to create, refine, extend or review an implementation plan for GAIFA — a new feature, mod, fix or migration, a sub-plan for one step, or "plan this out / break this into steps" before coding. Every new plan is its own file in docs/plans/<slug>.md, listed in docs/plans/README.md; docs/backend-plan.md is closed history and never gains phases.
---

# Planning in GAIFA

**One plan, one file.** Every new plan is a new file, `docs/plans/<slug>.md`, listed in [docs/plans/README.md](../../../docs/plans/README.md). The old master plan, [docs/backend-plan.md](../../../docs/backend-plan.md), is closed at Phase 51: read it for history and the reasons behind what exists, but **never add a phase, stage or step to it**, and don't renumber anything after its phases. Format rules: [planner.md](planner.md).

## Before writing
1. Load the `gaifa` skill (doc map and invariants), then read the architecture sections the work touches and any plan in `docs/plans/` that covers the same area.
2. Check what exists today in [docs/structure.md](../../../docs/structure.md). Don't plan files the architecture already places somewhere else.
3. Settle gaps: answer simple ones with a stated assumption; list complex ones as **needs a human answer** and stop short of planning around them.

## Settled preferences
- **New or changed?** Changing a plan that is still open (a step not done yet, a gap answered) edits that plan's file. New work, even in an area an earlier plan covered, gets a new file that links the earlier one.
- **Granularity:** full engineering plans. A plan has one or more phases, numbered from 1 inside the plan and sized **S / M / L**; steps are `<phase>.<n>` (a one-phase plan may just number its steps 1, 2, 3…).
- **Validation:** pytest (`uv run pytest`) for every step; browser checks against the live backend for UI wiring; `api.js` Node tests and the contract test where the UI/API boundary moves. Fake mods under the subprocess backend stand in for real apps; systemd tests are marked.
- **Git:** one commit per step, after tests pass, message `GAIFA (<slug> <phase>.<step>): <what was done>`. Push to `origin main` when the user asks or at the end of a plan's phase. Docs changes ride in the same commit as the behavior change.
- **Audience:** agentic implementation — Claude works the plan step by step, so every step must be executable without re-deriving context.

## Output
- A new plan: write `docs/plans/<slug>.md` (a short, lower-case, hyphenated name for the work, e.g. `gpu-queue-v2`), add a row to the table in `docs/plans/README.md` (status **Planned**) and a row to `docs/structure.md`'s docs table.
- As a plan's steps land, tick them in the plan's file and keep its status in `docs/plans/README.md` current (**Planned** → **In progress** → **Done**, with the date).
- A sub-plan for one step of a plan: return it in chat unless the user asks for a file; if a file, it's a plan of its own (`docs/plans/<slug>.md`) that names the step it serves.
