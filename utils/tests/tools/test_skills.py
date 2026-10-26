"""14.9: the mods' skills over HTTP: listed, read, and safe against traversal."""


async def test_skills_listed_and_read(th):
    r = (await th.client.get("/api/skills")).json()
    assert r == [{"mod": "fake-tools", "name": "drawing", "description": "How to draw with fake-tools"}]
    s = (await th.client.get("/api/skills/fake-tools/drawing")).json()
    assert s["body"].strip() == "Use 16:9 for landscapes." and s["description"].startswith("How to draw")
    for bad in ("/api/skills/fake-tools/nope", "/api/skills/fake-tools/..%2F..%2Fservice.toml", "/api/skills/other/drawing"):
        assert (await th.client.get(bad)).status_code == 404, bad


async def test_a_skills_other_files(th, root):
    """skill-sources 1.2: a skill lists its other files and reads them as text, never outside its folder."""
    d = root / "services" / "fake-tools" / "skills" / "drawing"
    (d / "references").mkdir()
    (d / "references" / "sizes.md").write_text("16:9 is 1344x768\n")
    (d / "logo.png").write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00")
    (d / ".hidden").write_text("x")
    (root / "outside.md").write_text("secret")
    (d / "link.md").symlink_to(root / "outside.md")
    s = (await th.client.get("/api/skills/fake-tools/drawing")).json()
    assert [f["path"] for f in s["files"]] == ["logo.png", "references/sizes.md"]
    r = await th.client.get("/api/skills/fake-tools/drawing/files/references/sizes.md")
    assert r.status_code == 200 and r.json() == {"path": "references/sizes.md", "text": "16:9 is 1344x768\n"}
    assert (await th.client.get("/api/skills/fake-tools/drawing/files/logo.png")).json()["code"] == "binary"
    for bad in ("link.md", ".hidden", "..%2F..%2Fservice.toml", "nope.md", "SKILL.md/x"):
        assert (await th.client.get(f"/api/skills/fake-tools/drawing/files/{bad}")).status_code == 404, bad
    assert (await th.client.get("/api/skills/fake-tools/nope/files/references/sizes.md")).status_code == 404
