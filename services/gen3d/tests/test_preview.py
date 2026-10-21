"""The Blender preview: its command line, the software-GL switch, the face limit, and what it refuses to import.
Nothing here runs Blender; render_blender.py is loaded without bpy (main() is never called)."""

import importlib.util
import json
import struct
from pathlib import Path

import pytest

from gen3d import preview
from gen3d.preview import blender_command, blender_env, check_previewable, external_uris

_spec = importlib.util.spec_from_file_location("render_blender", preview.SCRIPT)
rb = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rb)


def _glb(path: Path, doc: dict) -> Path:
    js = json.dumps(doc).encode()
    js += b" " * (-len(js) % 4)
    path.write_bytes(b"glTF" + struct.pack("<II", 2, 20 + len(js)) + struct.pack("<II", len(js), 0x4E4F534A) + js)
    return path


def test_command_disables_autoexec_and_passes_the_limits():
    cmd = blender_command("/bin/blender", Path("/j/mesh.glb"), Path("/j/preview.png"), 384, "gpu", 300000)
    assert cmd[:4] == ["/bin/blender", "-b", "--factory-startup", "--disable-autoexec"]
    assert cmd.index("--disable-autoexec") < cmd.index("-P")
    assert "--gpu-backend" not in cmd
    tail = cmd[cmd.index("--") + 1:]
    assert tail == ["/j/preview.png", "/j/mesh.glb", "--size", "384", "--max-faces", "300000", "--device", "gpu"]


def test_cpu_device_forces_software_gl():
    cmd = blender_command("blender", Path("m.glb"), Path("p.png"), 384, "cpu", 0)
    assert cmd[cmd.index("--gpu-backend") + 1] == "opengl" and cmd.index("--gpu-backend") < cmd.index("-P")
    assert cmd[-2:] == ["--device", "cpu"]
    env = blender_env("cpu", {"PATH": "/usr/bin"})
    assert env["LIBGL_ALWAYS_SOFTWARE"] == "1" and env["GALLIUM_DRIVER"] == "llvmpipe" and env["PATH"] == "/usr/bin"
    assert blender_env("gpu", {"PATH": "/usr/bin"}) == {"PATH": "/usr/bin"}


def test_device_setting_defaults_to_cpu(monkeypatch):
    from gen3d.config import Settings, _device
    for value, want in (("", "cpu"), ("cpu", "cpu"), (" GPU ", "gpu"), ("gpu", "gpu"), ("cuda", "cpu")):
        monkeypatch.setenv("GEN3D_PREVIEW_DEVICE", value)
        assert _device("GEN3D_PREVIEW_DEVICE") == want
    monkeypatch.delenv("GEN3D_PREVIEW_DEVICE")
    assert Settings().preview_device == "cpu"


def test_face_limit_decides_the_simplification():
    calls = []

    def count(dist):                      # each coarser step keeps 40% of the faces
        calls.append(dist)
        return int(2_000_000 * 0.4 ** len(calls))

    assert rb.FACE_LIMIT == 300_000
    for faces, limit in ((300_000, 300_000), (12, 300_000), (5_000_000, 0)):   # 0 = never simplify
        assert rb.choose_merge(faces, limit, 2.0, count) is None
    assert calls == []
    dist, left = rb.choose_merge(2_000_000, 300_000, 2.0, count)
    assert calls == [2.0 / 2000, 2.0 / 1000, 2.0 / 500] and dist == calls[-1] and left == 128_000


def test_simplification_stops_near_a_pixel():
    seen = []
    dist, left = rb.choose_merge(25_000_000, 300_000, 1.0, lambda d: seen.append(d) or 1_000_000)
    assert seen == [1 / s for s in rb.WELD_STEPS] and dist == 1 / 250 and left == 1_000_000
    assert rb.choose_merge(400_000, 300_000, 1.0, lambda d: 1000) == (1 / 2000, 1000)


