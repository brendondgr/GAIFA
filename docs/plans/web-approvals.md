# Plan: fewer approvals for web pages: a decision-model judge, and every site in one chat

**Asked for:** 2026-11-08 · **Status:** In progress

## 1. Introduction

Researching on the web asks for approval far too often. The hub's records for 2026-11-08 show two causes.

1. **The Auto judge doesn't answer.** `[agent.judge]` on this machine named `gemma4-26B` through the relay. That model runs only in `lcpp`, which was stopped, so every judgement got `HTTP 404` and failed closed. `judged` holds `web_fetch ask fail-closed "the judge isn't available (HTTP 404)" gemma4-26B` for both pages that asked in the FSU chat (`t_8dcff652c9ed`), and `GET /api/judge/status` said `available: false`. Even when it answers, a 26B chat model takes seconds per link. The user's decision (2026-11-08): **the judge is only ever a decision model with a structured answer, d3-lite in the `decide` mod, never a chat model, and never Gemma 4 26B.** d3-lite answers a `web_fetch` in about 0.2 s once loaded (measured: it allowed `pc.fsu.edu` and `www.cs.fsu.edu` faculty pages for a request about FSU faculty, p 0.53 and 0.77, and asked for `evil.example/collect?d=<the user's details>`, p 0.00). Cold, its load counted against the judge's 3 s budget, so the first two judgements after it unloaded failed closed. The `decide` mod unloads after 300 s idle, so that happens often.
2. **A grant covers one exact host.** "Allow in this chat" on a `web_fetch` covers its host only (`grant_key = "url:host"`): `www.cs.fsu.edu`, `pc.fsu.edu` and `www.sc.fsu.edu` each asked. The user's choice (2026-11-08): a new card option, **Allow every site in this chat**: one answer lets the chat open any page, still under the URL checks that search-found pages pass (`judge_rules.fetch_rule`: no credentials, no long encoded values, no private addresses).

Phase 1 makes the judge d3-lite only: config, code, the Settings picker, the decide mod's budget, and the rule in CLAUDE.md. Phase 2 adds the chat-wide web grant. Touches architecture §9 (`[agent.judge]`) and §14.7 (the judge, grants), the brief §11.7 / §11.12 (`remember`), backend-plan Phase 30 (the judge) and Phase 25 (grants), and [settings-redesign](settings-redesign.md) (the Auto judge group).

## 2. Gaps & unanswered questions

- **The judge's backend** (answered 2026-11-08): a decision model only (`backend = "decide"`, d3-lite). A chat model is never the judge, whatever `config.toml` says.
- **An old `config.toml` with `backend = "relay"`:** *Assumption:* read as the decide judge with d3-lite (the hub logs one warning naming the keys it ignored), so the hub still starts; `PUT /api/settings` refuses `judge.backend = "relay"` with `422`; `gaifa doctor` names the stale keys. This machine's `config.toml` is rewritten to `backend = "decide"`, `model = "d3-lite"`.
- **The judge's chat-model code:** *Assumption:* it leaves the hub (`ask_relay`, `describe`, `SYSTEM`, `SYSTEM_CONTEXT`, `parse_verdict`). The judge eval (`services/agent/evals/judge/run.py`) compares chat models with the decision model, so its copy moves into the eval (`relay_judge.py`), which is research and never runs in a chat.
- **Screening's `confirm`** (a chat model re-reads what d3-lite flags, only when the judge is on the relay): *Assumption:* it no longer fires (the judge is never on the relay); `[agent.screen]` keeps its own backends, since the user asked about the judge only. The confirm path and `[agent.screen] confirm` are removed with the judge's chat model, and docs say so.
- **Cold d3-lite:** *Assumption:* the caller's budget (`X-GAIFA-Answer-Within`, 3 s) starts once the model is loaded, not once the GPU slot is held; the wait for the slot *and* the load stays under `gpu_wait_s` (90 s). d3-lite stays on its 300 s idle unload: no new resident memory.
- **Every site in a chat, in which modes:** *Assumption:* any mode but Plan (Plan refuses network calls before grants are read, as today). Pages it opens are still screened (`[agent.screen] pages`). It is a `thread` grant only: an "always" version would be an allow list for the whole internet.
- **Which tools:** *Assumption:* any tool whose `grant_key` is `url:host` (today only `web_fetch`); the option is offered only on those cards.

## Phase 1 — The judge is d3-lite (M)

