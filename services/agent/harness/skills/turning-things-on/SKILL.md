---
name: turning-things-on
description: >-
  When something the user asks for is off on this machine (not set up, turned off, stopped): say so, then start it, turn it on or set it up with them
---
# Turning things on

Lines under "Off on this machine" in your instructions name what is missing, its tools, why, and the one tool that turns it on.

- **Stopped:** nothing to do. Call its tool; the call starts it. (`hub_start_service` starts it on its own.)
- **Turned off:** it is set up, and the user turned it off in Settings. Calling its tools turns it on for you; to turn it on by itself, `hub_enable_service` with its id.
- **Failed to start:** try `hub_start_service` once. If it fails again, tell the user what the error says and that its Logs tab has more; don't keep trying.
- **Not set up:** say in one sentence what is missing ("I can't search the web: Web isn't set up on this machine") and ask if they want it set up. Never reach for it another way (a shell, `curl`, another tool standing in).
  1. On a yes, call `hub_setup_plan` with the ids and tell the user everything it says: what each gives, what is installed and where, how big it is, every download with its source and licence, containers and ports. If it has questions, ask them (`ask_user` with the choices).
  2. Then call `hub_setup` with the ids and their answers, in the same reply: its card is where they confirm (it shows before anything runs), so don't ask "shall I proceed?" a second time. It takes a while for a large mod.
  3. When it's done, run `hub_setup_test` for a mod that has a test, and say what works now and what still needs them. Then do what they asked for in the first place.
  4. If it comes back `needs_you`, give the exact command or answer it needs (anything with `sudo`, or a login, is theirs to run), then call `hub_setup` again with `done` or their answers.
  5. If it fails, say what failed and where its log is. The easier way is often their own coding agent: `gaifa setup --prompt <ids>` prints a prompt to paste into Claude Code or Codex, which reads the same docs and can fix what goes wrong on their machine.
- **Can't run here** (its variant needs hardware this machine doesn't have): say so; `hub_setup` can set it up again with another variant.

If you can still answer well without it, do, and say what you couldn't check.
