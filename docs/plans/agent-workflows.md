# Plan: Agent workflows (sub-agents in chats)

**Asked for:** 2026-11-09 · **Status:** Planned

## 1. Introduction

A chat can't hand work to another agent today: the agent is one loop per chat, and no tool starts, messages or waits on another chat. This plan lets a chat spawn **sub-agents**, each a real chat of its own, linked to the chat that started it. A parent with its sub-agents is an **agent workflow** (the name borrowed from Claude Code). The parent calls an `agent` tool with a prompt; the child runs in its own context and its final answer comes back as the tool's result (or, in the background, as a note that starts the parent's next turn). The sidebar shows the children nested under the parent's row as a tree; the parent's activity fold shows each child live, and **Open** puts it in a split pane. Claude Code and Codex get the same over `/mcp`: start a GAIFA chat, send to it, wait and read its answer.

This reverses a recorded decision, "one agent; no sub-agents for now" (`docs/agent-architecture.md` §1), so it carries its answers to that decision's three reasons. **Tokens:** a step and token budget per child and per workflow, and a cap on children. **Sequential work gets worse:** the prompt says to spawn only for independent work (research, surveys of folders or pages) and never to split sequential edits; Phase 5's eval measures it. **One GPU only queues:** children of a local model run one at a time (the gain there is a clean context, not speed); remote and cloud models run several. Children are read-only unless the parent asks for one writer.

Approvals keep GAIFA's rule that **the model never decides whether a call is allowed**: a child's approval or question goes to the parent agent, which may **deny** it (with a reason the child reads) or **forward** it; forwarded ones are cards on the parent chat that you decide. The parent can't approve. Grants you give in the workflow cover all its chats.

Builds on: architecture §14 (the agent, approvals, grants) and §14.1 (scheduled tasks); the scheduled-tasks runner (`services/agent/agent/tasks/runner.py`: a chat made in code, its grants, `on_turn_end`, a queue with a cap), which `agent/workflows/` mirrors; chat-split (Open in a pane), chat-responsive (one stream, the queue), settings-that-stick (open state on the hub), web-approvals (the judge), and the `/mcp` server (`utils/tools/mcp.py`, architecture §6). `services/agent/agent/loop.py` (783 lines) and `server.py` (737) are near the limit: everything new goes in new modules.

## 2. Gaps & unanswered questions

- **Who approves a child's calls?** *Answered (2026-11-09):* the parent agent filters (deny with a reason, or forward), you approve; the parent can never say yes. Anything the workflow already allows (its mode, grants, the Auto judge) runs without asking.
- **Where do children show?** *Answered:* nested under the parent's row in the sidebar, out of the flat list.
- **External agents?** *Answered:* in this plan (Phase 4).
- **Scripted workflows** (saved fan-out / verify scripts, like Claude Code's Workflow tool). *Answered:* not in this plan; a later plan if wanted.
- **Depth.** *Assumption:* 1: a child can't spawn children (`max_depth = 1`, a setting).
- **Child context.** *Assumption:* fresh, like Claude Code's sub-agents: the parent's project, instructions, environments and skills, the profile and recall, and the parent's prompt, but not the parent's history.
- **Child model.** *Assumption:* the parent's; the `model` argument may name any model the parent's chat could use.
- **Writes.** *Assumption:* a child is read-only (the hub refuses anything above `read` for it) unless spawned with `write: true`; at most one live writer per workflow.
- **Caps.** *Assumption:* `[agent.workflows]` `enabled = true`, `parallel_local = 1`, `parallel_remote = 3`, `max_children = 8` per workflow, `max_depth = 1`, `child_max_steps = 25`, `workflow_tokens = 400000`; a queued child waits at most 30 min. *Added in 1.3:* `min_window = 16384`: the `agent` tool only in chats whose model's window is at least that (a small window has no room for a workflow's answers, and the tool's schema alone crowded the test chats' 8k windows).
- **Memory and learning.** *Assumption:* children read memory but don't write it (`no_learn`, the memory tools left out); the miner and learner skip them.
- **Mode.** *Assumption:* children take the parent's mode. A chat started over `/mcp` may not be Bypass.
- **Deleting and archiving a parent.** *Assumption:* deleting a parent deletes its children (the confirm says how many) and archiving archives them; forking a parent copies no children. Deleting a child alone is allowed.
- **Unattended parents** (scheduled runs): children inherit `unattended`; what would ask is refused as in the run itself, never forwarded.
- **`docs/agent-rebuild-guide.md`** (untracked, not this plan's) also says "no sub-agents"; its owner updates it.

## Phase 1 — The engine (M)

- [x] **1.1 Children in the store: `services/agent/agent/store.py`, `agent/api_workflows.py`.**
  - **Marker:** a child is a thread with `parent_id` set and `settings.spawn = {root, parent, label, by: "agent"|"mcp", tool_call_id, write, depth}`; a fork has `parent_id` without `spawn`. `SPAWN_OF` (a `json_extract` like `TASK_OF`).
  - **Store:** `children(tid)`, `tree(root)` (root plus children with state, label, model, `seen`, last event time), `root_of(tid)`; `list_threads`, `count` and `groups` leave children out unless `children=1` or `q` is given (a search hit carries `parent`); a thread row carries `children` (count) and `spawn`.
  - **Routes** (a new router in `api_workflows.py`, mounted in `server.py`): `GET /v1/threads/{tid}/tree`; `DELETE /v1/threads/{tid}` and archive cascade to children.
  *Done when:* `services/agent/tests/test_workflow_store.py` covers the marker vs a fork, the tree, the list filters and the cascades.

- [x] **1.2 The runner: `services/agent/agent/workflows/runner.py`, `workflows/settings.py`.**
  - `Workflows(agent)`, made in the lifespan next to the task runner, hooked to `agent.on_turn_end`. `spawn(parent, prompt, label, model=None, write=False, background=False) -> child_id`: refuses past `max_depth`, `max_children` or a second live writer (`409 workflow_limit` with the reason); makes the child with `child_settings(parent, …)`; queues it, launches while under `parallel_local` / `parallel_remote` (local or remote from the relay's model facts), drains on each end.
  - `child_settings`: the parent's model, mode, project, environments, `mcp_on`, skills and `unattended`; `no_learn`; `spawn`; `max_steps = child_max_steps`. Per-thread `max_steps` replaces the loop's constant (a one-line change in `loop.py`).
  - **Budgets:** tokens counted from the workflow's `usage` events; past `workflow_tokens` its running children are stopped with a note.
  - **End:** on a child's turn end, `result(child)`: its last assistant text capped at ~2k tokens (`…open the chat for the rest`), its state, refused calls.
  - **Stop:** `Agent.cancel` of a parent cancels its children (a hook the runner registers; no loop logic moves).
  *Done when:* `test_workflow_runner.py` (scripted model, `fakehub.py`): two children queue and run one at a time under `parallel_local = 1`, the limits refuse with their codes, the budget stops a child, cancelling the parent cancels both.

- [x] **1.3 The `agent` tool, in the foreground: `agent/workflows/tool.py`, `tools.py`, `prompts.py`.**
  - A local tool `agent {prompt, label, model?, write?}` offered when `[agent.workflows] enabled` and the chat isn't at `max_depth` (gated in `ToolSet` like `task_note`). It spawns and waits like `_wait_call`: transient `progress` events carry the child's state and current step for the fold; the result is `{child, label, state, answer, refused}`.
  - A **Sub-agents** prompt part (only when the tool is offered): when to spawn (independent parts, broad reading, a second opinion) and when not to (sequential edits, a single lookup), that a child sees none of this chat, and that a child is read-only unless `write`.
  *Done when:* `test_workflow_tool.py`: a scripted parent spawns two children, gets both answers as results and replies; a child at depth 1 isn't offered the tool; the prompt part appears only with the tool.

- [x] **1.4 The hub side: `utils/tools/calls.py`, `utils/tools/grants.py`, the agent's `origin`.**
  - The agent's calls carry `origin.root`, `origin.parent` and `origin.read_only` (from `settings.spawn`).
  - `calls.py`: a call above `read` with `origin.read_only` is refused (`read_only`, with a fix: "ask the parent to spawn a writer").
  - `grants.py`: a grant on thread R also matches calls whose `origin.root` is R, so "allow in this chat" on the parent covers the workflow.
  - Docs: architecture §14 (origin fields, the read-only refusal, grants by root).
  *Done when:* `utils/tests/tools/test_workflow_origin.py` covers the refusal and the grant match; the agent's suite is green.

**Wire — Phase 1:** nothing in the UI; a parent's `agent` call shows as a generic step.

**Checks & deliverables — Phase 1**
- [ ] Second hub (`--port 7078`, scripted model): a chat spawns two read-only children that read files in its environment; their answers come back; a child's write is refused with the fix; Stop on the parent stops both.
- [ ] Delivered: `agent/workflows/` (runner, settings, tool), `api_workflows.py`, the store's tree, origin fields, read-only refusal, grants by root.

## Phase 2 — Background children, messages and requests (M)

- [ ] **2.1 Background and messages: `workflows/tool.py`, `workflows/notes.py`.**
  - `agent {…, background: true}` returns at once with the child's id. Further local tools: `agent_wait {child?, timeout}` (the first or named child to finish), `agent_send {child, text}` (a `user` event `by: "parent"`), `agent_stop {child}`, `agent_list`.
  - When a background child ends, the parent gets a stored `agent_done` event (read by the model as `[sub-agent <label> finished] <answer>`); an idle parent starts a turn, a running one reads it on its next call (like a steer), a parent waiting on you holds it until then.
  *Done when:* `test_workflow_background.py`: a background child's end starts the idle parent's turn; `agent_send` reaches a running child; `agent_stop` writes the cancelled result.

- [ ] **2.2 Requests go to the parent: `workflows/requests.py`, `local.py`.**
  - A child's `needs_approval` or `ask_user` also writes an `agent_request` event on the parent: `{id, child, label, kind: approval|question, approval_id|question_id, tool, risk, summary}`. A foreground `agent` wait returns early with `needs_review`; a background request starts an idle parent's turn.
  - `agent_review {request, action: "deny"|"forward", reason}`: deny decides the hub approval as denied (or answers the question) with the reason, which the child reads; forward writes `agent_forwarded`, and the card is yours. There is no approve action, and the route refuses one from the model. A request not reviewed by the end of the parent's turn is forwarded. You can decide any time from the header's Approvals or the child's chat.
  - Unattended parents: the child's `ask` is refused as today (`unattended`), nothing is forwarded.
  *Done when:* `test_workflow_requests.py`: deny reaches the child with its reason; forward leaves the approval open for the user; an unreviewed request is forwarded at turn end; the model can't approve; an unattended child is refused.

- [ ] **2.3 Deciding from the parent: `api_workflows.py`.**
  - `POST /v1/threads/{parent}/requests/{rid}` `{approve, arguments?, reason?, remember?}` decides the child's approval through `agent.approval(child, …)`; `remember: "chat"` writes the grant on the root (1.4 covers the children). `GET /v1/threads/{tid}/requests` lists the open ones.
  - Docs: brief §6 / §11.7 (the routes and events).
  *Done when:* `test_workflow_decide.py`: an approval from the parent's route runs the child's call; a remembered one covers a second child's same call.

- [ ] **2.4 Children and memory: `memory/`, `learn/mine.py`, `tasks/runner.py`.**
  - Children get no `remember` / `agent_memory_*` tools; the miner, auto-learning and the learner skip `spawn` chats. A scheduled run's children are covered by the run's grants (the run is the root).
  *Done when:* `test_workflow_memory.py` and an added case in the tasks tests.

**Wire — Phase 2:** none yet; the events exist for Phase 3.

**Checks & deliverables — Phase 2**
- [ ] Second hub: a parent starts two background children, keeps talking, and answers when both finish; a child's web fetch is forwarded and approved from the parent's route; a denied one reaches the child with the reason.
- [ ] Delivered: background children, `agent_wait/send/stop/list/review`, requests, the decide route.

## Phase 3 — The UI (L)

- [ ] **3.1 Client and mock: `web/chat/chat-api.js`, `chat-mock-agents.js`.**
  - `c.tree(tid)`, `c.requests(tid)`, `c.decideRequest(parent, rid, …)`; the stream's new events (`agent_request`, `agent_forwarded`, `agent_done`); `?mock` gets a workflow with a running, a waiting and a finished child.
  *Done when:* `utils/tests/web/chat-agents.test.mjs` covers the client calls and the mock.

- [ ] **3.2 The sidebar tree: `web/chat/chat-tree.js`, `chat-list.js`.**
  - A row with `children > 0` gets a chevron; open, it fetches the tree and draws the children beneath it with ├ / └ lines: label, a running / queued / waiting / error dot, an unread dot (finished, not seen). Open rows kept on the hub (`hub.chat.tree.open`); the tree follows the stream. Children leave the flat list, the date, environment and project groups; Show all's search shows them with "in <parent>".
  *Done when:* the web test covers the tree's rows, and the browser shows it on the second hub (live and `?mock`).

- [ ] **3.3 The parent's fold: `web/chat/chat-agents.js`.**
  - `registerStep('agent', …)` (spawning, running, done sentences) and `registerCard('live:agent', …)`: the child's label, state, current step, tokens, **Open** (a split pane, `chat-split.js`) and **Stop**. Background children as a small strip above the composer while they run.
  *Done when:* browser check: a live workflow draws its children's steps and Open splits the pane.

- [ ] **3.4 Request cards on the parent: `web/chat/chat-agent-requests.js`.**
  - Docked on the parent's composer like approvals: "<label> wants to <tool summary>", the parent's note when it forwarded, "the parent agent is reviewing…" before that, **Approve / Deny / Allow in this workflow**. The header's Approvals popover names the child and its parent.
  *Done when:* browser check: a forwarded request decided on the parent runs in the child.

- [ ] **3.5 The child's chat and the dialogs: `chat-header.js`, `chat-actions.js`.**
  - A link back ("↖ <parent title>"), a sub-agent chip and a read-only chip; the composer works (your message is a normal `user` event). Delete and Archive on a parent say how many sub-agents go with it.

- [ ] **3.6 Settings: `config.example.toml`, `web/settings/`.**
  - `[agent.workflows]` with the 1.2 defaults; Settings → Agent → Sub-agents rows (on/off, parallel local and remote, children, depth, steps, tokens), with keys, defaults and Reset.
  - Docs: brief §11 (a new section on workflows), `web/PATCHES.md`, `docs/structure.md`.
  *Done when:* the settings tests and the docs tests pass.

**Wire — Phase 3:** the sidebar tree, the fold's live card, request cards, the child's header, Settings → Agent → Sub-agents.

**Checks & deliverables — Phase 3**
- [ ] Browser, installed hub after `gaifa restart`: a chat spawns three readers over a folder, the tree fills and updates, Open splits a child beside the parent, a forwarded request is approved on the parent, deleting the parent removes the tree.
- [ ] Delivered: `chat-tree.js`, `chat-agents.js`, `chat-agent-requests.js`, `chat-mock-agents.js`, the settings rows.

## Phase 4 — Claude Code and Codex over `/mcp` (M)

- [ ] **4.1 Chat tools for outside agents: `agent/api_external.py`, `services/agent/service.toml`.**
  - Routes and `[tools]` entries with `mcp = true` (the catalog names them `agent_chat_*`): `chat_start {prompt, title?, model?, mode?, environment?, project?}` (risk `execute`), `chat_send {chat, text}` (`execute`), `chat_read {chat, after?}` (`read`: state, the last answer, open approvals as `waiting_for_you`), `chat_wait {chat, timeout ≤ 60}` (`read`), `chat_stop {chat}` (`write`), `chat_list` (`read`: chats this client started).
  - A started chat is a root with `spawn.by = "mcp"` and the client's name; it may spawn sub-agents as any chat. `mode: "bypass"` is refused. Its approvals are yours (the chat, the header); the outside agent only sees that they wait.
  *Done when:* `test_external_chats.py`: start → wait → read returns the answer; Bypass is refused; an approval shows as `waiting_for_you`.

- [ ] **4.2 The client's name: `utils/tools/mcp.py`.**
  - MCP calls carry `origin.client` (from `initialize`'s `clientInfo`). Docs: architecture §6 (`/mcp`).
  *Done when:* `utils/tests/tools/test_mcp_origin.py`.

- [ ] **4.3 In the UI: `chat-tree.js`, `chat-header.js`.**
  - A "from Claude Code" chip on such chats and their rows; Show all can filter them.

**Checks & deliverables — Phase 4**
- [ ] Live: a Claude Code session with GAIFA's `/mcp` starts a chat, waits, reads its answer, and sees an approval it can't decide; Codex the same if installed.
- [ ] Delivered: `api_external.py`, the six tools, the client's name, the chip; `docs/` on using GAIFA's chats from another agent.

## Phase 5 — Eval and the decision (S)

- [ ] **5.1 `services/agent/evals/subagents.py`.**
  - Cases where splitting should help (survey three folders, compare three pages, a second opinion) and where it shouldn't be used (a sequential edit, one lookup): pass, tokens, time, and spawns where none belonged; with and without the tool. Run on the remote test LLM; at most 2 cases at once (the eval also loads stt/embed/decide on this GPU).
  *Done when:* results in `docs/agent-eval.md`.
- [ ] **5.2 The decision.** Update `docs/agent-architecture.md` §1's "Agents" row with what the eval found; if spawning hurt on the local model, `enabled` defaults to false for local models.

## 4. Deliverables

| Deliverable | Description | Location |
| --- | --- | --- |
| Workflows runner | spawn, queue, caps, budgets, results, stop with the parent | `services/agent/agent/workflows/runner.py`, `settings.py` |
| Sub-agent tools | `agent`, `agent_wait/send/stop/list/review` | `services/agent/agent/workflows/tool.py`, `requests.py`, `notes.py` |
| Tree and request routes | `/v1/threads/{id}/tree`, `/requests` | `services/agent/agent/api_workflows.py` |
| External chat tools | `agent_chat_*` at `/mcp` | `services/agent/agent/api_external.py`, `service.toml` |
| Hub changes | read-only origin, grants by root, MCP client name | `utils/tools/calls.py`, `grants.py`, `mcp.py` |
| UI | sidebar tree, fold card, request cards, child header, settings | `web/chat/chat-tree.js`, `chat-agents.js`, `chat-agent-requests.js`, `chat-mock-agents.js`, `web/settings/` |
| Eval | when sub-agents help | `services/agent/evals/subagents.py`, `docs/agent-eval.md` |
| Tests | scripted models and the fake hub; hub tools; web | `services/agent/tests/test_workflow_*.py`, `test_external_chats.py`, `utils/tests/tools/test_workflow_origin.py`, `test_mcp_origin.py`, `utils/tests/web/chat-agents.test.mjs` |
