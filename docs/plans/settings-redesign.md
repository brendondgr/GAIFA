# Plan: the Settings page, regrouped, with a sticky strip, search and row details

**Asked for:** 2026-10-25 · **Status:** In progress

## 1. Introduction

The Settings page (brief §4.5) grew section by section: eight sections picked from a left-hand list that scrolls away, General with one field in it, Paths and Interface each a short list, and Agent ten cards deep (Chat, Documents, Reading web pages, Instructions, Memory, Skills, Learning, Speech input, Voice, Permissions with its modes, rules, grants, judge and judged calls). The hub's sections are template text inside `web/Hub.dc.html` (about lines 695–900, the view-model `vmSettings` near line 2248) and save through the page's Save bar; the Agent cards are React modules in `web/chat/` that each save the moment a value changes. Nothing can be searched, and no row says which `config.toml` key it is or what its default was.

This plan moves Settings into its own module, `web/settings/`, where every row is declared as data (section, group, label, hint, config key, default, control, keywords), and builds on that one schema: eight balanced sections (General, Machine, Services, Agent, Permissions, Speech, Sessions, About) with collapsible groups and sub-anchors; a section strip that stays pinned under the header; a find-in-page search that keeps only matching groups open and highlights the matches; and on every row its key, its default, Reset to default and a restart mark. It touches architecture §6 (one new hub route), §9 (`config.toml`), the brief's §4.5, §6 (`api.js` methods) and §11.10, and builds on plan 6.5 (revision 2), 12.4 (Doctor), 14.1 (Settings → Agent), 15 (Sessions), 21.7 (Learning), 25.3 (grants), 29.4 and 49.1 (speech), 30.3–30.8 (the judge, screening, web reading), 33.5 (the header's "where you are") and 35.2 (Hardware), all in [backend-plan.md](../backend-plan.md).

## 2. Gaps & unanswered questions

- **One save model or two?** Today the hub sections use a draft and the Save bar, while the Agent cards save instantly. *Assumption:* every row backed by the hub's `Settings` (brief §6: `hub`, `memory`, `services`, `ui`, `learning`, `speech_input`, `speech_output`, `judge`, `screen`, `permissions`, `web`, `outputs`) joins the page draft and the Save bar, so one Save writes `config.toml` once and Revert undoes everything. Rows owned by the agent mod (`/api/s/agent/v1/settings`: the model, AGENT.md, MEMORY.md, documents, skills) and the action blocks (grants, judged calls, sessions, Doctor, Hardware) keep their own buttons inside their card, each marked "saved by the agent" or acting at once.
- **Old section links.** `#/settings/paths`, `#/settings/memory` and `#/settings/interface` are referenced from docs and the palette. *Assumption:* they keep working as aliases to the new place (Phase 2.2); nothing links to a hash that no longer resolves.
- **Where the defaults come from.** The UI has no list of defaults; `config.example.toml` is the source of truth (plan 23.11). *Assumption:* a new read-only route, `GET /api/settings/defaults`, returns the `Settings` shape built from the example (Phase 4.1); the UI never hard-codes a default.
- **How matches are highlighted.** *Assumption:* rows render their label, hint and key through one `highlight()` helper that wraps matches in `<mark>`; no pass over the DOM and no Custom Highlight API, so it works in every browser the UI targets and under React re-renders. Custom blocks (grants, judged calls, the services table, Doctor) match on their declared keywords and show whole.
- **Which sections show.** *Assumption:* Speech shows while the `stt` or `tts` mod is installed (in the services list), and each of its cards says when its mod is down, as today; Sessions shows while the `sessions` area is live; Agent and Permissions while the `agent` mod is installed, with the hub-owned rows (judge, screening, permissions lists) still editable when it is stopped.
- **Where the config key shows.** *Assumption:* under the hint, always, in 11 px mono muted text (`memory.reserve_gb`), so it reads and searches without hovering; rows with no key (agent-owned, blocks) show none.
- **Clean-up actions from Settings** (empty the saved-pages trash, delete old logs, make a backup from the page). They delete data or write outside `outputs/` and `data/logs/`. *Needs a human answer*; not planned here. A later plan can add them to Machine → Storage.
- **Drag to reorder** the services and the unload order. *Assumption:* the up/down buttons stay (they work with a keyboard); drag is not planned.

## Phase 1 — The module and the row schema (M)

Settings leaves `Hub.dc.html` for `web/settings/`, looking and working exactly as today, with every hub row declared as data.

