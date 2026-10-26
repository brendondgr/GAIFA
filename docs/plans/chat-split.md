# Plan: several chats side by side on the Chat page

**Asked for:** 2026-10-25 · **Status:** In progress

## 1. Introduction

The Chat page shows one chat at a time: `ChatPage` (`web/chat/chat.js`) holds the chat list and one thread's events, live progress, composer and approvals, and takes the thread from the URL (`#/chat/<id>`). The user wants to watch and talk to several agents at once, the way a tiling window manager works: drag a chat from the list (or an open pane by its header) onto the top, bottom, left or right edge of an open pane to split it that way, split any pane again without a limit, drag the line between two panes to change their sizes, and close a pane with ×.

The approach: first make one chat a component of its own (`ChatPane`) that can run many times on one page, with the page-wide singletons it relies on made per pane (Phase 1). Then a layout tree of splits and panes, its drawing, resizing and drag and drop (Phase 2). Each pane opens its own server-sent event stream today, and over HTTP/1.1 a browser keeps about six connections per host, so Phase 2 caps the panes at four; Phase 3 adds one agent route that streams every open chat's events over one connection, and the cap goes. Touches architecture §14.1 (the agent's routes), the brief's §11.13 (the Chat page as built) and the chat plans in [backend-plan.md](../backend-plan.md) Phases 14 and 19.

## 2. Gaps & unanswered questions

- **Where the layout is kept**: unknown. *Assumption:* per browser, in `localStorage` under `gaifa.chat.layout` (like `gaifa.chat.steps`); a chat deleted elsewhere closes its pane on load.
- **What the URL says**: unknown. *Assumption:* the active pane's chat (`#/chat/<id>`, or `#/chat` for a new chat). Opening a chat from the list, a link or a fork opens it in the active pane, as today; the other panes stay.
- **Narrow windows**: unknown. *Assumption:* under 760 px wide only the active pane is drawn, with a row of tabs for the others; the layout is kept for a wider window.
- **Smallest pane**: *Assumption:* 320 px wide and 240 px tall; a divider stops there, and a split that would make a pane smaller is refused with a toast.
- **The same chat in two panes**: *Assumption:* allowed; both draw the same thread and stay in step through their streams.
- **Older agents without the shared stream route**: *Assumption:* the client falls back to one stream per pane when `/v1/streams` answers 404, and keeps the cap of four.

## Phase 1 — One chat as a component (M)