- [x] **1.1 Config: `utils/config.py` `JudgeCfg`, `config.example.toml`, `CLAUDE.md`.**
  - `JudgeCfg.backend: Literal["decide"] = "decide"`, `model = "d3-lite"`, `url = "http://127.0.0.1:7000/api/s/decide"`. A `model_validator(mode="before")` reads `backend = "relay"` as decide: the backend, model and url become the defaults, and the ignored keys go in `JudgeCfg.ignored` (not saved), logged once at load.
  - `utils/settings.py` refuses `judge.backend` other than `"decide"` (`422 invalid_settings`, fix: "the judge is a decision model (decide mod)"); `utils/doctor` (the config checks) warns while `config.toml` still has the stale keys.
  - `config.example.toml`: `[agent.judge]` shows `backend = "decide"`, `model = "d3-lite"` commented, saying it's the only kind of judge.
  - `CLAUDE.md` Rules: "The Auto judge is only ever a decision model with a structured answer (the `decide` mod, d3-lite). Never a chat model through the relay (never Gemma 4 26B): it is slow and not built for this." The `gaifa` skill's invariants get the same line (copied to `.agents/skills/`).
  - This machine's `config.toml`: `[agent.judge]` `model = "d3-lite"`, `backend = "decide"`, `url` the decide mod's (keeps `context = "full"`).
  *Done when:* `utils/tests/settings/test_judge_config.py`: the defaults; a relay config loads as decide with `ignored`; a settings save with `backend = "relay"` is 422. The existing settings and config tests pass. Architecture §9 updated. *As built (2026-11-08):* no `ignored` field or log line: the validator replaces backend, model and url, and `gaifa doctor` (`doctor._judge`) warns while `config.toml` still names them. `JudgeSettings.backend` is `Literal["decide"]`, so the 422 comes from the model. The agent's setup doc no longer asks for the judge's model (it says to install the decide mod). This machine's `config.toml` was switched through `PUT /api/settings` on the running hub the same day (the old code already took a decide judge), so the judge answered before this landed. Committed with 1.2: the default change alone broke screening and the status (both follow the judge).
