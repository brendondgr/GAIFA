"""44.1: a mod's chat module: `[ui] chat`, `chat_url` in the services view, and `aihub check`."""

from __future__ import annotations

import httpx
import pytest
from pydantic import ValidationError

from utils.manifest import UiSpec
from utils.services.check import chat_check
from utils.tests.services.conftest import ready
from utils.tests.services.test_check import check, statuses


@pytest.mark.parametrize("bad", ["chat.js", "ui/../x.js", "/ui/chat.js", "ui/chat.mjs.txt", "ui/chat.html"])
def test_chat_must_be_a_js_file_in_ui(bad):
    with pytest.raises(ValidationError):
        UiSpec(chat=bad)
    assert UiSpec(chat="ui/chat.js").chat == "ui/chat.js"


def test_chat_check(tmp_path):
    assert chat_check(tmp_path / "chat.js")[0] == "fail"
    (tmp_path / "chat.js").write_text("export function setup() {}\n")
    assert chat_check(tmp_path / "chat.js")[0] == "fail"
    (tmp_path / "chat.js").write_text("export default function setup(chat) {}\n")
    assert chat_check(tmp_path / "chat.js")[0] == "ok"


async def test_chat_url_served_and_checked(rig, serve):
    d = rig.add("fake-ok")
    (d / "ui").mkdir()
    (d / "ui" / "chat.js").write_text("export default function setup(chat) { chat.registerStep('x', {}); }\n")
    with open(d / "service.toml", "a") as f:
        f.write('\n[ui]\nchat = "ui/chat.js"\n')
    m = rig.add("fake-ok", as_id="missing")
    with open(m / "service.toml", "a") as f:
        f.write('\n[ui]\nchat = "ui/chat.js"\n')
    rig.add("fake-ok", as_id="plain")
    served = await serve()
    await ready(served, "fake-ok", "missing", "plain")
    async with httpx.AsyncClient(base_url=served.url) as c:
        items = {s["id"]: s for s in (await c.get("/api/services")).json()}
        assert items["fake-ok"]["chat_url"] == "/ui/services/fake-ok/chat.js"
        assert items["missing"]["chat_url"] is None and items["plain"]["chat_url"] is None
        r = await c.get("/ui/services/fake-ok/chat.js")
        assert r.status_code == 200 and "setup(chat)" in r.text
    assert statuses(await check(served, "fake-ok"))["chat"] == "ok"
    rep = await check(served, "missing")
    assert statuses(rep)["chat"] == "fail" and rep["ok"] is False