- [x] **1.1 The schema: `web/settings/schema.js`.**
  - **Shape:** `sections(ctx)` returns `[{id, label, icon, areas, groups: [{id, label, summary(ctx), rows: [...]}]}]`. A row is `{id, key, label, hint, keywords, control, restart, get(draft), set(draft, v), validate(v), when(ctx)}`, where `control` is one of `number` (with `min`, `max`, `unit`), `toggle`, `segmented` (with `choices`), `chips` (multi-select over `choices`), `order` (an up/down list), `text`, `time`, `list` (one line per entry, for the permission and command lists), or `block` (a React element made by `render(ctx)`, for anything that isn't a plain value: the memory chart, the paths list, the services table, the process card, the versions, the CLI list, Doctor, Hardware, Sessions and the agent's cards). `key` is the dotted `config.toml` key (`memory.reserve_gb`, `ui.theme`); `areas` is the `SETTINGS_AREAS` map, moved here, for the mock note.
  - **Content:** the eight sections as they are today (General, Paths, Memory, Services, Interface, Agent, Sessions, About), one group each, with every hub-owned control from `vmSettings` as a row and every custom piece as a `block`.
  - **Pure parts:** `rowsOf(sections)` (flat, with the section and group ids), `rowAt(sections, 'section/group/row')`, `validateDraft(sections, draft)` → `{field: message}` (the port and reserve rules from `vmSettings`).
  *Done when:* `utils/tests/web/settings-schema.test.mjs` imports the module without a DOM, lists the rows (every `Settings` key of brief §6 that the page edits has a row with that `key`), finds `memory.reserve_gb`, and `validateDraft` rejects port 80 and reserve 99 with the same messages the page shows today.

- [x] **1.2 Row renderers: `web/settings/rows.js`.**
  - **Components:** `Row({row, value, onChange, error, query})` draws the row anatomy (label, hint, control on the right, as the current template does) and one component per control (`NumberInput`, `Toggle`, `Segmented`, `Chips`, `OrderList`, `TextInput`, `TimeInput`, `ListEditor`); `Group({group, open, onToggle, children})` draws a card with the group's title. Styles come from `web/chat/chat-ui.js` (`T`, `MONO`, `inputSt`, `chipSt`, `Badge`) and match the current template's values.
  - **Why:** the toggle, chip, segmented and order-list markup exists three times in `Hub.dc.html`; once here.
  *Done when:* each control renders in the browser against the mock and the live hub with the same look as today (a screenshot pair per section in `docs/reference/settings-2026-10/`, before and after), and the toggles keep `role="switch"` and `aria-checked`.
  *As built:* the rows render only once the page mounts them (1.4), so the browser check and the after screenshots were taken with 1.4; `settings-blocks.test.mjs` renders each control with a minimal React stand-in. A `select` control was added for choices too many for a segmented control (used from Phase 2 on).

- [x] **1.3 The blocks: `web/settings/blocks-hub.js` and `web/settings/blocks-agent.js`.**
  - **Hub blocks** (moved out of `Hub.dc.html`'s template and `vmSettings`, as React components): `ProcessCard` (version, PID, uptime, RSS from `getSystem`), `PathsList` (the folders with sizes, Copy path, the disk bar), `MemoryHistory` (`views.js`'s `MemoryChart` with the draft reserve), `ServicesTable` (enabled, autostart, order, the broken mods' errors, the link to each mod's own Settings tab), `AddModCard`, `Versions`, `CliList`, `DoctorPanel` (`getDoctor`, Show all, Run again), and `hardware.js`'s `HardwareCard` and `sessions.js`'s `SessionsPanel` used as they are.
  - **Agent blocks:** `chat/chat-settings.js`'s cards become exports the schema can place one by one: `ModelsCard`, `DocumentsCard`, `WebReadingSection`, `InstructionsCard`, `MemoryCard`, `SkillsCard`, `LearningSection`, `SpeechInputSection`, `SpeechOutputSection`, `ModesCard`, `PermissionRules`, `GrantsList`, `JudgedList` and `chat-judge.js`'s judge pickers. `AgentSettings` stays as a thin composition of them, so nothing else that imports it changes.
  *Done when:* each block mounts on its own in `utils/tests/web/settings-blocks.test.mjs` (a React render to string of the pure ones with fixed data), and the Node test suite and `uv run pytest` pass. Keep each file under 500 lines: split `blocks-hub.js` into `blocks-machine.js` and `blocks-about.js` if it passes.
  *As built:* `blocks-hub.js` is under 200 lines, so it wasn't split. The agent's cards share one load of the agent's settings (`useAgent` in `chat-settings.js`); Phase 1's Permissions card stays one block (`PermissionsCard`) until 2.1 splits it.