- [x] **1.2 The judge's code: `utils/tools/judge.py`, `utils/tools/screen.py`, `services/agent/evals/judge/`.**
  - `judge()` asks `ask_decide` only, with `describe_json`; `status()` reads the decide mod only (`choices`: its usable models). `ask_relay`, `describe`, `SYSTEM`, `SYSTEM_CONTEXT`, `parse_verdict`, `VERDICT_SCHEMA` move to `services/agent/evals/judge/relay_judge.py`, which `run.py` imports for its chat-model candidates.
  - `JudgeConfig.backend` stays a field (screening builds its own `JudgeConfig` with `backend = "relay"` for passages), but `judge()` given anything other than `"decide"` fails closed with "the judge is a decision model".
  - `screen.screen_config`: the `confirm` branch (judge on the relay) goes; `ScreenCfg.confirm` is read and ignored (old configs still load).
  - The module docstring says what the judge is and why (speed, structure, the user's rule).
  *Done when:* `test_judge.py`, `test_judge_auto.py`, `test_judge_context.py`, `test_judge_holes.py`, `test_screen_models.py` pass, rewritten where they used the relay judge; a new case: a `JudgeConfig(backend="relay")` judgement fails closed without a request. `uv run python -m services.agent.evals.judge.run --help` still imports. Architecture §14.7 (the judge's model) updated. *As built:* `judge()` takes `ask` and `state` (the eval passes `relay_judge.ask_relay` / `relay_judge.state` for `--backend relay`; `d3_tune.py` imports `describe` from there); `CLOUD_ONLY_CHATS` went (a decide model is never a cloud one). Screening with no model of its own follows the judge, so it is d3-lite now; the tests that fake a chat-model screener say `backend = "relay"` (`fake_screen`). The tests of the chat-model judge import it from the eval. Also updated: the brief §6 (`Settings.judge`, `screen.confirm`, `JudgeStatus.choices`), docs/agent-eval.md (the pick then, the rule now). The Settings page's "Let the judge's chat model confirm" checkbox does nothing now; it goes in 1.4.
- [x] **1.3 Load time isn't answer time: `services/decide/decide/server.py`.**
  - In `/v1/decide`, the work loads the model (`dec.load(mid)`, or the call `make_room` + load already make) inside the slot **before** `started.set()`, so `X-GAIFA-Answer-Within` counts the answer only. The caller's `gpu_wait_s` still bounds slot plus load.
  *Done when:* `services/decide/tests/test_decide.py`: with a fake model whose load takes 2 s and whose answer 0.1 s, a call with `Answer-Within: 1` answers (today: 504). Live: `POST /api/s/decide/v1/unload`, then one judgement through `judge()` answers with source `model`, not `fail-closed`. Architecture §5 (the GPU paragraph, `X-GAIFA-Answer-Within`) updated. *As built:* the work loads the model (`dec.load`) after `make_room` and before `started.set()`; a failed load still answers its error. The test is `test_gpu_queue.py::test_answer_within_counts_from_the_load` (fails on the old code: 504). The live check runs with Phase 1's checks, after the merge (the installed decide mod runs from main's checkout).
- [ ] **1.4 Settings → Permissions → Auto judge: `web/chat/chat-judge.js`, `web/settings/schema.js`, `web/mock.js`.**
  - `JudgeModelPick` has no backend select: a decision model from the decide mod's list (`st.choices`), and the line "The judge is a decision model: it answers in a fraction of a second, with probabilities, and never writes text". The group's summary reads `d3-lite (decision model) · N command rules`. The mock's settings and judge status say decide/d3-lite.
  *Done when:* `utils/tests/web/settings-schema.test.mjs` (the summary), a `chat-judge` test (no backend choice; changing the model keeps `backend: "decide"`); the contract test passes. Browser check on the installed hub after `gaifa restart`: the group shows d3-lite, "answering".

**Checks & deliverables — Phase 1**
- [ ] On the installed hub after `gaifa restart`: `GET /api/judge/status` → `available: true`, `backend: "decide"`, `model: "d3-lite"`. A chat in Auto researching a site (search, then pages and the links from them): every `web_fetch` the judge decides is in `GET /api/judge/recent` with `model: "d3-lite"`, under 1 s once loaded; none `fail-closed`. After the decide mod unloads (idle, or `POST /v1/unload`), the next judgement still answers.
- [ ] Delivered: `JudgeCfg` decide-only with the old config read over, `judge.py` without a chat model, `evals/judge/relay_judge.py`, the decide mod's budget after load, the Settings picker, the rule in CLAUDE.md and the `gaifa` skill.

## Phase 2 — Every site in one chat (S)

- [ ] **2.1 The grant: `utils/tools/grants.py`, `utils/tools/calls.py`.**
  - `REMEMBER` gains `"sites"`: on an approval of a tool whose `grant_key` is `url:host`, from a chat, it writes `{tool, key: "*", kind: "url:any", scope: "thread", thread}`. Another tool → `422 not_a_web_tool`; no thread → `422 no_thread`.
  - `Grants.match`: a `url:any` grant covers a call of its tool when `judge_rules.fetch_rule({"url": …})` doesn't ask (credentials, a long encoded value, a private address still take the usual way: a card, or the judge in Auto). A host grant still matches first when both exist (the newest wins, as today).
  - The call's record keeps `origin.grant`; the reason reads "allowed in this chat for every site".
  *Done when:* `utils/tests/tools/test_grants.py`: `sites` writes the grant; it covers another host in the same chat, not another chat; a URL with credentials or a long encoded query still asks; `sites` on a tool without `url:host` is 422; Plan still refuses. Architecture §14.7 (Keys), the brief §11.7 (`remember: "sites"`) and §11.12 updated.
- [ ] **2.2 The card: `web/chat/chat-risk.js`, `web/chat/chat-forms.js`, `web/chat/chat-approvals.js`, `web/chat/chat-mock.js`.**
  - `approvalButtons(risk, {thread, grantKey})` adds **Allow every site in this chat** (`remember: "sites"`) after "Allow in this chat" when `grantKey === "url:host"` and the call is from a chat. Its hint: "Open any web page in this chat without asking. Links with passwords, long encoded values or private addresses still ask." `rememberText('sites')` → "Every site allowed in this chat". The header's Approvals popover offers it too.
  *Done when:* `utils/tests/web/chat-risk.test.mjs` (the buttons for a `url:host` card in a chat, and none outside one); the mock's approval decides with `sites`. Browser check on the installed hub: a chat in Manual, a `web_fetch` card, **Allow every site in this chat**, then pages on two other hosts open without a card (their step rows say "allowed in this chat for every site"), and Settings → Permissions lists the grant with Revoke.

**Checks & deliverables — Phase 2**
- [ ] On the installed hub: the browser check above, plus a `web_fetch` of a URL with a long base64 query in the same chat still asks.
- [ ] Delivered: the `sites` grant and its card option.

## Deliverables

| Deliverable | Description | Location |
| --- | --- | --- |
| Decide-only judge config | `JudgeCfg` fixed to the decide mod, old relay configs read over, settings refuse a chat-model judge | `utils/config.py`, `utils/settings.py`, `config.example.toml` |
| The judge | d3-lite only; the chat-model judge kept for the eval | `utils/tools/judge.py`, `services/agent/evals/judge/relay_judge.py` |
| Budget after load | `X-GAIFA-Answer-Within` counts the answer, not the load | `services/decide/decide/server.py` |
| Settings picker | Decision models only | `web/chat/chat-judge.js`, `web/settings/schema.js` |
| The rule | The judge is a decision model, never a chat model | `CLAUDE.md`, `.claude/skills/gaifa/SKILL.md`, `.agents/skills/gaifa/SKILL.md` |
| Every site in a chat | `remember: "sites"`, the `url:any` grant under the URL checks, the card's option | `utils/tools/grants.py`, `web/chat/chat-risk.js`, `web/chat/chat-forms.js` |
| Tests | config, judge, decide budget, grants, the card | `utils/tests/settings/test_judge_config.py`, `utils/tests/tools/test_judge*.py`, `utils/tests/tools/test_grants.py`, `services/decide/tests/test_decide.py`, `utils/tests/web/chat-risk.test.mjs` |
