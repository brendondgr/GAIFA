# Plan: a responsive Chat: messages that show at once, and a queue for messages sent during a turn

**Asked for:** 2026-11-07 · **Status:** In progress

## 1. Introduction

The Chat page feels slow at the moment the user acts. Sending a first message in a new chat waits for two requests in a row through the hub (`create`, then `send`; `web/chat/chat-pane.js` `ensureThread` and `send`). The pane then clears itself when its `tid` changes from null to the new id, and stays blank until the shared stream reconnects. The stream closes and reopens the whole `EventSource` for every open chat (`chat-streams.js` `open`), and the user's own `user` event arrives on it. In any chat, the user's message is never drawn by the page itself: the `user` event that `c.send` returns is thrown away, and the message shows only when that event comes back on the stream. On the agent's side, `Agent.send` (`services/agent/agent/loop.py`) waits for memory recall before it writes the `user` event: a call to `hub.services`, two hub calls for the chat's folders, then a search by meaning capped at 2.5 s. Every message waits for this before it can show.

A message sent during a turn is written into the thread straight away with `queued: true`, and the next model call reads it (steering). It isn't held until the reply ends, and it shows only as a small badge inside the thread. It can also be stranded: the agent decides `queued` before recall, and the turn can end during recall. A turn that ends with a reply never looks for messages that arrived while that reply streamed. And `running()` stays true while the turn-end hooks run. In each case no turn ever answers the message. The button in the composer is Stop during a turn, so the only way to send is Enter.

The approach has three phases. Phase 1 makes the message appear the moment the user sends it. The page draws it at once (an optimistic message, matched to the stored event by a client id). A new chat is made and sent in one request, and the pane keeps what it drew. The agent writes the `user` event before recall, and recall becomes an event of its own. Phase 2 adds a real queue. Messages sent during a turn are held by the agent (in `agent.db`, outside the event log, so the model never sees them early). They are shown in a strip above the composer, each one editable, removable or sendable now (today's steering). When the turn ends, the agent posts the next one as a new user message and starts a new turn. Phase 3 removes the remaining waits around the first token: the shared stream adds a chat without reconnecting, and the title and the context meter no longer compete with the turn. Touches architecture §14.1 (the agent's routes, quote-replies and attachments at `send`) and §14.2 (the event log), the brief's §11.13 (the Chat page as built), and the plans [chat-split](chat-split.md) (the pane and the shared stream) and [structured-memory](structured-memory.md) 3.3 (recall on each message).

## 2. Gaps & unanswered questions

- **Enter during a turn: queue or steer?** *Assumption:* queue (what was asked). Today's steering stays, as **Send now** on a queued message: the message goes into the running turn at its next model call, as today.
- **Several queued messages** (answered 2026-11-07): one reply for all of them. When the turn ends, every queued message is posted in order, each as its own user message, and one new turn answers them together.
- **Stop with a queue** (answered 2026-11-07): Stop ends the running turn and sends the queue at once: the queued messages are posted and the agent answers them right away. With an empty queue, Stop only stops. A turn that ends in an error pauses the queue (**Resume**, **Clear**), so a broken model doesn't loop.
- **A turn that ends waiting (a question or a parameter card)** (confirmed 2026-11-07): the queue waits for the card. Once the user answers it and that turn ends, the queue goes on. **Send now** on a queued message dismisses the card, as sending does today ("The user wrote a message instead of answering.").
- **The same chat in two panes:** the queue lives in the agent, so both panes show the same strip through the stream.
- **Restarts:** the queue is in `agent.db`, so it survives a restart. A turn that resumes after a restart pops the queue when it ends, like any other turn.
- **Older events with `queued: true`:** they are still drawn as they are today (badge cleared by the next step). New messages sent with Send now carry `steer: true` instead.
- **Response-time targets:** *Assumption:* the page draws the user's message in the same frame as Send. The stored `user` event is on the stream within 300 ms on the installed hub. A new chat's pane is in the chat's URL within 100 ms of Send. Phase 3's check measures these.

## Phase 1 — The message shows at once (M)

