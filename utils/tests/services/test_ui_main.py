"""calendar 3.1 and 7.1: a mod's main view (`[ui] main`) and its side panel in Chat (`[ui] chat_panel`): the
manifest fields, a clashing id, and `main`/`chat_panel` in the services view."""

from __future__ import annotations

import httpx
import pytest
from pydantic import ValidationError

from utils.manifest import ChatPanelSpec, Manifest, UiSpec

RUN = {"port": 5150, "command": ["x"]}


def test_main_fields():
    m = Manifest(id="calendar", run=RUN, ui=UiSpec(page="ui/page.js", main={"label": "Calendar"}))
    assert m.ui.main.after == "chat"
    with pytest.raises(ValidationError):
        Manifest(id="calendar", run=RUN, ui=UiSpec(page="ui/page.js", main={"label": "Calendar", "after": "models"}))
    with pytest.raises(ValidationError):
        Manifest(id="calendar", run=RUN, ui=UiSpec(main={"label": "Calendar"}))          # no page
    with pytest.raises(ValidationError):
        Manifest(id="calendar", run=RUN, ui=UiSpec(page="ui/Page.dc.html", main={"label": "Calendar"}))


@pytest.mark.parametrize("bad", ["chat", "outputs", "services", "settings"])
def test_main_id_clashing_with_a_hub_page(bad):
    with pytest.raises(ValidationError, match="hub's own pages"):
        Manifest(id=bad, run=RUN, ui=UiSpec(page="ui/page.js", main={"label": "X"}))
    Manifest(id=bad, run=RUN, ui=UiSpec(page="ui/page.js"))                                # fine without a main view


@pytest.mark.parametrize("bad", ["panel.js", "ui/../x.js", "/ui/panel.js", "ui/panel.html"])
def test_chat_panel_module(bad):
    with pytest.raises(ValidationError):
        ChatPanelSpec(module=bad, label="X")
    assert ChatPanelSpec(module="ui/panel.js", label="Calendar").module == "ui/panel.js"


async def test_in_the_services_view(rig, serve):
    d = rig.add("fake-ok", as_id="cal")
    (d / "ui").mkdir()
    (d / "ui" / "page.js").write_text("export default { mount() {}, main: { mount() {} } };\n")
    (d / "ui" / "panel.js").write_text("export default { mount() {} };\n")
    with open(d / "service.toml", "a") as f:
        f.write('\n[ui]\npage = "ui/page.js"\nmain = { label = "Cal", after = "chat" }\nchat_panel = { module = "ui/panel.js", label = "Cal" }\n')
    rig.add("fake-ok", as_id="plain")
    served = await serve()
    async with httpx.AsyncClient(base_url=served.url) as c:
        svcs = {s["id"]: s for s in (await c.get("/api/services")).json()}
    assert svcs["cal"]["main"] == {"label": "Cal", "after": "chat"}
    assert svcs["cal"]["chat_panel"] == {"label": "Cal", "url": "/ui/services/cal/panel.js"}
    assert svcs["plain"]["main"] is None and svcs["plain"]["chat_panel"] is None
