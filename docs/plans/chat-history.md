# Plan: a cleaner chat history: names only, grouped by date or environment, a short sidebar and a Show all page

**Asked for:** 2026-11-08 · **Status:** In progress

## 1. Introduction

The Chat page's sidebar (`web/chat/chat-list.js`, `chat-groups.js`) lists every chat the agent has, 200 at a time. With grouping off, each row carries its environment's name ("None", "Ariadne") and an age ("13m", "1d") at its right edge. That makes the list noisy, and it looks grouped when it isn't. The View menu can show live chats or archived chats, never both. Grouped by environment, each section shows 6 chats, and **Show more** adds 20 at a time.

This plan makes the list calm and short. Each row shows only the chat's name, plus the running dot and the ⋯ menu on hover. The View menu offers **Show: Chats · Archived · Both** and **Group by: Environment · Date · None**. Grouped by date, the sections are **Today**, **Yesterday**, one per day for the two days before that (labelled "Nov 6", "Nov 5"), **Last week** (4–7 days ago) and **Older**. Grouped by date or not at all, the sidebar shows the 20 newest chats, then **Show all**. Show all opens a full chat browser in the main area: search, the same View choices, rows with their date and environment, and scrolling that loads more as it goes. Grouped by environment, each section shows 5 chats, and **Show more** opens that environment's whole list in place: environments are meant to be tidied by archiving.

Touches the agent's thread routes (architecture §14.1), Stage O's chat list (backend-plan Phases 41–42), [settings-that-stick](settings-that-stick.md) 3.3 (`[ui.chat.list]` in `config.toml`), and the brief's §11.13 (the Chat page as built). The [projects](projects.md) plan builds on this one: it adds **Group by: Project** and the Projects entry under New.

## 2. Gaps & unanswered questions

- **Date buckets** (answered 2026-11-08): Today · Yesterday · the date for 2 and 3 days ago ("Nov 6", "Nov 5") · Last week (4 to 7 days) · Older. Days start at local midnight, in the browser's time zone. *Assumption:* a chat's bucket is decided by the field the chosen order sorts on (`updated` for Recent activity, `created` for Created). With order by Name, it is decided by `updated`, and the chats inside each bucket go A to Z.
- **The sidebar's limit** (answered 2026-11-08): grouped by date or not at all, 20 chats, then **Show all**. Grouped by environment, 5 per section, then **Show more**, which loads all of that section's chats (in pages of 200 from the agent, so a big environment still loads, just in more than one request).
- **Show all** (answered 2026-11-08): a page in the main area (`#/chat/all`), searchable, that scrolls without end and shows dates. *Assumption:* rows there show the title, the environment (and later the project) and the date: a time for today ("14:32"), "Yesterday", "Nov 5", and "Nov 5, 2025" for another year. Clicking a row opens the chat in the Chat page's panes, as the sidebar does. Search there is the same title-and-message search as the sidebar (`?q=`). The search by meaning stays in the header's Search.
- **Group by None:** kept. It is the flat list, newest first, with the same 20 and Show all.
- **Both, archived and live together:** *Assumption:* archived rows are drawn dimmed, with a small archive mark, and their ⋯ menu says Unarchive. With grouping by environment, the section counts include both.
- **Search in the sidebar:** stays as it is: one flat list of matches, each row's name only. Search shows up to 20, then Show all, which opens the Show all page with the same search.
- **What a row loses:** the age, and the environment name in a flat list. The environment is still there in the ⋯ menu (Move to…), the header's chip and the Show all page. Nothing else on the row changes: the running, waiting and error dot, rename by double-click, drag into a pane, and the ⋯ menu with its keys.
- **Saved view:** the new choices (`show`, and `group = "date"`) go in `[ui.chat.list]` in `config.toml`, as the others do (settings-that-stick 3.3). A saved `archived` toggle from before reads as `show = "archived"`.

## Phase 1 — The agent lists chats the new way (S)

