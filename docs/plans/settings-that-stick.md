# Plan: settings that stick: preferences kept in `config.toml`, and saves that never drop what another save wrote

**Asked for:** 2026-11-08 · **Status:** Planned

## 1. Introduction

The user changes a setting, it works for a while, then it is back to what it was before. The first one they noticed is Settings → Agent → **Steps between messages**: they choose "Split at each message", and later chats are drawn as "One fold per turn" (the default) again. The goal (2026-11-08): everything the user chooses is kept on this machine, in GAIFA's files, and nothing depends on the browser. Looking at the code, two problems cause this.

1. **Some preferences live only in the browser.** `gaifa.chat.steps` is a `localStorage` key (`web/chat/chat-ui.js` `usePref`, read by `chat-activity.js` `TurnView` and written by `chat-settings.js` `ModelsCard`); `config.toml` never sees it. A `localStorage` value belongs to one browser profile *and* one origin. It is gone, or was never there, when: the site data is cleared (LibreWolf, this machine's browser, clears cookies and site data on close by default); the page is opened as `localhost:7000` instead of `127.0.0.1:7000`; or another browser, a private window or another port is used. Other preferences work the same way (inventory below). Theme and density do have a copy in `config.toml` (`[ui]`), but the browser's copy wins over it (`Hub.dc.html` `loadExtras`), so the two can disagree.
2. **Saves overwrite lists with an old copy.** Every writer of `config.toml` lists sends the *whole list* from a copy it loaded earlier, and the hub replaces the list (`utils/settings.py` `_merge`/`save`). The command rules (`[agent.judge] allow_commands` / `ask_commands`, the "commands" that go missing) have three writers: the Settings page's draft (`web/settings/schema.js` `saveBody`, loaded once when the page opens); "Always allow" under Judged calls (`web/chat/chat-judge.js` `JudgedList.always`, with its own copy loaded at mount); and the rules editor (`chat-rules.js`). Example: the page is open, a rule is added from a chat or another tab, then the page saves its own edit to the list. The new rule is lost. On the Settings page, "Always allow" only adds the rule to the draft ("save the page to keep it"), so leaving without Save also loses it. The tool permission globs (`[agent.permissions]`), the services' order and every other list behave the same. Nothing tells an open page that another one saved.
The approach: Phase 1 reproduces both causes with failing tests. Phase 2 makes saves safe: the hub merges a change with what is saved now (three-way, against the value the writer started from), saves one at a time, and announces each save so every open page updates. Phase 3 moves the chat's and the hub's preferences into `config.toml` (`[ui.chat]`, `[ui.overview]`), with the browser's copy kept only as a cache for the first paint. Phase 4 moves everything else the browser keeps (the open panes, folded Settings groups, recent copy formats, table sorts) and the mods' pages' choices (the `store` in `web/mod-kit.js`) to small JSON files under `data/state/ui/`. Only unsent text stays in the browser. Touches architecture §9 (`config.toml`) and §6 (hub routes), the brief §11.7 (the API contract) and §11.13 (Chat), docs/mods.md (the page `store`), and the plans [settings-redesign](settings-redesign.md) (the page, `saveBody`, instant rows) and backend-plan Phase 33 (`[ui.nav]`, the first preference synced this way).

### Preferences kept in the browser today

| Key | What | Plan |
| --- | --- | --- |
| `gaifa.chat.steps` | Steps between messages (`fold` / `split`) | `[ui.chat] steps` (3.1) |
| `gaifa.chat.list` | The chat list's view (grouping, sort, filter; `chat-groups.js`) | `[ui.chat] list` (3.1) |
| `gaifa.chat.environment` | The environment a new chat starts in (`chat-env.js`) | `[ui.chat] environment` (3.1) |
| `hub.theme`, `hub.density` | Theme, density (already in `[ui]`, browser wins) | config wins (3.3) |
| `hub.ovView`, `hub.tlRange`, `hub.svcRange` | Overview view, timeline and service chart ranges | `[ui.overview]` (3.1) |
| `hub.nav` | The sidebar (already `[ui.nav]`, Phase 33) | unchanged: the pattern 3.3 follows |
| `gaifa.chat.layout` | Open panes and their chats (`chat-layout.js`) | `data/state/ui/hub.json` `chat.layout` (4.3) |
| `gaifa.settings.open` | Which Settings groups are folded | `data/state/ui/hub.json` `settings.open` (4.3) |
| `gaifa.chat.copyModes` | Recently used copy formats (a log) | `data/state/ui/hub.json` `chat.copyModes` (4.3) |
| `hub.tableSort` | A table's sort column | `data/state/ui/hub.json` `table.sort` (4.3) |
| mods' `store` keys (`tts.speak`, `stt.preset`, `comfy.filter`, `relay.window`, `gen3d.create`, `lcpp.chatTarget`, `comfy.values.<wf>`, …) | Each mod page's remembered choices | `data/state/ui/<mod>.json` (4.1–4.2) |
| `tts.draft`, the composer's unsent text | Text being typed | stays in the browser: not a choice |
| `gaifa.sessions.restoreDismissed` (`sessionStorage`) | "Restore" dismissed for this tab | stays: lasts one tab by design |

## 2. Gaps & unanswered questions

- **Which layout should stick?** (answered 2026-11-08): Split at each message. The user picks it, and chats later go back to one fold per turn (the default, after the browser forgot). A turn drawn as two folds is not the problem, so nothing changes in `chat-turn.js`.
- **What moves off the browser?** (answered 2026-11-08): everything the user chooses. *Assumption:* unsent text (drafts) and the one-tab `sessionStorage` flag stay in the browser, since they aren't choices.
- **How the browser is opened:** *Assumption:* sometimes `127.0.0.1:7000` and sometimes `localhost:7000` (or LibreWolf clears site data on close). Either way Phase 3 fixes it; 1.1 records which is true on this machine.
- **Preferences per machine or per browser?** *Assumption:* per machine (one `config.toml`), the same for every browser and tab, as `[ui.nav]` already is. A browser that wants something different is out of scope.
- **Two writers changing the same scalar at once** (both started from 0.35, one sets 0.4, the other 0.5): *Assumption:* the later save gets `409 settings_conflict` naming the field, and the page shows "Changed elsewhere since you opened this page", with **Use theirs** / **Keep mine**. Lists merge without asking (the additions and removals of both are kept).
- **Where the mods' page choices and the view state go:** *Assumption:* `data/state/ui/<mod>.json`, and `data/state/ui/hub.json` for the hub's own (not `config.toml`). They are free-form values the hub can't check, and `gaifa backup` already copies `data/state/*/*.json` under 1 MB. Each key is capped at 16 KB and each file at 256 KB. Drafts (`tts.draft`) stay in the browser, through `store.local`.
- **The open panes with two tabs open:** *Assumption:* one layout per machine. The last change is saved, and a tab opened later starts from it. Tabs already open keep their own panes until reloaded, so two tabs don't fight over the layout.
- **Old browser values:** *Assumption:* imported once. On the first load after 3.3, a browser value that differs from the default, for a key `config.toml` doesn't set, is saved to the hub, then marked done (`gaifa.prefs.imported`). A value `config.toml` already sets wins and the browser's copy is replaced.

## Phase 1 — Find what's lost (S)

- [ ] **1.1 Reproduce on the installed hub, and record it in this plan.**
  - **Browser:** with Steps set to Split on `127.0.0.1:7000`, open `localhost:7000`, restart the browser, then a private window. Note which ones show Fold. In LibreWolf, read Settings → Privacy → "Delete cookies and site data when LibreWolf is closed", and its exceptions.
  - **Lost update:** open Settings → Permissions, add a command rule there without saving, add another from a chat's Judged calls "Always allow" (or a second tab), then Save the page. The second rule is gone.
  *Done when:* the plan's §2 records what happened in each case (which of these lost Split on this machine).
- [ ] **1.2 Failing tests for each cause.**
  - `utils/tests/settings/test_settings_lost_update.py`: a `PUT /api/settings` adds `judge.allow_commands: ["a", "b"]` from base `["a"]` after another PUT saved `["a", "c"]`; the file must hold `a`, `b`, `c` (fails today). Two concurrent PUTs to different keys both land.
  - `utils/tests/web/ui-prefs.test.mjs`: a `getSettings` with `ui.chat.steps = "split"` and an empty `localStorage` must give `split` (fails today: there is no such key).
  *Done when:* the tests exist and fail for the reasons above; `uv run pytest` is otherwise green (the new ones are marked expected to fail, then unmarked by the step that fixes each).
## Phase 2 — Saves that keep what others saved (M)

- [ ] **2.1 Three-way merge, one save at a time: `utils/settings.py`, `utils/routes/settings.py`.**
  - **Body:** `PUT /api/settings` takes an optional `base`: `{section: {key: value}}`, the value each changed key had when the writer loaded it. Without `base`, a key is replaced as today (the CLI's `cli_setup_config.py` and old pages keep working).
  - **Merge** (`_merge3(current, patch, base)`): for a list key, the result is the current list, plus what the writer added (in its order), minus what it removed. For a dict key (`services.enabled`, `ui.dashboard.ranges`), the same per entry. For a scalar, it is the writer's value when `current == base` or `current == value`; otherwise `409` with code `settings_conflict`, `data: {field, current, yours}`.
  - **One at a time:** an `asyncio.Lock` on the hub (`hub.settings_lock`, made in `create_app`'s lifespan) around `save()` and the `PUT /api/services/{id}/config` save (`utils/routes/services.py`), so two saves can't read the same `before`.
  - **Revision:** `GET /api/settings` and every save return `rev` (a counter kept in memory, plus the `config.toml` mtime). The page sends it back. A `rev` that is behind only means `base` is used. It is never refused on its own.
  *Done when:* `test_settings_lost_update.py` passes, `test_settings_conflict.py` covers the scalar 409 and the both-equal case, and the existing settings tests pass unchanged. Update architecture §6 (the route), §9 (how saves merge) and the brief §11.7 (`saveSettings(patch, base)`, the new error code).
- [ ] **2.2 Every writer sends what it started from: `web/api.js`, `web/settings/schema.js`, `web/chat/chat-judge.js`, `web/chat/chat-rules.js`, `web/mock.js`.**
  - `api.saveSettings(patch, {base})` sends `base`; `saveBody(draft, orig, secs)` returns `{patch, base}` with `base` taken from `orig` for each changed key.
  - **Always allow** (`JudgedList.always`) sends `{judge: {allow_commands: [...old, p]}}` with `base` = the old list. On the Settings page it **saves at once** (after the confirm, as it does in a chat), and the page's `orig` and draft take the answer. "save the page to keep it" goes away. The rules editor (`CommandRules`) and the tool permission lists do the same.
  - The mock (`web/mock.js`) merges and refuses the same way, so `?mock` pages behave like the hub.
  *Done when:* `utils/tests/web/settings-schema.test.mjs` covers `saveBody`'s `base`; `api.test.mjs` the body; `chat-judge.test.mjs` (new or extended) that Always allow sends the old list as `base`; the contract test still passes.
- [ ] **2.3 Open pages follow every save: `utils/settings.py`, `web/Hub.dc.html`, `web/settings/settings.js`.**
  - **Event:** after each save the hub publishes `{type: "settings", rev, changed: [<dotted keys>]}` on `hub.bus` (the `/api/events` stream).
  - **Settings page:** on that event, reload settings. Keys the user hasn't touched take the new value in both `orig` and the draft. A touched key whose saved value changed is marked "Changed elsewhere", with **Use theirs** / **Keep mine** (the same banner as the 409 from 2.1).
  - **Hub shell:** `onEvent` reapplies `ui.*` (theme, density, nav, and 3.x's keys) from the event's reload, so every tab follows.
  *Done when:* `utils/tests/settings/test_settings_event.py` (a save publishes the event with its keys); `settings-page.test.mjs` (or the schema test) covers merging a reload into a draft with touched and untouched keys. Browser check on a second hub: two tabs on Settings → Permissions; a rule added in one shows in the other without a reload, and saving the other keeps both. Update architecture §6 (the event) and the brief §11.7.

**Checks & deliverables — Phase 2**
- [ ] On the installed hub: Settings → Permissions open with an edit to the tool list, a command rule added from a chat's Judged calls, then the page saved. `config.toml` holds both. `gaifa restart`, and both are still there.
- [ ] Delivered: `_merge3` and the lock in `utils/settings.py`, `base` in `api.js` and `saveBody`, Always allow saving at once, the `settings` event and the page's merge.

## Phase 3 — Preferences in `config.toml` (M)

- [ ] **3.1 The new keys: `utils/config.py`, `utils/settings.py`, `config.example.toml`.**
  - `UiCfg` gains `chat: ChatUiCfg` (`steps: Literal["fold", "split"] = "fold"`, `list: ChatListCfg` with the fields `chat-groups.js` `readView` keeps today, `environment: str | None = None`) and `overview: OverviewCfg` (`view: Literal[…] = "dashboard"`, `timeline_range: str = "24h"`, `services_range: str = "24h"`; the allowed ranges are the ones `Hub.dc.html` offers).
  - `settings.view` / `defaults` / `save` carry them, as `[ui.nav]` is (only values that differ from the default are written; `Replace` for the tables).
  - `config.example.toml` lists them, commented, under `[ui]`.
  *Done when:* `utils/tests/settings/test_settings_ui_prefs.py`: a save of `ui.chat.steps = "split"` writes `[ui.chat] steps = "split"`, back to `"fold"` removes the key, a bad value is a 422 naming the field; `GET /api/settings/defaults` has them. Update architecture §9.
- [ ] **3.2 One way to read a preference: `web/ui-prefs.js` (new), `web/chat/chat-ui.js`.**
  - `ui-prefs.js` keeps the hub's `ui` settings for the page. `load(api)` reads `GET /api/settings` once at start. It is refreshed by the `settings` event (2.3), and a cache in `localStorage` (`gaifa.ui.cache`) gives the first paint before the hub answers. `useUiPref(path, default)` returns `[value, set]`. `set` updates at once and saves `{ui: {...}}` with `base` (2.1), then puts the hub's answer in the cache. If the save fails, it keeps the value for this page and shows the error once ("Couldn't save: kept in this browser only").
  - `chat-ui.js` `usePref` stays for the per-browser keys in the inventory. The moved keys are read only through `useUiPref`.
  - `?mock`: the mock's settings hold `ui.chat`/`ui.overview`, so mock pages work the same.
  *Done when:* `ui-prefs.test.mjs` (1.2's case passes): the hub's value wins over the cache, the cache is used before `load` resolves, a `settings` event updates subscribers, a failed save keeps the value locally. Update the brief §11.7.
- [ ] **3.3 Every preference through it, and the one-time import: `chat-activity.js`, `chat-settings.js`, `chat-groups.js`, `chat-env.js`, `web/Hub.dc.html`, `web/settings/schema.js`.**
  - **Steps:** `TurnView` and the Settings row read `useUiPref('chat.steps', 'fold')`. The row moves out of `ModelsCard` into the schema as an `instant` row `ui.chat.steps` (Agent → Chat), with its key, default and Reset. "This browser only" goes away.
  - **Others:** the chat list view, the new chat's environment, and the Overview view and ranges move the same way. Theme and density: `config.toml` wins over the browser, and the browser's `hub.theme` is only the first-paint cache (no flash).
  - **Import:** on the first load with `ui-prefs.js`, each moved key that the browser holds with a non-default value, while `config.toml` holds the default, is saved once in one `PUT`. Then `gaifa.prefs.imported = 1` is set. Older `aihub.*` copies are read the same way (`chat-ui.js` `legacy`).
  *Done when:* `ui-prefs.test.mjs` covers the import (a non-default browser value saved once, a value `config.toml` sets wins); `settings-schema.test.mjs` has the new rows with their keys. Browser checks on a second hub: set Split, open the same hub as `localhost:<port>` and in a private window, and both show Split; change it in one tab and an open chat in another redraws. Update the brief §11.13 (Steps between messages) and §4.5 (Settings).

**Checks & deliverables — Phase 3**
- [ ] On the installed hub: set Steps to the user's choice, then clear the site's data in LibreWolf (or restart it with clear-on-close). The chat still uses the choice, and `config.toml` shows `[ui.chat]`. `gaifa restart` keeps it.
- [ ] Delivered: `[ui.chat]`, `[ui.overview]`, `web/ui-prefs.js`, the moved rows, the import.

## Phase 4 — Everything else off the browser (M)

- [ ] **4.1 A small store per mod: `utils/routes/ui_store.py` (new), `utils/ui_store.py` (new).**
  - `GET /api/ui/store/{mod}` → `{values: {key: value}}`; `PATCH /api/ui/store/{mod}` `{set: {key: value}, delete: [key]}` merges per key, so two pages never overwrite each other's keys. Values are JSON, each ≤ 16 KB, the file ≤ 256 KB (`413` past it); `mod` must be a known mod id or `hub`.
  - Kept in `data/state/ui/<mod>.json` (atomic writes, `paths.write_atomic`), which `gaifa backup` already copies. A save publishes `{type: "ui_store", mod, keys}`.
  *Done when:* `utils/tests/ui/test_ui_store.py` covers get, set, delete, the limits, an unknown mod, and two patches to different keys both kept. Update architecture §6 and §3 (the folder), and the brief §11.7.
- [ ] **4.2 `store` in `web/mod-kit.js` uses it.**
  - The page's `store` loads its mod's values when the page mounts. `get` reads that copy, with `localStorage` as the fallback until it arrives (and when the hub is down). `set` writes both. `store.local.get/set` stay browser-only, for drafts. `tts.draft` moves to `store.local`; that is the only change in a mod that is its own repository (tts: a commit in LocalTTS, then `gaifa repos pin tts`, per docs/mods.md §10). Every other mod page works unchanged. On the first load, the browser's values for the mod are imported once, as in 3.3.
  *Done when:* `utils/tests/web/mod-kit.test.mjs` covers the load, the fallback, `set` writing both, `store.local` staying local, and the import. Browser check on the installed hub: pick a voice on the Speech page and a preset on the Dictation page, clear the site's data, and both are still there. Update docs/mods.md (the page `store`, `store.local`).
- [ ] **4.3 The hub's own view state: `chat-layout.js`, `settings.js`, `chat-copy.js`, `web/views.js`.**
  - The same store, under mod id `hub` (`data/state/ui/hub.json`), through a `hubStore` in `web/ui-prefs.js`: `chat.layout` (`loadLayout`/`saveLayout`; saved at most every 2 s while dividers move), `settings.open`, `chat.copyModes`, `table.sort`. The browser's copy is the first-paint cache only, as in 3.2, and the import is the same as 3.3.
  - After this, `chat-ui.js` `usePref`/`getPref` and the direct `localStorage` calls are used only for drafts and the first-paint cache. `utils/tests/web/no-local-prefs.test.mjs` fails on a new `localStorage` key outside an allowlist (`gaifa.ui.cache`, `gaifa.prefs.imported`, drafts), so a new preference can't go back to the browser by accident.
  *Done when:* `chat-layout.test.mjs` (layout saved to and read from the store, throttled), `no-local-prefs.test.mjs`. Browser check on a second hub: split the chat into two panes, fold a Settings group, sort a table, clear the site's data, reload, and all three are back.

**Checks & deliverables — Phase 4**
- [ ] On the installed hub, after clearing LibreWolf's data for the site: Split, the open panes, the Speech page's voice and the Overview's ranges are all as they were.
- [ ] `gaifa backup` includes `data/state/ui/*.json`. `gaifa check` passes for tts, stt and comfy.
- [ ] Delivered: `utils/ui_store.py`, its route, the synced `store`, the hub's view state in `hub.json`, the `localStorage` guard test, docs/mods.md.

## 4. Deliverables

| Deliverable | Description | Location |
| --- | --- | --- |
| Three-way settings save | Lists and dicts merged against what the writer started from, scalars refused when both changed, one save at a time, a `settings` event | `utils/settings.py`, `utils/routes/settings.py`, `utils/routes/services.py` |
| Writers that send `base` | The Settings page, Always allow (saving at once), the rules editor, the mock | `web/api.js`, `web/settings/schema.js`, `web/settings/settings.js`, `web/chat/chat-judge.js`, `web/chat/chat-rules.js`, `web/mock.js` |
| UI preferences in `config.toml` | `[ui.chat]` (steps, list, environment), `[ui.overview]`; theme and density read from config first | `utils/config.py`, `config.example.toml`, `web/ui-prefs.js`, `web/Hub.dc.html`, `web/chat/*.js`, `web/settings/schema.js` |
| UI store | Each mod page's remembered choices and the hub's view state (panes, folded groups, sorts) on the hub; only drafts in the browser | `utils/ui_store.py`, `utils/routes/ui_store.py`, `web/mod-kit.js`, `web/ui-prefs.js`, `data/state/ui/<mod>.json`, `data/state/ui/hub.json` |
| Tests | Lost updates, conflicts, the event, the new keys, `ui-prefs.js`, the import, the mod store | `utils/tests/settings/test_settings_lost_update.py`, `test_settings_conflict.py`, `test_settings_event.py`, `test_settings_ui_prefs.py`, `utils/tests/ui/test_ui_store.py`, `utils/tests/web/ui-prefs.test.mjs`, `mod-kit.test.mjs`, `chat-layout.test.mjs`, `no-local-prefs.test.mjs`, `settings-schema.test.mjs` |
| Docs | architecture §3, §6, §9; the brief §4.5, §11.7, §11.13; docs/mods.md; structure | `docs/` |