def test_script_arguments_clamp_size_and_refuse_other_formats():
    a = rb.parse_args(["out.png", "a.glb", "b.PLY", "--size", "4096", "--device", "cpu"])
    assert a["inputs"] == ["a.glb", "b.PLY"] and a["size"] == rb.MAX_SIZE == 512 and a["device"] == "cpu"
    assert a["max_faces"] == 300_000
    assert rb.parse_args(["o.png", "m.obj", "--max-faces", "0"])["max_faces"] == 0
    for bad in (["o.png", "scene.gltf"], ["o.png", "m.stl"], ["o.png"], ["o.png", "m.glb", "--device", "cuda"]):
        with pytest.raises(SystemExit):
            rb.parse_args(bad)


def test_glb_with_outside_files_is_refused(tmp_path):
    ok = _glb(tmp_path / "ok.glb", {"asset": {"version": "2.0"}, "buffers": [{"byteLength": 4}],
                                    "images": [{"uri": "data:image/png;base64,AAAA"}]})
    assert external_uris(ok) == []
    check_previewable(ok)
    bad = _glb(tmp_path / "bad.glb", {"asset": {"version": "2.0"},
                                      "buffers": [{"byteLength": 4}, {"uri": "/home/u/.ssh/id_ed25519", "byteLength": 9}],
                                      "images": [{"uri": "../../secret.png"}]})
    assert external_uris(bad) == ["/home/u/.ssh/id_ed25519", "../../secret.png"]
    with pytest.raises(RuntimeError, match="outside files"):
        check_previewable(bad)
    (tmp_path / "junk.glb").write_bytes(b"not a glb at all, really")
    with pytest.raises(RuntimeError, match="not a GLB"):
        check_previewable(tmp_path / "junk.glb")


@pytest.mark.parametrize("name", ["input.gltf", "input.stl", "input.off", "mesh"])
def test_only_glb_obj_ply_reach_blender(tmp_path, name):
    (tmp_path / name).write_text("{}")
    with pytest.raises(RuntimeError, match="no preview"):
        check_previewable(tmp_path / name)
    for ok in ("input.obj", "input.ply"):
        (tmp_path / ok).write_text("v 0 0 0\n")
        check_previewable(tmp_path / ok)


async def _never(*a, **k):
    raise AssertionError("Blender must not start")


def test_refused_mesh_never_starts_blender(tmp_path, monkeypatch):
    monkeypatch.setattr(preview, "blender", lambda: "/bin/blender")
    monkeypatch.setattr(preview.asyncio, "create_subprocess_exec", _never)
    (tmp_path / "input.gltf").write_text('{"buffers": [{"uri": "/etc/passwd"}]}')
    import asyncio
    with pytest.raises(RuntimeError, match="no preview"):
        asyncio.run(preview.render_preview(tmp_path, tmp_path / "input.gltf", tmp_path / "preview.png"))


def test_stuck_blender_is_killed(tmp_path, monkeypatch):
    import asyncio
    from dataclasses import replace

    script = tmp_path / "hang.sh"
    script.write_text("#!/bin/sh\nexec sleep 30\n")
    script.chmod(0o755)
    glb = _glb(tmp_path / "m.glb", {"asset": {"version": "2.0"}})
    monkeypatch.setattr(preview, "blender", lambda: str(script))
    monkeypatch.setattr(preview, "settings", replace(preview.settings, preview_timeout_s=0.3))
    seen = {}
    real = asyncio.create_subprocess_exec

    async def spawn(*cmd, **kw):
        seen["proc"] = await real(*cmd, **kw)
        return seen["proc"]

    monkeypatch.setattr(preview.asyncio, "create_subprocess_exec", spawn)
    with pytest.raises(RuntimeError, match="longer than 0.3s"):
        asyncio.run(preview.render_preview(tmp_path, glb, tmp_path / "preview.png"))
    assert seen["proc"].returncode is not None        # killed and reaped
