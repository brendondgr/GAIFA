# Calendar

A GAIFA mod: events and to-dos (a reminder is a to-do with a time), repeats, alerts as in-app toasts, `.ics` import and export, plain-words dates, free time and day plans, for you (the Calendar page, the Chat side panel) and the agent (its `calendar_*` tools and the agenda in every chat's prompt). Plan: [docs/plans/calendar.md](../../docs/plans/calendar.md). Setup: [setup/linux.md](setup/linux.md).

- `server.py` the app; `store.py` SQLite; `repeat.py` occurrences and series edits; `items.py` writes with undo; `when.py` the date parser; `settings.py`.
- Tests: `.venv/bin/python -m pytest` in this folder.