- [x] **1.4 The page: `web/settings/settings.js`.**
  - **Component:** `SettingsPage({api, services, system, route, go, toast, theme, density, setTheme, setDensity, ref})` owns what `vmSettings` and the shell's `st` state own today: load (`getSettings` and `getSystem`), the draft, `dirty`, Save (`saveSettings` with the whole draft; a `422 invalid_config` marks its `data.field`'s row), Revert, the restart banner, the mock note, and the Save bar (sticky at the bottom, as now). It exposes `dirty()` through the ref for the shell's unsaved-changes guard (`Hub.dc.html` line ~1432) and `beforeunload`.
  - **Shell:** `Hub.dc.html`'s settings template shrinks to `<sc-if value="{{ se.loaded }}">{{ se.pageEl }}</sc-if>` around the `h1`; `vmSettings` returns `pageEl` (a `React.createElement(this.Settings.SettingsPage, …)`), the `st` state keeps only what the guard reads, and `imp('settings/settings.js')` joins the module loads near line 1162. `SETTINGS_AREAS` leaves the shell. The header's "where you are" (plan 33.5) keeps naming the section.
  - **Docs:** `web/PATCHES.md` gets a row; `docs/structure.md` lists `web/settings/`; the brief's §4.5 says Settings is `web/settings/` and names the schema.
  *As built:* checked on a second hub (7077): the reserve changed and saved (config.toml written), a port of 80 refused with the page’s message, 7010 saved with the restart note, Revert, the guard on leaving with a dirty draft (Cancel keeps you there), every section at its hash, and `?mock`. Theme and density are now saved when picked (`syncUi` → `saveSettings({ui})`), not with the next Save, and Save sends only `saveBody` (no `ui`), so the sidebar’s and the dashboard’s own saves are never overwritten.
  *Done when:* the page behaves as before on the live hub (change the reserve, Save, the restart note on a port change, Revert, the guard on leaving with a dirty draft, every section reachable at its hash) and `Hub.dc.html` lost the settings template; `utils/tests/settings/test_web_settings.py` and `test_settings_nav.py` still pass; `uv run pytest` green.

**Wire — Phase 1:** nothing changes for the user; the same areas are live (`settings`, `system`, `memory`, `services`, `sessions`).

**Checks & deliverables — Phase 1**
- [x] Before/after screenshots of all eight sections match (`docs/reference/settings-2026-10/`).
- [x] `Hub.dc.html` is shorter by the settings template and view-model; no settings strings remain in it besides the page title and the palette rows.
- [x] Delivered: `web/settings/schema.js`, `rows.js`, `blocks-hub.js` (or `blocks-machine.js` + `blocks-about.js`), `blocks-agent.js`, `settings.js`; `chat/chat-settings.js` exporting its cards; tests `settings-schema.test.mjs`, `settings-blocks.test.mjs`.

## Phase 2 — Regrouped sections, the sticky strip and groups (M)

