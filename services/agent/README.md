# Agent: GAIFA's chat agent

One Claude-Code-style loop, written for a local model: call the model, run its tool calls, append the results, repeat until a reply has no tool calls. Design and research: [docs/agent-architecture.md](../../docs/agent-architecture.md); plan Phases 13–14.

## Files

| File | What it does |
|---|---|
| `agent/llm.py` | The model client: streams `/v1/chat/completions` from the relay (no `max_tokens`), thinking from `reasoning`/`reasoning_content`, leaked tool calls re-parsed |
| `agent/loop.py` | `Agent`: turns, pauses (`ask_user`, parameter cards), queued messages, cancel, actions (buttons), the step cap, fallback model |
| `agent/compaction.py` | Compaction, mixed into `Agent`: clear old tool results, then summarize the older part of the chat |
| `agent/store.py` | `agent.db`: threads and their append-only event log; fork |
| `agent/context.py` | Messages rebuilt from the log, the context meter, result capping, compaction helpers |
| `agent/tools.py` | The local tools' schemas and `ToolSet` (core + loaded + pinned − disabled) |
| `agent/local.py` | The local tools: ask_user, update_todos, find_tools, load_tools, read_skill (a skill's body and its other files, `<id>/<path>`; a workspace folder's skills and instruction files, `<folder>:<skill>`, through the workspace mod), view_output (a PDF's page as an image; the start of a text output), read_result, chat_search, memory_search, remember |
| `agent/knowledge.py` | `data/agent/`: AGENT.md, memory, user skills; mod skills from the hub |
| `agent/prompts.py` | The system prompt, in plan order (the base text is `harness/systemprompt.md`) |
| `agent/harness.py`, `harness/` | The harness as versioned files (plan 22.1): the base in git, learned versions in `data/agent/harness/`, rollback |
| `agent/hooks.py` | Declarative hooks in the tool loop: hint_after_error, cap, require_first, trim (plan 22.2) |
| `agent/records.py` | Turn records (`turns` in agent.db, plan 21.4) |
| `agent/gpuwait.py` | "Waiting for the GPU" on the turn (plan 31.4): each model call names its chat (`X-GAIFA-Thread`); while the relay holds it in GAIFA's GPU queue, the hub's `GET /api/gpu` shows a waiting lease of that chat and the agent sends the transient `gpu_wait` `{text, eta_s, ahead}` (an empty one clears it) |
| `agent/learn/` | Learning: `mine.py` preferences from card edits, answers and thumbs (21.5); `replay.py`, `loop.py`, `prompts.py`, `library.py`, `schedule.py` the harness learner (Phase 22) |
| `ui/page.js` | The Learning page: Preferences, Review, Tool usage, Harness, Runs, Library |
| `agent/hubapi.py` | GAIFA over HTTP: tools, calls, approvals, outputs, skills, the event stream |
| `agent/server.py` | The HTTP API (`create_app`) |
| `agent/memory/` | Structured memory (plan structured-memory): `model.py` kinds, paths, normalized names; `store.py` `MemoryStore` (entities, aliases, anchors, the log and undo, `mem_*` tables in `agent.db`); `facts.py` facts added, replaced, retired, approved, forgotten, searched by keyword (FTS5); `importer.py` agent preferences and the old memory files become facts; `index.py` keeps the embed mod's `memory` collection in step; `search.py` `memory_search`: names, keywords and meaning fused |
| `agent/api_memory.py` | The memory routes: `/v1/memory/tree`, `/entities`, `/facts`, `/undo`, `/log` |
| `agent/api_skills.py` | Your own skills (skill-sources 3.1): `POST /v1/skills` (a folder's files, a zip or one SKILL.md, base64), `POST /v1/skills/copy` (a workspace folder's skill), `PATCH /v1/skills/{name}` (on or off), `DELETE /v1/skills/{name}` (to `data/agent/skills/.trash/`); `.gaifa.json` beside a skill: where it came from, on or off, the hub's pattern screening |
| `evals/` | The eval (plan 13.5): `python -m evals.run --model skynet --runs 3` (`--live` for real outputs; each run's chats and outputs are deleted afterwards unless `--keep`, `evals/cleanup.py`), `python -m evals.vision` |
| `tests/` | `.venv/bin/python -m pytest`: a scripted model (`fakemodel.py`) and a stand-in hub (`fakehub.py`); no model or GPU needed |

## API (through the hub: `/api/s/agent/…`)

- `GET/POST /v1/threads`, `GET/PATCH/DELETE /v1/threads/{id}` (mode `ask` | `auto` | `read_only`; settings `pinned`, `disabled`, `loaded`, `dry_run`)
- `GET /v1/threads?environment=a,b&sort=updated|created|title&offset=` (a chat without `settings.environment` is in `default`), `GET /v1/threads/groups?archived=` (per environment: count, newest `updated`, running): the chat list's sections (plan 41.1)
- `POST /v1/threads/{id}/messages {text, attachments}`: starts a turn, or queues the message during one
- `GET /v1/threads/{id}/events?after=`, `GET /v1/threads/{id}/stream?after=` (SSE: events, then live deltas, progress and the context meter)
- `GET /v1/streams?threads=<id>:<after>,…` (SSE for up to 64 chats on one connection: each chat's events after its seq and a `ready` for it, then live events of all of them, each with `thread_id`; an unknown chat gets `gone`. The Chat page's split view uses it, plan chat-split 3.1)
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

`AGENT_MODEL` (default `skynet`: Gemma 4 31B through the relay), `AGENT_FALLBACK_MODEL` (empty: no fallback; this machine sets `gemma4-26B` in its `config.toml`; see [setup/agent.md](setup/agent.md) to pick yours), `AGENT_MAX_STEPS` (25), `AGENT_INLINE_TOKENS` (6000: an attached document up to this size goes into the message whole; plan 24.5) and `AGENT_REPLY_RESERVE` (4096: tokens kept free for the reply), the defaults for Settings → Agent → Documents (saved in `data/agent/documents.json`; plan 24.9), `AGENT_DB`, `AGENT_DATA`, `AGENT_LLM_URL`.
