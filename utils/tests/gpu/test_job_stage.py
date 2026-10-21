"""Plan 31.3: a mod's job that waits for the slot (`stage: "waiting_gpu"`, `ahead`, `eta_s`) reaches the UI:
through the status poller's job list, and as the one-line note on a chat step."""

from __future__ import annotations

from utils.gpu import gpu_note
from utils.services.status import validate


def test_status_keeps_the_waiting_stage():
    st, problems = validate({"jobs": [{"id": "j1", "label": "Image", "state": "queued", "stage": "waiting_gpu",
                                       "ahead": [{"service": "gen3d", "label": "model", "eta_s": 240}], "eta_s": 240},
                                      {"id": "j2", "state": "running"}]})
    assert not problems
    j1, j2 = st["jobs"]
    assert j1["stage"] == "waiting_gpu" and j1["ahead"][0]["service"] == "gen3d" and j1["eta_s"] == 240
    assert "stage" not in j2


def test_gpu_note():
    names = {"gen3d": "3D Generate", "comfy": "Images & Video"}.get
    body = {"state": "queued", "stage": "waiting_gpu", "ahead": [{"service": "gen3d", "label": "model"}], "eta_s": 240}
    assert gpu_note(body, names) == "Waiting for the GPU: 3D Generate (model), about 4 min"
    body["ahead"].append({"service": "comfy", "label": "image"})
    body["eta_s"] = 30
    assert gpu_note(body, names) == "Waiting for the GPU: 3D Generate (model) and 1 more, about 30 s"
    assert gpu_note({"stage": "waiting_gpu"}) == "Waiting for the GPU"
    assert gpu_note({"stage": "rendering"}) is None and gpu_note(None) is None