- [ ] **2.1 The new sections, in `web/settings/schema.js`.**
  - **General:** groups *Hub* (port, the process card), *Interface* (theme, density, the sidebar's `ui.nav.services` mode and `ui.nav.folded` as rows, a "Reset the dashboard layout" block that clears `ui.dashboard`), *Outputs* (`outputs.hidden_keep_days`, moved out of Reading web pages).
  - **Machine:** groups *Memory* (the chart, reserve, auto make room, never unload, unload order), *Storage* (the paths list with sizes and the disk bar, renamed from Paths), *Hardware* (`HardwareCard`, moved from About).
  - **Services:** as today (the table, Add a mod), plus a *Tools* column (each mod's tool count from `listTools`, or "—").
  - **Agent:** groups *Model* (the models card and the steps layout), *Documents*, *Reading web pages*, *Instructions*, *Memory*, *Skills*, *Learning*.
  - **Permissions:** groups *Modes*, *Tool rules* (`permissions.deny`, `ask`, `allow` as `list` rows), *Grants*, *Auto judge* (backend and model, `judge.context`, `judge.threshold`, `judge.timeout_s`, the command rules `judge.allow_commands` and `judge.ask_commands` as `list` rows), *Screening* (`screen.*`), *Judged calls*.
  - **Speech:** groups *Dictation* (`SpeechInputSection`) and *Voice* (`SpeechOutputSection`); the section shows under the gap's rule.
  - **Sessions** and **About** (GAIFA line, versions, CLI, Doctor) as today.
  - **Summaries:** every group has `summary(ctx)`, one line for its closed state ("Reserve 8 GB · auto make room on · 2 never unloaded", "gemma4-26B via decide · 3 command rules").
  *Done when:* `settings-schema.test.mjs` lists the eight sections in this order with these group ids, every row from Phase 1 still has a home, `outputs.hidden_keep_days` lives in `general/outputs`, and the summaries render from a fixed draft.

- [ ] **2.2 Routes and aliases: `web/settings/route.js`.**
  - **Hash:** `#/settings/<section>[/<group>[/<row>]]`; `parseSettingsRoute(parts, sections)` → `{section, group, row}` with unknown parts dropped and no section meaning General. Aliases: `paths` → `machine/storage`, `memory` → `machine/memory`, `interface` → `general/interface`, `agent/permissions` → `permissions`. The page opens the group a hash names and scrolls its row into view with a short flash (`.gaifa-flash`, 1.2 s).
  - **Elsewhere:** the shell's palette rows (`Hub.dc.html` ~line 1807) list the eight new sections, and `docTitle()` and the header's "where you are" name the section and group ("Settings / Machine / Memory"). Every "Settings → Paths", "Settings → Memory", "Settings → Interface", "Settings → About → Hardware" and "Settings → Agent → Permissions" in `docs/` and `web/` is reworded to the new place (grep for `Settings →`).
  *Done when:* `utils/tests/web/settings-route.test.mjs` covers the aliases, the three-part hash and an unknown section; on the live hub `#/settings/paths` opens Machine → Storage and `#/settings/permissions/judge` opens the judge group with the flash.

- [ ] **2.3 The strip: `web/settings/strip.js`.**
  - **Component:** `SectionStrip({sections, current, counts, onPick, search})`: the page title and the sections as tabs in one bar, `position: sticky; top: <header height>` (44 px compact, 52 px comfortable, from the shell's `density`), `z-index` under the header's 40, the page's background behind it, scrolling sideways under 760 px with the current tab kept in view. It replaces the left-hand list in every width. The search box (Phase 3) sits at its right end; until then the slot is empty.
  - **Badges:** a tab shows a small count when `counts[section]` is set (Phase 3's matches, Phase 4's changed values).
  *Done when:* in the browser the strip stays pinned while a long section (Permissions) scrolls, in both densities and at 360 px; keyboard focus moves along the tabs with the arrow keys (`role="tablist"`).

- [ ] **2.4 Collapsible groups, in `rows.js` and `settings.js`.**
  - **Behaviour:** each group is a `<details>`-like card with its title, summary and a chevron; open state per group in `localStorage` (`gaifa.settings.open`, a list of `section/group` ids; everything open by default). "Expand all" and "Collapse all" at the section's top. A group named by the hash or holding a validation error or a search match opens regardless.
  *Done when:* `settings-route.test.mjs` (or a small `settings-groups.test.mjs`) covers the pure `openGroups(saved, forced)`; in the browser a collapsed group shows its one-line summary and reopens on reload as left.

**Wire — Phase 2:** no new areas; the Services section reads `listTools` for its Tools column (area `tools`, live since plan 13).

**Checks & deliverables — Phase 2**
- [ ] Each section is between one and seven groups; the longest page (Permissions) reads as a list of summaries when collapsed.
- [ ] The brief's §4.5 is rewritten to the new sections and groups; §11.10 lists the strip at 360 px among the states.
- [ ] Delivered: `web/settings/route.js`, `strip.js`; the regrouped `schema.js`; tests `settings-route.test.mjs`, `settings-groups.test.mjs`.

## Phase 3 — Search with highlighting (M)

- [ ] **3.1 The index and the matcher: `web/settings/search.js` (pure).**
  - **Functions:** `indexRows(sections, ctx)` → `[{id: 'section/group/row', section, group, text: [label, hint, key, ...keywords]}]` (blocks contribute their `keywords` and label); `matches(index, query)` → `{rows: [{id, section, group}], perSection: {section: n}, perGroup: {…}}`, case-insensitive substring over each text, `query` trimmed, two characters or more; `highlight(text, query)` → `[{text, hit: bool}]` parts for the renderer. A small synonym list per row through `keywords` ("dark mode" on theme, "RAM" and "unified" on the reserve, "VRAM" and "GPU" on Hardware, "MCP" on sessions).
  *Done when:* `utils/tests/web/settings-search.test.mjs` finds `memory.reserve_gb` by "reserve", by "RAM" and by "reserve_gb", counts per section, returns nothing for one character, and `highlight('Memory reserve', 'mem')` splits as expected (one hit, case kept).

- [ ] **3.2 The search box and the filtered view, in `strip.js`, `rows.js` and `settings.js`.**
  - **Box:** in the strip's right end, placeholder "Search settings", `/` focuses it when nothing else has focus on the page, Esc clears, the clear button clears. Live `aria-live` text "12 matches in 4 sections".
  - **View:** with a query, the page shows every section that has a match (in strip order) instead of only the current one; only groups with a match stay open, the rest collapse; non-matching rows inside a matching group stay, dimmed; the strip badges each section with its count and dims sections with none. `Row` passes `query` down and renders label, hint and key through `highlight()` as `<mark>` (the accent background at low alpha, the theme's text colour). Clearing restores the section and open state from before the search.
  - **Walking:** Enter and ↓ move to the next match, ↑ to the previous, scrolling it into view with the flash; the current match's `<mark>` gets the full accent colour.
  *Done when:* in the browser, typing "memory" highlights "Memory" in Machine → Memory's title and rows and in Agent → Memory (MEMORY.md), keeps both groups open and collapses the rest; "judge" lands on Permissions → Auto judge; Enter walks the matches; clearing returns to where you were. No new network requests on typing.

- [ ] **3.3 The palette: `Hub.dc.html`'s `palItems()`.**
  - **Rows:** besides the eight "Settings › <Section>" rows, one per group ("Settings › Permissions › Auto judge") and one per hub row ("Reserve · Settings › Machine › Memory", with the key as the sub line), read from `web/settings/search.js`'s `indexRows` on the loaded schema; each navigates to `#/settings/<section>/<group>/<row>` so the page opens the group and flashes the row (2.2).
  *Done when:* the palette finds "reserve" and lands on the row with the flash; `settings-search.test.mjs` covers `paletteRows(index)` (label, sub, hash).

**Checks & deliverables — Phase 3**
- [ ] Search is keyboard-complete: `/`, type, Enter, ↑/↓, Esc, with focus never lost.
- [ ] The brief's §4.5 describes the search; `docs/structure.md` lists `search.js`.
- [ ] Delivered: `web/settings/search.js`; the box and the filtered view; the palette rows; `settings-search.test.mjs`.

## Phase 4 — Row details: keys, defaults, reset and changes (M)

- [ ] **4.1 Defaults from the hub: `GET /api/settings/defaults` in `utils/routes/settings.py` and `utils/settings.py`.**
  - **Route:** returns the `Settings` shape (brief §6) built from `config.example.toml` through `utils.config.validate` and `settings_mod.view`'s shaping (the `services.order` and `memory.priority` lists are the installed mods in sidebar order, as `view` does for an empty config), read once per process and cached. `api.js` gets `getSettingsDefaults()` (area `settings`); the mock returns its seed's defaults.
  - **Docs:** architecture §6 (hub-only routes) and the brief's §6 method table.
  *Done when:* `utils/tests/settings/test_defaults.py` checks the shape validates as `Settings`, `hub.port` is 7000 and `memory.reserve_gb` is the example's value, and a changed `config.toml` does not change the answer; `test_contract.py` sees the new method.

- [ ] **4.2 Keys, defaults and Reset, in `rows.js` and `settings.js`.**
  - **Row:** under the hint, the key in 11 px mono; when the draft's value differs from the default, a "Reset to default (<value>)" link at the control's side that sets the draft to the default (still unsaved); `OrderList`, `Chips` and `ListEditor` compare as lists. A row with `restart: true` (`hub.port`) shows a small "restart" badge beside its label before saving, and the Save bar says "Save and restart later" while such a row is dirty.
  - **Counts:** `changedRows(sections, draft, defaults)` (pure, in `schema.js`) feeds the strip's badges ("General 2") and a "Changed" chip at the section's top that filters the view to changed rows, like a search with no query.
  *Done when:* `settings-schema.test.mjs` covers `changedRows` on a fixed draft and defaults (lists compared by value, order rows by order); in the browser the reserve shows its key and, once changed, its Reset link; Reset marks the page dirty and Save writes the default (the `config.toml` line is removed or set, as `settings_mod.save` already does with `_or_default`).

- [ ] **4.3 One Save for the hub-owned agent rows, in `blocks-agent.js`, `chat-judge.js`, `chat-webprefs.js`, `chat-speech-input.js`, `chat-speak.js` and `chat-settings.js`.**
  - **Change:** the rows these cards save through `api.saveSettings` (learning, speech_input, speech_output, judge, screen, web, outputs, permissions) become schema rows on the page draft (2.1 placed them; this step removes their own instant saves), so Save and Revert cover them. What the agent mod owns (`c.saveSettings` to `/v1/settings`: AGENT.md, MEMORY.md, documents, the models card) keeps its own Save button inside its card, labelled "Saved by the agent". `JudgedList`, `GrantsList` and the judge's model picker that calls the mod to list choices stay blocks.
  - **Why:** one page, one Save; today a page can be half-saved.
  *Done when:* on the live hub, changing the judge's threshold and the reserve together dirties the page once, Save writes both and `GET /api/settings` shows both; Revert restores both; the chat's mode picker still reads the judge's status (plan 30.5); `utils/tests/web/chat-webprefs.test.mjs` and `chat-speak.test.mjs` are updated for the moved saves; `uv run pytest` green.

**Checks & deliverables — Phase 4**
- [ ] Every hub-owned row shows its key; every changed row offers Reset; the strip counts match `changedRows`.
- [ ] Delivered: `GET /api/settings/defaults`, `getSettingsDefaults()`, the Reset and restart marks, the Changed filter; tests `test_defaults.py`, the updated web tests.

## Phase 5 — This machine's settings and the mods in search (S)

- [ ] **5.1 "Set on this machine" block, in `blocks-hub.js`, placed in General → Hub.**
  - **Block:** `OverridesCard`: the rows whose saved value differs from the default (from `changedRows` over `orig`, not the draft), as "key · value (default x)" lines, each a link to the row's hash; "Nothing changed from the defaults" when empty; a Copy button that copies the lines as TOML. Read-only.
  *Done when:* the card lists this machine's overrides and each link lands on its row with the flash; `settings-schema.test.mjs` covers `overrideLines(rows)` → the TOML text.

- [ ] **5.2 Mods in search, in `search.js` and `schema.js`.**
  - **Rows:** each installed mod contributes a jump row to the index ("<name> settings", keywords: its id, name and `services/<id>`), navigating to `#/s/<id>/settings`; shown in a "Mods" pseudo-section at the end of the search results and the palette, never in the strip.
  *Done when:* typing "tts" in the box offers "LocalTTS settings" under Mods; `settings-search.test.mjs` covers the mod rows.

**Checks & deliverables — Phase 5**
- [ ] CLAUDE.md's status line and `docs/plans/README.md` say the plan is done; the brief's §4.5 is final.
- [ ] Delivered: `OverridesCard`, the mod jump rows; tests.

## Deliverables

| Deliverable | Description | Location |
| --- | --- | --- |
| `schema.js` | The sections, groups and rows as data; `rowsOf`, `rowAt`, `validateDraft`, `changedRows`, `overrideLines` | `web/settings/schema.js` |
| `rows.js` | The row anatomy and the controls; groups that collapse with a summary; keys, Reset, the restart badge, `<mark>` highlighting | `web/settings/rows.js` |
| `blocks-hub.js`, `blocks-agent.js` | The custom pieces: process, storage, memory chart, services table, versions, CLI, Doctor, overrides; the agent's cards placed one by one | `web/settings/` |
| `settings.js` | The page: load, draft, Save, Revert, the guard, the filtered view | `web/settings/settings.js` |
| `strip.js` | The sticky section strip with badges and the search box | `web/settings/strip.js` |
| `route.js` | `#/settings/<section>/<group>/<row>` and the aliases | `web/settings/route.js` |
| `search.js` | `indexRows`, `matches`, `highlight`, `paletteRows` | `web/settings/search.js` |
| Defaults route | `GET /api/settings/defaults` from `config.example.toml`; `getSettingsDefaults()` | `utils/routes/settings.py`, `utils/settings.py`, `web/api.js`, `web/mock.js` |
| Docs | brief §4.5, §6, §11.10; architecture §6; `structure.md`; `PATCHES.md`; the reworded "Settings →" references | `docs/`, `web/PATCHES.md` |
| Tests | Node tests of the pure modules and blocks; the defaults route; the contract test | `utils/tests/web/settings-*.test.mjs`, `utils/tests/settings/test_defaults.py` |
