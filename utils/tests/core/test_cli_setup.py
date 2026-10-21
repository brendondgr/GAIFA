"""`aihub setup` (plan 23.9): one process for a person and an agent. Fake mods with setup docs, a
fake runner that records commands instead of running them, a fake host."""

from __future__ import annotations

import json
from argparse import Namespace
from pathlib import Path
from typing import Any

import pytest

from utils import cli, cli_setup, cli_setup_host


def block(eid: str, title: str, **keys: str) -> str:
    extra = "\n".join(f"{k} = {v}" for k, v in keys.items() if not k.startswith("_"))
    tail = keys.get("_tables", "")
    return f'<!-- aihub-setup\nid = "{eid}"\ntitle = "{title}"\n{extra}\n{tail}\n-->\n\n# {title}\n'


RELAY = block("relay", "Relay", summary='"LLM routing"', gpu="false", disk_gb="0.2", check='"aihub check relay"',
              _tables='[[steps]]\nrun = "aihub install relay"\nwhat = "the backend venv"')
AGENT = block("agent", "Agent", summary='"Chat"', gpu="false", disk_gb="0.1", after='["relay"]', check='"aihub check agent"',
              _tables='[[steps]]\nrun = "aihub install agent"\nwhat = "the venv"')
TTS = block("tts-kokoro", "Kokoro", summary='"Speech"', gpu="true", disk_gb="14", needs='["espeak-ng"]', check='"aihub check tts"',
            _tables='[[steps]]\nrun = "aihub install tts"\nwhat = "the server venv"\n\n'
                    '[[steps]]\nrun = "scripts/install-runtime.sh --accept-breeze-license"\nwhat = "the engines"\nask = "Accept the licence?"\n\n'
                    '[[suggest]]\nname = "Kokoro 82M"\nrepo = "hexgrad/Kokoro-82M"\nrevision = "f3ff3571791e39611d31c381e3a41a3af07b4987"\ndest = "hf-cache"\nkind = "tts"\nsize_gb = 0.34\ngood_for = "voices"\nrequired = true\n\n'
                    '[[suggest]]\nname = "Whisper"\nop = "POST /v1/load"\nbody = { preset = "small" }\nsize_gb = 0.5\ngood_for = "transcripts"')
BARE = block("bare", "Bare")   # no summary: not offered


class FakeRunner(cli_setup.Runner):
    def __init__(self, fail: set[str] = frozenset(), up: bool = True, jobs: list[list[dict]] | None = None, refuse: set[str] = frozenset()) -> None:
        self.ran: list[tuple[str, str, dict | None]] = []
        self.calls: list[tuple[str, str, Any]] = []
        self.fail, self.up, self.refuse = set(fail), up, set(refuse)
        self.jobs = list(jobs or [])          # successive answers of GET /api/services/<mod>'s jobs

    def run(self, cmd: str, cwd: Path, env: dict | None = None, stream: bool = True) -> tuple[int, str]:
        self.ran.append((cmd, cwd.name, env))
        if cmd == "bin/aihub install":
            self.up = True
        return (1, f"{cmd}: boom") if cmd in self.fail else (0, "")

    def call(self, method: str, path: str, body: Any = None) -> Any:
        self.calls.append((method, path, body))
        if path in self.refuse:
            raise cli.ApiError(500, "the mod said no", "hub_error")
        if method == "GET" and path.startswith("/api/services/"):
            return {"jobs": self.jobs.pop(0) if self.jobs else []}
        return {}

    def sleep(self, s: float) -> None:
        pass

    def hub_up(self) -> bool:
        return self.up


class FakeProbe(cli_setup_host.Probe):
    def __init__(self, cmdline: str = "amdgpu.gttsize=131072 ttm.pages_limit=33554432", groups=("video", "render"), have=("uv", "git", "espeak-ng")) -> None:
        self._cmdline, self._groups, self._have = cmdline, set(groups), set(have)

    def cmdline(self) -> str: return self._cmdline
    def groups(self) -> set[str]: return self._groups
    def which(self, cmd: str) -> bool: return cmd in self._have
    def free_gb(self, path: Path) -> float: return 500.0
    def gtt_bytes(self) -> int: return 130_000_000_000
    def mem_bytes(self) -> int: return 130_000_000_000
    def linger(self) -> bool: return True


