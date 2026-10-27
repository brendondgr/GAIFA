# Plan: every LLM server in one place: cloud providers in the relay, local engines, Settings → LLMs and the Chat picker

**Asked for:** 2026-10-26 · **Status:** In progress

## 1. Introduction

GAIFA's language models are spread over four mods:
- **relay:** one OpenAI-compatible `/v1` with routing, tunnels and telemetry.
- **lcpp (LLM Launcher):** llama.cpp servers for GGUF files.
- **vllm:** one vLLM container at a time for Hugging Face models.
- **opencode:** an agent server the relay translates to.

The Chat model menu (`web/chat/chat-controls.js` `ModelMenu`) is a flat list of what the relay's `/v1/models` names. That list holds the relay's aliases and the model ids typed into each endpoint's allowlist (`app/services/catalog.py`). It never asks a server what it serves, a model that isn't loaded doesn't appear, and the relay speaks only two protocols (`openai`, `opencode`).

The user wants (2026-10-26):
- Claude, OpenAI and Gemini models usable **in chats** (not by the judge, screening or other background work).
- Model lists **read from each server**, never hardcoded.
- A **Settings → LLMs** section to add servers and keys, see each server's models and switch between them.
- **A server → model picker in Chat**.
- lcpp and vllm kept as **two mods behind one contract and one UI**.

The approach:
- **Phase 1:** the relay learns the Anthropic and Gemini protocols, OpenAI's quirks and live discovery, and routes `<server>/<model>`.
- **Phase 2:** the agent keeps the providers' hidden reasoning state across turns.
- **Phase 3:** one engine contract lets any local engine list and load its models.
- **Phases 4–5:** Settings and Chat.
- **Phase 6:** OpenCode's models, read live.
- **Phase 7:** the pins are updated and the whole thing is checked live.

**Where the work lands.** This plan needs [mod-repos.md](mod-repos.md) Phase 2 done first. After that, `relay` and `lcpp` are submodules of `brendondgr/Relay` and `brendondgr/LLMs`:
- Relay and lcpp steps are commits on a feature branch in that repository (made in a worktree of it outside GAIFA), with its own tests, pushed there; each step's GAIFA commit ticks it here and names the mod's commit.
- The pin moves at the release step (1.8 for the relay, 3.3 for lcpp): the branch is merged on the mod's `main`, pushed, and `gaifa repos update <id>` brings it into GAIFA (the real update from GitHub that [mod-repos.md](mod-repos.md) Phase 3 still has to check).
- Steps in `vllm`, `agent`, the hub and `web/` are ordinary GAIFA commits.

The relay must keep working on its own, without GAIFA: everything GAIFA-specific is off unless GAIFA's environment turns it on, as with the GPU slot today.

The provider details come from the `llm-integration` skill (`~/Projects/bdgrClaudeSkills/llm-integration`). Read its `references/discovery.md`, `anthropic.md`, `gemini.md`, `openai.md`, `capability-matrix.md` and `pitfalls.md` before Phase 1. Its `templates/llmkit/providers/*` adapters and `scripts/selftest.py` mocks are the starting point for the relay's adapters and tests: port them into the relay, don't add llmkit as a dependency.

Touches architecture §4.3 (a new `[llm]` manifest section), §6 (hub routes), §10 (relay, lcpp, vllm), §14.1 (the agent), §14.7 (permissions); the brief §11.13 (Chat) and the Settings schema ([settings-redesign.md](settings-redesign.md)); the GPU slot (plan 31.4).

## 2. Gaps & unanswered questions

