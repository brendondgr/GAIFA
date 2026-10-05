"""6.4: a mod with a broken service.toml (or a config.toml port clash) raises an alert; fixing it
and rescanning, or removing the mod, clears it."""

from __future__ import annotations

import shutil

from utils.tests.services.conftest import _set_line


async def test_manifest_alerts(rig):
    rig.add("fake-ok")
    broken = rig.add("fake-slow", as_id="broken")
    good_text = (broken / "service.toml").read_text()
    (broken / "service.toml").write_text(good_text.replace("[run]\n", "[run]\nnonsense = 1\n"))
    mgr = await rig.manager()
    alerts = lambda: {a["id"]: a for a in mgr.alerts.list()}  # noqa: E731
    a = alerts()["manifest-broken"]
    assert a["level"] == "error" and a["service"] == "broken" and a["action"] == {"label": "Show details", "route": "#/s/broken/settings"}
    assert a["text"].startswith('Mod "broken" has a manifest error: ') and "nonsense" in a["text"]
    assert "manifest-fake-ok" not in alerts()
    # fixed, then rescanned: cleared
    (broken / "service.toml").write_text(good_text)
    await mgr.rescan(autostart=False)
    assert "manifest-broken" not in alerts()
    # a config.toml override that clashes with another mod's port is a manifest error too
    port = rig.ports["fake-ok"]
    from utils import config

    cfg = config.validate({"services": {"broken": {"port": port}}})
    mgr.reconfigure(cfg)
    assert f"port {port} is already used by broken" in alerts()["manifest-fake-ok"]["text"]  # ids in order: broken took it
    mgr.reconfigure(config.Config())
    assert not [a for a in alerts() if a.startswith("manifest-")]
    # broken again, then the folder is removed: cleared
    (broken / "service.toml").write_text(_set_line(good_text, "port", '"x"'))
    await mgr.rescan(autostart=False)
    assert "manifest-broken" in alerts()
    shutil.rmtree(broken)
    await mgr.rescan(autostart=False)
    assert "manifest-broken" not in alerts()
