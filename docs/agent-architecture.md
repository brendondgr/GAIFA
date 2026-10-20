# The chat agent's architecture: research and decisions

Why the Stage D agent (plan Phases 13–14, architecture §14) is one hand-written loop modelled on Claude Code, and not a framework or a team of agents. Researched on 2026-10-06. Numbers marked *vendor* come from the model's maker and aren't directly comparable across setups.

## 1. Decisions

| Decision | Choice | Main reasons |
|---|---|---|
| Loop | One loop, written by us (about 400 lines) | Claude Code's core is a plain while-loop. Anthropic advises starting without frameworks. A local model needs control over thinking fields, leaked tool calls and tool loading |
| Agents | One agent; no sub-agents for now | Multi-agent setups cost about 15× the tokens of chat and make sequential, tool-heavy work 39–70% worse. On one GPU they only queue |
| Tools | A few `core` tools always loaded; the rest found and loaded on demand | Accuracy falls as the tool list grows. Loading tools on demand is the best-evidenced fix (Anthropic: 49% → 74%; RAG-MCP: roughly 3×) |
| Asking | `ask_user` question cards, plus parameter cards for every generating call | In a live test, Gemma 4 31B picked an aspect ratio itself instead of asking, so choices are a fixed step rather than the model's judgement |
| Safety | The hub enforces approvals; permissions are checked deny → ask → allow by risk | Prompt-injection research: never rely on the model alone. MCP clients may ignore hints |
| State | An append-only event log in SQLite; fork = copy up to a point | Claude Code keeps sessions the same way. A pause for approval needs no checkpointer library |
| Context | A meter from the relay's window and each response's `usage`; capped tool results; compaction at 70% and 85% | Context degrades with length. Compaction helps small models most (ACON: up to +46%) |
| Instructions | `AGENT.md`, skills loaded only when needed, a memory index | Claude Code's CLAUDE.md, skills and auto memory |
| Model | Gemma 4 31B via the relay's `skynet` endpoint (131,072 tokens), local Gemma 4 26B as the fallback | *Vendor* τ²-bench Retail: Gemma 4 31B 86.4%, 26B A4B 85.5%; Gemma 3 27B 6.6%. Thinking adds 6–10 BFCL points (Qwen3 report) |
| Evaluation | 30 real tasks, each run 3 times (pass^3), graded on outcomes | τ-bench: consistency is where models fail. Anthropic's eval guidance |
| Learning (2026-10-19, plans 21–22) | Preferences as hub data filled into cards (from what you say, card edits seen twice in two chats, carried within a chat); the harness as versioned files improved by a learner after Harness² (two scoped editors, replays as probes, a composer, the eval as gate, a library), on the same model as the chat | Harness² ([arXiv 2610.14224](https://arxiv.org/abs/2610.14224)): one contrastive step gave the largest gain, scoping and the library helped, editing without execution evidence hurt; card edits give AIHub the label the paper lacks |

## 2. How Claude Code is built

The sources are Anthropic's docs and engineering posts. The paper "Dive into Claude Code" (Liu et al., 2026) analyses its source code.

- **The loop.** Call the model, run its tools, feed back the results, and stop when a reply has no tool calls. Limits are a maximum number of turns and a budget. A denied tool returns a rejection the model can work around. Esc cancels; a message typed during a turn is read after the current tool calls. Sources: [Building effective agents](https://www.anthropic.com/engineering/building-effective-agents), [agent loop](https://code.claude.com/docs/en/agent-sdk/agent-loop), [how Claude Code works](https://code.claude.com/docs/en/how-claude-code-works), [Dive into Claude Code](https://arxiv.org/abs/2604.14228), whose analysis puts about 98% of the code around the loop.
- **Tools** ([writing tools for agents](https://www.anthropic.com/engineering/writing-tools-for-agents), [tools reference](https://code.claude.com/docs/en/tools-reference)):
  - workflow-level tools rather than thin API wrappers, with names grouped by service;
  - results with names instead of ids, capped (about 25k tokens), and spilled to a file with a preview;
  - error messages that say what to fix;
  - read-only tools run in parallel, tools that change state run one at a time.
- **Tools on demand.** Tools are listed by name only and a search tool loads their schemas. Tool-choice accuracy went from 49% to 74% (Opus 4), and tokens fell about 85%. Example arguments raised accuracy on complex parameters from 72% to 90%. Sources: [advanced tool use](https://www.anthropic.com/engineering/advanced-tool-use), [MCP in Claude Code](https://code.claude.com/docs/en/mcp).
- **Context** ([effective context engineering](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents), [memory](https://code.claude.com/docs/en/memory)):
  - CLAUDE.md is loaded after the system prompt and kept under 200 lines; everything else is fetched just in time;
  - compaction clears old tool results first, then summarizes, keeping decisions, open issues and recent files;
  - auto memory is an index plus topic files read on demand.
- **Asking and planning.** `AskUserQuestion` asks 1–4 questions with options. Plan mode presents a plan for approval. Todo lists track multi-step work.
- **Safety** ([permissions](https://code.claude.com/docs/en/permissions), [hooks](https://code.claude.com/docs/en/hooks)):
  - deny → ask → allow rules, where the first match wins;
  - permission modes;
  - hooks before and after each tool, which can block a call or edit its input;
  - checkpoints and rewind.
- **Skills** ([agent skills](https://www.anthropic.com/engineering/equipping-agents-for-the-real-world-with-agent-skills)): a name and description in the prompt, the body loaded when relevant, extra files only as needed.
- **Sessions:** an append-only transcript per session, which can be resumed or forked.
- **Sub-agents** ([multi-agent research system](https://www.anthropic.com/engineering/multi-agent-research-system), [sub-agents](https://code.claude.com/docs/en/sub-agents)): each gets its own context and returns a 1–2k-token summary. They are worth it for broad research (+90%), at about 15× the tokens, and Anthropic itself names coding as a poor fit.
- **Evaluation** ([demystifying evals](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents)): start with 20–50 real tasks, grade outcomes rather than tool sequences, read the transcripts, and report pass^k for consistency.

## 3. What the literature adds

- **Consensus architecture.** One model in an observe → reason → act loop, with working memory plus external stores. The field's emphasis has moved to *context engineering* and *tool design*. Surveys: [Wang et al. 2023](https://arxiv.org/abs/2308.11432), [Mei et al. 2025](https://arxiv.org/abs/2507.13334).
- **Patterns:**
  - [ReAct](https://arxiv.org/abs/2210.03629) with native tool calls is the robust default;
  - plan-first ([ReWOO](https://arxiv.org/abs/2305.18323)) saves tokens on predictable tasks;
  - Reflexion and LATS need a verifier and actions that can be undone, so they don't fit real generation jobs;
  - [CodeAct](https://arxiv.org/abs/2402.01030) composes tools well but defeats per-call approval.
- **Single vs multi-agent:**
  - [Kim et al. 2025](https://arxiv.org/abs/2512.08296): multi-agent made sequential planning 39–70% worse;
  - [Cemri et al. 2025](https://arxiv.org/abs/2503.13657): 14 ways they fail, mostly in coordination;
  - [Cognition, "Don't build multi-agents"](https://cognition.com/blog/dont-build-multi-agents).
- **Tool count and reliability:**
  - [LongFuncEval](https://arxiv.org/abs/2505.10570): 7–85% drops as the catalog grows;
  - ["Less is More"](https://arxiv.org/abs/2411.15399): fewer tools on edge hardware gave better accuracy and speed;
  - [RAG-MCP](https://arxiv.org/abs/2505.03275): retrieving tools went from 13.6% to 43.1% selection accuracy;
  - [Laban & Hayashi 2025](https://arxiv.org/abs/2505.06120): about 39% worse in multi-turn conversations, mostly from early wrong assumptions, which is another reason to ask instead of guessing;
  - [τ-bench](https://arxiv.org/abs/2406.12045): GPT-4o passed all 8 repeats of a task under 25% of the time.
- **Output format.** Constrain the tool-call span, not the reasoning: format limits hurt reasoning ([Tam et al. 2024](https://arxiv.org/abs/2408.02442)).
- **Safety:**
  - [design patterns against prompt injection](https://arxiv.org/abs/2506.08837);
  - [CaMeL](https://arxiv.org/abs/2503.18813);
  - Meta's "Rule of Two": an agent shouldn't combine untrusted input, sensitive systems and actions without a human. Our parameter cards are that human.
- **Memory.** [MemGPT](https://arxiv.org/abs/2310.08560); [ACON](https://arxiv.org/abs/2510.00615) found that context compression helps small models most.

## 4. Frameworks considered

| Option | Verdict |
|---|---|
| Hand-written loop | **Chosen.** Full control of templates, thinking fields, retries and tool loading; dependency: `httpx` |
| Pydantic AI 2.x | The fallback if we stop wanting to own the loop: deferred-tool approvals and capabilities loaded on demand fit this design |
| LangGraph / LangChain 1.x | The strongest middleware (approval, summarization, tool selection), but heavy abstraction sitting between us and the model server. It was the earlier plan |
| OpenAI Agents SDK | Good approval design, still pre-1.0, and its tracing must be turned off for local models |
| Claude Agent SDK | Runs the Claude Code binary and is tuned for Claude models. Not the engine here, but **Claude Code can use AIHub as an MCP client** (plan 13.4) |
| smolagents, Google ADK | Code-as-action defeats per-call approval; ADK is Gemini-first and heavy |

## 5. Facts checked on this machine (2026-10-06)

- `127.0.0.1:9090` is an SSH tunnel to `skynet`. There a DashLLM relay fronts vLLM serving Gemma 4 31B (`artemis31B-mtp`). The hub's relay already has it as the `skynet` endpoint.
- **Tool calls** are parsed natively by vLLM, and thinking arrives in `reasoning`. A fox-image request returned a valid `generate_image` call in 1.7 s, but the model chose `aspect: "1:1"` on its own (hence the parameter cards).
- **Context window:** 131,072 tokens. vLLM's error for an oversized `max_tokens` names `max_model_len`, which is how 13.3 reads it through the remote relay. The local Gemma 4 26B (llama.cpp, port 7071) reports `n_ctx` 262,144 in `/props`.
- **Not yet checked:**
  - whether the 31B endpoint takes image inputs (13.5's vision check);
  - whether llama.cpp's Gemma 4 tool-call parsing leaks markup on our build (the loop re-parses it anyway).
