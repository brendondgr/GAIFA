"""14.9: the mods' skills over HTTP: listed, read, and safe against traversal."""


async def test_skills_listed_and_read(th):
    r = (await th.client.get("/api/skills")).json()
    assert r == [{"mod": "fake-tools", "name": "drawing", "description": "How to draw with fake-tools"}]
    s = (await th.client.get("/api/skills/fake-tools/drawing")).json()
    assert s["body"].strip() == "Use 16:9 for landscapes." and s["description"].startswith("How to draw")
    for bad in ("/api/skills/fake-tools/nope", "/api/skills/fake-tools/..%2F..%2Fservice.toml", "/api/skills/other/drawing"):
        assert (await th.client.get(bad)).status_code == 404, bad
