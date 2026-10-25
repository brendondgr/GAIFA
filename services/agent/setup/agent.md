<!-- gaifa-setup
id = "agent"
title = "Chat agent"
models = []
scan = []
summary = "Chat agent: the Chat page's tool loop (files, search, images, speech) on any chat model the relay serves"
gpu = false
disk_gb = 0.05
needs = ["uv"]
after = ["relay"]
check = "gaifa check agent --start"

[[steps]]
run = "gaifa install agent"
what = "makes .venv/ from requirements-dev.txt (about 45 MB, seconds from uv's cache)"

[[steps]]
run = "gaifa start agent"
what = "starts the agent on 127.0.0.1:5100; after install, the wizard asks which of your relay's models it uses"

[[config]]
key = "services.agent.env.AGENT_MODEL"
text = "Which model should Chat use? (one your relay serves; with no local LLM, add a hosted provider)"
required = true
restart = "agent"

[[config]]
key = "agent.judge.model"
text = "Which model should judge Auto mode's actions? (a small, quick one is fine; without one, Auto mode asks about everything)"

[[variants]]                    # plan 39.1: no GPU work, so one variant everywhere; tested on Linux
accel = "cpu"
os = ["linux", "wsl", "darwin"]
tested = ["linux"]
-->

# Chat agent: setup

