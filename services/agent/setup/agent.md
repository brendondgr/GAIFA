<!-- aihub-setup
id = "agent"
title = "Chat agent"
models = []
scan = []
summary = "Chat agent: the Chat page's tool loop (files, search, images, speech) on any chat model the relay serves"
gpu = false
disk_gb = 0.05
needs = ["uv"]
after = ["relay"]
check = "aihub check agent"

[[steps]]
run = "aihub install agent"
what = "makes .venv/ from requirements-dev.txt (about 45 MB, seconds from uv's cache)"

[[steps]]
run = "aihub start agent"
what = "starts the agent on 127.0.0.1:5100; set AGENT_MODEL to one of your relay's models (Choosing models in its setup doc)"
-->

# Chat agent: setup

The format is in [docs/mods.md §9](../../../docs/mods.md#9-setup-docs).

## What it is

The `agent` mod (port 5100) is AIHub's chat agent: our own tool loop (call the model, run its tool calls, repeat), behind the Chat page and the Learning page (`#/s/agent/learning`). Its one environment is `.venv/` in this folder: FastAPI, uvicorn, httpx and Pillow. It runs no model. Every model call goes to the [relay](../../relay/setup/relay.md) at `http://127.0.0.1:4000/v1`, and every tool call goes through the hub's catalog. So the agent works only when the relay has at least one chat model, and when the model names below exist on your relay.

## Tested with

Read from this machine on 2026-10-21:

| Part | Version |
|---|---|
| Python | 3.12.13 (uv-managed) |
| fastapi, uvicorn, httpx, pydantic | 0.142.2, 0.54.0, 0.28.1, 2.13.5 |
| pillow | 12.3.0 |
| pytest | 9.1.1 (from `requirements-dev.txt`) |

`requirements.txt` doesn't pin versions; these are what uv picked when the venv was made.

## Prerequisites

- [The hub](../../../docs/setup/hub.md) and the [relay](../../relay/setup/relay.md), installed first.
- A chat model on the relay, from one of: [llama.cpp](../../lcpp/setup/llama-cpp.md) (`lcpp`), [vLLM](../../vllm/setup/vllm.md), an endpoint added on the relay's page, or [OpenCode](../../opencode/setup/opencode.md)'s free hosted models. The model must take tool calls (OpenAI `tools`).
- No GPU of its own.

## Install

```bash
aihub install agent
```

Runs `install.sh`: makes `.venv/` with uv-managed Python and installs `requirements-dev.txt` (about 45 MB, seconds from uv's cache).

Then point it at models that exist on **your** relay (next section) and start it:

```bash
aihub start agent
```

## Choosing models

The agent runs no model and downloads none, so it has no suggestions. It sends every turn to the relay under a model name, so `AGENT_MODEL` (and, optionally, `AGENT_FALLBACK_MODEL`) must be names your relay's `/v1/models` lists, from a model that takes tool calls. Where such names come from:
- **[llama.cpp](../../lcpp/setup/llama-cpp.md) (`lcpp`):** any GGUF you add; a running instance registers under its catalog nickname (`nicknames` in `services/lcpp/data/models.json`), or the alias given at launch. Its doc suggests two models that take tool calls.
- **[vLLM](../../vllm/setup/vllm.md):** a loaded profile registers under its `alias` (such as `Qwen3-0.6B-vLLM`; the profiles are parked here).
- **[OpenCode](../../opencode/setup/opencode.md):** `agent`, or a free hosted id such as `opencode/glm-5.3-flash-free`, with no GPU at all.
- **An endpoint you added** on the relay's page (any OpenAI-compatible server): its alias.

A model that is always up makes the better default; an lcpp nickname is listed only while its instance runs. The thread's model can also be changed per chat in Chat's header.

## Configuration

`service.toml` `[run.env]` sets every key. To change one on your machine, don't edit `service.toml`: put it in `config.toml`, which wins (architecture §4.4), and restart the mod:

```toml
[services.agent]
env = { AGENT_MODEL = "gemma4-26B", AGENT_FALLBACK_MODEL = "" }
```

| Key | Set to | Required | Meaning |
|---|---|---|---|
| `AGENT_MODEL` | `skynet` | yes | the default chat model: a name the relay's `/v1/models` lists |
| `AGENT_FALLBACK_MODEL` | `gemma4-26B` | optional | when the thread's model doesn't answer, the turn goes on with this one; empty for none |
| `AGENT_LLM_URL` | `http://127.0.0.1:4000/v1` | yes (set) | the relay |
| `AGENT_DB` | `{databases}/agent.db` | yes (set) | threads and their event logs |
| `AGENT_DATA` | `{root}/data/agent` | yes (set) | AGENT.md, memory, skills, the learned harness |
| `AGENT_MAX_STEPS` | `25` | optional | tool steps per turn |
| `AGENT_INLINE_TOKENS` | `6000` | optional | an attached document up to this size goes into the message whole |
| `AGENT_DEFAULT_WINDOW`, `AGENT_REPLY_RESERVE`, `AGENT_SUMMARY_IDLE_MIN`, `AGENT_ALL_TOOLS` | unset | optional | 32768, 4096, 30 and none by default (`agent/server.py`) |

**The two model names are this machine's,** as examples: `skynet` is a remote GPU box reached through an SSH tunnel that exists only here, and `gemma4-26B` is lcpp's nickname for the Gemma 4 26B-A4B GGUF used here. On your machine, set names you have (Choosing models, above).

**Settings → Agent** holds the Auto mode's judge model: `config.toml [agent.judge]`, here `model = "gemma4-26B"` with `backend = "relay"`. The default in code is `minicpm-5-2B`, which isn't on this relay either: pick one of yours there, or the `decide` mod's models with `backend = "decide"`. The same page has the document defaults and speech input.

## Check it works

```bash
aihub check agent
```

Expect `agent: all checks passed` (two widgets, the Learning page).

```bash
curl -s http://127.0.0.1:7000/api/s/agent/v1/models
```

The agent's view of the relay: `default`, `fallback`, and `models` with each one's facts (`context_length`, `tools`, `vision`, `reasoning`). Here (2026-10-21) `{"default":"skynet","fallback":"gemma4-26B","models":[{"id":"auto",…},{"id":"skynet",…,"health":"healthy"}]}`. Your `AGENT_MODEL` should be in that list; `gemma4-26B` isn't here because no lcpp instance was running.

The unit tests (a scripted model and a stand-in hub; no model, relay or GPU):

```bash
cd services/agent && .venv/bin/python -m pytest -q
```

Expect `225 passed` (2026-10-21, about a minute).

## What to look for

- **Every chat fails or falls back.** `AGENT_MODEL` names a model your relay doesn't have (`skynet` on any other machine). Check the list above and set it in `config.toml`.
- **A fallback that's off most of the time.** An lcpp nickname is on the relay only while its instance runs. Start it from the LLM Launcher page, or choose a fallback that is always up.
- **The judge asks about everything in Auto.** Its model doesn't answer within `timeout_s` (3 s) or isn't on the relay, so each call falls back to asking you. Pick a reachable model in Settings → Agent.
- **A model without tool calls** answers but never uses a tool. The relay's facts (`tools`) say which ones take them.
- The eval (`evals/`, results in [docs/agent-eval.md](../../../docs/agent-eval.md)) runs real models; it's not part of the install check.

## Known gaps

- `aihub install agent` doesn't check that `AGENT_MODEL` and `AGENT_FALLBACK_MODEL` exist on the relay; nothing warns until a chat fails.
- `requirements.txt` is unpinned.