@pytest.fixture
def root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    for mod, text in (("relay", RELAY), ("agent", AGENT), ("tts", TTS), ("bare", BARE)):
        d = tmp_path / "services" / mod / "setup"
        d.mkdir(parents=True)
        (d.parent / "service.toml").write_text(f'id = "{mod}"\n')
        (d / "env.md").write_text(text)
    (tmp_path / ".venv" / "bin").mkdir(parents=True)
    (tmp_path / ".venv" / "bin" / "python").write_text("")
    (tmp_path / "config.toml").write_text('[services]\norder = ["relay", "tts", "agent"]\n')
    monkeypatch.setattr(cli, "ROOT", tmp_path)
    monkeypatch.setattr(cli, "CODE", tmp_path)
    cli_setup.cli = cli
    return tmp_path


def args(*targets: str, **kw: Any) -> Namespace:
    base = dict(targets=list(targets), plan=False, json=True, yes=False, answers=None, accept=None, decline=None, done=None, models=None, from_scratch=False)
    return Namespace(**{**base, **kw})


def out(capsys: pytest.CaptureFixture[str]) -> dict:
    return json.loads(capsys.readouterr().out)


def test_choices_list_only_docs_with_a_summary(root: Path, capsys) -> None:
    assert cli_setup.cmd_setup(args(), FakeRunner(), FakeProbe()) == 0
    assert sorted(c["id"] for c in out(capsys)["choices"]) == ["agent", "relay", "tts-kokoro"]


def test_resolve_adds_what_a_choice_needs_in_order(root: Path) -> None:
    offered, _ = cli_setup.choices(root)
    assert [e.id for e in cli_setup.resolve(["agent"], offered, root)] == ["relay", "agent"]
    assert [e.id for e in cli_setup.resolve(["agent", "tts"], offered, root)] == ["relay", "tts-kokoro", "agent"]   # config order, deps first
    with pytest.raises(cli_setup.Stop) as x:
        cli_setup.resolve(["nope"], offered, root)
    assert x.value.reason == "unknown" and "relay" in x.value.data["choices"]


def test_the_plan_as_json(root: Path, capsys) -> None:
    assert cli_setup.cmd_setup(args("agent", "tts", plan=True), FakeRunner(), FakeProbe()) == 0
    p = out(capsys)
    assert p["setups"] == ["relay", "tts-kokoro", "agent"] and p["gpu"] is True and p["disk_gb"] == 14.3
    assert [s["id"] for s in p["steps"]] == ["relay/1", "tts-kokoro/1", "tts-kokoro/2", "agent/1"]
    assert [q["id"] for q in p["questions"]] == ["tts-kokoro/2", "tts-kokoro/models"]
    assert p["questions"][0]["answer_with"] == "--accept tts-kokoro/2 or --decline tts-kokoro/2" and p["hub"] == []
    assert p["questions"][1]["required"] == ["Kokoro 82M"] and p["required_models_gb"] == 0.34
    assert p["blocking"] == [] and {c["id"] for c in p["host"]} >= {"kernel-gtt", "iommu-on", "needs:espeak-ng"}


def test_plan_text_for_a_person(root: Path, capsys) -> None:
    assert cli_setup.cmd_setup(args("agent", plan=True, json=False), FakeRunner(), FakeProbe()) == 0
    text = capsys.readouterr().out
    assert "relay/1" in text and "aihub install agent" in text


def test_root_fixes_are_printed_never_run(root: Path, capsys) -> None:
    runner = FakeRunner()
    probe = FakeProbe(cmdline="amd_iommu=off", groups=(), have=("uv", "git"))
    assert cli_setup.cmd_setup(args("tts", yes=True), runner, probe) == 1
    r = out(capsys)
    assert r["reason"] == "host"
    fixes = {c["id"]: c for c in r["checks"]}
    assert fixes["iommu-on"]["needs_root"] and "grubby" in fixes["iommu-on"]["fix"]
    assert fixes["needs:espeak-ng"]["fix"] == "sudo dnf install espeak-ng"
    assert runner.ran == []                                           # nothing ran, least of all sudo


def test_a_gpu_problem_blocks_only_gpu_mods(root: Path, capsys) -> None:
    probe = FakeProbe(cmdline="amd_iommu=off", groups=())
    assert cli_setup.cmd_setup(args("relay", yes=True), FakeRunner(), probe) == 0