- [x] **1.1 The `user` event before recall: `services/agent/agent/loop.py`, `context.py`.**
  - **Order in `Agent.send`:** check and number as now, write the `user` event, then return 202. Recall (`_recall`) runs after the emit, in a task, and writes a `recall` event `{for: <user seq>, memory: [...]}` only when it found something. The turn starts after recall finishes, or after `MEANING_WAIT_S` at most, so the first model call still sees what was recalled. `describe_docs` stays before the emit (attachments only), because a document's `#n` is numbered there.
  - **Reading it back:** `context.py` attaches a `recall` event's `memory` to the user message it names, exactly where the payload's `memory` goes today. Events written before this change keep their `memory` on the `user` payload and are read as before.
  - **Races fixed:** `queued` is decided with no `await` between the check and the emit. `_turn` marks the thread not running before the `on_turn_end` hooks, which move to their own task. When the model's reply has no tool calls, `_turn` checks for user events written after that model call began, and goes round again if there are any.
  - **Client id:** `POST /v1/threads/{id}/messages` takes an optional `client_id` (≤ 64 characters), stored on the `user` event's payload.
  *Done when:* `services/agent/tests/test_send_order.py` shows the following. The `user` event is published before a slow recall (a fake embed search that waits 2 s) returns. The turn's first model call sees the recalled facts. A message sent while the last reply streams gets its own model call. A message sent during the turn-end hooks starts a turn. `test_memory_time.py` and `test_replay.py` still pass. *As built:* the turn starts at once and its first model call waits for the message's recall (`RECALL_WAIT_S`, 10 s); `Agent.busy()` is a turn that will still read messages (not in its turn-end hooks), and `send` decides `queued` with it right before the emit; `test_memory_prompt.py` reads the `recall` event. Update architecture §14.1 (recall in Instructions, skills, memory; quote-replies) and §14.2.1 (the `recall` event).
- [x] **1.2 A new chat in one request: `services/agent/agent/server.py`, `web/chat/chat-api.js`.**
  - **Route:** `POST /v1/threads` takes an optional `message` (the same body as `/messages`: `text`, `attachments`, `doc_modes`, `quotes`, `mentions`, `client_id`). With a message, it creates the thread and sends the message in one call, and answers the thread with that message's `event`. A model chosen for the new chat that the relay's last list names (however old) is accepted without asking the relay again; any other is checked as before (`400`).
  - **Client:** `c.create(body)` passes `message` through, built by `messageBody(text, attachments, doc_modes, quotes, mentions, client_id)` (`chat-api.js`, also behind `send`). The mock (`chat-mock.js`) does the same.
  *Done when:* `services/agent/tests/test_threads_create.py` shows the following. A create with a message returns the thread and the `user` event, and starts a turn. A create without one behaves as before. A bad model is still refused. The mock's create in `utils/tests/web/chat.test.mjs` covers this too. Update architecture §14.1 (the agent's routes).
- [x] **1.3 Optimistic messages: `web/chat/chat-pane.js`, `chat-thread.js`, `chat-cards.js`.**
  - **Drawing:** `send` adds a pending message `{cid, text, attachments, quotes, mentions, state: 'sending'}` to the pane before any request. `buildView` draws pending messages after the thread's events as user messages, slightly dimmed while sending. When a `user` event with the same `client_id` arrives, it takes the pending message's place; the scroll position and the message's key don't jump. If the request fails, the message stays, marked **Not sent**, with **Retry** and **Edit** (Edit puts the text back in the composer). The draft is no longer restored behind the user's back.
  - **New chat:** `ensureThread` and `send` become one `c.create({…, message})` for a new chat. When `tid` changes from null to the id this pane just created, the pane keeps its pending messages and the fresh chat's settings (no wipe), and skips `c.context` until the first turn ends.
  *Done when:* `utils/tests/web/chat-thread.test.mjs` (new) covers a pending message drawn, matched by `client_id`, failed with Retry, and two pending messages kept in order. `chat.test.mjs` covers `create` with a message on the mock. Checked in the browser on a second hub (`?mock#/chat`): the message is drawn 6 ms after Enter, the pane never blanks, and the chat's URL follows; and on the installed hub. *As built:* the pane isn't rendered in the Node tests (no DOM), so the never-blank check is the browser's; a pending message also marks its turn running, so its status header shows at once. Update the brief §11.13.

**Wire — Phase 1:** the Chat page draws a sent message at once, in new and existing chats, with **Not sent** / Retry on failure.

