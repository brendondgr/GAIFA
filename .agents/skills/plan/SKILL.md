---
name: plan
description: Use when asked to create, refine, extend or review an implementation plan for AIHub — a new phase or step for docs/backend-plan.md, a sub-plan for one step, a migration plan for moving an app in, or "plan this out / break this into steps" before coding. Writes plans in the same format as docs/backend-plan.md.
---

# Planning in AIHub

AIHub already has a master plan: [docs/backend-plan.md](../../../docs/backend-plan.md). Every new plan either **amends that file** (a new or changed phase or step) or is a **sub-plan for a single step**, written in the same shape so it can be pasted in. Format rules: [planner.md](planner.md).

## Before writing
1. Load the `aihub` skill (doc map and invariants), then read the plan section you're touching and the architecture sections it cites.
2. Check what exists today in [docs/structure.md](../../../docs/structure.md). Don't plan files the architecture already places somewhere else.
3. Settle gaps: answer simple ones with a stated assumption; list complex ones as **needs a human answer** and stop short of planning around them.

## Settled preferences (answers to the original skill's setup questions)
- **Granularity:** full phase-by-phase engineering plans. Phases are sized **S / M / L**; steps are numbered `<phase>.<n>`.
- **Validation:** pytest (`uv run pytest`) for every step; browser checks against the live backend for UI wiring; `api.js` Node tests and the contract test (6.6) where the UI/API boundary moves. Fake mods under the subprocess backend stand in for real apps; systemd tests are marked.
- **Git:** one commit per step, after tests pass, message `AIHub (<phase>.<step>): <what was done>`. Push to `origin main` when the user asks or at the end of a phase. Docs changes ride in the same commit as the behavior change.
- **Audience:** agentic implementation — Codex works the plan step by step, so every step must be executable without re-deriving context.

## Output
- Amending the master plan: edit `docs/backend-plan.md` directly, update the phase table if a phase is added, and keep the "Nothing in it has been implemented yet" note accurate.
- Sub-plan for one step: return it in chat unless the user asks for a file; if a file, put it in `docs/plans/<phase>.<step>-<slug>.md` and add it to `docs/structure.md`.