def test_no_answer_stops_with_the_question(root: Path, capsys) -> None:
    assert cli_setup.cmd_setup(args("relay"), FakeRunner(), FakeProbe()) == 2
    assert out(capsys)["id"] == "plan"
    runner = FakeRunner()
    assert cli_setup.cmd_setup(args("tts", yes=True), runner, FakeProbe()) == 2
    assert out(capsys)["id"] == "tts-kokoro/2"                        # the licence question
    assert runner.ran == []                                           # asked before anything ran
    runner = FakeRunner()
    assert cli_setup.cmd_setup(args("tts", yes=True, accept=["tts-kokoro/2"]), runner, FakeProbe()) == 2
    assert out(capsys)["id"] == "tts-kokoro/models" and runner.ran == []   # the model choice, also first


def test_questions_come_before_the_hub_is_installed(root: Path, capsys) -> None:
    runner = FakeRunner(up=False)
    assert cli_setup.cmd_setup(args("tts", yes=True), runner, FakeProbe()) == 2
    assert runner.ran == []                                           # no `bin/aihub install` before the licence is answered


def test_a_full_run_with_answers(root: Path, capsys) -> None:
    runner = FakeRunner()
    a = args("tts", yes=True, accept=["tts-kokoro/2"], models=["tts-kokoro=Kokoro 82M,Whisper"])
    assert cli_setup.cmd_setup(a, runner, FakeProbe()) == 0
    r = out(capsys)
    assert r["failed"] == [] and r["done"] == ["tts-kokoro/1", "tts-kokoro/2", "tts-kokoro:Kokoro 82M", "tts-kokoro:Whisper"]
    assert r["hub"] == ["already installed and running"]
    cmds = [(c, cwd) for c, cwd, _ in runner.ran]
    assert ("aihub install tts", "tts") in cmds and ("scripts/install-runtime.sh --accept-breeze-license", "tts") in cmds
    dl = next((c, env) for c, _, env in runner.ran if c.startswith("uvx"))
    assert dl[0] == "uvx --from huggingface_hub hf download hexgrad/Kokoro-82M --revision f3ff3571791e39611d31c381e3a41a3af07b4987" and dl[1]["HF_HOME"].endswith("data/models/hf-cache")
    ref = root / "data/models/hf-cache/hub/models--hexgrad--Kokoro-82M/refs/main"
    assert ref.read_text() == "f3ff3571791e39611d31c381e3a41a3af07b4987"        # engines that load by main find it offline
    reg = next(b for m, p, b in runner.calls if p == "/api/models")
    assert reg["path"] == "hf-cache/hub/models--hexgrad--Kokoro-82M" and reg["kind"] == "tts" and reg["source"]["revision"].startswith("f3ff357")
    assert ("POST", "/api/s/tts/v1/load", {"preset": "small"}) in runner.calls and ("aihub start tts", "", None) in [(c, "" if c.startswith("aihub start") else cwd, e) for c, cwd, e in runner.ran]
    assert r["checks"] == [{"setup": "tts-kokoro", "run": "aihub check tts", "ok": True}]
    assert ("aihub check tts", "tts") in cmds or ("aihub check tts", "tts") in [(c, cwd) for c, cwd, _ in runner.ran]   # checks run in the mod's folder


def test_answers_file_and_none(root: Path, tmp_path: Path, capsys) -> None:
    f = tmp_path / "answers.json"
    f.write_text(json.dumps({"yes": True, "accept": ["tts-kokoro/2"], "models": {"tts": []}}))
    runner = FakeRunner()
    assert cli_setup.cmd_setup(args("tts", answers=str(f)), runner, FakeProbe()) == 0
    assert not any(c.startswith("uvx") for c, _, _ in runner.ran) and out(capsys)["failed"] == []


def test_unknown_model_name(root: Path, capsys) -> None:
    a = args("tts", yes=True, accept=["tts-kokoro/2"], models=["tts=Nope"])
    assert cli_setup.cmd_setup(a, FakeRunner(), FakeProbe()) == 1
    assert out(capsys)["reason"] == "unknown-model"


