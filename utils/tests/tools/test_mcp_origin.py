"""Plan agent-workflows 4.2: an /mcp call carries the client's name as `origin.client` (the 2026-07-28 era's per-request
`clientInfo`, else the user agent), which a mod reads from X-GAIFA-Origin: the agent mod keeps the chats each client
started (`agent_chat_*`) by it."""

from __future__ import annotations

from utils.tests.tools.test_mcp import MODERN, call


async def test_the_client_s_name_is_in_the_origin(th):
    await call(th, "fake_tools_make_image", {"prompt": "a fox"}, version=MODERN)          # asks: an approval with its origin
    await call(th, "fake_tools_make_image", {"prompt": "a cat"}, headers={"User-Agent": "codex-cli/1.2 (linux)"})
    origins = sorted(a["origin"]["client"] for a in (await th.client.get("/api/approvals")).json())
    assert origins == ["codex-cli/1.2", "pytest"]
    assert all(a["origin"]["service"] == "mcp" for a in (await th.client.get("/api/approvals")).json())
