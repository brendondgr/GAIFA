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
| `agent/prompts.py` | The system prompt, in plan order |
| `agent/hubapi.py` | AIHub over HTTP: tools, calls, approvals, outputs, skills, the event stream |
| `agent/server.py` | The HTTP API (`create_app`) |
| `evals/` | The eval (plan 13.5): `python -m evals.run --model skynet --runs 3` (`--live` for real outputs), `python -m evals.vision` |
| `tests/` | `.venv/bin/python -m pytest`: a scripted model (`fakemodel.py`) and a stand-in hub (`fakehub.py`); no model or GPU needed |

## API (through the hub: `/api/s/agent/…`)

- `GET/POST /v1/threads`, `GET/PATCH/DELETE /v1/threads/{id}` (mode `ask` | `auto` | `read_only`; settings `pinned`, `disabled`, `loaded`, `dry_run`)
- `POST /v1/threads/{id}/messages {text, attachments}`: starts a turn, or queues the message during one
- `GET /v1/threads/{id}/events?after=`, `GET /v1/threads/{id}/stream?after=` (SSE: events, then live deltas, progress and the context meter)
- `POST /v1/threads/{id}/answer {question_id, answers}`, `/approval {approval_id, approve, arguments?}`, `/action {tool, arguments}`, `/fork {seq}`, `/cancel`, `/compact`; `GET /v1/threads/{id}/context`
- `GET /v1/models`, `GET/PUT /v1/settings` (AGENT.md, memory)

## Settings (`service.toml` `[run].env`)

`AGENT_MODEL` (default `skynet`: Gemma 4 31B through the relay), `AGENT_FALLBACK_MODEL` (`gemma4-26B`, local), `AGENT_MAX_STEPS` (25), `AGENT_DB`, `AGENT_DATA`, `AGENT_LLM_URL`.
