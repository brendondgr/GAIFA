# GAIFA's chats from another agent

Claude Code, Codex or any MCP client can hand a task to GAIFA's own agent: start a chat in GAIFA, let it work with GAIFA's tools (images, video, 3D, speech, the workspace folders, the web), and read its answer. The chat is an ordinary GAIFA chat, in your chat list with a chip naming the client ("Claude Code"); it can start sub-agents of its own (plan [agent-workflows](plans/agent-workflows.md), Phase 4).

## Connect

GAIFA's MCP endpoint is `http://127.0.0.1:7000/mcp` (streamable HTTP, loopback only).

```bash
claude mcp add --transport http gaifa http://127.0.0.1:7000/mcp
```

Codex: add a server with `url = "http://127.0.0.1:7000/mcp"` under `[mcp_servers.gaifa]` in `~/.codex/config.toml`.

## The tools

| Tool | Risk | What it does |
| --- | --- | --- |
| `agent_chat_start {prompt, title?, model?, mode?, environment?, project?}` | execute | Starts a chat whose first message is `prompt`; answers `{chat, title, state, link}`. `mode`: `manual` (the default: anything that changes something asks you first), `plan`, `accept_edits` or `auto`; never `bypass`. |
| `agent_chat_wait {chat, timeout ≤ 60}` | read | Waits for the chat's turn to end, then reads it. Call it again while `running`. |
| `agent_chat_read {chat, after?}` | read | Its state, last `answer`, its `messages` after a seq (`last_seq`), its `sub_agents`, and `waiting_for_you`. |
| `agent_chat_send {chat, text}` | execute | A follow-up or a correction (held until a running turn ends). |
| `agent_chat_stop {chat}` | write | Stops it and its sub-agents. |
| `agent_chat_list {}` | read | The chats this client started. |

## Who decides what

- **Starting or writing to a chat asks you.** `agent_chat_start` and `agent_chat_send` are `execute` tools: GAIFA asks you before they run (in your client's form when it shows MCP forms, else in GAIFA's header → Approvals; the client waits with `gaifa_wait_approval`). An "Always allow" grant skips that card from then on.
- **What the chat does is decided as in any chat:** by its mode and your rules. When it waits on a card, `agent_chat_read` lists it under `waiting_for_you`; you decide it in GAIFA (the chat, or the header's Approvals). The other agent can't: no tool approves anything.
- **It reaches only its own chats.** These tools see only chats started over `/mcp` and their sub-agents, never your other chats.

## Headless clients

A client run without a person (`claude -p`, `codex exec`) has its own permission rules for MCP tools, and they apply before GAIFA's: allow GAIFA's server in them (Claude Code: `--allowedTools mcp__gaifa`). Headless Claude Code cancels MCP forms it can't show, and GAIFA counts a cancelled form as a denial, so approve such calls with an "Always allow" grant ahead of time, or run the client interactively.
