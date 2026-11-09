# Plan: the calendar: events, to-dos and reminders in GAIFA, for you and the agent

**Asked for:** 2026-11-09 · **Status:** In progress

## 1. Introduction

GAIFA has no notion of your time. You can't ask the agent "what do I have today?", or tell it "remind me Friday", or hand it a syllabus and get the dates out. This plan adds a **calendar** that does what a basic calendar app does, plus what only GAIFA can do:
- **Events and to-dos.** A reminder is a to-do with a time. Both repeat with the same rules, and both can have alerts.
- **Your view of it.** A **Calendar** entry in the sidebar, under Chat and above Outputs, opens a full page in the main view (day, week, month and agenda). A side panel in Chat, like Outlook's on the web, shows the day or the week next to your chats.
- **The agent's view of it.**
  - Tools to read, add and change items, and to read dates written in plain words.
  - A deterministic free-time finder.
  - Proposals you tick through: dates from a document, an imported `.ics`, a plan for your day.
  - Today's agenda (and all of tomorrow) in every chat's prompt.
  - Writes only when the judge agrees you asked for them.
- **Scheduled tasks on the calendar.** Tasks show as a layer, and a task can run once or N minutes before an event ("prep for this meeting").
- **In the app only.** Reminders show as toasts in the app and as an unread count on the Calendar entry. Nothing goes out of the app yet.

**Where things live:**
- **The `calendar` mod** (`services/calendar/`, port 5109) owns the data (`{databases}/calendar.db`), repeats, alerts, the date parser, free time, `.ics` import and export, its tools, its chat cards, its page and its chat panel.
- **The hub** gains three things any mod can use, so adding this mod still needs no calendar code in the hub:
  - a main-view page declared by a mod (`[ui] main`);
  - a side panel in Chat (`[ui] chat_panel`);
  - in-app notifications with an unread badge (`POST /api/notify`);
  - plus one approval action, `change` (a change to your records: the judge decides in Auto), which the calendar's preflight (`[agent] limits`) answers for its writes.
- **The agent mod** gains the agenda prompt part, two schedule kinds (`once`, `event`), the task layer's route and the history route.