- [x] **1.1 Archived, live or both: `services/agent/agent/store.py`, `server.py`.**
  - **Store:** `Store.threads(…, archived: bool | None)` and `Store.groups(archived: bool | None)`. `None` means both, with no `archived = ?` clause. The SQL and the sort stay as they are.
  - **Routes:** `GET /v1/threads` and `GET /v1/threads/groups` take `archived=true|false|all` (default `false`, so existing callers are unchanged). Each thread already carries `archived`.
  - **Count:** `GET /v1/threads/count?archived=&q=&environment=` returns `{count}`, so the Show all page can say how many there are and the sidebar knows whether Show all is needed without loading 21 rows. *Assumption:* the count route is cheap (one `COUNT(*)` with the same clauses as `threads`).
  *Done when:* `services/agent/tests/test_threads_list.py` (new) covers archived `false`, `true` and `all`, with `q`, `environment` and `offset`, plus `groups` with `all`, and `count` matches the list's length for the same filters. The existing thread tests still pass. Update architecture §14.1 (the agent's routes).
  *As built:* one `Store._where` builds the clauses for `threads`, `count` and `groups`. `archived` is now exactly `false`, `true` or `all` (422 for anything else, where FastAPI's bool also took `1` or `yes`; no caller sent those). §14.1 gained a "chat list" bullet with the three routes, and the agent's README says the same.
- [x] **1.2 The client and the mock: `web/chat/chat-api.js`, `chat-mock.js`.**
  - `c.threads({archived})` passes `true`, `false` or `'all'`. `c.threadGroups({archived})` does the same, and `c.threadCount({q, archived, environment})` is new. The mock does the same over its fixture chats. Give some of them older dates so every date bucket has a chat, and archive one or two.
  *Done when:* `utils/tests/web/chat.test.mjs` covers `archived: 'all'` and `threadCount` on the mock.
  *As built:* the mock's older chats are their own file, `web/chat/chat-mock-history.js` (28 chats from 25 minutes to 380 days old, two archived; `createMockClient(api, {history: false})` leaves them out), as `chat-mock.js` was already past 500 lines. The mock had no workspace mod, so `?mock` couldn't group by environment at all: `web/mock-workspace.js` adds one with four environments (None, Default, Ariadne, Thesis) and only the routes the chat pages read.

**Wire — Phase 1:** nothing visible yet. The agent and the mock answer the new filters.

**Checks & deliverables — Phase 1**
- [x] `services/agent/tests` and `uv run pytest` are green.
- [x] Delivered: the changed `store.py`, `server.py`, `chat-api.js`, `chat-mock.js`, and tests.

## Phase 2 — The sidebar: names only, the View menu, date groups, 20 and Show more (M)

- [ ] **2.1 Rows show only the name: `web/chat/chat-list.js`.**
  - `Item` drops the `where` label and the `fmtAgo` time. The ⋯ button moves into a slot that is empty until hover or focus, or always visible on touch screens (`LIST_CSS`'s hover rules change to match). An archived row (in Both) is dimmed, with an `archive` icon before the title, and the menu shows Unarchive. The `where` prop goes away from `itemProps` in `chat.js`.
  *Done when:* `utils/tests/web/chat-list.test.mjs` (new; the pure parts: what a row shows for live, archived and running chats, and `menuKey`) passes. In the browser on a second hub (`?mock#/chat`), the rows show only names.
- [ ] **2.2 The View menu: `web/chat/chat-groups.js` (`ViewMenu`, `readView`, `uiOfView`, `viewOfUi`), `chat.js`.**
  - `SHOW` becomes `[['chats','Chats'],['archived','Archived'],['both','Both']]`. `GROUP_BY` becomes `[['environment','Environment'],['date','Date'],['none','None']]`. The view gains `show` (default `'chats'`). The page's `archived` state is replaced by `view.show`, mapped to the agent's `archived` (`false` / `true` / `'all'`) by one helper, `archivedParam(show)`. The bottom-bar Archived chip goes. The View menu is the one place to choose (the Sessions chip stays).
  - `[ui.chat.list]` gains `show`. A saved view with `group = "date"` or `show = "both"` is accepted by `readView`. Add these keys to `config.example.toml`'s commented `[ui.chat.list]` and to the Settings row schema if it lists `[ui.chat.list]` keys (check `web/settings/`).
  *Done when:* `utils/tests/web/chat-groups.test.mjs` covers `readView` with the new keys, the old `archived` toggle migrating to `show`, and `archivedParam`. `utils/tests/ui/test_ui_prefs*.py` (or whichever hub test checks `[ui.chat.list]` keys) is green.
- [ ] **2.3 Date groups: `web/chat/chat-dates.js` (new).**
  - **Pure helpers:** `dayStart(now)`, `bucketOf(ts, now)` → `{key, label}`: `today` "Today", `yesterday` "Yesterday", `d2` / `d3` labelled with a short date ("Nov 6", via `Intl.DateTimeFormat` in the browser's locale, month short and day numeric), `week` "Last week", `older` "Older". `groupByDate(threads, {field, now, order})` → `[{key, label, threads}]` in that order, skipping empty buckets, sorted inside each bucket by the view's order. `shortDate(ts, now)` for the Show all page: a time today, then "Yesterday", "Nov 5", and "Nov 5, 2025" for another year.
  - **Drawing:** a `DateSections` component draws each bucket as a plain heading (11.5 px, dim, no collapse arrow, no counts), then its rows. It takes the 20 chats the page already loads, so no section has its own paging.
  *Done when:* `utils/tests/web/chat-dates.test.mjs` covers every bucket's edges (just after midnight, 23:59 the day before, exactly 3 and 4 days back, 7 and 8 days back), a change of year, ordering by name inside a bucket, and `shortDate`.
- [ ] **2.4 Twenty, then Show all; five, then Show more: `web/chat/chat.js`, `chat-list.js`, `chat-groups.js`.**
  - **Flat and by date:** `LIST_PAGE` becomes 20 and the page loads `limit: 20` (search too). When `c.threadCount` says there are more, the list ends with a **Show all** bar (the `MoreBar` style, the words "Show all · N") that goes to `#/chat/all`, carrying the search as `?q=` when there is one. The old `onMore` paging goes.
  - **By environment:** `FIRST` becomes 5. **Show more** in a section loads all of that environment's chats (`limit: 200`, then the next 200 at the end of the section if the count says there are more). It changes to **Show less** once open. Whether a section is expanded is page state, not saved.
  *Done when:* `chat-groups.test.mjs` covers the section's first 5 and the expanded state (the pure helpers: `sectionChats`, the more and less decision). In the browser on the mock, the list shows 20 then Show all, and a section shows 5 then all.

**Wire — Phase 2:** the sidebar shows names only, the View menu has Show (Chats, Archived, Both) and Group by (Environment, Date, None), and the list is short.

**Checks & deliverables — Phase 2**
- [ ] On a second hub (`uv run python app.py --port 7077 --dev --demo-mods`, page at `?mock#/chat`), each grouping and each Show choice draws as described, and the choice survives a reload (it is in that hub's `config.toml`).
- [ ] Delivered: `web/chat/chat-dates.js`, the changed `chat-list.js`, `chat-groups.js`, `chat.js`, and tests.

## Phase 3 — The Show all page (M)

- [ ] **3.1 `#/chat/all`: `web/chat/chat-all.js` (new), `chat.js`.**
  - **Route:** `ChatPage` reads `route.parts[1] === 'all'` (thread ids start with `t_`, so they never clash) and draws `AllChats` in the main area instead of the panes. The sidebar stays. Opening a chat from it goes to `#/chat/<id>` and the panes come back as they were.
  - **The page:** a title "All chats" with the count, a search box (focused on open, `?q=` from the URL, 220 ms debounce as in the sidebar), and the View's Show and Group by choices as chips. They share the sidebar's saved view, so changing one changes both. Then the rows: grouped by date (the same `groupByDate` headings, over everything loaded), by environment (a heading per environment), or flat. Each row shows the title, the environment's name (dim), `shortDate` at the right, and the same ⋯ menu as the sidebar (rename, Move to, archive, delete, through the page's existing handlers). Archived rows (in Both) are dimmed.
  - **Scrolling:** pages of 50 (`limit`, `offset`), loaded by an `IntersectionObserver` on a sentinel near the end, until the count is reached. A search or view change starts again from offset 0. Keyboard: ↑/↓ move through rows, Enter opens one, `/` focuses the search.
  - **Narrow screens:** the page fills the screen, as the panes do.
  *Done when:* `utils/tests/web/chat-all.test.mjs` (new; the pure parts: page arithmetic, merging pages without duplicates when a chat moves between loads, grouping what is loaded) passes. In the browser on the mock: Show all opens the page with the count, it scrolls to the last chat in pages, search narrows it, and a row opens its chat. Update the brief §11.13 (the Chat page: the sidebar and Show all).
- [ ] **3.2 Command palette and docs: `web/Hub.dc.html` (the palette's pages), `docs/structure.md`, `web/PATCHES.md`.**
  - The palette gains "All chats" (`#/chat/all`). `web/PATCHES.md` gets an entry for the changed list, the View menu, the date groups and the Show all page. `docs/structure.md` lists `chat-dates.js` and `chat-all.js`.
  *Done when:* the docs tests (`utils/tests/docs/`) and `utils/tests/web/` are green. The palette finds "All chats".

**Wire — Phase 3:** Show all opens a full, searchable, endlessly scrolling list of chats with their dates.

**Checks & deliverables — Phase 3**
- [ ] On the installed hub after merging and `gaifa restart`: the sidebar shows names only. By date, the headings match the real chats' days. By environment, 5 per section and Show more opens the rest. Both shows archived chats dimmed. Show all lists every chat and scrolls to the oldest. A screenshot of the sidebar by date and of Show all goes in the commit message's description of the check.
- [ ] Delivered: `web/chat/chat-all.js`, the palette entry, the docs, and tests.

## 4. Deliverables

| Deliverable | Description | Location |
| --- | --- | --- |
| Thread filters | `archived=all`, `GET /v1/threads/count` | `services/agent/agent/store.py`, `server.py` |
| Client and mock | `archived: 'all'`, `threadCount` | `web/chat/chat-api.js`, `chat-mock.js` |
| Rows and View | names only, Show (Chats, Archived, Both), Group by (Environment, Date, None) | `web/chat/chat-list.js`, `chat-groups.js`, `chat.js` |
| Date groups | buckets and their headings | `web/chat/chat-dates.js` |
| Show all | `#/chat/all`: search, view, dates, scrolling | `web/chat/chat-all.js` |
| Tests | the agent's list filters; the web helpers | `services/agent/tests/test_threads_list.py`, `utils/tests/web/chat-list.test.mjs`, `chat-dates.test.mjs`, `chat-all.test.mjs`, `chat-groups.test.mjs`, `chat.test.mjs` |