def test_a_failure_stops_and_a_rerun_resumes(root: Path, capsys) -> None:
    runner = FakeRunner(fail={"aihub install agent"})
    assert cli_setup.cmd_setup(args("agent", yes=True), runner, FakeProbe()) == 1
    r = out(capsys)
    assert r["reason"] == "failed" and r["report"]["failed"][0]["doc"] == "services/agent/setup/env.md"
    assert r["report"]["done"] == ["relay/1"]
    again = FakeRunner()
    assert cli_setup.cmd_setup(args("agent", yes=True), again, FakeProbe()) == 0
    r = out(capsys)
    assert r["skipped"] == ["relay/1: done in an earlier run"] and r["done"] == ["agent/1"]
    fresh = FakeRunner()
    assert cli_setup.cmd_setup(args("agent", yes=True, from_scratch=True), fresh, FakeProbe()) == 0
    assert out(capsys)["done"] == ["relay/1", "agent/1"]


def test_a_failed_check_is_reported_with_its_doc(root: Path, capsys) -> None:
    assert cli_setup.cmd_setup(args("relay", yes=True), FakeRunner(fail={"aihub check relay"}), FakeProbe()) == 1
    r = out(capsys)
    assert r["checks"][0]["ok"] is False and r["failed"][0]["doc"] == "services/relay/setup/env.md" and r["next"]


def test_the_hub_stage_from_a_bare_clone(root: Path, capsys) -> None:
    (root / ".venv" / "bin" / "python").unlink()
    runner = FakeRunner(up=False)
    assert cli_setup.cmd_setup(args("hub"), runner, FakeProbe()) == 0
    assert [c for c, _, _ in runner.ran] == ["uv sync", "bin/aihub install"]
    assert out(capsys)["done"] == ["uv sync", "aihub install"]


def test_the_host_stage(root: Path, capsys) -> None:
    assert cli_setup.cmd_setup(args("host"), FakeRunner(), FakeProbe(groups=("video",))) == 0   # GPU checks are advice here
    checks = {c["id"]: c for c in out(capsys)["host"]}
    assert checks["gpu-groups"]["ok"] is False and "usermod" in checks["gpu-groups"]["fix"]
    assert cli_setup.cmd_setup(args("host"), FakeRunner(), FakeProbe(have=("git",))) == 1        # uv missing blocks everything
    probe = FakeProbe()
    probe.gtt_bytes = lambda: 65_000_000_000                          # the default: half the memory
    assert {c.id: c for c in cli_setup_host.checks(probe, root)}["gtt-size"].ok is False


def test_opencode_installs_without_root(root: Path) -> None:
    found = {c.id: c for c in cli_setup_host.checks(FakeProbe(), root, {"opencode", "podman"})}
    assert found["needs:opencode"].needs_root is False and "opencode.ai/install" in found["needs:opencode"].fix
    assert found["needs:podman"].needs_root is True and found["needs:podman"].fix == "sudo dnf install podman"


def test_no_skips_that_setup_and_what_needs_it(root: Path, capsys) -> None:
    agent_doc = root / "services" / "agent" / "setup" / "env.md"
    agent_doc.write_text(AGENT.replace('after = ["relay"]', 'after = ["relay", "tts-kokoro"]'))
    runner = FakeRunner()
    assert cli_setup.cmd_setup(args("relay", "tts", "agent", yes=True, decline=["tts-kokoro/2"]), runner, FakeProbe()) == 0
    r = out(capsys)
    assert r["skipped"] == ["agent: needs a declined setup", "tts-kokoro: declined tts-kokoro/2"]
    assert r["done"] == ["relay/1"] and [c["setup"] for c in r["checks"]] == ["relay"]
    assert not any("tts" in c for c, _, _ in runner.ran)               # nothing of the declined setup ran