- **Keys.** *Assumption:* a provider key is typed in Settings → LLMs and stored only in the relay. It goes in the endpoint's `upstream_key`, in `relay.db`, the way remote endpoints keep theirs today. The API returns only `has_key` and the last four characters, and no key ever goes in `config.toml`. `gaifa backup` copies `relay.db`, so backups hold the keys; the Settings row says so.
- **Prices.** The providers' model lists don't carry prices, and the user doesn't want hardcoded tables. *Assumption:* the relay records tokens (cache reads and writes too), not dollars. A cost column can come later from a user-edited price table.
- **Which models a list shows.** OpenAI's `/v1/models` also lists embedding, speech, image and moderation models, with nothing but ids. *Assumption:* the catalog shows every model and lets the user hide any. A default hide filter on id words (`embedding`, `tts`, `whisper`, `transcribe`, `dall-e`, `image`, `moderation`, `realtime`, `audio`, `search`) is a rule about kinds, not a list of names, and the user can turn it off.
- **Chats only.** *Assumption:* a request to a `cloud` endpoint must carry `X-GAIFA-Purpose: chat`, else 403 `cloud_not_allowed`. Only the agent's chat turns send it, including that chat's compaction and its title. The judge, screening, the learner, evals and other mods never do, and their model pickers list no cloud models. A standalone relay has the rule off (`RELAY_CLOUD_REQUIRES_PURPOSE`, which GAIFA's `service.toml` sets).
- **Fallback when a cloud model fails** (quota, outage). *Assumption:* the chat's fallback model applies as it does today. The turn says so: "Claude didn't answer (429 rate limit); this reply is from gemma4-26B". There's no silent failover from a cloud model to a different endpoint inside the relay.
- **OpenAI: Chat Completions or Responses.** *Assumption:* Chat Completions, which the relay and agent already speak. OpenAI's encrypted reasoning items aren't carried, so reasoning models re-think each turn. That's acceptable for now and noted in the relay's docs.
- **Privacy.** *Assumption:* a chat on a cloud model is marked in its header and composer. The first message after switching to one says that the chat's history, attachments and tool results will go to that provider.
- **OpenCode's own keys** stay in `services/opencode/.env` (it calls the providers itself). Settings shows OpenCode's models and where its keys live. Sharing one set of keys is out of scope.

## Phase 1 — Cloud providers and live model lists in the relay (L)

Work in `services/relay` (repository `brendondgr/Relay`), on branch `feat/cloud-providers`. Tests: `services/relay/tests/backend/`, run with the relay's own venv.

- [x] **1.1 Cloud endpoints: `app/schemas/__init__.py`, `app/db.py`, `app/services/router.py`, `app/routes/admin_endpoints.py`.**
  - **Schema:**
    - `Protocol` adds `anthropic` and `gemini`.
    - `EndpointKind` adds `cloud`. It's inferred for `api.anthropic.com`, `api.openai.com` and `generativelanguage.googleapis.com`, or set explicitly.
    - `ServerType` adds `anthropic` and `gemini`.
  - **Presets:** `POST /admin/endpoints` with `{name, alias, protocol, upstream_key}` and no `base_url` fills each protocol's default URL.
  - **Responses:** keys are never returned; `has_key` and `key_hint` (last four) are.
  - **Migration:** existing rows keep their kind.
  - **Never for cloud:** the GPU lease (`gpu_lease.py` takes it only for `local` loopback endpoints; a test pins it), failover to another endpoint, or the `auto` route.
  *Done when:* `test_endpoints_api.py` covers creating each preset, the hidden key, kind inference; `test_gpu_slot.py` covers a cloud endpoint taking no lease; `test_proxy.py` covers no failover from a cloud endpoint.
  - **Done:** Relay `d6c1507` on `feat/cloud-providers` (`tests/backend/test_cloud_endpoints.py`, 9: each preset, what a preset keeps, no URL and no preset, kind inference and a patch keeping `cloud`, never `auto` or a failover target even when pinned, no GPU lease, the key hint; the relay's suite 212).
- [x] **1.2 Live model lists: `app/services/discovery.py`, `app/services/model_facts.py`.**
  - **Per protocol** (the skill's `discovery.md` §1), returning `[{id, display_name, context_length, max_output, tools, vision, reasoning, source}]`:
    - **openai:** `GET /v1/models`, ids only, so facts stay null unless the model facts override says otherwise. For llama.cpp, vLLM and Ollama it adds the second requests the skill names (`/props`, `/api/show`).
    - **anthropic:** `GET /v1/models` with `x-api-key` and `anthropic-version`, paginated (`after_id`), reading `max_input_tokens`, `max_tokens` and `capabilities`.
    - **gemini:** `GET /v1beta/models?key=`, paginated (`pageToken`), keeping models whose `supportedGenerationMethods` has `generateContent`, the `models/` prefix stripped, with `inputTokenLimit`/`outputTokenLimit`/`thinking`.
    - **opencode:** see Phase 6.
  - **Cache:** per endpoint, 10 minutes, refreshed in the background. A failure keeps the last good list with `{error, at}`, so discovery never raises into a request.
  - **Facts:** they feed `model_facts`, so `meta` comes from the provider when it says something.
  - **Routes:** `GET /admin/endpoints/{id}/models` (with `?refresh=1`) and `PATCH /admin/endpoints/{id}/models {hidden: [...] , hide_filter: bool}` (a new `hidden_models` column).
  *Done when:* `test_discovery.py` runs against mock servers reproducing each provider's list shapes, ported from the skill's `selftest.py`. It covers pagination, the generateContent filter, the prefix, the hide filter, a 401 (`{error: "key rejected"}` and an empty list), a timeout (the last good list) and an unreachable local server (connect timeout ≤ 2 s).
  - **Done:** Relay `2d34546`. The fakes are real HTTP servers (`tests/backend/fake_providers.py`) so the official SDKs talk to them as to the providers; `test_discovery.py` (9). Found: the anthropic SDK is 2.x (API version 2026-10-21: no sampling parameters at all, and it sends the key as `Authorization: Bearer`). A rejected key keeps the last good list with `HTTP 401: key rejected — …`.
- [x] **1.3 `<server>/<model>` routing and the grouped catalog: `app/services/catalog.py`, `app/services/router.py`.**
  - **Catalog:** every visible discovered model is listed as `<alias>/<model id>` (for example `claude/claude-opus-5-5`, `openai/gpt-5.6`, `gemini/gemini-3.7-flash`, `local/gemma4-26B`).
  - **Each entry's `relay`:** `{endpoint, alias, group: "local"|"cloud"|"remote"|"agent", provider, upstream_model, health, discovered: true}`.
  - **Routing:** `resolve_request_model` matches `alias/model` first (split at the first `/` whose prefix is an alias), then the existing alias and allowlist rules, unchanged, so `skynet`, `gemma4-26B` and OpenCode's `anthropic/…` ids keep working.
  - **Aliases:** they may not contain `/` (they can't today; a test pins it).
  *Done when:* `test_catalog.py` (new) covers grouping, hidden models, collisions (an allowlisted `openai/gpt-x` on OpenCode vs a cloud alias `openai`: the alias form wins, and the catalog marks the other unreachable) and the old names still routing.
  - **Done:** Relay `78eac71`; `test_catalog.py` (7), the relay's suite 228.
- [x] **1.4 The Anthropic adapter: `app/services/adapters/anthropic.py`.**
  - **Request (OpenAI → Messages API):**
    - `system` messages joined into `system`.
    - `tools`/`tool_choice` → `tools` with `input_schema`.
    - An assistant's `tool_calls` → `tool_use` blocks.
    - `tool` messages → `tool_result` blocks in one user turn (consecutive ones merged).
    - `image_url` data URIs and URLs → `image` blocks; PDF `file` parts → `document` blocks.
    - `max_tokens`, which Anthropic requires and the agent never sends, is filled from the model's discovered `max_tokens`.
    - `reasoning_effort` maps to the model's thinking mode by its discovered capabilities: adaptive or a budget. The skill warns that picking the wrong one is a 400.
    - Temperature is rescaled or dropped as the skill's `params.py` does.
  - **Response and stream (Messages → OpenAI):**
    - Text deltas → `delta.content`.
    - Thinking → `delta.reasoning_content`.
    - Each thinking block and its `signature`, and redacted thinking, → `reasoning_details: [{type, text|data, signature}]` on the message, and on the last delta of a stream.
    - `tool_use` → `delta.tool_calls` (arguments streamed as the JSON deltas arrive).
    - `stop_reason` → `finish_reason`.
    - Usage → `usage.prompt_tokens` (input + cache read + cache write), with the parts in `usage.prompt_tokens_details` (`cached_tokens`, `cache_creation_tokens`), and `completion_tokens`.
  - **Round trip:** an assistant message that carries `reasoning_details` sends its blocks back first, verbatim. That's how the second turn with tools stays valid.
  - **Caching:** `cache_control` on the system prompt, the last tool and the latest user turn, with the setting `prompt_cache = "auto"|"off"`.
  - **Errors:** 429 and 529 keep `Retry-After` and are retryable on the same endpoint only. A 400's message is passed through in the error envelope.
  - **Probe:** a model list call.
  *Done when:* `test_adapter_anthropic.py` (a mock Messages server) covers each translation, a two-turn tool conversation whose second request carries the first turn's thinking signature, streaming tool-call deltas, usage with cache tokens, the missing `max_tokens` filled, a 529 and a 400.
  - **Done:** Relay `3fb2253` with the shared base `adapters/translated.py`; `test_adapter_anthropic.py` (12), the relay's suite 240. Per the claude-api reference: the official SDK, no sampling parameters on API version 2026-10-21, adaptive thinking with `display: "summarized"` (the default shows none), forced `tool_choice` retried as `auto` on the newest models' 400, and the server-side refusal fallback (`fallbacks: "default"`, beta `server-side-fallback-2026-07-01`) on by default, dropped on a model's 400.
- [x] **1.5 The Gemini adapter: `app/services/adapters/gemini.py`.**
  - **Request:** `generateContent`, and `streamGenerateContent?alt=sse` for streams.
    - System → `systemInstruction`.
    - Messages → `contents` with roles `user`/`model`.
    - Tools → `functionDeclarations`, the schema cut to the subset Gemini accepts (the skill's `gemini.md`; unsupported keywords removed, never silently ignored).
    - `tool_calls`/`tool` messages → `functionCall`/`functionResponse` parts.
    - Images → `inlineData`.
    - `reasoning_effort` → `thinkingConfig` (`thinking_level` or `thinking_budget` by model).
  - **Response:**
    - Thought parts → `reasoning_content`.
    - Every part's `thoughtSignature` → `reasoning_details` with the part's index, sent back verbatim on the next turn.
  - **Blocked prompts:** a 200 with no candidates becomes an error with `promptFeedback.blockReason`, never an empty reply.
  - **Usage:** `usageMetadata` (including `cachedContentTokenCount` and `thoughtsTokenCount`) → OpenAI usage.
  *Done when:* `test_adapter_gemini.py` covers each translation, the schema subset, a two-turn function call carrying its thought signature, a blocked prompt and streamed usage.
  - **Done:** Relay `f8dd9f7` through `google-genai`; the schema isn't cut down (`parameters_json_schema` carries it whole), and the model's own parts, signatures included, go back as `reasoning_details`; `test_adapter_gemini.py` (10), the relay's suite 250.
- [x] **1.6 OpenAI's API: `app/services/adapters/passthrough.py` (cloud rules) or `openai_cloud.py` if it grows past ~150 lines.**
  - **On a `cloud` openai endpoint:**
    - `max_tokens` becomes `max_completion_tokens`.
    - Sampling parameters that reasoning models reject are dropped, with an `X-Relay-Dropped` header naming them, not a 400.
    - `stream_options.include_usage` is always set.
    - `reasoning_effort` passes through.
  - **Local servers:** unchanged.
  *Done when:* `test_proxy.py` covers each rule against a mock, and that a local endpoint's body is forwarded byte for byte as before.
  - **Done:** Relay `11465f2`; the rejected parameter comes from OpenAI's 400 (`code` `unsupported_parameter`/`unsupported_value`, `param`), so there's no list of reasoning models; `test_openai_cloud.py`.
- [x] **1.7 Chats only, and telemetry: `app/services/proxy.py`, `app/services/telemetry.py`, `app/config.py`.**
  - **Rule:** with `RELAY_CLOUD_REQUIRES_PURPOSE=1`, a request routed to a `cloud` endpoint without `X-GAIFA-Purpose: chat` gets 403 `{detail: "cloud models are for chats only", code: "cloud_not_allowed"}`.
  - **Telemetry:** requests record `group` and the cache token columns. The relay's dashboard filters by group.
  - **GAIFA:** `services/relay/service.toml` sets the variable in GAIFA.
  *Done when:* `test_proxy.py` covers the 403, the header letting it through and the rule off by default; `test_stats.py` covers the group filter.
  - **Done:** Relay `4202955` (GAIFA's `service.toml` in the Relay repo sets the variable). The group filter is on the Requests list (`GET /admin/stats/recent?group=`); the hourly rollups behind the dashboard's charts don't split by group. Tests in `test_openai_cloud.py` (9 there in all); the relay's suite 259.
- [x] **1.8 Relay docs and release.**
  - **Docs:** `README.md` (cloud providers, discovery, `<server>/<model>`, the chats-only rule), `docs/` (the API), `CLAUDE.md`.
  - **Release:** merge to `main` in Relay, push, then in GAIFA `gaifa repos pin relay`, `uv run pytest`, and commit.
  - **GAIFA docs:** architecture §10's relay row.
  *Done when:* the relay's suite passes; on the installed hub after `gaifa restart relay`, `GET /api/s/relay/v1/models` lists the local models grouped, and with a key added through the admin API, one cloud provider's models.
  - **Done 2026-10-26:** Relay `e1df518` (`docs/cloud.md`, README, routes, deployment, CLAUDE.md). `feat/cloud-providers` went onto Relay `main` as a fast-forward, and Settings → Services → Repositories brought it in: Check now showed 8 new commits, Update… listed them, and the hub fetched, checked out `e1df518`, ran the install (pyproject and uv.lock changed: anthropic 2.3, google-genai), read the manifest again, restarted the relay, `gaifa check relay` passed, and the pin was staged (committed here). The relay serves its models grouped (`remote`, `agent` on this machine, no cloud key yet). A cloud provider's live list waits for the user's key (Phase 1's checks).

**Checks & deliverables — Phase 1**
- [ ] With the user's keys (step needs them): one plain request and one streamed request to each of Claude, OpenAI and Gemini through `/v1`; each shows in the relay's Requests screen with tokens.
- [ ] Delivered: `discovery.py`, `adapters/anthropic.py`, `adapters/gemini.py`, the cloud rules, tests, Relay's docs.

## Phase 2 — The agent with cloud models (M)

- [x] **2.1 Hidden reasoning state across turns: `services/agent/agent/llm.py`, `services/agent/agent/loop.py`, the store.**
  - **What:** `Reply` gains `reasoning_details` (from deltas and the final message). The assistant event stores it, and the messages built for the next call put it back on that assistant message unchanged. Tool-call ids stay as the provider gave them.
  - **Headers:** chat turns send `X-GAIFA-Purpose: chat`.
  - **`max_tokens`:** still not sent.
  *Done when:* `services/agent/tests/test_llm.py` and `test_loop.py`: a scripted model returns `reasoning_details` with a tool call; the next request carries them verbatim; a chat's compaction and title requests carry the purpose header; the judge's requests (hub, `utils/tools/judge.py`) don't.
  - **Done:** the details are their own event (`reasoning_details` {details, model, step}, which the Chat page doesn't draw), put back on that step's assistant message by `context.rebuild` and sent only to the model that made them (`llm.for_model`), so a local server never sees another provider's fields. The purpose header rides on every call made with a chat's `THREAD` (turns, titles, compaction); background summaries of a cloud chat use the agent's default model (`LLM.is_cloud`). The judge calls the relay from the hub without the header. Tests: `services/agent/tests/test_cloud_models.py` (7); the agent's suite 315.
- [x] **2.2 Models by server: `services/agent/agent/server.py` (`GET /v1/models`).**
  - **What:** each model carries `{id, name, server, group, provider, health, meta, cloud}` from the relay's catalog, grouped in server order (this machine, remote, cloud), and still without OpenCode's protocol.
  - **Validation:** the chat's model and `/model` accept `server/model`; an unknown id is a 400 that lists the near matches.
  *Done when:* `test_models_route.py` (new) covers the grouping, `cloud`, and `/model claude/claude-opus-5-5`.
  - **Done:** `services/agent/agent/server.py` `model_list()` and `check_model()` (creating a chat and changing its model; with the relay unreachable any id is taken); `tests/test_models_route.py` (3).
- [x] **2.3 The cloud marker, the notice and the fallback note: `services/agent/agent/loop.py`, `web/chat/chat-header.js`, `web/chat/chat-controls.js`.**
  - **Marker:** a chat whose model is `cloud` shows the provider beside the model name.
  - **Notice:** the first turn after switching to cloud gets a one-line notice event: "This chat now goes to Anthropic: its messages, attachments and tool results".
  - **Fallback:** a fallback turn says which model failed and why.
  *Done when:* `utils/tests/web/chat.test.mjs` covers the marker and the notice; `test_loop.py` covers the fallback note.
  - **Done:** the notice (`Agent._cloud_notice`: a `cloud_notice` event and an info `note`, once per switch) and the fallback note (it already said which model failed and why) are tested in `tests/test_cloud_models.py`. The marker is drawn by Phase 5's model menu (5.1), which shows each model's group; the notice is a `note`, which the Chat page already draws.
- [x] **2.4 No cloud for background work: `utils/tools/judge.py`, `utils/tools/screen.py`, `web/settings/blocks-agent.js`.**
  - **What:** the judge's and screening's model pickers list only non-cloud models. A config that names a cloud model is refused with "cloud models are for chats only; pick a model on this machine or a remote server", and `GET /api/judge/status` says so.
  *Done when:* `utils/tests/tools/test_judge.py` covers the refusal and the picker filter.
  - **Done:** `judge.relay_choices()` gives both pickers (the judge's `GET /api/judge/status`, screening's `GET /api/web/reading`) local, remote and named models only; a judge set to a cloud model is unavailable with `CLOUD_ONLY_CHATS` as its detail (the relay refuses it anyway: the hub sends no purpose header). Saving such a setting isn't refused (that would need the relay at save time); the status says why it doesn't run. Test: `test_judge_auto.py::test_no_cloud_for_the_judge`.

**Checks & deliverables — Phase 2** (live, with a key): waits for the user's provider key; everything else is tested against the scripted model.

**Phase 2's live check**
- [ ] On the installed hub with the user's keys: a chat on Claude runs a turn with two tool calls and a second turn; the same on Gemini; a chat on a local model is unchanged.
- [ ] Delivered: agent changes, tests; docs: architecture §14.1, the agent's `README.md`.

## Phase 3 — One contract for local engines (M)

- [x] **3.1 The `[llm]` manifest section: architecture §4.3, `utils/manifest.py`.**
  - **Fields:** `[llm] catalog = "GET /v1/llm/catalog"`, `load = "POST /v1/llm/load"`, `unload = "POST /v1/llm/unload"`, `engine = "GET /v1/llm/engine"`.
  - **Catalog entries:** `{id, name, format: "gguf"|"hf", size_gb, memory_gb, context, downloaded, loaded, endpoint?, relay_model?}`.
  - **Load:** `{id, wait: false}` → 202.
  - **`engine`:** `{state, stage, loaded: [ids]}`.
  - **Contract:** a mod declares only routes it serves, and `gaifa check` calls `catalog` and `engine`.
  *Done when:* `utils/tests/services/test_manifest.py` covers the section and its validation; `utils/tests/services/test_check.py` covers `gaifa check` on a fake engine mod (`utils/tests/fixtures/mods/fake-engine/`).
- [x] **3.2 vLLM implements it: `services/vllm/vllm_mod/api_llm.py`, `service.toml`.**
  - **What:** profiles become catalog entries, and load/unload/engine wrap the existing ones. Memory acquisition and the chat card are unchanged.
  *Done when:* `services/vllm/tests/test_api_llm.py` (with the fake engine) covers each route; `gaifa check vllm` passes.
- [x] **3.3 lcpp implements it: `src/lcpp/daemon/routes/llm.py`, `service.toml` (repository `brendondgr/LLMs`, branch `feat/llm-contract`).**
  - **What:** catalog models become entries; several can be loaded. A load starts an instance with the catalog's defaults and the relay alias, through the existing start path that asks GAIFA for memory. Unload stops it.
  - **Release:** merge, push, `gaifa repos pin lcpp`.
  *Done when:* lcpp's tests cover each route; `gaifa check lcpp` passes.
  - **Done 2026-10-26:** LLMs `0324288` (`/api/llm/*`; lcpp's own API lives under `/api`, and `[llm]` names the paths), released on `master` and brought in with `gaifa repos update lcpp` from the CLI (fetch, checkout, check, pin staged; committed here). Live: `gaifa check lcpp --start` passed with `llm: 2 models, engine idle` (gemma-4-26B-it, 17 GB, its relay name `gemma4-26B`); lcpp was stopped again after.
- [x] **3.4 The hub's view of engines: `utils/routes/llm.py`.**
  - **What:** `GET /api/llm/engines` gathers every running mod with `[llm]` (its catalog and engine state, each entry marked with the relay id it will have once loaded). `POST /api/llm/{sid}/load {id}` and `/unload` pass through. Errors use the envelope, and the memory manager's `needs_room` card is passed on.
  - **Loadable models:** the Chat picker (5.1) reads `/api/llm/engines` beside the agent's model list and offers what isn't loaded as Load; neither the relay (standalone) nor the agent needs to know about engines.
  *Done when:* `utils/tests/services/test_llm_routes.py` covers two fake engine mods, one stopped, and a load that needs room; the contract test covers the routes; architecture §6 and brief §6 list them.

**Checks & deliverables — Phase 3**
- [x] `GET /api/llm/engines` on the installed hub lists lcpp's and vLLM's models with what's loaded (2026-10-27: lcpp's two, gemma-4-26B-it and smollm2 loaded in turn; vLLM's profiles are parked on this machine, so it lists none).
- [x] Delivered: the manifest section, two implementations, the hub route, tests.

## Phase 4 — Settings → LLMs (M)

- [x] **4.1 The section: `web/settings/schema.js`, `web/settings/blocks-llm.js` (and `blocks-llm-servers.js` if over ~450 lines).**
  - **Place:** a new section **LLMs** (icon `cpu`) between Services and Agent.
  - **Groups:**
    1. **Servers:** each relay endpoint as a card with group badge, health, model count, key status (Add / Replace / Remove, typed into a password field and sent once to the relay through `/api/s/relay/admin/endpoints`), Refresh models, Enable, and a model list with hide toggles and the hide filter.
    2. **Add a server:** presets Anthropic, OpenAI, Gemini, any OpenAI-compatible URL, and a link to the relay's page for SSH tunnels.
    3. **On this machine:** `/api/llm/engines`' models with Load / Unload, memory and context.
    4. **Defaults:** the chat model and fallback, which are the agent's settings moved here; Agent → Model links to it.
  - **Errors:** a rejected key shows the provider's message on its card; an unreachable local engine shows "not running" with Start.
  *Done when:* `utils/tests/web/settings-llm.test.mjs` covers the cards per state (no key, key rejected, healthy, unreachable), hide toggles and the presets' bodies; the settings search finds "Claude", "API key", "OpenAI", "Gemini", "llama.cpp" and "vLLM"; `settings-search.test.mjs` passes.
- [ ] **4.2 Live check.**
  *Done when:* on the installed hub, a key added in Settings lists that provider's models within one refresh; a hidden model leaves the Chat picker; Load on an lcpp model starts it and its card turns healthy.
  *So far (2026-10-27):* Start and Load on lcpp's models work (from the Chat menu, through the same `loadLlm`), and the relay's card for the loaded model turns healthy. The key and hide checks wait for a provider key (skynet doesn't list its models, so there's nothing to hide on this machine yet).

**Wire — Phase 4:** Settings → LLMs goes live on the relay's admin API and `/api/llm/engines`.

## Phase 5 — The Chat picker (M)

- [x] **5.1 Server → model: `web/chat/chat-controls.js` (`ModelMenu`), `web/chat/chat-model-menu.js` (new, if `chat-controls.js` would pass ~450 lines).**
  - **Layout:** the menu groups by server (This machine, Remote, Cloud), each with its health and models (context window, tools, vision), plus a search field.
  - **Local models not loaded:** listed with Load. Choosing one loads it through `/api/llm/{sid}/load` and shows the engine's existing chat card in that chat, and the chat switches to it when it's ready.
  - **Badges:** cloud models carry the provider badge.
  - **Per pane:** each split pane picks its own (plan chat-split).
  - **`/model`:** completes `server/model`.
  - **Reuse:** the Settings default picker (4.1) uses the same component.
  *Done when:* `utils/tests/web/chat-model-menu.test.mjs` covers grouping, search, a loadable model and the cloud badge; on the installed hub two panes talk to a local model and a cloud model side by side.
  *As built (2026-10-27):* `chat-model-menu.js`. While a model loads, the model button says "Loading <id>…" (and "Starting <engine>…") instead of drawing the engine's chat card in the chat (that card belongs to a tool call); the chat switches when the relay serves it. A stopped engine has no catalog, so it shows a Start row. The relay can list one id twice (a local endpoint whose alias is its model id), so the agent's `/v1/models` and the menu keep one row per id (the relay's own fix is in Phase 6). A small model's `<title>…</title>` is taken as the title. Checked on the installed hub: LLM Launcher started and smollm2 and gemma4-26B loaded from the menu, the chat switching to each; two panes side by side on gemma4-26B and skynet both answered; `/model gem` completed. smollm2's 8,192-token window is too small for the agent's prompt (it says `context_full`). The cloud pane waits for a provider key.

## Phase 6 — OpenCode's models, read live (S)

- [x] **6.1 `app/services/discovery.py` (relay), `app/services/opencode_boot.py`.**
  - **What:** an `opencode` endpoint's models come from OpenCode's provider list (`GET /config/providers` with its Basic auth), instead of the allowlist written at boot. They're listed in the `agent` group as `<alias>/<provider>/<model>`, and the old `<provider>/<model>` ids keep routing.
  - **Settings:** OpenCode's card in Settings → LLMs says its keys live in `services/opencode/.env`.
  - **Chat:** the Chat picker still leaves OpenCode out (the agent's `/v1/models` filters it).
  *Done when:* `test_opencode_boot.py` and `test_discovery.py` cover the live list and the old ids; Relay is released and pinned as in 1.8.
  *As built (2026-10-27):* Relay 1f6189e and a98d8e3 (a running `opencode serve` reports `capabilities.{toolcall, reasoning, input.image}` beside `limit`, models.dev's entries `tool_call` and `modalities`: both are read): `Discovery._list_opencode` reads `/config/providers` with the endpoint's Basic auth through the adapter's `catalog_entries` (free models only, with the window, output cap, tools, images and thinking OpenCode reports); `listed_models` is on for `opencode`; the catalog lists them as `agent/<provider>/<model>` and no longer lists the allowlisted `<provider>/<model>` ids (they still route), and lists any id once (lcpp's alias that is also its model id). `opencode_boot.py` is unchanged: its allowlist keeps the old ids routing and the adapter's free-model rule. The tests are in `test_opencode_boot.py` (the fake OpenCode now reports facts), `test_catalog.py` and `test_adapter_opencode.py`. Settings → LLMs: OpenCode's card says where its keys live. Live (relay updated with `gaifa repos update relay` once the other session's evals were idle): OpenCode's 10 free models listed as `agent/<provider>/<model>` with their windows, tools, images and thinking; with OpenCode stopped, its card shows the connection error; no id is listed twice.

## Phase 7 — Release, pins and the live run (S)

- [x] **7.1 Pins and docs.**
  - **Pins:** Relay and LLMs `main` include every step; `gaifa repos status` is clean.
  - **GAIFA docs:** architecture §4.3/§6/§10/§14.1, the brief §11.13, `docs/structure.md`, `web/PATCHES.md`, and the `CLAUDE.md`/`AGENTS.md` status lines.
  - **Setup docs:** relay's setup doc (`services/relay/setup/relay.md`) says how to add a provider key; `gaifa docs --check --strict` passes.
  *Done when:* the docs checks and `uv run pytest` pass.
  *As built (2026-10-27):* Relay main a98d8e3 and LLMs master 0324288 pinned; architecture §10 and §14.1, the brief, structure, PATCHES #66–68, the status lines; the relay's setup doc has "Adding Claude, OpenAI or Gemini"; `gaifa docs --check --strict` passes.

**Checks & deliverables — the whole plan** (with the user's keys)
- [ ] One chat each on Claude, OpenAI and Gemini, each with a tool call, a second turn and an attached picture; the relay's Requests screen shows each with tokens and cache tokens.
- [ ] The judge refuses a cloud model; a request without the purpose header gets 403.
- [ ] A wrong key shows on its Settings card; turning the network off leaves the local models working and the cloud cards showing their last list with the error.
- [x] A local model loaded from the Chat picker answers in that chat (gemma4-26B, 2026-10-27).
- [x] `uv run pytest`, the relay's, lcpp's, vLLM's and the agent's suites pass (2026-10-27: 2012, 262, 94, 32, 326).

## 4. Deliverables

| Deliverable | Description | Location |
| --- | --- | --- |
| Cloud endpoints | `cloud` kind, presets, hidden keys, no GPU lease or failover | relay: `app/schemas`, `app/services/router.py`, `app/routes/admin_endpoints.py` |
| Discovery | live model lists per protocol with facts, cached, never raising | relay: `app/services/discovery.py` |
| Routing | `<server>/<model>`, grouped catalog, hidden models | relay: `app/services/catalog.py`, `router.py` |
| Adapters | Anthropic, Gemini, OpenAI cloud rules | relay: `app/services/adapters/` |
| Chats-only rule | `X-GAIFA-Purpose: chat` for cloud endpoints | relay: `app/services/proxy.py`; agent; `utils/tools/judge.py` |
| Agent | reasoning state kept across turns, models by server, cloud marker | `services/agent/agent/` |
| Engine contract | `[llm]` section; vLLM and lcpp implement it; `/api/llm/*` | `utils/manifest.py`, `services/vllm/vllm_mod/api_llm.py`, lcpp `src/lcpp/daemon/routes/llm.py`, `utils/routes/llm.py` |
| Settings → LLMs | servers, keys, models, engines, defaults | `web/settings/blocks-llm*.js`, `schema.js` |
| Chat picker | server → model, load from the menu, per pane | `web/chat/chat-model-menu.js`, `chat-controls.js` |
| Tests | mock provider servers (from the skill's self-test), routing, agent round trips, UI | relay `tests/backend/test_{discovery,catalog,adapter_anthropic,adapter_gemini}.py`, agent tests, `utils/tests/services/test_llm_routes.py`, `utils/tests/web/{settings-llm,chat-model-menu}.test.mjs` |
