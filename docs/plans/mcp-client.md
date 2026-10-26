# Plan: other MCP servers in GAIFA's chats, Blender first

**Asked for:** 2026-10-26 · **Status:** In progress

## 1. Introduction

GAIFA is an MCP *server* (plan 13.4: `/mcp` gives Claude Code and other clients GAIFA's tools); its own chats can't use anyone else's MCP server. The user wants to try local models driving Blender through an MCP server, and MCP servers in general, set up once and switched on in a chat when a skill or the user asks for one.

The approach is one new mod, `mcp` (port 5108), that is an MCP *client*: it starts the configured servers (stdio processes, or Streamable HTTP connections) with the `mcp` Python SDK the hub already uses in its tests, and offers their tools to the hub through `tools_source`, with a `tools_rev` that changes when a server's tools do (plan 51.1), so the hub needs no change and every MCP tool gets GAIFA's risk levels, approvals, grants, the Auto judge and records. A server's tools are approved by the user once and fingerprinted; a server whose tools change is held until the user looks again (the "rug pull" defence). Servers are off in a chat until a skill that names them is read, or the user names one; their tools are deferred like any other tool (`find_tools` / `load_tools`), so a small model doesn't get dozens of new tools in every prompt. Blender is the first server, with a skill and an eval. Touches architecture §4 (a mod with `tools_source`), §14.7 (permissions), §10 (the mods' table), the brief's §11.12, and backend-plan 13.4 and 51.1.

## 2. Gaps & unanswered questions

- **Who turns a server on:** answered (2026-10-26): mostly a skill, when the user asks for that kind of work; the chat then runs it like any Auto-mode chat (the hub's permissions and judge decide each call).
- **Where servers are configured:** *Assumption:* `data/state/mcp/servers.json` (the mod's own settings, in `gaifa backup`), secrets in `services/mcp/.env` referenced by name (`${BLENDER_TOKEN}`), never in the JSON.
- **Reading other apps' MCP configs** (`~/.claude.json`, `~/.codex/config.toml`, `~/.cursor/mcp.json`, `~/.gemini/settings.json`, `~/.config/Claude/claude_desktop_config.json`, a workspace folder's `.mcp.json` or `.vscode/mcp.json`): *Assumption:* only when the user presses Import on the mod's page, read-only, showing what will be added (never values of `env` or `headers`; those become `.env` names for the user to fill).
- **Stdio servers' processes:** *Assumption:* one process per server for the whole machine (not per chat), started on first use and stopped after 15 idle minutes; a minimal environment (`PATH`, `HOME`, `LANG` and the server's own variables only).
- **Risk of an MCP tool:** *Assumption:* `readOnlyHint` → `read`; `destructiveHint` → `destructive`; a name or description about running code (`execute`, `exec`, `run_code`, `eval`, `python`, `shell`) → `execute`; everything else `write`. The user can change any tool's risk on the page; that wins.
- **Which Blender server:** *Assumption, checked in 5.1:* the Blender Lab's official server if it supports this machine's Blender 5.2.2, otherwise the community `blender-mcp` (ahujasid) whose add-on (1.8) is already installed, pinned to a version that matches the add-on, with `DISABLE_TELEMETRY=true`. Its `execute_blender_code` runs any Python as the user, outside the sandbox, so it is `execute` (Manual asks; Auto asks the judge; never a standing grant for it by default).
- **Blender has to be running** with its add-on's server started (the GUI), or be started headless by a server that can do that. *Needs the user* for the first live check: open Blender and start the add-on's server.
- **Results that are pictures** (screenshots, renders): *Assumption:* saved as outputs (`outputs/mcp/<date>/`, architecture §4.7) and returned as `output:<id>`, so `view_output` and the chat's cards work; text results stay text, inside `<untrusted>`.

## Phase 1 — The client mod (M)

- [x] **1.1 The mod: `services/mcp/` from `gaifa new mcp`.**
  - **Files:** `service.toml` (port 5108, `[agent] tools_source = "GET /v1/tools"`, `skills = "skills"`, a status route with `tools_rev`), `server.py` (FastAPI), `servers.py` (the config: `{id, name, transport: stdio|http, command, args, env: [names], url, headers: [names], enabled, approved: {hash, at, tools}, risks: {tool: risk}, allow, deny}`), `install.sh` (a venv with `mcp`, `httpx`, `fastapi`, `uvicorn`), `setup/mcp.md` with its `gaifa-setup` block.
  - **Routes:** `GET /health`, `GET /v1/status` (`{servers: [{id, state, tools, error}], tools_rev}`), `GET/POST /v1/servers`, `GET/PATCH/DELETE /v1/servers/{id}`.
  *Done when:* `gaifa check mcp` passes; `services/mcp/tests/test_servers.py` covers saving, validating (`id` rules, stdio needs `command`, http needs `url`) and the env names.
- [x] **1.2 Sessions: `services/mcp/client.py`.**
  - **Work:** `Pool.get(server)` opens a client session (stdio: `StdioServerParameters` with the minimal environment and the server's `.env` values; HTTP: `streamable_http_client` with its headers), lists tools (paging, `ttlMs` honoured), calls tools with a timeout (default 120 s), restarts a crashed stdio server once, stops idle ones; logs each server's stderr to `data/logs/mcp-<server>.log`.
  - **Both protocol eras:** the SDK's own negotiation (2026-07-28, falling back to 2025 `initialize`); an `input_required` (elicitation) answer becomes a question card through the hub (Phase 2).
  *Done when:* `services/mcp/tests/test_client.py` runs against a tiny stdio server in the tests (`tests/fake_server.py`, FastMCP: one read tool, one tool that returns an image, one that fails, one that sleeps) and an HTTP one: list, call, error, timeout, crash and restart, idle stop.
- [x] **1.3 Tools to the hub: `GET /v1/tools`, `POST /v1/call/{server}/{tool}`.**
  - **Rows:** only approved servers' tools whose fingerprint still matches: name `mcp_<server>_<tool>` (cut to 64 characters), `description` prefixed "<Server name>: ", the input schema as given, `risk` (§2's mapping or the user's), `group = "mcp:<server>"`, `mcp = false` (structured-memory 3.1: GAIFA doesn't pass other servers' tools on to its own MCP clients).
  - **Results:** text content joined; images and audio written as outputs (architecture §4.7: `{outputs}/<date>/<HHMMSS>-<slug>.<ext>` with a sidecar naming the server and tool) and returned as `output:<id>` refs once indexed; `structuredContent` kept; `isError` → the error envelope with the server's text as `detail`; results over 64 KB cut with a note.
  - **`tools_rev`:** a hash of the approved, enabled servers' fingerprints; the hub re-reads the tools when it changes.
  *Done when:* `services/mcp/tests/test_tools.py` covers names, risks, the image result as an output (fake hub), errors and the rev changing; with the hub (fake mod setup in `utils/tests/fixtures/mods/`) the tools show in `/api/tools` and a `read` one runs through `POST /api/tools/call`.

**Checks & deliverables — Phase 1**
- [x] On the installed hub with the fake server configured and approved, a chat finds its tools with `find_tools`, loads them and calls one. *As checked (2026-10-26, skynet, Auto):* "echo the word hello with it, then get its picture and show it to me" → `mcp_fake_echo` (the hub's argument check corrected `message` → `text`), `mcp_fake_picture` (an output in `outputs/mcp/`), `view_output` on it.
- [x] Delivered: `services/mcp/` (mod, client, tools), tests, the setup doc; docs: architecture §10 (the mods' table), `docs/structure.md`.

## Phase 2 — Safety (M)

- [x] **2.1 Approving a server's tools: `services/mcp/approve.py`.**
  - **Fingerprint:** a hash over each tool's name, description, input schema and annotations, in name order. A new server's tools wait for approval; a changed list holds the server (its tools leave the catalog) until the user approves the difference, shown as a diff.
  - **Screening:** on approval each tool's description and schema text go through the hub's screening (`POST /api/screen`, skill-sources 3.1); findings are shown next to the tool; a flagged tool starts denied.
  *Done when:* `services/mcp/tests/test_approve.py` covers a first approval, a changed description (held, diff), a removed and an added tool, and a flagged description.
- [x] **2.2 Questions and untrusted text.**
  - **Elicitation:** *as built:* the session's elicitation callback declines (both protocol eras: 2026's `input_required` and the older server-to-client request) and records the question; a mod has no way to put a question card in a chat today, so a server's `input_required` form is declined, and the result tells the model what the server asked so it can ask the user and call again with the answer in its arguments. A real card is later work (a hub route for a mod's question), noted in the mod's README.
  - **Untrusted:** every text result reaches the model inside `<untrusted>`. *As built:* the mod wraps a server's text itself (`<untrusted source="mcp:<server>/<tool>">`), and the agent counts `mcp_` tools among those that bring untrusted text (`context.UNTRUSTED_TOOLS`), so `remember` after one gets a card; no hub change.
  *Done when:* `services/mcp/tests/test_elicit.py` with the fake server's elicitation tool (declined, with what it asked); the hub's test for the `untrusted` row flag.

**Checks & deliverables — Phase 2**
- [ ] Changing the fake server's tool description on disk holds the server until it is approved again on the page.
- [ ] Delivered: `approve.py`, the elicitation path, tests; docs: architecture §14.7, the mod's README.

## Phase 3 — The page (M)

- [x] **3.1 `services/mcp/ui/page.js`.**
  - **Servers:** each with its state, tools (name, risk with a picker, allowed or not, description), Approve (and the diff when held), Start/Stop, its log; Add server (stdio command and arguments, or URL; env names to fill in `.env`).
  - **Import:** "Import from…" lists what other apps on this machine configure (read on demand from the files in §2, names, commands and URLs only), and a workspace folder's `.mcp.json`; picked ones are added unapproved.
  *Done when:* `utils/tests/web/mcp-page.test.mjs` covers the server list, the diff and the import list; on the installed hub the page adds, approves and starts the fake server.

**Wire — Phase 3:** the `mcp` mod's page.

**Checks & deliverables — Phase 3**
- [x] Import shows the `blender` server that `~/.claude.json` and `~/.codex/config.toml` configure, without any env value. *As checked (2026-10-26):* the Import tab lists Claude Code's `blender` (project `~/Projects/Blender`, `uvx blender-mcp`), Codex's `blender` (`uvx --from blender-mcp==2.0.0`, needs BLENDER_HOST, BLENDER_PORT, DISABLE_TELEMETRY), `node_repl` and `unity`; on Servers, the test server showed "tools changed (new: ask)" after a tool was added to it, and Approve the change put it back.
- [x] Delivered: `ui/page.js`, `importers.py`, tests; docs: the mod's README.

## Phase 4 — Turning servers on in a chat (S)

- [ ] **4.1 Skills that bring servers, and per-chat switches: `services/agent/agent/knowledge.py`, `loop.py`, `chat-composer.js`.**
  - **Skills:** a skill's frontmatter `metadata: {mcp-servers: "blender"}` (or Amp's `mcpServers` names) lists servers; when `read_skill` reads it, the agent loads those servers' tool groups in that chat (`load_tools group mcp:<server>`) and says so in the result.
  - **Asking for one:** `@mcp:blender` in the composer (plan 48's mentions, a new `mcp` kind listed from `GET /v1/servers`) loads the group for that turn's chat.
  - **Off by default:** `find_tools` lists an MCP tool only when its server is on in that chat or the query names the server; the composer's tools menu shows each server with a switch (the chat's `settings.mcp`).
  *Done when:* `services/agent/tests/test_mcp_servers.py` (fake hub): reading a skill with `mcp-servers` loads the group; `find_tools` hides an off server's tools; `@mcp:<id>` turns one on.

**Checks & deliverables — Phase 4**
- [ ] A chat that never mentions Blender carries no Blender tool; asking it to "make a scene in Blender" reads the Blender skill and loads the server's tools.
- [ ] Delivered: the agent's changes, the composer's, tests; docs: the brief's §11.13, architecture §14.1.

## Phase 5 — Blender (M)

- [ ] **5.1 Choosing and setting up the server: `services/mcp/setup/blender.md`.**
  - **Check:** whether the Blender Lab server supports Blender 5.2.2 here; else the community server pinned to the version matching the installed add-on, `DISABLE_TELEMETRY=true`, and its socket on `127.0.0.1:9876`.
  - **Config:** a `blender` entry (stdio) in the mod's `setup` defaults, unapproved until the user approves it; its code-running tool `execute`, screenshot and scene tools `read`, asset downloads `network`.
  *Done when:* the setup doc's check (`gaifa setup mcp --plan` lists it; `gaifa docs --check --strict` passes); with Blender open and the add-on's server started (the user), `GET /v1/servers/blender` lists its tools.
- [ ] **5.2 The Blender skill: `services/mcp/skills/blender/SKILL.md`.**
  - **Body:** look at the scene first (scene info, a screenshot), change it in small steps of code and look again, name objects, keep units, save with a path the user named or as an output; how to bring in a gen3d model (its GLB output's path) and render to an output; `metadata: {mcp-servers: "blender"}`.
  *Done when:* `services/mcp/tests/test_skill.py` checks the frontmatter (skill-sources 1.1); reading it in a chat loads the Blender tools (4.1).
- [ ] **5.3 A Blender eval: `services/agent/evals/blender.py`.**
  - **Tasks:** clear the scene and add three named primitives in a row; give one a red material; import the newest gen3d model and frame the camera on it; render a 512 px image to an output; answer how many objects the scene has.
  - **Runs:** the chat model of this machine and skynet; each task's success checked by the scene's state (the server's scene info), its steps and tokens; results in `docs/agent-eval.md`.
  *Done when:* the eval runs with Blender open (the user starts it), and the table is in the docs.

**Checks & deliverables — Phase 5**
- [ ] In a chat: "make a low-poly tree in Blender and show me a render" reads the skill, asks (Manual) or is judged (Auto) for each code step, and shows the render as an output.
- [ ] Delivered: the Blender setup doc, the skill, the eval; docs: `docs/agent-eval.md`, the mod's README.

| Deliverable | Description | Location |
| --- | --- | --- |
| `mcp` mod | MCP client: servers, sessions, tools to the hub | `services/mcp/server.py`, `servers.py`, `client.py` |
| Safety | fingerprints, approval with a diff, screening, elicitation | `services/mcp/approve.py` |
| Page | servers, tools, risks, import | `services/mcp/ui/page.js`, `importers.py` |
| In chats | servers switched on by skills, mentions and the composer | `services/agent/agent/knowledge.py`, `loop.py`, `web/chat/chat-composer.js` |
| Blender | setup doc, skill, eval | `services/mcp/setup/blender.md`, `services/mcp/skills/blender/`, `services/agent/evals/blender.py` |
| Tests | config, client against a fake server, tools, approval, page, agent | `services/mcp/tests/`, `services/agent/tests/test_mcp_servers.py`, `utils/tests/web/mcp-page.test.mjs` |