**Checks & deliverables — Phase 1**
- [x] On the installed hub with the embed mod unloaded, the first message of a new chat shows in the frame of Send. The URL is the chat's at once. The reply streams as before. The model still gets the recalled facts with the message. *Checked 2026-11-07:* drawn 7.5 ms after Enter, the chat's URL at 67 ms, its stored user event at 157 ms; the recall came 2.5 s later (the search by meaning at its cap: before, the message waited for it) and the model call after it; the reply on skynet.
- [x] Delivered: the changed `loop.py`, `context.py`, `server.py`, `chat-api.js`, `chat-mock.js`, `chat-pane.js`, `chat-thread.js`, `chat-cards.js`, and tests.

## Phase 2 — The queue (M)

- [ ] **2.1 The queue in the agent: `services/agent/agent/queue.py` (new), `loop.py`, `server.py`.**
  - **Store:** an `agent.db` table `queue` (id `q_…`, thread_id, position, body (the `/messages` body), created, edited). Plus `threads.queue_paused` (0/1).
  - **Sending:** `POST /v1/threads/{id}/messages` takes `when: "auto" | "queue" | "now"` (default `auto`). With `auto` or `queue`, a message sent while the thread is running or waiting is added to the queue. Nothing goes in the event log. The call answers 202 `{queued: {id, position}}` and the stream gets a `queue` event with the whole list. With `now`, it behaves as today (written at once, read by the next model call), stored with `steer: true`. An idle thread with an empty queue sends at once, whatever `when` says.
  - **Routes:** `GET /v1/threads/{id}/queue` (`{items, paused}`). `PATCH /v1/threads/{id}/queue/{qid}` (`text`, `position`). `DELETE /v1/threads/{id}/queue/{qid}`. `POST /v1/threads/{id}/queue/{qid}/send` (steer now: as `when: "now"`; on a waiting thread it dismisses the card). `POST /v1/threads/{id}/queue/resume`. `DELETE /v1/threads/{id}/queue` (clear). Each change publishes a `queue` event. Queue events are live only, and a stream's `ready` carries the current queue so a page that reconnects has it.
  - **Running the queue:** when `_turn` ends `idle` and the thread isn't paused, the agent pops every item, in order, and writes each as its own `user` event through the same path as `send` (recall over their joined text), then starts one turn that answers them all. Stop (`cancel`) ends the turn the same way: the cancelled turn is closed as today, then the queue is sent and answered at once. An `error` end sets `queue_paused`; Resume clears it and sends the queue. A `waiting` end leaves the queue as it is, and the turn that continues after the answer pops it when it ends. Deleting a thread deletes its queue, and a fork doesn't copy it.
  *Done when:* `services/agent/tests/test_queue.py` covers the following:
    - two messages queued during a turn become two `user` events, in order, answered by one more turn;
    - edit, reorder and delete;
    - Send now goes into the running turn;
    - Stop with a queue ends the turn and answers the queue at once; Stop without one only stops;
    - an error pauses the queue, and Resume sends it;
    - a waiting card holds the queue;
    - the queue survives an `Agent` restart over the same `agent.db`;
    - `ready` carries the queue.

  Update architecture §14.1 (the agent's routes) and §14.2 (the queue next to the event log).
- [ ] **2.2 The queue strip: `web/chat/chat-queue.js` (new), `chat-composer.js`, `chat-pane.js`, `chat-api.js`, `chat-mock.js`.**
  - **Composer:** during a turn the Send button stays, next to Stop. Enter and Send queue the message, and the placeholder says "Queue a message (sent when this reply ends)…". **Ctrl/⌘+Enter** sends now (steer).
  - **Strip:** right above the composer, shown while the queue has items. A header reads "Queued · N · sent when this reply ends (Stop sends them now)", or "Paused after an error · Resume · Clear", or "Waits for your answer" when a card is waiting. One row per message shows the text on one line, its attachments and quotes as small chips, and its actions: **Edit** (inline), **Send now**, **×**, and drag to reorder. A message the user just queued shows in the strip at once (optimistic, by `client_id`). When the agent sends the queue, its messages leave the strip and appear in the thread as user messages, answered by one reply.
  - **Client:** `queue(tid)`, `queueEdit`, `queueRemove`, `queueSend`, `queueResume`, `queueClear` in both the live client and the mock. The pane reads `queue` events and `ready`'s queue.
  *Done when:* `utils/tests/web/chat-queue.test.mjs` covers the strip's states (items, paused, waiting), edit, remove, Send now and reorder, against the mock. The mock answers the whole queue in one turn. In the browser on the installed hub: three messages typed during a long reply show in the strip at once; when the reply ends they appear as three messages with one reply; with another queue, Stop sends it and the reply starts at once. `chat-composer.js` and `chat-pane.js` stay under 500 lines (the strip and its handlers live in `chat-queue.js`). Update the brief §11.13.

**Wire — Phase 2:** the Chat page's composer queues messages during a turn and shows them above it. The old in-thread "queued" badge is used only for steered messages.

**Checks & deliverables — Phase 2**
- [ ] The same chat open in two panes shows the same queue, and an edit in one shows in the other.
- [ ] A queued message with an attached document and a quote-reply runs with both.
- [ ] Delivered: `services/agent/agent/queue.py`, `web/chat/chat-queue.js`, the changed agent and chat files, and tests.

## Phase 3 — Fewer waits around the first token (S)

- [ ] **3.1 Add a chat to the shared stream without reconnecting: `services/agent/agent/streams.py`, `web/chat/chat-streams.js`.**
  - **Route:** `/v1/streams` sends a `stream` id in its first event. `POST /v1/streams/{sid}/threads` `{add: [[tid, after]], remove: [tid]}` changes what an open stream carries, and replays an added chat's events after `after`. The pool uses it for new and closed panes, and reopens the connection only when that call fails (404: an older agent, or a stream that ended).
  *Done when:* `services/agent/tests/test_streams_add.py` covers add with replay, remove, and an unknown `sid` (404). `utils/tests/web/chat-streams.test.mjs` shows that a new pane adds itself without a new `EventSource`, and falls back to reconnecting on 404.
- [ ] **3.2 The title and the meter out of the turn's way: `loop.py` (`_title`), `server.py` (`/context`).**
  - **Title:** a new chat's title is asked for after the first turn's first model call ends, not before it. On a cloud model it is asked at once, as now.
  - **Meter:** `/context` reuses the system prompt the running turn last built, kept per thread for 10 s, instead of building it again with its hub calls.
  *Done when:* `test_loop.py` shows that the title call comes after the first model call (a fake model records the order). `test_send_order.py` shows that `/context` during a turn makes no hub calls.
- [ ] **3.3 Measured: `services/agent/evals/latency.py` (new).**
  - **What:** a script against the installed hub. It makes a new chat with a message, sends into an idle chat, and queues during a turn. It reports the time to the `user` event on the stream and the time to the first token, each as the median of 5 runs, written to `docs/agent-eval.md`. It uses a `dry_run` chat (no memory) and the skynet model. It is never part of `pytest`.
  *Done when:* the run shows the `user` event in under 300 ms (median) with the embed mod unloaded, and the results are in `docs/agent-eval.md`.

**Wire — Phase 3:** nothing new on screen. Opening a new chat no longer reconnects the others' stream.

**Checks & deliverables — Phase 3**
- [ ] With three panes open, a new chat in a fourth shows its message at once. The other three don't flicker or replay.
- [ ] Delivered: the changed `streams.py`, `chat-streams.js`, `loop.py`, `server.py`, `services/agent/evals/latency.py`, the results in `docs/agent-eval.md`.

## 4. Deliverables

| Deliverable | Description | Location |
| --- | --- | --- |
| Send order | `user` event first, recall as its own event, turn races fixed, `client_id` | `services/agent/agent/loop.py`, `context.py` |
| Create with a message | A new chat and its first message in one request | `services/agent/agent/server.py`, `web/chat/chat-api.js` |
| Optimistic messages | Pending messages drawn at once, matched by `client_id`, Not sent / Retry | `web/chat/chat-pane.js`, `chat-thread.js`, `chat-cards.js` |
| The queue | Held messages in `agent.db`, routes, sent together when a turn ends or on Stop, paused by an error | `services/agent/agent/queue.py` |
| The queue strip | Above the composer: edit, Send now, remove, reorder, paused and waiting states | `web/chat/chat-queue.js` |
| Stream add/remove | A chat joins or leaves the shared stream without a reconnect | `services/agent/agent/streams.py`, `web/chat/chat-streams.js` |
| Latency check | Median times to the `user` event and the first token on the installed hub | `services/agent/evals/latency.py`, `docs/agent-eval.md` |
| Tests | Fake hub, fake model and the mock client | `services/agent/tests/test_send_order.py`, `test_threads_create.py`, `test_queue.py`, `test_streams_add.py`; `utils/tests/web/chat-thread.test.mjs`, `chat-queue.test.mjs`, `chat-streams.test.mjs` |
