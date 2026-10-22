"""40.2: `aihub report`, the field report: notes, every section from a failed run on a recorded machine, the
likely causes, redaction, and a hub that doesn't answer."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest

from utils import cli, cli_report, hardware, report_hints, report_md

FIX = Path(__file__).resolve().parents[1] / "hardware" / "fixtures"
CUDA_OOPS = """Collecting torch
ERROR: Could not find a version that satisfies the requirement torch==2.9.1+cu130
ERROR: No matching distribution found for torch==2.9.1+cu130"""


@pytest.fixture
def field(tmp_path: Path, monkeypatch):
    """A clone on an NVIDIA box whose last setup run failed a step and a smoke; the hub is down."""
    monkeypatch.setattr(cli, "ROOT", tmp_path)
    monkeypatch.setenv("AIHUB_HARDWARE_FIXTURE", str(FIX / "linux-nvidia-1gpu.json"))
    hardware.detect(refresh=True)
    monkeypatch.setattr(cli_report, "cli", cli)
    monkeypatch.setattr(cli, "call", lambda *a, **k: (_ for _ in ()).throw(cli.HubDown("AIHub is not running")))
    doc = tmp_path / "services" / "tts" / "setup"
    doc.mkdir(parents=True)
    (doc / "kokoro.md").write_text("<!-- aihub-setup\nid = \"tts-kokoro\"\n[[steps]]\nrun = \"scripts/install-runtime.sh\"\n-->\n")
    logs = tmp_path / "data" / "state" / "setup" / "logs"
    logs.mkdir(parents=True)
    (logs / "tts-kokoro_3.log").write_text("$ scripts/install-runtime.sh\n" + CUDA_OOPS + "\nHF_TOKEN=hf_abcdefghijklmnopqrstuvwx\n# exit 1\n")
    (logs / "embed_smoke.log").write_text("$ curl …\ncurl: (7) Failed to connect to 127.0.0.1 port 7000\n# exit 7\n")
    last = {"machine": {}, "targets": ["tts", "embed"], "argv": ["setup", "tts", "embed", "--smoke"],
            "plan": {"setups": ["tts-kokoro", "embed"], "variants": [{"setup": "tts-kokoro", "accel": "cuda", "label": "CUDA", "untested": True, "note": None}],
                     "unavailable": [{"setup": "gen3d", "why": "it needs ROCm"}]},
            "result": {"stage": "stopped", "reason": "failed", "report": {
                "done": ["tts-kokoro/1"], "skipped": [], "next": ["restart the hub"], "checks": [],
                "smokes": [{"setup": "embed", "run": "curl …", "ok": False, "log": "data/state/setup/logs/embed_smoke.log"}],
                "failed": [
                    {"setup": "tts-kokoro", "step": "tts-kokoro/3", "run": "scripts/install-runtime.sh", "output": "", "doc": "services/tts/setup/kokoro.md",
                     "source": "services/tts/setup/kokoro.md:4", "cwd": "services/tts", "exit": 1, "env": {"AIHUB_ACCEL": "cuda", "AIHUB_DEVICE": "cuda"},
                     "log": "data/state/setup/logs/tts-kokoro_3.log"},
                    {"setup": "embed", "step": "smoke", "run": "curl …", "output": "", "doc": "services/embed/setup/embed.md", "exit": 7,
                     "log": "data/state/setup/logs/embed_smoke.log", "cwd": "services/embed"}]}}}
    (tmp_path / "data" / "state" / "setup" / "last-run.json").write_text(json.dumps(last))
    yield tmp_path
    monkeypatch.delenv("AIHUB_HARDWARE_FIXTURE")
    hardware.detect(refresh=True)


def args(action="write", text=None, **kw) -> argparse.Namespace:
    base = dict(action=action, text=text, cmd=None, output=None, setup=None, severity="major", tried=None, out=None)
    return argparse.Namespace(**{**base, **kw})


def test_a_full_report(field, capsys):
    out = field / "error.txt"
    out.write_text("Traceback …\nlibcudnn_ops.so.9: cannot open shared object file: No such file or directory\n")
    assert cli_report.cmd_report(args("note", "stt fell back to the CPU", cmd="aihub check stt", output=str(out),
                                      setup="stt", severity="blocker", tried="reinstalled the cuDNN wheel")) == 0
    assert cli_report.cmd_report(args()) == 0
    md_path = next((field / "data" / "state" / "reports").glob("*.md"))
    md = md_path.read_text()
    for heading in ("# AIHub field report", "## Summary", "## Machine", "## AIHub", "## Host checks", "## The setup run",
                    "## Issues", "## Mods", "## For the fixer"):
        assert heading in md, heading
    assert "NVIDIA GeForce RTX 4090 (`sm_89`)" in md and "accels `cuda, vulkan, cpu`" in md
    assert "3 (2 blocker, 1 major, 0 minor)" in md                                  # the step, the note, the smoke
    assert "`tts-kokoro`: CUDA (untested on this kind of machine)" in md and "`gen3d`: not available: it needs ROCm" in md
    issue = md[md.index("ISSUE-1 [blocker]") if "### ISSUE-1 [blocker]: tts-kokoro" in md else md.index("tts-kokoro: tts-kokoro/3"):]
    assert "**Source:** `services/tts/setup/kokoro.md:4`" in md and "**Exit code:** `1`" in md
    assert "No matching distribution found for torch==2.9.1+cu130" in md and "has no build for this platform" in md
    assert "`AIHUB_ACCEL=cuda`" in md and "**Files to look at:** `services/tts/setup/kokoro.md`, `services/tts/scripts/install-runtime.sh`" in md
    assert "stt fell back to the CPU" in md and "a shared library is missing" in md and "**Tried:** reinstalled the cuDNN wheel" in md
    assert "a download failed" in md                                                    # the smoke's curl
    assert "the hub wasn't answering" in md
    assert "hf_abcdefghijklmnopqrstuvwx" not in md and "HF_TOKEN=<redacted>" in md      # redacted
    assert str(Path.home()) not in md
    snap = md_path.with_suffix(".hardware.json")
    assert hardware.from_snapshot(json.loads(snap.read_text())).accels                    # the recording replays
    data = json.loads(md_path.with_suffix(".json").read_text())
    assert [i["id"] for i in data["issues"]] == ["ISSUE-1", "ISSUE-2", "ISSUE-3"]


def test_notes_and_clear(field, capsys):
    cli_report.cmd_report(args("note", "a"))
    cli_report.cmd_report(args("note", "b", severity="minor"))
    assert [n["text"] for n in cli_report.notes(field)] == ["a", "b"]
    assert cli_report.cmd_report(args("note")) == 2                                     # nothing to note
    cli_report.cmd_report(args("clear"))
    assert cli_report.notes(field) == [] and list((field / "data/state/reports").glob("notes-*.jsonl"))


@pytest.mark.parametrize("text, hint", [
    ("CUDA driver version is insufficient for CUDA runtime version", "cuda-driver"),
    ("RuntimeError: HIP error: hipErrorNoBinaryForGpu", "rocm-arch"),
    ("build-llama-cpp.sh: needs the CUDA toolkit's nvcc", "cuda-toolkit"),
    ("Error: setting up CDI devices: unresolvable CDI devices nvidia.com/gpu=all", "container-gpu"),
    ("ImportError: libze_loader.so.1: cannot open shared object file", "missing-lib"),
    ("NotImplementedError: The operator 'aten::x' is not currently implemented for the MPS device", "mps-op"),
    ("torch.OutOfMemoryError: CUDA out of memory", "oom"),
    ("System has not been booted with systemd as init system", "no-systemd"),
    ("open /dev/kfd: Permission denied", "permission-gpu"),
    ("OSError: [Errno 98] Address already in use", "port"),
    ("curl: (6) Could not resolve host: github.com", "network"),
    ("401 Client Error: Unauthorized for url", "gated"),
    ("bash: cmake: command not found", "missing-command"),
    ("error: externally-managed-environment", "pip-system"),
    ("fatal: reference is not a tree: 93810483", "git"),
])
def test_hints(text, hint):
    assert hint in [h.id for h in report_hints.hints(text)]


def test_redaction():
    text = ("token hf_ABCDEFGHIJKLMNOPQRSTUVWX and sk-proj-abcdefghijklmnopqrstuv, OPENAI_API_KEY=abc123, "
            "Authorization: Bearer xyz, /home/someone/AIHub and /home/someone")
    out = report_hints.redact(text, "/home/someone")
    assert "hf_ABC" not in out and "sk-proj" not in out and "abc123" not in out and "xyz" not in out
    assert "OPENAI_API_KEY=<redacted>" in out and "~/AIHub" in out and out.endswith("~")


def test_render_is_stable():
    data = {"written": "2026-10-22", "host": "box", "machine": {"error": "no"}, "aihub": {}, "host_checks": [],
            "last_run": None, "issues": [], "mods": [], "hub": {"error": "down"}, "setup_logs": []}
    assert report_md.render(data) == report_md.render(json.loads(json.dumps(data)))
    assert "No run recorded" in report_md.render(data) and "None recorded." in report_md.render(data)