- [x] **1.1 Per-pane singletons: `web/chat/chat-md.js`, `web/chat/chat-quote-reply.js`, `web/chat/chat-quote.js`, `web/chat/chat-cards.js`.**
  - **Outputs:** `renderMarkdown(text, {cites, hide, outputs})` takes the chat's outputs for `![caption](#n)` (set while it renders, like `cites` and `hide`); `AssistantCard` passes `ctx.outputs`. `setChatOutputs` stays as the fallback for callers without a chat (the viewer).
  - **Quote-reply:** `QuoteReplyBox` acts only on a selection inside its own `scrollRef`, so two panes don't both open a box; the pane's `ctx.scrollToReply` (1.2) calls `scrollToReply(seq, paneRoot)` so a quote jumps to its reply in the pane that asked.
  - **Why:** these module-level values are the last pane's when several panes render.
  *Done when:* `utils/tests/web/chat.test.mjs` covers `outputs` (its own chat's `#n`, the fallback restored after the render); `uv run pytest` passes.
- [x] **1.2 `ChatPane`: `web/chat/chat-pane.js`.**
  - **Split:** `ChatPage` keeps the chat list and its state, the data every pane shares (models, the agent's settings, tools, the judge's status, the speech output, environments, the mods' chat modules), the agent-down banner and the `gaifa:open-output` listener. `ChatPane({shared, tid, cmd, onOpen(tid | null), onFocus})`, where `shared` carries the client, that data and the list's updates (`addThread`, `listPatch`, `patched`, `rename`, `envDeleted`) and a `bus` (`EventTarget`) that hands a rename or setting change to every pane showing that chat (the agent doesn't stream them), holds one thread: its events and stream, live state, drafts and quote drafts, attachments, tool forms, folders, the header, the scroll area, the composer and the quote-reply box. `ensureThread`, forks and `/clear` call `onOpen` instead of changing the URL.
  - **Behavior:** with one pane the page looks and works as before.
  *Done when:* the existing chat tests pass; on a second hub (`uv run python app.py --port 7077 --dev --demo-mods`, `?mock#/chat`) a new chat, a turn, an approval, a fork and a quote-reply work as before. `chat.js` and `chat-pane.js` are each under 500 lines.

**Wire — Phase 1:** nothing new on screen; the Chat page is drawn by `ChatPane`.

**Checks & deliverables — Phase 1**
- [ ] A turn with a picture and a citation draws them in the reply; Select → Reply adds a card.
- [ ] Delivered: `web/chat/chat-pane.js`, the changed `chat.js`, `chat-md.js`, `chat-quote*.js`, `chat-cards.js`.

## Phase 2 — The split layout (M)

- [x] **2.1 The layout tree: `web/chat/chat-layout.js`.**
  - **Shape:** a pane `{id, tid}` (tid null: a new chat) or a split `{id, dir: 'row'|'col', sizes: [fractions], kids: [nodes]}`; one active pane id.
  - **Functions (pure):** `single(tid)`, `panes(tree)`, `findPane`, `splitPane(tree, paneId, edge, tid)` (edge `left|right|top|bottom`; same-direction splits add a sibling instead of nesting), `closePane` (its sibling takes the space; a split of one collapses), `movePane(tree, paneId, targetId, edge)`, `setTid`, `resize(tree, splitId, i, fraction, minFraction)`, `equalize`, `normalize`, `dropTids` (a deleted chat's panes close), `paneSize`/`splitPaneSize` (pixels, for refusing a split that's too small), `parseLayout`/`loadLayout`/`saveLayout` (`gaifa.chat.layout`; a read that throws or doesn't parse gives null, and the page starts from `single`).
  *Done when:* `utils/tests/web/chat-layout.test.mjs` covers each function, including nesting four deep, closing down to one pane and a corrupt saved value.
- [x] **2.2 Drawing and resizing: `web/chat/chat-split.js`.**
  - **SplitView:** draws the tree as nested flex boxes; each split's kids are separated by a 5 px divider dragged with pointer events (`setPointerCapture`), limited by the smallest pane; a double click equalizes. Each pane's own header gets the controls (no second bar): a grip at its left (dragged to move the pane), Split (a new chat beside, or below when the pane is taller than wide) and × at its right. The active pane has an accent outline; clicking a pane makes it active.
  - **Page:** `ChatPage` keeps the tree and the active id, draws `SplitView` with a `ChatPane` per pane, sets the hash when the active pane changes, and on a hash change opens that chat in the active pane. Under 760 px: the active pane only, with tabs for the rest.
  *Done when:* on the second hub two and three panes draw, the dividers resize and stop at the smallest size, the layout survives a reload; `chat-layout` tests pass.
- [x] **2.3 Drag and drop: `web/chat/chat-list.js`, `web/chat/chat-split.js`.**
  - **Sources:** a chat in the list (`draggable`, `dataTransfer` type `application/x-gaifa-chat` with `{tid}`) and a pane's bar (`{pane}`).
  - **Targets:** over a pane, five zones (`dropZone`: the nearest edge within 28% of it, else the middle): an edge splits that way, the middle opens the chat in that pane; the zone is shown as a shaded half. A dropped pane moves (`movePane`, keeping its id), or swaps chats when dropped on a middle.
  - **Cap:** at most four panes while each opens its own stream; a fifth is refused with a toast that says why.
  *Done when:* on the second hub dragging a chat to each edge and the middle does what the zone showed, moving a pane by its bar works, and a fifth pane is refused.

**Wire — Phase 2:** the Chat page draws several chats; the list's chats can be dragged into it.

**Checks & deliverables — Phase 2**
- [ ] Two chats run turns at the same time in two panes, each with its own composer and approvals.
- [ ] Delivered: `web/chat/chat-layout.js`, `web/chat/chat-split.js`, tests, docs: the brief's §11.13, `web/PATCHES.md`, `docs/structure.md`.

## Phase 3 — One stream for every pane (S)

- [x] **3.1 The agent's shared stream: `services/agent/agent/streams.py`.**
  - **Route:** `GET /v1/streams?threads=<tid>:<after>,<tid>:<after>…` sends the stored events after each `after`, a `ready` per thread (`{type: 'ready', thread_id, seq, running}`), then every live event and delta of those threads; each already carries `thread_id`. An unknown thread sends `{type: 'gone', thread_id}` and is skipped. The per-thread `/v1/threads/{tid}/stream` moves into the same file unchanged.
    - **Live bus:** `Live.subscribe(tid, q=None)` (`agent/loop.py`) takes a queue to share across threads.
  *Done when:* `services/agent/tests/test_streams.py` covers two threads' replay, live events of both, `after`, an unknown id and the unsubscribe; the agent's `README.md` lists the route (architecture §14.1 doesn't list the agent's routes).
- [ ] **3.2 The client's stream pool: `web/chat/chat-streams.js`, `web/chat/chat-api.js`.**
  - **Pool:** `c.stream(tid, after, handlers)` keeps its interface; the live client shares one `EventSource` for every open stream, reopened (debounced) with each thread's last seq when the set changes, and hands each event to its thread's handlers. A 404 from `/v1/streams` falls back to one stream per thread and keeps the cap.
  - **Cap:** gone while the pool is shared.
  *Done when:* `utils/tests/web/chat-streams.test.mjs` (a fake `EventSource`) covers sharing, reopening with the last seqs, `ready` per thread and the fallback; six panes stream at once on the installed hub after `gaifa restart`.

**Wire — Phase 3:** any number of panes, all on one connection.

**Checks & deliverables — Phase 3**
- [ ] Six panes, three running turns, the rest of the app (Overview, Outputs) still loads.
- [ ] Delivered: `services/agent/agent/streams.py`, `web/chat/chat-streams.js`, tests, docs: architecture §14.1, the brief's §11.13, `docs/structure.md`.

## 4. Deliverables

| Deliverable | Description | Location |
| --- | --- | --- |
| `ChatPane` | one chat: its stream, events, header, thread and composer | `web/chat/chat-pane.js` |
| Layout tree | splits and panes, pure functions, saved per browser | `web/chat/chat-layout.js` |
| `SplitView` | draws the tree, dividers, pane bars, drop zones | `web/chat/chat-split.js` |
| Shared stream | every open chat's events on one SSE connection | `services/agent/agent/streams.py` |
| Stream pool | `c.stream` over the shared stream, with a fallback | `web/chat/chat-streams.js` |
| Tests | the layout, the pool, markdown outputs, the agent's route | `utils/tests/web/chat-layout.test.mjs`, `utils/tests/web/chat-streams.test.mjs`, `services/agent/tests/test_streams.py` |
