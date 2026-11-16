<!-- gaifa-setup
id = "calendar"
title = "Calendar"
models = []
scan = []
summary = "Calendar: events, to-dos and reminders in GAIFA, with in-app alerts and tools for the agent"
recommended = true   # offered first for chat (capability-enablement 1.4)
gpu = false
disk_gb = 0.1
needs = ["uv"]
check = "gaifa start calendar && gaifa check calendar"

[[steps]]
run = "gaifa install calendar"
what = "makes .venv/ from requirements-dev.txt (about 60 MB, under a minute)"

[[variants]]                    # no GPU work: one variant everywhere; tested on Linux
accel = "cpu"
os = ["linux", "wsl", "darwin"]
tested = ["linux"]
-->

# Calendar: setup

**The easy way:** paste the text of `gaifa setup --prompt calendar` into your coding agent (Claude Code, Codex): it reads this doc, runs the same commands and checks, and can fix what goes wrong. Or run `gaifa setup calendar` yourself.

The format is in [docs/mods.md §9](../../../docs/mods.md#9-setup-docs).

## What it is

The `calendar` mod's own venv (FastAPI, icalendar, python-dateutil, tzlocal). It keeps its items in `data/databases/calendar.db` and its settings in `data/state/calendar/settings.json` (both in `gaifa backup`). It runs no model and needs no GPU or network: dates in words are read by its own parser.

## Tested with

Read from this machine on 2026-11-09: Python 3.14.6 (uv-managed), fastapi 0.162.2, uvicorn 0.54.0, icalendar 7.3.0, python-dateutil 4.0.0, httpx 0.28.1.

## Prerequisites

- [The hub](../../../docs/setup/hub.md).
- The `agent` mod for its tools, the agenda in chats and prep tasks (the page works without it).

## Install

```bash
gaifa install calendar
```

Makes `.venv/` in this folder from `requirements-dev.txt`.

## Choosing models

None: the calendar runs no model.

## Configuration

| Key | Where | Required | Meaning |
|---|---|---|---|
| `CALENDAR_DB` | `service.toml` `[run].env` | no | The SQLite file (default `{databases}/calendar.db`) |
| `CALENDAR_STATE` | `service.toml` `[run].env` | no | The settings folder (default `{root}/data/state/calendar`) |
| `CALENDAR_TZ` | environment | no | An IANA zone instead of the system's (the tests set it) |

Working hours, alert defaults, the week start, how `11/12` reads and whether today's agenda goes into chats are on the Calendar page's settings (`GET/PATCH /v1/settings`).

## Check

```bash
gaifa check calendar --start
```

Expect `calendar: all checks passed`.

```bash
curl -s "$(gaifa url api/s/calendar/v1/status)"
```

Expect `"stats":[{"label":"Items",…},{"label":"Calendars","value":1},…]`. The Calendar opens at `#/calendar`, and a chat's prompt holds *Your calendar* (today and tomorrow).

## When it fails

| What you see | What to check | The fix |
|---|---|---|
| the Calendar page says the mod isn't running | `gaifa status` | `gaifa start calendar` |
| alerts don't show | `curl -s "$(gaifa url api/s/calendar/v1/status)"` (`next_alert`) | keep a GAIFA page open (alerts are in-app toasts), and check the item has a time |
| an `.ics` import adds nothing | the import's proposal (it waits for you to tick and add) | tick the items and Add |
| `gaifa status` shows calendar `not set up`; a chat says it isn't set up | `ls services/calendar/.venv` | `gaifa setup calendar` (or the Set up dialog: Settings → Services → Set up) |
| `gaifa status` shows calendar `failed` | `gaifa logs calendar` (the last lines say why) | fix what the log names, then `gaifa start calendar`; still failing: `gaifa setup --prompt calendar` for your coding agent |
| calendar is off (Settings → Services shows its switch off) | Settings → Services | turn its switch on, or ask GAIFA's agent to turn it on; `gaifa start calendar` starts it once |

## What to look for

- Times show in the system's zone (`timedatectl`); set `CALENDAR_TZ` in the mod's `.env` to use another.
- An `.ics` from another app that won't import: the proposal lists what was skipped and why.
