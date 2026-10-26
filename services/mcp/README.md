# MCP servers (`mcp`)

GAIFA's MCP client (plan [mcp-client](../../docs/plans/mcp-client.md)): other MCP servers' tools in GAIFA's chats. GAIFA is also an MCP *server* (`/mcp`, plan 13.4); this mod is the other direction. Setup: [setup/mcp.md](setup/mcp.md). The mod guide is [docs/mods.md](../../docs/mods.md).

## How it works

1. **Add a server** (the page, or `POST /v1/servers`): a stdio program (`uvx`, `npx`, a path, with arguments) or a Streamable HTTP endpoint. Secrets go in this folder's `.env` and the config names them as `${NAME}`; they're never in `data/state/mcp/servers.json` or the API.
2. **Approve its tools.** The page starts the server and lists its tools with a risk each; every description and schema goes through the hub's fixed patterns (`POST /api/screen`), and a flagged tool starts turned off. Approving records a fingerprint of each tool (name, description, input schema, annotations).
3. **The hub offers them** (`[agent] tools_source = "GET /v1/tools"`): `mcp_<server>_<tool>`, deferred like every tool (`find_tools` / `load_tools`), all `mcp = false` (GAIFA doesn't pass them on to its own MCP clients). The status's `tools_rev` changes when approvals, risks or turned-off tools change, so the hub reads them again.
4. **A call** goes through the hub's permissions, approvals, grants and the Auto judge like any tool, then `POST /v1/call/{server}/{tool}`. Text comes back as text, pictures and sound as outputs (`outputs/mcp/<date>/`), structured content as is.
5. **A server whose tools change** (a new session lists them again) is held: its tools leave the catalog and calls answer `409 changed` until the user looks at the difference and approves again.

Risk of a tool: what the user chose on the page, else `readOnlyHint` → read, `destructiveHint` → destructive, a name or description about running code → execute, `openWorldHint` → network, else write.

Sessions: one per server for the machine, started on first use, stopped after 15 idle minutes; a stdio server gets a minimal environment (HOME, LOGNAME, PATH, SHELL, TERM, USER, LANG) plus its own variables, and its stderr goes to `data/logs/mcp-<id>.log`. A session that breaks under a call is stopped; the next call starts a new one (a call is never sent twice).

Elicitation: a server's request for more input is declined (a mod can't put a form in a chat yet); the result says what it asked, so the agent can ask the user and call again.

## Routes

| Route | What it does |
|---|---|
| `GET /health`, `GET /v1/status` | up; servers, running, tools offered, calls, `tools_rev` |
| `GET /v1/servers`, `POST /v1/servers` | the servers with their approval and session state; add one |
| `GET /v1/servers/{id}?tools=true` | one server; `tools=true` starts it and lists its tools now, with risks, fingerprints and the hash to approve |
| `PATCH /v1/servers/{id}`, `DELETE /v1/servers/{id}` | change it (a new launch means approving again; risks; turned-off tools), remove it |
| `POST /v1/servers/{id}/start`, `/stop` | the session |
| `POST /v1/servers/{id}/approve {hash}` | approve the tools as listed (refused when they changed since) |
| `GET /v1/tools` | the hub's `tools_source` rows |
| `POST /v1/call/{id}/{tool} {arguments}` | one call |

## Files

| File | What it does |
|---|---|
| `server.py` | the API, approval and screening, `tools_rev` |
| `servers.py` | `servers.json`, validation, `${NAME}` secrets from `.env` |
| `client.py` | `Pool`: a session per server (stdio or HTTP) through the `mcp` SDK, idle stop, broken sessions |
| `tools.py` | rows for the hub, risks, fingerprints and differences, results (outputs) |
| `ui/page.js` | the page: servers, tools, approval, import |
| `tests/` | a stdio fake server (`fake_server.py`) and the tests: `.venv/bin/python -m pytest` in this folder |
