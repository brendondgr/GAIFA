# Agent: AIHub's chat agent

One Claude-Code-style loop, written for a local model: call the model, run its tool calls, append the results, repeat until a reply has no tool calls. Design and research: [docs/agent-architecture.md](../../docs/agent-architecture.md); plan Phases 13–14.

## Files

| File | What it does |
|---|---|
| `agent/llm.py` | The model client: streams `/v1/chat/completions` from the relay (no `max_tokens`), thinking from `reasoning`/`reasoning_content`, leaked tool calls re-parsed |
| `agent/loop.py` | `Agent`: turns, pauses (`ask_user`, parameter cards), queued messages, cancel, actions (buttons), the step cap, fallback model, compaction |
| `agent/store.py` | `agent.db`: threads and their append-only event log; fork |
| `agent/context.py` | Messages rebuilt from the log, the context meter, result capping, compaction helpers |
| `agent/tools.py` | The local tools' schemas and `ToolSet` (core + loaded + pinned − disabled) |
| `agent/local.py` | The local tools: ask_user, update_todos, find_tools, load_tools, read_skill, view_output, read_result, remember |
| `agent/knowledge.py` | `data/agent/`: AGENT.md, memory, user skills; mod skills from the hub |
| `agent/prompts.py` | The system prompt, in plan order (the base text is `harness/systemprompt.md`) |
| `agent/harness.py`, `harness/` | The harness as versioned files (plan 22.1): the base in git, learned versions in `data/agent/harness/`, rollback |
| `agent/hooks.py` | Declarative hooks in the tool loop: hint_after_error, cap, require_first, trim (plan 22.2) |
| `agent/records.py` | Turn records (`turns` in agent.db, plan 21.4) |
| `agent/learn/` | Learning: `mine.py` preferences from card edits, answers and thumbs (21.5); `replay.py`, `loop.py`, `prompts.py`, `library.py`, `schedule.py` the harness learner (Phase 22) |
| `ui/page.js` | The Learning page: Preferences, Review, Tool usage, Harness, Runs, Library |
| `agent/hubapi.py` | AIHub over HTTP: tools, calls, approvals, outputs, skills, the event stream |
| `agent/server.py` | The HTTP API (`create_app`) |
| `evals/` | The eval (plan 13.5): `python -m evals.run --model skynet --runs 3` (`--live` for real outputs), `python -m evals.vision` |
| `tests/` | `.venv/bin/python -m pytest`: a scripted model (`fakemodel.py`) and a stand-in hub (`fakehub.py`); no model or GPU needed |

## API (through the hub: `/api/s/agent/…`)

- `GET/POST /v1/threads`, `GET/PATCH/DELETE /v1/threads/{id}` (mode `ask` | `auto` | `read_only`; settings `pinned`, `disabled`, `loaded`, `dry_run`)
- `POST /v1/threads/{id}/messages {text, attachments}`: starts a turn, or queues the message during one
- `GET /v1/threads/{id}/events?after=`, `GET /v1/threads/{id}/stream?after=` (SSE: events, then live deltas, progress and the context meter)
- `POST /v1/threads/{id}/answer {question_id, answers}`, `/approval {approval_id, approve, arguments?, remember?, confirm?}` (remember: once | thread | always, the hub's grants, plan 25.2; deleting a thread ends its grants), `/action {tool, arguments}`, `/fork {seq}`, `/cancel`, `/compact`; `GET /v1/threads/{id}/context`
- `GET /v1/models`, `GET/PUT /v1/settings` (AGENT.md, memory)
- Learning (Phases 21–22):
  - `POST /v1/threads/{id}/feedback {value, output_id | seq}`, `GET /v1/threads/{id}/turns`;
  - `GET/POST /v1/prefs`, `PATCH/DELETE /v1/prefs/{id}`, `POST /v1/prefs/{id}/approve|reject` (the hub's, proxied);
  - `POST /v1/learn/mine`, `POST /v1/learn/run`, `GET /v1/learn/runs[/{id}]`, `POST /v1/learn/runs/{id}/cancel`, `GET /v1/learn/library`, `GET /v1/learn/usage`;
  - `GET /v1/harness`, `GET /v1/harness/versions`, `GET /v1/harness/versions/{n}/diff`, `POST /v1/harness/versions/{n}/activate`.

## Learning

**What it learns from:** your card edits, the questions you answer, thumbs up or down, and what you say ("from now on…"). Eval dry runs and chats with learning switched off never count.

**Two levels:**
- **Preferences** (the hub's `/api/prefs`) fill your cards, marked "from your preferences". They come from what you state at once, and from the miner after you picked the same value twice in two chats (you approve those).
- **The harness learner** (`agent/learn/loop.py`, after Harness², arXiv 2610.14224) improves the agent's own instructions. It runs nightly, after an hour without a chat, or on Learn now. Per area it:
  1. reflects on your recent chats;
  2. proposes two scoped edits;
  3. replays your chats under each as dry runs;
  4. composes what the replays support;
  5. gates it on the eval;
  6. adopts tool notes, skills and hooks, while prompt or guardrail changes wait for you on the Learning page.

Every version can be rolled back there, and the base stays in git.

## Settings (`service.toml` `[run].env`)

`AGENT_MODEL` (default `skynet`: Gemma 4 31B through the relay), `AGENT_FALLBACK_MODEL` (`gemma4-26B`, local), `AGENT_MAX_STEPS` (25), `AGENT_DB`, `AGENT_DATA`, `AGENT_LLM_URL`.
