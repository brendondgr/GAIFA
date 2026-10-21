"""The pinned revision: only the revision whose remote code was read loads. Another revision named in the request,
a download of another revision, a changed or added code file, or missing weights are refused before any model code
runs."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from decide.models.d3_lite import D3Lite, from_d3, to_d3

REAL = Path(__file__).resolve().parents[3] / "data" / "models" / "decide" / "d3-lite"


def test_request_naming_another_revision_is_refused(client):
    q = [{"id": "q", "type": "yesno", "question": "x"}]
    r = client.post("/v1/decide", json={"input": "x", "questions": q, "model": "fake@deadbeef"})
    assert r.status_code == 409 and r.json()["code"] == "unpinned_revision" and "0000000000" in r.json()["fix"]
    r = client.post("/v1/decide", json={"input": "x", "questions": q, "model": "fake@" + "0" * 40})
    assert r.status_code == 200
    assert client.post("/v1/load", json={"model": "fake@abc123"}).status_code == 409


def test_downloaded_other_revision_is_refused(client, settings):
    (settings.models_dir / "fake" / "revision").write_text("1" * 40)
    r = client.post("/v1/decide", json={"input": "x", "questions": [{"id": "q", "type": "yesno", "question": "x"}]})
    assert r.status_code == 409 and r.json()["code"] == "unpinned_revision"
    from decide.models.fake import FakeModel
    assert FakeModel.loads == []                                     # refused before loading anything
    m = client.get("/v1/models").json()["models"][0]
    assert m["usable"] is False and "revision 111111111111" in m["problems"][0]


def test_missing_weights(client, settings):
    (settings.models_dir / "fake" / "weights.bin").unlink()
    r = client.post("/v1/load", json={})
    assert r.status_code == 503 and r.json()["code"] == "no_weights" and "install.sh" in r.json()["fix"]


@pytest.fixture
def d3_folder(tmp_path: Path) -> Path:
    """The pinned files of d3-lite (from data/models when downloaded, else stand-ins that fail the hashes)."""
    folder = tmp_path / "d3-lite"
    folder.mkdir()
    for name in D3Lite.PINNED:
        if (REAL / name).is_file():
            shutil.copy(REAL / name, folder / name)
    (folder / D3Lite.WEIGHTS).write_bytes(b"")
    return folder


@pytest.mark.skipif(not (REAL / "modeling_d3.py").is_file(), reason="d3-lite isn't downloaded")
def test_d3_lite_check(d3_folder):
    assert D3Lite.check(d3_folder) == []
    meta = d3_folder / ".cache" / "huggingface" / "download"
    meta.mkdir(parents=True)
    (meta / "modeling_d3.py.metadata").write_text("2227a85f59aaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\nx\n")
    assert "revision 2227a85f59aa was downloaded" in D3Lite.check(d3_folder)[0]
    (meta / "modeling_d3.py.metadata").write_text(D3Lite.REVISION + "\n")
    with open(d3_folder / "d3_runtime.py", "a") as f:
        f.write("\nimport os; os.system('true')\n")
    assert D3Lite.check(d3_folder) == [f"d3_runtime.py differs from revision {D3Lite.REVISION[:12]}, whose code was read"]
    shutil.copy(REAL / "d3_runtime.py", d3_folder / "d3_runtime.py")
    (d3_folder / "extra.py").write_text("print('hi')")
    assert "extra.py: a code file" in D3Lite.check(d3_folder)[0]
    (d3_folder / "extra.py").unlink()
    (d3_folder / "d3_fast.py").unlink()
    assert D3Lite.check(d3_folder) == ["d3_fast.py is missing"]
    with pytest.raises(PermissionError):
        D3Lite().load(d3_folder)                                     # refused before importing torch


def test_d3_lite_check_without_weights(tmp_path):
    assert D3Lite.check(tmp_path)[0].startswith("no weights")


def test_d3_translation():
    assert to_d3({"id": "a", "type": "yesno", "question": "Q?"}) == {"type": "noul", "instructions": "Q?"}
    assert to_d3({"id": "a", "type": "choice", "question": "Q?", "options": ["x", "y"]})["criteria"] == {"x": None, "y": None}
    assert to_d3({"id": "a", "type": "score", "question": "Q?", "scale": ["lo", "hi"]})["criteria"] == ["lo", "hi"]
    yes = from_d3({"type": "yesno"}, {"type": "noul", "noul": 0.25})
    assert yes == {"probs": {"yes": 0.25, "no": 0.75}, "top": "no", "p": 0.75}
    sc = from_d3({"type": "score", "scale": ["lo", "hi"]},
                 {"type": "score", "score": 0.9, "probabilities": {"0": 0.1, "1": 0.9}})
    assert sc == {"probs": {"lo": 0.1, "hi": 0.9}, "top": "hi", "p": 0.9, "value": 0.9}
    assert from_d3({"type": "yesno"}, {"error": "max_length_exceeded", "message": "m"})["error"] == "max_length_exceeded"
