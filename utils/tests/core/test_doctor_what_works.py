"""capability-enablement 1.7: the doctor's What works: one line per mod with what it gives and whether it can be used;
a recommended mod that isn't set up warns, others are notes; search needs a SearXNG; Auto needs decide."""

from __future__ import annotations

import re
import shutil

import httpx

from utils.tests.conftest import FAKE_MODS, free_port


def _mod(root, sid: str, edits: dict[str, str] | None = None, provides: str = "", recommended: bool = False) -> None:
    for helper in FAKE_MODS.glob("_*.py"):
        shutil.copy(helper, root / "services" / helper.name)
    d = root / "services" / sid
    shutil.copytree(FAKE_MODS / "fake-ok", d)
    text = (d / "service.toml").read_text().replace('id = "fake-ok"', f'id = "{sid}"').replace('name = "Fake OK"', f'name = "{sid.title()}"')
    text = re.sub(r"(?m)^port = \d+", f"port = {free_port()}", text)
    for k, v in (edits or {}).items():
        text = re.sub(rf"(?m)^{k} = .*$", f"{k} = {v}", text)
    if provides:
        text += f'\n[agent]\nprovides = "{provides}"\n'
    (d / "service.toml").write_text(text)
    if recommended:
        (d / "setup").mkdir()
        (d / "setup" / f"{sid}.md").write_text(f'<!-- gaifa-setup\nid = "{sid}"\ntitle = "x"\nsummary = "x"\nrecommended = true\n-->\n# x\n')


async def test_what_works(root, make_app):
    venv = {"command": '[".venv/bin/python", "server.py"]'}
    _mod(root, "web", venv, "search the web and read pages", recommended=True)
    _mod(root, "stt", venv, "transcribe audio or take dictation")
    _mod(root, "calendar", {}, "keep your calendar, to-dos and reminders")
    _mod(root, "mcp", {}, "use tools from other MCP servers")
    (root / "config.toml").write_text("[services.mcp]\nenabled = false\n")
    app = make_app(port=7000, autostart=False)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://hub") as c:
            r = (await c.get("/api/doctor")).json()
    works = {x["title"]: x for x in r["checks"] if x["area"] == "what works"}
    web = works["search the web and read pages: not set up (recommended)"]
    assert web["level"] == "warn" and web["fix"] == "gaifa setup web" and web["detail"] == "web: Web isn't set up on this machine"
    assert works["transcribe audio or take dictation: not set up"]["level"] == "note"
    assert works["keep your calendar, to-dos and reminders: works"]["level"] == "ok"
    off = works["use tools from other MCP servers: turned off"]
    assert off["level"] == "note"
    assert works["Auto mode's judge: off"]["fix"] == "gaifa setup decide"


async def test_search_needs_a_searxng(root, make_app):
    _mod(root, "web", {}, "search the web and read pages")
    app = make_app(port=7000, autostart=False)
    async with app.router.lifespan_context(app):
        from utils.doctor import _what_works
        hub = app.state.hub
        svc = hub.services.get("web")
        svc.state, svc.tools_off = "ready", {"search": {"why": "no SearXNG answers at http://127.0.0.1:8080", "fix": ""}}
        try:
            checks = {x["title"]: x for x in _what_works(hub)}
        finally:
            svc.state, svc.tools_off = "stopped", {}
    assert checks["web search: off"]["level"] == "warn" and "no SearXNG answers" in checks["web search: off"]["detail"]


def test_a_gaifa_searxng_left_without_its_mod():
    from types import SimpleNamespace

    from utils.doctor import _leftovers
    hub = SimpleNamespace(services=SimpleNamespace(services={}))
    seen = []

    def run(argv):
        seen.append(argv)
        return SimpleNamespace(stdout="gaifa-searxng\n" if argv[0] == "podman" else "")
    out = _leftovers(hub, run)
    assert [c["fix"] for c in out] == ["podman rm -f gaifa-searxng"] and out[0]["level"] == "warn"
    assert _leftovers(SimpleNamespace(services=SimpleNamespace(services={"searxng": object()})), run) == []


async def test_chat_needs_a_model_that_answers(root, make_app):
    _mod(root, "agent", {}, "chat with you and use GAIFA's tools")
    app = make_app(port=7000, autostart=False)
    async with app.router.lifespan_context(app):
        from utils.doctor import _what_works
        hub = app.state.hub
        svc = hub.services.get("agent")
        svc.state = "ready"
        try:
            svc.status = {"llm": {"url": "http://127.0.0.1:4000/v1", "kind": "relay", "answers": False, "models": [], "detail": "nothing answers"}}
            bad = {x["title"]: x for x in _what_works(hub)}["Chat has no model: nothing answers at http://127.0.0.1:4000/v1"]
            assert bad["level"] == "fail" and bad["fix"] == "gaifa start relay"
            svc.status = {"llm": {"url": "http://127.0.0.1:9090/v1", "kind": "direct", "answers": True, "models": ["m"], "detail": ""}}
            ok = {x["title"]: x for x in _what_works(hub)}["Chat has a model"]
            assert ok["level"] == "ok" and "a server of yours" in ok["detail"]
        finally:
            svc.state, svc.status = "stopped", None