def test_an_interactive_step_is_handed_to_the_person(root: Path, capsys) -> None:
    doc = root / "services" / "relay" / "setup" / "env.md"
    doc.write_text(RELAY.replace('what = "the backend venv"', 'what = "the backend venv"\n\n[[steps]]\nrun = "opencode auth login"\nwhat = "log in"\ninteractive = true'))
    runner = FakeRunner()
    assert cli_setup.cmd_setup(args("relay", yes=True), runner, FakeProbe()) == 2
    r = out(capsys)
    assert r["reason"] == "interactive" and r["id"] == "relay/2" and r["run"] == "opencode auth login" and "--done relay/2" in r["answer_with"]
    assert [c for c, _, _ in runner.ran] == ["aihub install relay"]    # it ran up to that step
    again = FakeRunner()
    assert cli_setup.cmd_setup(args("relay", yes=True, done=["relay/2"]), again, FakeProbe()) == 0
    r = out(capsys)
    assert r["done"] == ["relay/2 (run by you)"] and "opencode auth login" not in [c for c, _, _ in again.ran]


def test_a_route_download_is_followed_until_its_job_ends(root: Path, capsys) -> None:
    jobs = [[{"id": "old", "state": "done"}],                         # before the call: ignored
            [{"id": "old", "state": "done"}, {"id": "j1", "state": "running", "progress": 0.5}],
            [{"id": "j1", "state": "done"}], []]
    runner = FakeRunner(jobs=jobs)
    a = args("tts", yes=True, accept=["tts-kokoro/2"], models=["tts-kokoro=Whisper"])
    assert cli_setup.cmd_setup(a, runner, FakeProbe()) == 0
    assert "running 50%" in capsys.readouterr().err                   # progress on stderr under --json


def test_a_failed_job_or_route_is_a_failed_step_with_its_doc(root: Path, capsys) -> None:
    a = args("tts", yes=True, accept=["tts-kokoro/2"], models=["tts-kokoro=Whisper"], from_scratch=True)
    assert cli_setup.cmd_setup(a, FakeRunner(jobs=[[], [{"id": "j2", "state": "failed", "error": "disk full"}]]), FakeProbe()) == 1
    r = out(capsys)
    f = r["report"]["failed"][0]
    assert f["step"] == "model:Whisper" and "disk full" in f["output"] and f["doc"] == "services/tts/setup/env.md"
    assert cli_setup.cmd_setup(a, FakeRunner(refuse={"/api/s/tts/v1/load"}), FakeProbe()) == 1
    assert "the mod said no" in out(capsys)["report"]["failed"][0]["output"]


def test_a_mods_model_answer_covers_each_of_its_setups(root: Path, capsys) -> None:
    breeze = root / "services" / "tts" / "setup" / "breeze.md"
    breeze.write_text(block("tts-breeze", "Breeze", summary='"Cloning"', gpu="true", disk_gb="7",
                            _tables='[[suggest]]\nname = "Breeze 2"\nrepo = "o/breeze"\ndest = "tts/breeze"\nsize_gb = 7\ngood_for = "x"'))
    runner = FakeRunner()
    a = args("tts", yes=True, accept=["tts-kokoro/2"], models=["tts=Kokoro 82M,Breeze 2"])
    assert cli_setup.cmd_setup(a, runner, FakeProbe()) == 0
    assert {c for c in out(capsys)["done"] if ":" in c} == {"tts-kokoro:Kokoro 82M", "tts-breeze:Breeze 2"}
    assert cli_setup.cmd_setup(args("tts", yes=True, accept=["tts-kokoro/2"], models=["tts=Nope"], from_scratch=True), FakeRunner(), FakeProbe()) == 1
    assert out(capsys)["reason"] == "unknown-model"


def test_the_plan_shows_the_hub_stage_expansion_and_shared_images(root: Path, capsys) -> None:
    (root / ".venv" / "bin" / "python").unlink()
    img = 'images = { "docker.io/x/rocm" = 15.0 }'
    (root / "services" / "tts" / "setup" / "env.md").write_text(TTS.replace('disk_gb = 14', f'disk_gb = 1\n{img}'))
    breeze = root / "services" / "tts" / "setup" / "breeze.md"
    breeze.write_text(block("tts-breeze", "Breeze", summary='"Cloning"', gpu="true", disk_gb="2", images='{ "docker.io/x/rocm" = 15.0 }'))
    assert cli_setup.cmd_setup(args("tts", plan=True), FakeRunner(up=False), FakeProbe()) == 0
    p = out(capsys)
    assert p["expanded"] == {"tts": ["tts-breeze", "tts-kokoro"]} and p["disk_gb"] == 18.0     # 1 + 2 + the image once
    assert p["hub"][0].startswith("uv sync") and p["hub"][1].startswith("aihub install")
