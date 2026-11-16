"""The prompt for your own coding agent (plan capability-enablement 3.2): one text, the same from `gaifa setup --prompt`,
`GET /api/setup/prompt` and the docs, with this clone's path and the chosen mods filled in. Standard library only (the
CLI imports it).

It tells a coding agent (Claude Code, Codex) where it is, what to read and what to do: plan, tell the person, run with
their answers, hand them any `sudo` or login step, check with the doctor, and what to do on a failure. Nothing from
`config.toml` goes into it: it may be pasted anywhere.
"""

from __future__ import annotations

from pathlib import Path


def coding_agent_prompt(root: Path | str, ids: list[str]) -> str:
    root = Path(root)
    mods = " ".join(ids) if ids else "<the mods you choose>"
    first = ids[0] if ids else "<id>"
    docs = ", ".join(f"services/{i}/setup/*.md" for i in ids) if ids else "services/<id>/setup/*.md"
    return f"""Set up {('these GAIFA mods: ' + ', '.join(ids)) if ids else 'GAIFA mods'} on this machine.

GAIFA is a local app that runs AI services as mods. Its clone is at {root}.

Read first:
- {root}/AGENTS.md (how to work in this repository),
- the gaifa-setup skill: {root}/.agents/skills/gaifa-setup/SKILL.md (or .claude/skills/gaifa-setup/SKILL.md),
- each mod's setup doc: {docs}.

Then:
1. Run `bin/gaifa setup --plan --json {mods}` in {root} and tell me, in plain words, what it will install, where, how big it
   is, what it downloads and from where (with licences), and every question it asks. Wait for my answers.
2. Run `bin/gaifa setup {mods} --json` with my answers (`--answers <file>`, or `--accept`, `--decline`, `--models`, `--set`).
   Exit code 2 means it needs me: show me the question, or the command to run myself (anything with `sudo` or a login is
   mine to run; give me the exact command), then go on with `--done <id>`.
3. Run `bin/gaifa doctor -v` (`-v` lists what works too) and stop when each mod shows as working under "what works"
   (and its check passed); then run each mod's setup doc **Check** commands.
4. If something fails, read the step's log (the report names it, under data/state/setup/logs/) and the "When it fails"
   part of the mod's setup doc, try the documented fix, and if it still fails run `bin/gaifa report` and give me its path.

Change no tracked file unless I ask. Never run `git clean -x`. For one mod alone: `bin/gaifa setup {first}`.
"""
