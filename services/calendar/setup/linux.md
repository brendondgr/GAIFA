<!-- gaifa-setup
id = "calendar"
title = "Calendar"
models = []
scan = []
summary = "Calendar: events, to-dos and reminders in GAIFA, with in-app alerts and tools for the agent"
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

## Check it works

```bash
gaifa start calendar && gaifa check calendar
```

Expect `all checks passed`.

## What to look for

- Times show in the system's zone (`timedatectl`); set `CALENDAR_TZ` in the mod's `.env` to use another.
- An `.ics` from another app that won't import: the proposal lists what was skipped and why.