**Touches:**
- architecture §4.1–4.3 (the manifest's `[ui]` and `[tools]`), §6 (hub routes), §14.1 (the agent's routes), §14.7 (the approvals order);
- the brief §5 (page modules) and a new §11.15 (the Calendar);
- the plans [scheduled-tasks](scheduled-tasks.md) (schedule kinds, runs, unattended calls), [projects](projects.md) (items in a project), [web-approvals](web-approvals.md) (the judge is d3-lite only), [chat-cards](chat-cards.md) (cards, `undo`, @-mentions), [chat-split](chat-split.md) (the Chat page's layout) and [settings-that-stick](settings-that-stick.md) (choices kept on the hub).

## 2. Gaps & unanswered questions

Answered by the user on 2026-11-09:
- **In:**
  - events and to-dos (a reminder is a to-do with a time);
  - repeating events and to-dos;
  - alerts on both;
  - `.ics` import and export;
  - plain-words dates as a tool;
  - a deterministic free-time finder with working hours and focus blocks;
  - scheduled tasks as a layer, and calendar tools in task runs;
  - prep tasks before events;
  - today's agenda in the prompt, as a setting;
  - events from documents;
  - planning your day;
  - a history layer, off by default;
  - items in projects;
  - a side panel in Chat.
- **Out for now:**
  - subscribing by link and two-way sync (later, and only into GAIFA, never out of it);
  - travel time;
  - invites, sharing and booking pages;
  - printing and the year view;
  - voice;
  - a widget on Overview;
  - holiday and birthday calendars (they're ordinary yearly events).
- **Notifications:** in the app only. A reminder that fires with no tab open stays unread: a count on the Calendar entry and a list of what fired.
- **The agent's writes:** only when the user explicitly asked, grounded by the Auto judge.
- **Deleting:** doesn't always ask: an item the agent made in this chat (a test, say) may be deleted by it like an edit.
- **Cloud models:** the agenda goes into the prompt whatever the model. No private calendars.
- **The agenda in the prompt:** today's events, to-dos due today, overdue to-dos, and all of tomorrow.
- **Scheduled tasks:** they gain "once" and "N minutes before an event (each occurrence)".
- **The page:** its own main view, like Chat. Clean, even, and easy to read with repeating events.

Assumed:
- **Ids:**
  - items `c_<10 hex>`, calendars `cal_<8 hex>`, alerts fired `f_<10 hex>`, proposals `pr_<10 hex>`;
  - an occurrence of a repeating item is `<item id>@<local start ISO>`.
- **Time:**
  - Times are wall-clock times with the machine's IANA zone at the time they were made (`tz`). All-day items are dates. Repeats expand in their item's zone and show in the machine's.
  - Daylight-saving gaps and repeats follow the scheduled-tasks rules: the next valid minute, and one occurrence.
- **The data model** follows iCalendar (RFC 5545), so `.ics` import and export map directly:
  - `RRULE`, `EXDATE`, and overrides by `RECURRENCE-ID` for "this one";
  - to-dos are `VTODO` with `DUE`;
  - alerts are `VALARM` with a trigger before the start (events) or at or before the due time (to-dos).
  - Libraries: `icalendar` and `python-dateutil` (rrule).
- **Calendars:** one to start, **Personal**. You add more (name and color), turn each on or off in views, and choose the default. A calendar can't be deleted while it has items unless they move or go to the trash with it.
- **Deleting:** an item goes to the **trash**, kept 30 days, restorable, then purged.
- **The agent's writes in each mode:** the mod's preflight (`[agent] limits = "POST /v1/limits"`) answers each call's action, and the hub's mode × action table decides:
  - reads are `read`;
  - adding, changing, completing, and deleting an item someone else made are `change`: refused in Plan, ask in Manual and **Accept edits** (that mode accepts file edits; a calendar isn't a file), the judge in Auto (failing closed to a card), run in Bypass;
  - deleting or changing an item the agent made **in this chat** that you haven't changed since (`source.kind = "agent"`, `source.thread`) is `edit`: it runs in Accept edits, Auto and Bypass, and asks in Manual.
  - Unattended runs refuse what would ask, unless pre-allowed.
  - Each write's result carries `undo`, so the turn's **Undo** reverses it.
- **Who the judge listens to:** it reads the user's own typed messages (`origin.said`). In a task run, the task's instructions are the user's words (scheduled-tasks §2).
- **The date parser** is deterministic, its own small grammar, not `dateparser`:
  - dates: "today", "tomorrow", weekdays, "next Fri", "Nov 14", "14/11", "in 3 days";
  - times: "1pm", "13:00", "noon";
  - ranges and lengths: "1–2pm", "for 90 min";
  - repeats: "every Tuesday", "every weekday at 9", "monthly on the 1st";
  - all-day: "all day".
  - It returns what it read plus the rest of the text (the title). Text it can't read answers `422 unreadable_when` with the part it stopped at, and the agent then passes ISO times.
  - Numeric dates follow the browser's locale setting, kept as `date_order` (`mdy` | `dmy`, default `mdy`) in the mod's settings.
- **Working hours and focus blocks:** working hours are per weekday (default Mon–Fri 09:00–17:00). Focus blocks are ordinary events with `busy: "focus"`. The free finder treats them as busy unless asked to include them.
- **Planning your day** is deterministic too. It takes the open to-dos (due soonest first, then priority, then those with an `estimate_min`, default 30) and places them in free time inside working hours, with 10-minute gaps. The agent can propose again with changes.
- **The agenda in the prompt** only changes when the calendar or the date changes. It lists the whole day, not "what's left", and no current time, so the prompt stays cached. It comes after Environment, so the parts before it stay cached too. It's capped at 40 lines; past the cap it says how many it left out.
- **A project's items:** an item may name one project (`project_id`). In that project's chats the agenda adds a "Project dates" list: the project's items in the next 14 days.
- **Alerts:**
  - Defaults: events 10 minutes before, to-dos at their time. An all-day event's alert is at 09:00 the day before. You set the defaults in the mod's settings.
  - A fired alert stays unread until you open it, mark it done or snooze it (5, 10 or 60 minutes, or tomorrow 09:00).
  - Alerts missed while the mod was down fire once, marked late, when it comes back. Ones over 24 hours old are only listed.
- **Prep tasks:**
  - A task with `{kind: "event", item, before_min}` runs once per occurrence.
  - A run missed while the agent was down runs late only if the event hasn't ended. Otherwise it's `skipped` (why `event passed`).
  - Deleting the item turns the task off with a problem (`event_gone`).
- **The task layer** shows each task's next times in the range (from the agent's schedules) and its runs (done, failed, skipped, unread). Clicking opens the task's page or the run's chat.
- **The history layer:** chats (a block per day with a turn in it), outputs and task runs, in a muted style, off by default and kept per view.
- **What the page remembers** (the view, the date, calendars on or off, the layers, the side panel's view) is kept on the hub (`/api/ui/store/calendar`, `hub.chat.panel`), never only in the browser. Settings (working hours, defaults, week start, date order, agenda in prompt) are in `data/state/calendar/settings.json`, which `gaifa backup` picks up.
- **The side panel** is a right-hand column on the Chat page. Its toggle sits in the Chat header, one panel shows at a time, it's 260–440 px wide (default 320) and resizable, and it becomes a drawer under 760 px.
- **Notifications:**
  - `POST /api/notify` publishes a `notification` event and adds an activity item.
  - Toasts can have up to 3 actions. Each action is a mod route that the UI calls through the hub's proxy.
  - A mod's unread count rides on the same route (`unread`). The hub keeps the latest count per mod in memory, so the mod posts it again when it starts.
- **Mod page modules:** a main view is `main: {mount(el, ctx)}` in the mod's `ui/page.js`, and a chat panel is `export default {mount(el, ctx)}` in its own file. Both use only `ctx` (brief §5).
- **The design:**
  - the hub's colour tokens; an 8-colour calendar palette checked for contrast in light and dark;
  - hour rows 48 px, gutters on an 8 px grid;
  - today and the now-line in the accent colour; weekends a shade quieter;
  - a repeating item marked by a small repeat glyph, never a different shape.

**Needs a human answer:** none. The judge eval's live run (4.5) loads d3-lite on this GPU; the user said yes on 2026-11-09.

## Phase 1 — The calendar mod and its data (L)

- [x] **1.1 The mod: `services/calendar/` (new, `gaifa new calendar`).**
  - **`service.toml`:**
    - `[run]`: `command = [".venv/bin/python", "server.py"]`, `port = 5109`, `health = "/health"`, `status = "/v1/status"`;
    - `env = { CALENDAR_DB = "{databases}/calendar.db", CALENDAR_STATE = "{root}/data/state/calendar" }`.
  - **Files:** `requirements.txt` (`fastapi`, `uvicorn`, `icalendar`, `python-dateutil`, `tzlocal`), `install.sh`, `README.md`, `ui/logo.svg` (a calendar glyph).
  - **The setup doc:** `setup/linux.md` with its `gaifa-setup` block (summary, steps, check `gaifa check calendar`; no models).
  - **`/v1/status`:** counts (items, calendars, unread alerts) and the next alert time.
  *Done when:* `gaifa check calendar` passes, `gaifa docs --check --strict` passes, and `services/calendar/tests/test_health.py` starts the app with a temp DB.
- [x] **1.2 The store: `services/calendar/store.py` (new).**
  - **Tables:**
    - `calendars(id, name, color, is_default, hidden, position, created)`;
    - `items(id, calendar_id, kind 'event'|'todo', title, notes, location, url, start, end, all_day, tz, due, done_at, priority 0–3, estimate_min, busy 'busy'|'free'|'focus', rrule, exdates JSON, project_id, alerts JSON, prep JSON, source JSON, created, updated, deleted_at)`;
    - `overrides(item_id, occurrence, fields JSON, cancelled)`;
    - `fired(id, item_id, occurrence, alert_at, fired_at, state 'unread'|'seen'|'done'|'snoozed', snooze_until, late)`;
    - `proposals(id, kind 'items'|'ics'|'plan', items JSON, source, created, accepted JSON)`;
    - `undo(id, ops JSON, created)`.
  - **Shapes:** `alerts` is `[{before_min}]` (to-dos: `0` = at the time). `prep` is `{task_id, before_min}`, set by Phase 6. `source` is `{kind: "ics"|"document"|"agent"|"you", ref?}`.
  - **`Store`:**
    - `calendars()`, `add_calendar`, `patch_calendar`;
    - `get`, `create`, `patch`, `trash`, `restore`, `purge(older_than)`;
    - `search(q, limit)`, `by_project(pid, frm, to)`;
    - `fired_list(state)`, `unread_count()`;
    - `record_undo(ops) -> id`, `undo(id)`.
  - **Rules:** every write is in one transaction and returns the inverse ops for undo. Titles are 1–200 characters and notes up to 8 000.
  *Done when:* `services/calendar/tests/test_store.py` covers CRUD, the default calendar, trash and restore, purge after 30 days, search, a project's items, and undo of a create, a patch and a trash.
- [x] **1.3 Repeats: `services/calendar/repeat.py` (new).**
  - **`occurrences(item, overrides, frm, to) -> list[Occ]`:**
    - expands `rrule` in the item's `tz`;
    - drops `exdates` and cancelled overrides;
    - applies the overrides' fields;
    - each `Occ` has `id`, `start`, `end` (to-dos: `due`), `all_day`, `item_id`, `recurring`.
  - **`edit(item, occurrence, scope 'this'|'following'|'all', fields) -> ops`:**
    - `this` writes an override;
    - `following` ends the series before the occurrence (`UNTIL`) and makes a new item from it;
    - `all` patches the item and keeps the overrides whose fields still apply.
    - Deleting with each scope works the same way (`EXDATE`, `UNTIL`, trash).
  - **To-dos:** completing a repeating to-do marks that occurrence done (an override with `done_at`). The next one shows.
  - **Edge cases:** the 31st in a short month follows RFC 5545 (skipped). The UI's monthly picker offers "last day" (`BYMONTHDAY=-1`).
  *Done when:* `services/calendar/tests/test_repeat.py` covers daily, weekly on several days, monthly by day and last day, yearly, `COUNT`/`UNTIL`, `EXDATE`, each edit and delete scope, a repeating to-do, an all-day series, and a DST change (`TZ` set in the test).
- [x] **1.4 Routes: `services/calendar/server.py`, `api_items.py` (new).**
  - **Calendars:** `GET/POST /v1/calendars`, `PATCH /v1/calendars/{id}`. `DELETE` takes `?items=move:<id>|trash`.
  - **Items:**
    - `POST /v1/items` takes `when` text or `start/end/due`, plus `all_day`, `rrule` or `repeat` text, `alerts`, `calendar`, `project_id`.
    - `GET/PATCH/DELETE /v1/items/{id}`, where `PATCH` and `DELETE` take `?occurrence=&scope=`.
    - `POST /v1/items/{id}/done` (`?occurrence=`, `undone=true` to reopen).
  - **Range:** `GET /v1/range?from=&to=&calendars=&kinds=` returns the occurrences, sorted, with each one's calendar colour.
  - **Search:** `GET /v1/search?q=`.
  - **Trash:** `GET /v1/trash`, `POST /v1/trash/{id}/restore`.
  - **Undo:** `POST /v1/undo/{uid}`.
  - **Answers:** every write answers `{item, undo: "/api/s/calendar/v1/undo/<uid>"}`, so the chat's generic **Undo this turn** picks it up (chat-turn.js `undoOf`). Errors use the envelope `{detail, code, data?}`.
  - **Events:** each change goes into `/v1/status`'s `rev`, and the page refreshes when `rev` moves (a `ctx.on('services')` tick). There's no stream of its own.
  *Done when:* `services/calendar/tests/test_api_items.py` covers each route, the scopes, `undo` in answers, a bad `when` (422), and the range across a DST change.
- [x] **1.5 Plain-words dates: `services/calendar/when.py` (new), `GET /v1/parse`.**
  - **`parse(text, now, tz, date_order) -> Parsed`** returns `{start?, end?, due?, all_day, rrule?, title, matched: [spans], confidence: "exact"|"assumed", assumed: [str]}`.
    - `assumed` says what it filled in, e.g. "no end: 1 hour", "Fri = Fri 14 Nov".
  - **The grammar** is §2's list. Times without am/pm between 1 and 7 are afternoon ("at 3" is 15:00), with an assumption noted.
  - **The route:** `GET /v1/parse?text=&kind=event|todo`.
  *Done when:* `services/calendar/tests/test_when.py` covers about 60 phrases (each grammar part, ranges, repeats, all day, both date orders, "next Fri" on a Friday, past times today moving to tomorrow for to-dos only, the title left over, and three unreadable ones).
- [x] **1.6 Free time: `services/calendar/free.py` (new), `GET /v1/free`, `POST /v1/plan`.**
  - **`free(frm, to, min_minutes, within: 'work'|'any', include_focus) -> [slot]`:** busy is events with `busy` other than `free`, plus focus unless `include_focus`. Each slot has `{start, end, minutes}`.
  - **`plan_day(date, todo_ids?) -> proposal`:** §2's placement. It answers a proposal (Phase 4 accepts it) with the to-dos that didn't fit.
  - **Settings:** `settings.py` keeps working hours, default alerts, week start, date order and `agenda_in_prompt` in `CALENDAR_STATE/settings.json`. `GET/PATCH /v1/settings`.
  *Done when:* `services/calendar/tests/test_free.py` covers overlapping events, all-day events, focus in and out, a slot shorter than the minimum, working hours by weekday, and a plan with due dates, priorities, estimates and leftovers.
- [x] **1.7 `.ics`: `services/calendar/ics.py` (new).**
  - **Import:** `POST /v1/import` (a file upload or `{ics}` text, up to 5 MB) answers a proposal of kind `ics` with every event and to-do. Read: `RRULE`/`EXDATE`/`RECURRENCE-ID`, `VALARM`, `TZID` (with `VTIMEZONE` or IANA names), and all-day dates. The proposal lists what was skipped and why. Items already imported (same `UID`, kept in `source.ref`) are marked "already here".
  - **Export:** `GET /v1/export.ics?calendars=` (everything, or some calendars) and `GET /v1/items/{id}.ics`.
  *Done when:* `services/calendar/tests/test_ics.py` covers import from fixture files (a Google export, an Outlook export, a syllabus with all-day dates, a series with an override), skipped parts, the "already here" mark, and a round trip that exports and imports to the same occurrences.

  *As built (1.1–1.7):* the proposal store (`proposals.py`, `api_more.py`: `/v1/proposals`, accept with one undo) landed here with import and plans, ahead of 4.3. An all-day event doesn't block free time. Who wrote an item is kept as `touched_by` (`agent` only while only the agent has changed it), for the preflight in 4.1. The worktree's setup index rows were added by hand: its submodule mods are empty, so `gaifa docs` there would drop them.

**Checks & deliverables — Phase 1**
- [ ] `services/calendar/tests` and `uv run pytest` are green. `gaifa check calendar` passes on a second hub (`--dev`, port 7078).
- [ ] Delivered: `services/calendar/` (`server.py`, `store.py`, `repeat.py`, `api_items.py`, `when.py`, `free.py`, `settings.py`, `ics.py`, `service.toml`, setup doc) and tests.

## Phase 2 — In-app notifications and alerts (M)

- [x] **2.1 The hub: `utils/routes/notify.py` (new), `utils/events.py`, `utils/services/views.py`.**
  - **`POST /api/notify`:**
    - **Body:** `{service, title?, body?, level: info|warn, route?, key?, actions?: [{label, op: "POST /v1/…"}], unread?: int}`.
    - **Checks:** `service` must be a known mod (`422 unknown_service`), `actions` at most 3, and each op a `POST` or `PATCH` path of that mod.
    - **With a title:** publishes `{type: "notification", id, ts, service, title, body, level, route, key, actions}` and adds an activity item (`Activity.add`, with the route).
    - **With `unread`:** keeps the mod's count in memory and publishes `{type: "badge", service, unread}`.
  - **Badges:** `GET /api/services` items carry `badge` (the count, when set).
  *Done when:* `utils/tests/routes/test_notify.py` covers a notification (event and activity), an unknown service, bad actions, the badge in the event and in `/api/services`, and a badge alone without a toast.

  Update architecture §6 and the brief §6 / §11.7.
- [x] **2.2 The UI: `web/Hub.dc.html`, `web/nav/nav-model.js`, `web/nav/sidebar.js`.**
  - **Toasts:** `onEvent('notification')` shows a toast with its title, body, an **Open** link (the route) and its actions. Each action calls `/api/s/<service><path>` and the toast closes on success. Notification toasts stay until closed (others still close after 4 s), at most 5 at once.
  - **Badges:** sidebar items (fixed and mods') draw `badge` as a small count (9+ past 9), updated on `badge` events.
  *Done when:* `utils/tests/web/notify.test.mjs` covers the toast model (actions, the route, staying open) and `nav.test.mjs` the badge on an item. Checked in the browser on the second hub with a notification posted by curl.

  Update the brief §11.7 and `web/PATCHES.md` (#84).
- [x] **2.3 Alerts: `services/calendar/alerts.py` (new), `api_alerts.py` (new).**
  - **The loop:** every 20 s, the alerts due since the last tick (from `occurrences`, the next 24 h kept in memory and rebuilt when `rev` moves) go into `fired` and are posted to `/api/notify`.
    - title: the item's title;
    - body: its time, e.g. "in 10 min · 14:00–15:00", or "due 17:00";
    - route: `#/calendar?item=<occ>`;
    - actions: Snooze 10 min, and **Done** for a to-do.
    - It then posts `unread`.
  - **Start-up:** missed alerts are handled per §2, and the count is posted again.
  - **Routes:** `GET /v1/alerts?state=` (fired, newest first), `POST /v1/alerts/{fid}/seen|done|snooze` (`{minutes | until}`), `POST /v1/alerts/seen-all`.
  - **Errors:** a hub that's down is retried on the next tick. A fired alert is never lost.
  *Done when:* `services/calendar/tests/test_alerts.py` (a fake clock and a fake hub) covers an event alert, a to-do at its time, an all-day alert, snooze and re-fire, done on a repeating to-do, missed alerts late and the 24 h limit, the count, and the hub being down.

**Wire — Phase 2:** notifications and badges are live for every mod; the calendar's alerts post them.

**Checks & deliverables — Phase 2**
- [x] On the second hub: an item set two minutes ahead with a 1-minute alert shows a toast with Snooze. Snoozed, it fires again. With the page closed, the badge counts it when the page opens.
  *As built (2026-11-09, a second hub on port 7079 from the worktree, `--dev`):* the item's alert fired 16 s after its time (`in 1 min · 18:03–19:03`), the Calendar item showed the badge 1 on load, a toast with Open and Snooze 10 min drew, and Snooze went through the proxy (the alert `snoozed`, the badge gone at once by its `badge` event). Found: `api.js` drops event types without an area, so `EVENT_AREA` maps `notification` and `badge` to `notify`; and an `sc-if` inside the toasts' `sc-for` stopped every toast from drawing, so the body and actions are spans shown by style.
- [x] Delivered: `utils/routes/notify.py`, the changed `events.py`, `views.py`, `Hub.dc.html`, `nav-model.js`, `sidebar.js`, the calendar's `alerts.py` and `api_alerts.py`, and tests.

## Phase 3 — The Calendar in the main view (L)

- [ ] **3.1 Main views declared by mods: `utils/manifest.py`, `utils/services/views.py`, `web/Hub.dc.html`, `web/nav/nav-model.js`.**
  - **The manifest:** `[ui] main = { label = "Calendar", after = "chat" }`, where `after` is one of `overview`, `chat`, `outputs`. The icon is the mod's `logo`. A mod id equal to a hub page (`overview`, `chat`, `outputs`, `models`, `settings`, `services`, `s`) is a manifest error.
  - **The views:** `main` goes into the service view (`main: {label, after}`), with `page_url`.
  - **The sidebar:** `groups()` puts each running or installed mod's main item after its `after` item, gated on the mod being present (like Memory with the agent). It has a badge (2.2). The tooltip is the mod's description.
  - **The route:** `#/<id>[/…][?…]` mounts the page module's `main.mount(el, ctx)` full-height with no padding (like Chat). `ctx.route` holds the rest of the hash. A stopped mod shows the usual `requireRunning` card with Start. The page is also listed in the command palette.
  *Done when:*
  - `utils/tests/manifest/test_ui_main.py` covers the field and a clashing id;
  - `nav.test.mjs` covers the item after Chat, its absence without the mod, and its `on` state (the test's fixed top items change);
  - `utils/tests/web/main-view.test.mjs` covers the route parse;
  - the contract test is still green.

  Update architecture §4.2–4.3 and the brief §5.
- [ ] **3.2 The page shell: `services/calendar/ui/page.js`, `ui/cal-shell.js` (new), `ui/cal-api.js` (new), `ui/cal-mock.js` (new).**
  - **The header:** Today, ‹ ›, the range's title ("November 2026", "Nov 9 – 15"), the view switch (Day · Week · Month · Agenda), search, and the quick-add box. Quick-add uses `GET /v1/parse` and shows what it read under the box before Enter. **New** has an Event / To-do choice.
  - **The left column (240 px):**
    - a mini month (click a day; the shown range shaded);
    - Calendars (colour dot, on/off, New calendar, edit);
    - Layers (Scheduled tasks, History; each a switch, filled in later phases);
    - **To-dos** (open, overdue first, a tick to complete);
    - **Reminders** (fired alerts, unread first, with Seen / Done / Snooze).
    - The column folds away under 1000 px.
  - **Keys:** `t` today, `d`/`w`/`m`/`a` views, `j`/`k` previous/next, `n` new, `/` search, `Esc` close.
  - **Kept on the hub:** the view, the date and calendars on/off (`calendar.view`, `calendar.date`, `calendar.on`; `ctx` store). `?item=<occ>` opens that item.
  - **`cal-api.js`:** the mod's routes through `/api/s/calendar`. **`cal-mock.js`:** two calendars, a week of events (a repeating one, an all-day one, an overlap), to-dos and fired alerts, used on `?mock`.
  *Done when:* `services/calendar/tests/ui/shell.test.mjs` (run by `services/calendar/tests/test_ui_js.py` with `node --test`, skipped without node) covers the range title per view, the keys, quick-add's preview and the stored choices.
- [ ] **3.3 Day and week: `ui/cal-grid.js` (new), `ui/cal-layout.js` (new).**
  - **`layout(occs, day) -> [{occ, top, height, col, cols}]`:** overlapping events share the width in even columns, and a short event keeps a 20 px minimum height.
  - **The grid:**
    - hour rows of 48 px, the working hours shaded, scrolled to 07:00 or now;
    - a now-line in the accent colour;
    - an all-day row on top, growing up to 3 rows then "+N";
    - to-dos with a time shown as a small chip at that time, with a tick.
  - **Drag:** drag on empty space to create (15-minute steps), drag an event to move, and drag its bottom edge to resize. A repeating event asks This / This and following / All on drop.
  *Done when:* `tests/ui/layout.test.mjs` covers overlaps (2, 3, a chain), the minimum height, events across midnight, the all-day row's overflow, and the 15-minute snapping of a drag.
- [ ] **3.4 Month and agenda: `ui/cal-month.js` (new), `ui/cal-agenda.js` (new).**
  - **Month:**
    - weeks starting on the setting's day;
    - each day lists up to 3 items (all-day and multi-day as bars across days), then "+N more" opening the day;
    - today ringed;
    - a click on empty space starts a new all-day item.
  - **Agenda:** 30 days from the date, grouped by day, with empty days left out and "Load more". Each row has the time, the calendar colour, the title, the location, the repeat glyph and the project chip.
  *Done when:* `tests/ui/month.test.mjs` covers the weeks of a month for each week start, multi-day bars across a week break, and "+N more"; `agenda.test.mjs` covers the grouping and Load more.
- [ ] **3.5 The editor: `ui/cal-edit.js` (new), `ui/cal-repeat.js` (new).**
  - **A popover** for a quick look: title, time, calendar, Edit, Delete, Done (to-dos). **A side sheet** for editing.
  - **The sheet's fields:**
    - Event / To-do;
    - title; when (date pickers, all day, or typed words through `/v1/parse`);
    - repeat (`cal-repeat.js`: Never, Daily, Weekdays, Weekly on days, Monthly on day N or last day, Yearly, Custom with interval and end: never, on a date, after N; it shows the rule in words);
    - alerts (add or remove; the defaults filled in);
    - calendar; busy (busy, free, focus); location; link; notes;
    - project (the agent's projects through `/api/s/agent/v1/projects`, hidden when the agent mod is absent);
    - to-dos: priority and estimate.
  - **Saving or deleting** a repeating item asks the scope. Deleting says "moved to the trash, kept 30 days". A toast offers Undo.
  *Done when:* `tests/ui/repeat.test.mjs` covers the picker's rule for each choice and its words back. `edit.test.mjs` covers the scope question and the fields for each kind.
- [ ] **3.6 Import, export and the trash: `ui/cal-files.js` (new).**
  - **Import:** an `.ics` dropped on the page, or **Import…**, shows the proposal sheet (Phase 4's component, built here first) with every item ticked except those "already here", the calendar to add them to, and Add N.
  - **Export:** a calendar's menu has **Export .ics**.
  - **Trash:** a list with Restore.
  *Done when:* `tests/ui/files.test.mjs` covers the proposal sheet's ticks and the count.

  Write the brief §11.15 (the Calendar page) and add `web/PATCHES.md` rows for the hub parts.

**Wire — Phase 3:** the sidebar's Calendar entry under Chat, and `#/calendar` against the live mod.

**Checks & deliverables — Phase 3**
- [ ] In the browser on the second hub (live and `?mock`):
  - each view draws, even and aligned, in light and dark;
  - a drag creates, moves and resizes;
  - a repeating event's "this one" edit shows only on that day;
  - an `.ics` from another calendar imports;
  - the item from a toast's Open opens;
  - no console errors.
  - Screenshots go in `docs/reference/calendar-2026-11/`.
- [ ] Delivered: the hub's `main` view, `services/calendar/ui/` (`page.js`, `cal-*.js`), and tests.

## Phase 4 — The agent's tools and approvals (L)

- [ ] **4.1 The `change` action and the calendar's preflight: `utils/tools/approvals.py`, `services/calendar/limits.py` (new).**
  - **The hub:** `ACTIONS` gains `change` ("changes to your records"): `plan` deny, `manual` ask, `accept_edits` ask, `auto` judge, `bypass` allow. Nothing else in the order changes.
  - **The judge:** `judge_rules.classify` leaves calendar tools `unsure`, so the decide model answers its three questions against the user's own words. A call with no `origin.said` asks without the model.
  - **`POST /v1/limits`** (`[agent] limits`): `{tool, arguments, origin}` → `{action, allow_bypass: true, preview}`: `read` for reads and proposals; `edit` for a delete or change of an item the agent made in `origin.thread` and nobody changed since; `change` for the other writes; `refuse` for an unknown item.
  *Done when:* `utils/tests/tools/test_approvals_change.py` covers the action in each mode, a grant and the allow list still allowing, and unattended refused; `services/calendar/tests/test_limits.py` covers each answer.

  Update architecture §14.7 (the table) and docs/mods.md (the actions a preflight may answer).
- [ ] **4.2 The tools: `services/calendar/service.toml` `[tools]`.**

  | Tool | Op | Risk | Notes |
  |---|---|---|---|
  | `calendar_agenda` | `GET /v1/agenda` | read | `from`, `to` (or `day: today\|tomorrow\|<date>`, `days`). Occurrences and to-dos, short. `core` |
  | `calendar_search` | `GET /v1/search` | read | |
  | `calendar_when` | `GET /v1/parse` | read | Plain words to exact times, with what it assumed. `core` |
  | `calendar_free` | `GET /v1/free` | read | |
  | `calendar_add` | `POST /v1/items` | write (`change`) | `when` words or ISO, `repeat` words or `rrule`. `core` |
  | `calendar_update` | `PATCH /v1/items/{id}` | write (`change`, or `edit` for its own) | `occurrence`, `scope` |
  | `calendar_done` | `POST /v1/items/{id}/done` | write (`change`) | |
  | `calendar_delete` | `DELETE /v1/items/{id}` | write (`change`, or `edit` for its own) | To the trash |
  | `calendar_propose` | `POST /v1/proposals` | read | Adds nothing; the user ticks and adds |
  | `calendar_plan_day` | `POST /v1/plan` | read | A proposal |

  - **Descriptions** tell the agent to:
    - use `calendar_when` when unsure of a date and say the exact date it chose;
    - add or change only what the user asked for;
    - use `calendar_propose` for more than 3 items or for dates read from a document, a page or an `.ics`;
    - never use `calendar_add` for those.
  - **`GET /v1/agenda`** answers compact rows (`{id, kind, title, start, end, all_day, due, done, calendar, project, recurring}`) with `cap_kb = 16`.
  *Done when:* `services/calendar/tests/test_tools.py` checks the manifest's tools load in the catalog (a fake hub), with each risk, and `/v1/agenda`'s shape.
- [ ] **4.3 Proposals: `services/calendar/proposals.py` (new), `api_proposals.py` (new).**
  - **`POST /v1/proposals`:** `{items: [item fields with when words or ISO], source: {kind: "document"|"agent", ref?, title?}}`, up to 200 items. Each item is parsed. Items that couldn't be read are kept with their problem.
  - **The other routes:** `GET /v1/proposals/{id}` and `POST /v1/proposals/{id}/accept` (`{ids, calendar?, project_id?}`). Accepting creates them in one undo.
  - **Accepting is the user's click on the card,** a request from the UI through the hub's proxy, not a tool call, so it needs no approval.
  - **Plans and imports** (`/v1/plan`, `/v1/import`) answer proposals the same way.
  *Done when:* `services/calendar/tests/test_proposals.py` covers a proposal with readable and unreadable items, accepting some, the undo, and a plan accepted.
- [ ] **4.4 Chat cards and mentions: `services/calendar/ui/chat.js` (new), `service.toml` `[ui] chat`, `[[agent.mentions]]`.**
  - **Cards:**
    - `result:calendar_add|update|done`: the item as a chip with its colour, day and time, repeat words and calendar, plus Open in Calendar (Undo is the turn's).
    - `result:calendar_agenda`: a compact day list.
    - `result:calendar_propose|plan_day`: the proposal sheet from 3.6 inline, with ticks, the calendar, the project and Add N. Once added it reads "Added N · Undo".
    - `approval:calendar_add|update`: the item as it would be, with the fields editable (`ask = ["when", "title", "calendar"]`).
  - **Mentions:** `kind = "calendar"`, listing Today, Tomorrow, This week and the next 20 items, with `fills = ["calendar_agenda.day"]`. An item mention gives its id to the agent's text.
  *Done when:* `services/calendar/tests/ui/chat.test.mjs` covers each card's model, the proposal card's accept, and the mention list.
- [ ] **4.5 The judge eval: `services/agent/evals/judge/calendar.py` (new), `bench.py`, `run.py`.**
  - **Cases:** about 30, each the user's words with one calendar call:
    - asked for (add "lunch with Sam Friday", move "the dentist" to 3, complete "pay rent");
    - not asked for (adding dates found in a document the user only asked to summarise, moving an event the user didn't name, adding at a different time than asked, deleting through an update);
    - task runs whose instructions ask for calendar changes.
  - **The runner:** `run.py --source calendar`.
  *Done when:* `utils/tests/tools/test_judge_calendar.py` checks the cases load and that the rules never allow one alone. The live d3-lite run (the user said yes, 2026-11-09) is recorded in `docs/agent-eval.md`: overreach allowed (target 0) and asked-for calls that would have asked.

**Wire — Phase 4:** the calendar tools in Chat, cards, mentions, and the judge's decision on writes.

**Checks & deliverables — Phase 4**
- [ ] On the second hub (the remote test LLM, or the scripted model when it's down, as in scheduled-tasks Phase 2):
  - "remind me to call the bank tomorrow at 10" in Auto adds a to-do with its alert, and the card shows it;
  - Undo removes it;
  - a summary of a document with dates adds nothing until its proposal card's Add;
  - deleting an event you made shows a card, and the agent deletes a test event it made itself without one.
- [ ] Delivered: the hub's `change` action, the calendar's preflight, the calendar's tools, `proposals.py`, `ui/chat.js`, the eval cases, and tests.

## Phase 5 — The agenda in the prompt, and projects (M)

- [ ] **5.1 The agenda text: `services/calendar/agenda.py` (new), `GET /v1/agenda/prompt`.**
  - **`?date=&project=`** answers `{text, rev}`. The text has:
    - **Today, <Mon 9 Nov>:** every item;
    - **To-dos:** due today and overdue;
    - **Tomorrow, <Tue 10 Nov>:** every item;
    - with `project`, **Project dates (14 days)**.
  - **Rows:** each is `HH:MM–HH:MM Title (calendar) [id]`, with all-day and to-do forms, and repeats marked.
  - **Stable:** no "now" and no relative times, so the text is the same all day until something changes. Capped per §2. An empty answer when `agenda_in_prompt` is off.
  *Done when:* `services/calendar/tests/test_agenda.py` covers each section, the cap, project dates, the setting off, and the same text at 08:00 and 20:00 of one day.
- [ ] **5.2 The prompt part: `services/agent/agent/prompting.py`, `prompts.py`, `context.py`, `hubapi.py`.**
  - **`ctx.chat_agenda(thread)`:** like `chat_folders`, only when the calendar mod is ready and its tools aren't turned off in the chat. It calls `GET /api/s/calendar/v1/agenda/prompt?date=<local today>&project=<the chat's project>`, cached by `(date, project, rev)`, and gives None on any error.
  - **The part:** `parts["agenda"]`, a section **Your calendar** after Environment. A line says the agent can read more with `calendar_agenda` and must ask before adding. It's counted in the context meter (`sizes`). Task runs read it too.
  *Done when:* `services/agent/tests/test_prompt_agenda.py` covers the part present, its place, absent when the mod is down or turned off in the chat, the project passed, and the cache.

  Update architecture §14 (the prompt's parts).
- [ ] **5.3 Projects: `services/calendar/ui/`, `web/chat/chat-project-panels.js`.**
  - **The calendar:** items carry `project_id` (the editor, cards and proposals since Phase 3), with a project filter in the page's search.
  - **The project page:** a **Dates** panel with the project's next 14 days and New (the project preset), read from the mod and shown only when it's present.
  *Done when:* `utils/tests/web/chat-project.test.mjs` covers the panel with and without the mod.

**Checks & deliverables — Phase 5**
- [ ] With the agent on the second hub, "am I free at 3 tomorrow?" is answered from the prompt (no tool call in the turn). In a project's chat, a project deadline is named.
- [ ] Delivered: `agenda.py`, the agent's part, the project's Dates panel, and tests.

## Phase 6 — Scheduled tasks and the calendar (L)

- [ ] **6.1 Once: `services/agent/agent/tasks/when.py`, `store.py`, `schedule.py`, `web/chat/chat-when.js`, `chat-task-edit.js`.**
  - **The kind:** `{kind: "once", at: "YYYY-MM-DDTHH:MM"}` (local). `next_after` answers None after it, and `describe` reads "Once, Fri 14 Nov 07:00".
  - **The loop:** `tick` and the store accept None. A once task that ran is turned off (`why: "ran once"`). A missed once runs late per the usual rule.
  - **The editor:** a **Once** choice with a date and time.
  *Done when:* `test_task_when.py`, `test_task_schedule.py` and `chat-tasks.test.mjs` cover once: next, run and turned off, missed, and the picker.
- [ ] **6.2 Before an event: `tasks/when.py`, `tasks/event_due.py` (new), `store.py` (migration), `check.py`.**
  - **The kind:** `{kind: "event", item: "c_…", before_min: 0–1440}`.
  - **`EventDue.next(task, now)`** asks the calendar mod for the item's next occurrence (`GET /api/s/calendar/v1/items/{id}/next?after=`), so `tick` awaits it for these tasks. Answers are cached for 5 minutes and dropped when the calendar's `rev` moves.
  - **Runs:** `task_runs` gains `occurrence`. A run per occurrence happens once, and the missed rule is §2's.
  - **Checks:** the item must exist and not be in the trash (`event_gone` turns the task off). The calendar mod being down is a warning, and the run waits.
  - **The calendar side:** `GET /v1/items/{id}/next` is a new route there.
  *Done when:* `services/agent/tests/test_task_event.py` (a fake calendar) covers next from a repeating event, a moved occurrence, one run per occurrence, missed before and after the event's end, the item gone, and the mod down.
- [ ] **6.3 Prep from the event: `services/calendar/ui/cal-edit.js`, `ui/cal-prep.js` (new), the agent's `api_tasks.py`.**
  - **The sheet:** the event editor gets **Prep task**: instructions ("Gather my notes on… and write a brief"), minutes before, model and mode (defaults from Settings → Agent), and pre-allows.
  - **Saving:** creates the task through `POST /api/s/agent/v1/tasks` with the event kind and a name "Prep: <title>", and stores `prep` on the item. The item shows a small prep mark and opens its task page.
  - **Deleting the event** asks whether to delete its prep task too.
  *Done when:* `services/calendar/tests/ui/prep.test.mjs` covers the task body and the item's mark; `test_tasks_api.py` covers the event kind's checks.
- [ ] **6.4 The task layer: the agent's `api_tasks.py` (`GET /v1/tasks/calendar`), `services/calendar/ui/cal-layers.js` (new).**
  - **`GET /v1/tasks/calendar?from=&to=`:** each enabled task's due times in the range (from `next_after`, or the events for event kinds) and its runs there (`state`, `seen`, `thread_id`). At most 200 per task.
  - **The page:** a **Scheduled tasks** layer, on by default, draws due times as thin marks with the clock icon and runs as small chips coloured by state. A click opens `#/chat/tasks/<id>` or the run's chat.
  - **An empty slot's menu** has **Schedule a task here**, which opens the task editor with Once at that time (`#/chat/tasks?new=once&at=`).
  *Done when:* `services/agent/tests/test_tasks_calendar.py` covers the range for each kind and the runs; `tests/ui/layers.test.mjs` covers the marks and the new-task link.

  Update architecture §14.1 and the scheduled-tasks section of the brief §11.13.

**Checks & deliverables — Phase 6**
- [ ] On the second hub: a prep task 2 minutes before a test event runs once, its chat opens from the calendar, and the next occurrence shows its mark. A once task runs and turns off.
- [ ] Delivered: `tasks/event_due.py`, the changed `when.py`, `store.py`, `schedule.py`, `check.py`, `api_tasks.py`, `chat-when.js`, `chat-task-edit.js`, the calendar's `cal-prep.js` and `cal-layers.js`, and tests.

## Phase 7 — The side panel in Chat (M)

- [ ] **7.1 Chat panels declared by mods: `utils/manifest.py`, `utils/services/views.py`, `web/chat/chat.js`, `web/chat/chat-panel.js` (new).**
  - **The manifest:** `[ui] chat_panel = { module = "ui/panel.js", label = "Calendar" }`.
  - **The Chat page:** a third column after the main element. Its toggle is in the Chat header (an icon per panel-providing mod); one panel is open at a time.
    - It's resizable (260–440 px) with the split view's divider style.
    - Under 760 px it's a right drawer.
    - Open, which one and the width are kept as `hub.chat.panel` (`ui-store.js`).
    - The module gets `mount(el, ctx)` with `ctx.openRoute`, `ctx.insertText(text)` (into the focused pane's composer) and `ctx.store`.
  *Done when:* `utils/tests/web/chat-panel.test.mjs` covers the toggle, width limits, the stored state and the drawer under 760 px. `test_ui_main.py` covers the field.

  Update architecture §4.2 and the brief §11.13.
- [ ] **7.2 The calendar's panel: `services/calendar/ui/panel.js` (new).**
  - **The top:** Day · Week, a mini month folded under the date, and ‹ Today ›.
  - **Day:** a compact hour column (36 px rows) from the first item or 08:00, with the now-line.
  - **Week:** a list of the 7 days with their items.
  - **Below:** to-dos due and overdue, with ticks, and unread reminders.
  - **A click** opens the popover from 3.5. **Mention** on it inserts `@calendar:<id>` into the composer. Changes follow the mod's `rev`.
  *Done when:* `tests/ui/panel.test.mjs` covers each view's model and the mention text.

**Wire — Phase 7:** the Chat page's right panel with the calendar.

**Checks & deliverables — Phase 7**
- [ ] In the browser: the panel opens next to a split chat, resizes, keeps its state after a reload, follows an item the agent added, and draws as a drawer at phone width.
- [ ] Delivered: `web/chat/chat-panel.js`, the changed `chat.js`, the calendar's `ui/panel.js`, and tests.

## Phase 8 — The history layer (S)

- [ ] **8.1 The agent: `GET /v1/history?from=&to=` in `services/agent/agent/server.py`, `store.py`.** Per day, the chats with a user turn in it: `{thread_id, title, project, first, last, turns}`. Task runs are flagged. It reads the events' times and is capped at 500.
  *Done when:* `services/agent/tests/test_history.py` covers a chat across two days, archived chats included, and the cap.
- [ ] **8.2 The layer: `services/calendar/ui/cal-layers.js`.** **History** is off by default and kept per view. In muted blocks it draws:
  - chats from their first to their last turn that day (at least 15 minutes);
  - outputs as dots at their time (`GET /api/outputs?from=&to=`);
  - task runs from 6.4.

  A click opens the chat or the output.
  *Done when:* `tests/ui/layers.test.mjs` covers the history blocks' layout next to events.

**Checks & deliverables — Phase 8**
- [ ] In the browser: last Tuesday in Week view shows its chats and outputs with History on, and nothing with it off.
- [ ] Delivered: `/v1/history`, the History layer, and tests.

## Phase 9 — On the installed hub (S)

- [ ] **9.1 The live check.** `gaifa setup calendar`, then `gaifa restart` and the agent restarted:
  - the sidebar shows Calendar under Chat;
  - an event and a repeating to-do made on the page fire their alerts as toasts, and the badge counts the unseen one;
  - a chat (Auto, d3-lite) adds an event you asked for and asks for one you didn't;
  - a syllabus PDF gives a proposal card;
  - a prep task runs before an event;
  - the Chat panel shows the day;
  - `gaifa backup` includes `calendar.db` and its settings.

  The test items, calendars and tasks are deleted. CLAUDE.md's status, the plans index, `docs/structure.md` and `docs/agent-eval.md` are updated.

## 4. Deliverables

| Deliverable | Description | Location |
| --- | --- | --- |
| The calendar mod | data, repeats, routes, undo, trash | `services/calendar/server.py`, `store.py`, `repeat.py`, `api_items.py` |
| Dates in words | the deterministic parser | `services/calendar/when.py` |
| Free time and plans | the free finder, working hours, the day planner, settings | `services/calendar/free.py`, `settings.py` |
| `.ics` | import as a proposal, export | `services/calendar/ics.py` |
| Alerts | the loop, fired alerts, snooze and done | `services/calendar/alerts.py`, `api_alerts.py` |
| Proposals | from documents, imports and plans; accept with undo | `services/calendar/proposals.py`, `api_proposals.py` |
| Agenda | the prompt's text | `services/calendar/agenda.py` |
| The page | shell, day/week, month, agenda, editor, repeat picker, files, prep, layers | `services/calendar/ui/page.js`, `ui/cal-*.js` |
| Chat | cards, mentions, the side panel | `services/calendar/ui/chat.js`, `ui/panel.js` |
| Setup | the setup doc | `services/calendar/setup/linux.md` |
| Hub | notifications and badges, mod main views and chat panels, the `change` action | `utils/routes/notify.py`, `utils/manifest.py`, `utils/tools/approvals.py`, `web/Hub.dc.html`, `web/nav/`, `web/chat/chat-panel.js` |
| Agent | the agenda part, once and event schedules, the task layer, history | `services/agent/agent/prompting.py`, `tasks/when.py`, `tasks/event_due.py`, `api_tasks.py`, `server.py` |
| Eval | calendar judge cases | `services/agent/evals/judge/calendar.py` |
| Tests | the mod's (Python and node), the hub's, the agent's, the web's | `services/calendar/tests/`, `utils/tests/routes/test_notify.py`, `utils/tests/tools/test_approvals_change.py`, `utils/tests/manifest/test_ui_main.py`, `services/agent/tests/test_task_event.py`, `test_prompt_agenda.py`, `utils/tests/web/chat-panel.test.mjs` |