The format is in [docs/mods.md §9](../../../docs/mods.md#9-setup-docs).

## What it is

The `agent` mod (port 5100) is GAIFA's chat agent: our own tool loop (call the model, run its tool calls, repeat), behind the Chat page and the Learning page (`#/s/agent/learning`). Its one environment is `.venv/` in this folder: FastAPI, uvicorn, httpx and Pillow. It runs no model. Every model call goes to the [relay](../../relay/setup/relay.md) at `http://127.0.0.1:4000/v1`, and every tool call goes through the hub's catalog. So the agent works only when the relay has at least one chat model, and when the model names below exist on your relay.

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
gaifa install agent
```

Runs `install.sh`: makes `.venv/` with uv-managed Python and installs `requirements-dev.txt` (about 45 MB, seconds from uv's cache).

Then point it at models that exist on **your** relay (next section) and start it:

```bash
gaifa start agent
```

## Choosing models

The agent runs no model and downloads none, so it has no suggestions. `gaifa setup` asks which model it uses once the relay and your LLM mods are installed (their models exist only then), offers to add a hosted provider when the relay has none, saves the answer through the hub (into `config.toml`, applied at once), restarts the agent, and checks it's on the relay; an agent passes it with `--set "services.agent.env.AGENT_MODEL=<name>"`. The Auto judge's model (`[agent.judge] model`) is asked the same way, and can be skipped. It sends every turn to the relay under a model name, so `AGENT_MODEL` (and, optionally, `AGENT_FALLBACK_MODEL`) must be names your relay's `/v1/models` lists, from a model that takes tool calls. Where such names come from:
- **[llama.cpp](../../lcpp/setup/llama-cpp.md) (`lcpp`):** any GGUF you add; a running instance registers under its catalog nickname (`nicknames` in `services/lcpp/data/models.json`), or the alias given at launch. Its doc suggests two models that take tool calls.
- **[vLLM](../../vllm/setup/vllm.md):** a loaded profile registers under its `alias` (such as `Qwen3-0.6B-vLLM`; the profiles are parked here).
- **[OpenCode](../../opencode/setup/opencode.md):** a free hosted id such as `opencode/glm-5.3-flash-free`, with no GPU at all. (Its `agent` model is OpenCode's own coding agent, which runs shell commands in its folder; setup doesn't offer it as Chat's model.)
- **An endpoint you added** on the relay (any OpenAI-compatible server, such as a hosted provider: [Adding a hosted provider](../../relay/setup/relay.md#adding-a-hosted-provider)): the model ids you listed on it, or its alias. With no GPU, this or OpenCode is the way to a model.

A model that is always up makes the better default; an lcpp nickname is listed only while its instance runs. The thread's model can also be changed per chat in Chat's header.

## Configuration

`service.toml` `[run.env]` sets every key. To change one on your machine, don't edit `service.toml`: `config.toml` wins (architecture §4.4). `gaifa setup` sets the two it asks for through the hub, which saves `config.toml` and applies the value at once, then restarts the mod. By hand, the hub reads `config.toml` only when it starts, so edit it, run `gaifa restart` (the hub), then `gaifa restart agent`:

```toml
[services.agent.env]
AGENT_MODEL = "<your-model>"
AGENT_FALLBACK_MODEL = "<another-model>"   # optional; "" (the default) for none
```

(When the hub isn't running, `gaifa setup` edits this table form in the file itself; it leaves an inline `env = { … }` alone and asks you to set it by hand.)

| Key | Set to | Required | Meaning |
|---|---|---|---|
| `AGENT_MODEL` | `<your-model>`, asked by `gaifa setup` (`service.toml` and the code say `skynet`, a name from the machine these docs were written on) | yes | the default chat model: a name the relay's `/v1/models` lists |
| `AGENT_FALLBACK_MODEL` | `""` (none) | optional | when the thread's model doesn't answer, the turn goes on with this one; empty, the default, means no fallback |
| `AGENT_LLM_URL` | `http://127.0.0.1:4000/v1` | yes (set) | the relay |
| `AGENT_DB` | `{databases}/agent.db` | yes (set) | threads and their event logs |
| `AGENT_DATA` | `{root}/data/agent` | yes (set) | AGENT.md, memory, skills, the learned harness |
| `AGENT_MAX_STEPS` | `25` | optional | tool steps per turn |
| `AGENT_INLINE_TOKENS` | `6000` | optional | an attached document up to this size goes into the message whole |
| `AGENT_DEFAULT_WINDOW`, `AGENT_REPLY_RESERVE`, `AGENT_SUMMARY_IDLE_MIN`, `AGENT_ALL_TOOLS` | unset | optional | 32768, 4096, 30 and none by default (`agent/server.py`) |

**Use names your relay has** (Choosing models, above). For example, on the machine these docs were written on, `AGENT_MODEL` is `skynet` (a remote GPU box reached through an SSH tunnel that exists only there) and the fallback was `gemma4-26B` (lcpp's nickname for the Gemma 4 26B-A4B GGUF); neither name exists on yours.

**Settings → Permissions → Auto judge** holds the Auto mode's judge model: `config.toml [agent.judge]`, `model = "<your-model>"` with `backend = "relay"` (on the machine these docs were written on, for example, `gemma4-26B`). The default in code is `minicpm-5-2B`, which a relay rarely has: pick one of yours there, or the `decide` mod's models with `backend = "decide"`. The same page has the document defaults and speech input.

## Check it works

```bash
gaifa check agent --start
```

Starts the agent if it's stopped (a stopped mod's live checks are skipped), then checks it. Expect `agent: all checks passed` (two widgets, the Learning page).

```bash
curl -s http://127.0.0.1:7000/api/s/agent/v1/models
```

The agent's view of the relay: `default`, `fallback`, and `models` with each one's facts (`context_length`, `tools`, `vision`, `reasoning`). Expect `{"default":"<your-model>","fallback":null,"models":[{"id":"auto",…},{"id":"<your-model>",…,"health":"healthy"}]}` (`fallback` is the name when you set one). Your `AGENT_MODEL` should be in that list; an lcpp nickname is there only while its instance runs.

The unit tests (a scripted model and a stand-in hub; no model, relay or GPU):

```bash
cd services/agent && .venv/bin/python -m pytest -q
```

Expect `225 passed` (2026-10-21, about a minute).

## What to look for

- **Every chat fails or falls back.** `AGENT_MODEL` names a model your relay doesn't have (such as `service.toml`'s `skynet`, which exists only on the machine these docs were written on). Check the list above, then `gaifa setup agent --set "services.agent.env.AGENT_MODEL=<name>"`, or edit `config.toml` and restart the hub, then the agent (Configuration).
- **A fallback that's off most of the time.** An lcpp nickname is on the relay only while its instance runs. Start it from the LLM Launcher page, or choose a fallback that is always up.
- **The judge asks about everything in Auto.** Its model doesn't answer within `timeout_s` (3 s) or isn't on the relay, so each call falls back to asking you. Pick a reachable model in Settings → Agent.
- **A model without tool calls** answers but never uses a tool. The relay's facts (`tools`) say which ones take them.
- The eval (`evals/`, results in [docs/agent-eval.md](../../../docs/agent-eval.md)) runs real models; it's not part of the install check.

## Known gaps

- `gaifa install agent` alone doesn't check that `AGENT_MODEL` exists on the relay (`gaifa setup` does, and asks for it); `AGENT_FALLBACK_MODEL` isn't asked or checked.
- `requirements.txt` is unpinned.
