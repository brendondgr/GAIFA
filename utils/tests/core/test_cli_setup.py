"""`aihub setup` (plan 23.9): one process for a person and an agent. Fake mods with setup docs, a
fake runner that records commands instead of running them, a fake host."""

from __future__ import annotations

import json
from argparse import Namespace
from pathlib import Path
from typing import Any

import pytest

from utils import cli, cli_setup, cli_setup_host, hardware


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

    def run(self, cmd: str, cwd: Path, env: dict | None = None, stream: bool = True, echo: bool = False, log: Path | None = None) -> tuple[int, str]:
        self.ran.append((cmd, cwd.name, env))
        if cmd == "bin/aihub install":
            self.up = True
        out = f"{cmd}: boom" if cmd in self.fail else ""
        if log is not None:                    # plan 40.1: the whole output goes to the step's log
            log.parent.mkdir(parents=True, exist_ok=True)
            log.write_text(f"$ {cmd}\n{out}\n")
        return (1, out) if cmd in self.fail else (0, "")

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
    def machine(self):   # this machine's recording (plan 37.3), so the checks don't depend on where tests run
        return hardware.from_snapshot(json.loads((Path(__file__).resolve().parents[1] / "hardware" / "fixtures" / "strix-halo.json").read_text()))


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
    base = dict(targets=list(targets), plan=False, json=True, yes=False, answers=None, accept=None, decline=None, done=None, models=None, set=None, from_scratch=False, accel=None, smoke=False)
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
    assert r["checks"] == [{"setup": "tts-kokoro", "run": "aihub check tts", "ok": True, "log": "data/state/setup/logs/tts-kokoro_check.log"}]
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


# ---- values asked after install (plan 23.12) --------------------------------------------------

from utils import cli_setup_config  # noqa: E402

AGENT_CFG = '''[[config]]
key = "services.agent.env.AGENT_MODEL"
text = "Which model should Chat use?"
required = true
restart = "agent"

[[config]]
key = "agent.judge.model"
text = "Which model should judge Auto mode?"
restart = "hub"'''


class RelayRunner(FakeRunner):
    """A relay with `models`, and a hub that remembers what's saved through it (env, judge) and
    writes it to config.toml, as the real one does."""

    def __init__(self, models: list[str], **kw: Any) -> None:
        super().__init__(**kw)
        self.models = models
        self.env: dict[str, dict[str, str]] = {}
        self.judge: str | None = None

    def call(self, method: str, path: str, body: Any = None) -> Any:
        if path in self.refuse:
            raise cli.ApiError(500, "the hub said no", "hub_error")
        if path == "/api/s/relay/v1/models":
            self.calls.append((method, path, body))
            return {"data": [{"id": m} for m in self.models]}
        if method == "PUT" and path.endswith("/config"):
            self.calls.append((method, path, body))
            mod = path.split("/")[3]
            self.env[mod] = dict(body["env"])
            for var, v in body["env"].items():
                cli_setup_config.set_value(cli.ROOT / "config.toml", f"services.{mod}.env.{var}", v)
            return {}
        if method == "PUT" and path == "/api/settings":
            self.calls.append((method, path, body))
            self.judge = body["judge"]["model"]
            cli_setup_config.set_value(cli.ROOT / "config.toml", "agent.judge.model", self.judge)
            return {}
        if method == "GET" and path == "/api/settings":
            return {"judge": {"model": self.judge}}
        if method == "GET" and path.startswith("/api/services/"):
            self.calls.append((method, path, body))
            return {"jobs": [], "config": {"env": self.env.get(path.split("/")[3], {})}}
        return super().call(method, path, body)


@pytest.fixture
def agent_root(root: Path) -> Path:
    doc = root / "services" / "agent" / "setup" / "env.md"
    doc.write_text(AGENT.replace('what = "the venv"', 'what = "the venv"\n\n' + AGENT_CFG))
    return root


def test_a_required_value_stops_with_the_relays_models(agent_root: Path, capsys) -> None:
    runner = RelayRunner(["gpt-4o", "qwen3-8b"])
    assert cli_setup.cmd_setup(args("agent", yes=True), runner, FakeProbe()) == 2
    r = out(capsys)
    assert r["kind"] == "value" and r["id"] == "agent/config:services.agent.env.AGENT_MODEL" and r["choices"] == ["gpt-4o", "qwen3-8b"]
    assert r["report"]["done"] == ["relay/1", "agent/1"]                # install first: the choices exist only then


def test_set_writes_config_and_restarts(agent_root: Path, capsys) -> None:
    runner = RelayRunner(["gpt-4o", "qwen3-8b"])
    a = args("agent", yes=True, set=["services.agent.env.AGENT_MODEL=qwen3-8b"])
    assert cli_setup.cmd_setup(a, runner, FakeProbe()) == 0
    r = out(capsys)
    assert ("PUT", "/api/services/agent/config", {"env": {"AGENT_MODEL": "qwen3-8b"}}) in runner.calls   # through the hub: applied at once
    assert 'AGENT_MODEL = "qwen3-8b"' in (agent_root / "config.toml").read_text()                     # written by the hub
    assert any(c == "aihub restart agent" for c, _, _ in runner.ran)
    assert "agent/config:services.agent.env.AGENT_MODEL = qwen3-8b" in r["done"]
    assert any("agent.judge.model" in n for n in r["next"])            # optional, left for later
    assert {"setup": "agent", "run": "services.agent.env.AGENT_MODEL on the relay", "ok": True} in r["checks"]


def test_a_value_the_relay_doesnt_serve_is_refused(agent_root: Path, capsys) -> None:
    a = args("agent", yes=True, set=["services.agent.env.AGENT_MODEL=skynet"])
    assert cli_setup.cmd_setup(a, RelayRunner(["gpt-4o"]), FakeProbe()) == 1
    r = out(capsys)
    assert r["reason"] == "unknown-value" and r["choices"] == ["gpt-4o"]


def test_a_hosted_provider_is_added_first(agent_root: Path, tmp_path: Path, capsys) -> None:
    f = tmp_path / "a.json"
    f.write_text(json.dumps({"yes": True, "providers": [{"name": "openai", "base_url": "https://api.openai.com/v1", "key": "sk-test", "models": ["gpt-4o"]}],
                             "values": {"services.agent.env.AGENT_MODEL": "gpt-4o"}}))
    runner = RelayRunner(["gpt-4o"])
    assert cli_setup.cmd_setup(args("agent", answers=str(f)), runner, FakeProbe()) == 0
    body = next(b for m, p, b in runner.calls if p == "/api/s/relay/admin/endpoints")
    assert body == {"name": "openai", "base_url": "https://api.openai.com/v1", "protocol": "openai", "available_models": ["gpt-4o"], "upstream_key": "sk-test"}
    assert "relay: provider openai" in out(capsys)["done"]


def test_the_check_fails_when_the_model_is_gone(agent_root: Path, capsys) -> None:
    a = args("agent", yes=True, set=["services.agent.env.AGENT_MODEL=gpt-4o"])
    assert cli_setup.cmd_setup(a, RelayRunner(["gpt-4o"]), FakeProbe()) == 0
    capsys.readouterr()
    gone = RelayRunner([])
    gone.env["agent"] = {"AGENT_MODEL": "gpt-4o"}
    cli_setup_config.verify([e for e in cli_setup.resolve(["agent"], cli_setup.choices(agent_root)[0], agent_root)], agent_root, gone, report := {"checks": [], "failed": []})
    assert report["failed"][0]["step"] == "config:services.agent.env.AGENT_MODEL"


def test_set_value_edits_in_place_and_refuses_what_it_cant(tmp_path: Path) -> None:
    f = tmp_path / "config.toml"
    f.write_text('# mine\n[services.agent.env]\nAGENT_MODEL = "old"   # a comment\nOTHER = "x"\n\n[hub]\nport = 7000\n')
    cli_setup_config.set_value(f, "services.agent.env.AGENT_MODEL", "new")
    assert f.read_text() == '# mine\n[services.agent.env]\nAGENT_MODEL = "new"\nOTHER = "x"\n\n[hub]\nport = 7000\n'
    cli_setup_config.set_value(f, "agent.judge.model", "gemma")
    assert f.read_text().endswith('[agent.judge]\nmodel = "gemma"\n')
    g = tmp_path / "inline.toml"
    g.write_text('[services.agent]\nenv = { AGENT_MODEL = "a" }\n')
    with pytest.raises(cli_setup.Stop) as x:
        cli_setup_config.set_value(g, "services.agent.env.AGENT_MODEL", "b")
    assert "set it by hand" in x.value.data["output"] and g.read_text() == '[services.agent]\nenv = { AGENT_MODEL = "a" }\n'


# ---- the second review's fixes (plan 23.14) ---------------------------------------------------


def test_providers_start_the_relay_first(agent_root: Path, tmp_path: Path, capsys) -> None:
    f = tmp_path / "a.json"
    f.write_text(json.dumps({"yes": True, "providers": [{"name": "or", "base_url": "https://openrouter.ai/api/v1", "key": "k", "models": ["m"]}],
                             "values": {"services.agent.env.AGENT_MODEL": "m"}}))
    runner = RelayRunner(["m"])
    assert cli_setup.cmd_setup(args("agent", answers=str(f)), runner, FakeProbe()) == 0
    paths = [p for _, p, _ in runner.calls]
    assert paths.index("/api/s/relay/v1/models") < paths.index("/api/s/relay/admin/endpoints")


def test_not_chat_models_are_left_out(agent_root: Path, capsys) -> None:
    assert cli_setup.cmd_setup(args("agent", yes=True), RelayRunner(["agent", "auto", "gpt-4o"]), FakeProbe()) == 2
    assert out(capsys)["choices"] == ["gpt-4o"]
    assert cli_setup.cmd_setup(args("agent", yes=True), RelayRunner(["auto"]), FakeProbe()) == 2
    r = out(capsys)
    assert r["choices"] == [] and "serves no chat model yet" in r["answer_with"]


def test_a_route_download_waits_for_its_job_to_appear(root: Path, capsys) -> None:
    jobs = [[], [], [], [], [{"id": "j1", "state": "running"}], [{"id": "j1", "state": "done"}], [], []]
    runner = FakeRunner(jobs=jobs)
    a = args("tts", yes=True, accept=["tts-kokoro/2"], models=["tts-kokoro=Whisper"])
    assert cli_setup.cmd_setup(a, runner, FakeProbe()) == 0
    polls = [p for m, p, _ in runner.calls if m == "GET" and p == "/api/services/tts"]
    assert len(polls) >= 6                                            # not done at the first quiet polls


SHARED = block("comfyui", "ComfyUI", summary='"Images"', gpu="true", disk_gb="4",
               _tables='[[suggest]]\nname = "Qwen encoder and VAE"\nrepo = "Comfy-Org/Qwen-Image-2.1"\ndest = "comfyui"\nfiles = ["text_encoders/enc.safetensors", "vae/vae.safetensors"]\n'
                       'kind = "text-encoder"\nsize_gb = 18\ngood_for = "x"\nnext = "update ComfyUI first (its doc)"')


def test_files_in_a_shared_folder_register_one_by_one(root: Path, capsys) -> None:
    d = root / "services" / "comfy" / "setup"
    d.mkdir(parents=True)
    (d.parent / "service.toml").write_text('id = "comfy"\n')
    (d / "comfyui.md").write_text(SHARED)
    runner = FakeRunner()
    assert cli_setup.cmd_setup(args("comfyui", yes=True, models=["comfyui=Qwen encoder and VAE"]), runner, FakeProbe()) == 0
    regs = [b for m, p, b in runner.calls if p == "/api/models"]
    assert [b["path"] for b in regs] == ["comfyui/text_encoders/enc.safetensors", "comfyui/vae/vae.safetensors"]
    assert regs[0]["name"] == "Qwen encoder and VAE: enc.safetensors"
    assert "comfyui: Qwen encoder and VAE: update ComfyUI first (its doc)" in out(capsys)["next"]


def test_skip_if_and_optional_steps(root: Path, capsys) -> None:
    doc = root / "services" / "relay" / "setup" / "env.md"
    doc.write_text(RELAY.replace('what = "the backend venv"', 'what = "the backend venv"\n\n'
                                 '[[steps]]\nrun = "opencode auth login"\nwhat = "log in"\ninteractive = true\nskip_if = "test -f ~/.auth"\n\n'
                                 '[[steps]]\nrun = "install-nodes"\nwhat = "the custom nodes"\nask = "Install third-party nodes?"\noptional = true\n\n'
                                 '[[steps]]\nrun = "after-nodes"\nwhat = "the rest"'))
    runner = FakeRunner()                                             # every command exits 0, so skip_if says: nothing to do
    assert cli_setup.cmd_setup(args("relay", yes=True, decline=["relay/3"]), runner, FakeProbe()) == 0
    r = out(capsys)
    ran = [c for c, _, _ in runner.ran]
    assert "opencode auth login" not in ran and "install-nodes" not in ran and "after-nodes" in ran
    assert "relay/2: nothing to do (test -f ~/.auth)" in r["skipped"] and "relay/3: declined (optional)" in r["skipped"]


def test_a_resumed_run_keeps_the_answers(root: Path, capsys) -> None:
    a = args("tts", yes=True, accept=["tts-kokoro/2"], models=["tts-kokoro=none"])
    assert cli_setup.cmd_setup(a, FakeRunner(fail={"aihub check tts"}), FakeProbe()) == 1
    capsys.readouterr()
    assert cli_setup.cmd_setup(args("tts", yes=True), FakeRunner(), FakeProbe()) == 0   # no licence or model question again
    assert out(capsys)["failed"] == []


def test_a_folder_value(root: Path, tmp_path: Path, capsys) -> None:
    doc = root / "services" / "relay" / "setup" / "env.md"
    doc.write_text(RELAY.replace('what = "the backend venv"', 'what = "the backend venv"\n\n[[config]]\nkey = "services.opencode.env.OPENCODE_PROJECT_DIR"\ntext = "Which folder?"\nchoices = "folder"\nrequired = true'))
    inside = str(root / "services")
    assert cli_setup.cmd_setup(args("relay", yes=True, set=[f"services.opencode.env.OPENCODE_PROJECT_DIR={inside}"]), RelayRunner([]), FakeProbe()) == 1
    assert out(capsys)["reason"] == "unknown-value"
    outside = tmp_path.parent / f"{tmp_path.name}-project"
    runner = RelayRunner([])
    assert cli_setup.cmd_setup(args("relay", yes=True, set=[f"services.opencode.env.OPENCODE_PROJECT_DIR={outside}"]), runner, FakeProbe()) == 0
    assert outside.is_dir() and runner.env["opencode"] == {"OPENCODE_PROJECT_DIR": str(outside.resolve())}


def test_start_op_runs_after_the_download(root: Path, capsys) -> None:
    doc = root / "services" / "tts" / "setup" / "env.md"
    doc.write_text(TTS.replace('body = { preset = "small" }', 'body = { preset = "small" }\nstart_op = "POST /api/instances"\nstart_body = { model_id = "w" }'))
    runner = FakeRunner()
    assert cli_setup.cmd_setup(args("tts", yes=True, accept=["tts-kokoro/2"], models=["tts-kokoro=Whisper"]), runner, FakeProbe()) == 0
    posts = [(p, b) for m, p, b in runner.calls if m == "POST"]
    assert posts.index(("/api/s/tts/v1/load", {"preset": "small"})) < posts.index(("/api/s/tts/api/instances", {"model_id": "w"}))


def test_host_labels(root: Path) -> None:
    found = {c.id: c for c in cli_setup_host.checks(FakeProbe(have=("uv", "git")), root, {"ffmpeg", "blender"})}
    assert found["needs:ffmpeg"].needs_root and found["needs:ffmpeg"].fix.startswith("sudo dnf install ffmpeg")
    assert not found["needs:blender"].needs_root and "blender.org" in found["needs:blender"].fix
    assert "clone-under-home" in found and "clone-under-home" in cli_setup_host.ADVICE


def test_output_streams_to_stderr_under_json(tmp_path: Path, capsys) -> None:
    cli_setup.run_mod.cli = cli
    rc, tail = cli_setup.Runner().run("echo hello; echo there >&2", tmp_path, stream=False, echo=True)
    assert rc == 0 and tail == "hello\nthere\n" and "    hello" in capsys.readouterr().err


def test_a_mod_id_means_all_its_setups_even_when_one_shares_its_id(root: Path) -> None:
    d = root / "services" / "gen3d" / "setup"
    d.mkdir(parents=True)
    (d.parent / "service.toml").write_text('id = "gen3d"\n')
    (d / "gen3d.md").write_text(block("gen3d", "Base", summary='"3D base"', gpu="true"))
    (d / "cube.md").write_text(block("gen3d-cube", "Cube", summary='"3D engine"', gpu="true", after='["gen3d"]'))
    offered, _ = cli_setup.choices(root)
    assert [e.id for e in cli_setup.resolve(["gen3d"], offered, root)] == ["gen3d", "gen3d-cube"]
    assert [e.id for e in cli_setup.resolve(["gen3d-cube"], offered, root)] == ["gen3d", "gen3d-cube"]   # after: the base only


# ---- the third review (plan 23.14) ----------------------------------------------------------------

def test_a_value_the_hub_wont_take_goes_into_the_file_and_a_rerun_applies_it(agent_root: Path, capsys) -> None:
    a = args("agent", yes=True, set=["services.agent.env.AGENT_MODEL=qwen3-8b"])
    refusing = RelayRunner(["qwen3-8b"], refuse={"/api/services/agent/config"})
    assert cli_setup.cmd_setup(a, refusing, FakeProbe()) == 0
    capsys.readouterr()
    assert '[services.agent.env]\nAGENT_MODEL = "qwen3-8b"' in (agent_root / "config.toml").read_text()
    ran = [c for c, _, _ in refusing.ran]
    assert ran.index("aihub restart") < ran.index("aihub restart agent")   # the hub reads the file, then the mod restarts with it
    down = RelayRunner(["qwen3-8b"], refuse={"/api/services/agent/config"})
    down.up = False
    cli_setup_config.phase(cli_setup.resolve(["agent"], cli_setup.choices(agent_root)[0], agent_root), a, cli_setup.run_mod.read_answers(a),
                           agent_root, down, report := {"done": [], "skipped": [], "next": []}, {})
    assert any("while the hub is down" in n for n in report["next"]) and "aihub restart agent" not in [c for c, _, _ in down.ran]
    again = RelayRunner(["qwen3-8b"])
    assert cli_setup.cmd_setup(a, again, FakeProbe()) == 0                # not "already set": the hub runs without it
    assert again.env["agent"] == {"AGENT_MODEL": "qwen3-8b"}


def test_a_skipped_optional_value_isnt_verified(agent_root: Path, capsys) -> None:
    runner = RelayRunner(["m"])
    runner.judge = "minicpm-5-2B"                                     # the code's default, not on the relay
    assert cli_setup.cmd_setup(args("agent", yes=True, set=["services.agent.env.AGENT_MODEL=m"]), runner, FakeProbe()) == 0
    assert out(capsys)["failed"] == []

def test_the_whole_env_table_is_sent_and_every_restart_runs_in_order(agent_root: Path, capsys) -> None:
    (agent_root / "config.toml").write_text('[services.agent.env]\nAGENT_FALLBACK_MODEL = "m2"\n')
    doc = agent_root / "services" / "agent" / "setup" / "env.md"
    doc.write_text(doc.read_text().replace('restart = "agent"', 'restart = "agent relay"'))
    runner = RelayRunner(["m1", "m2"])
    assert cli_setup.cmd_setup(args("agent", yes=True, set=["services.agent.env.AGENT_MODEL=m1"]), runner, FakeProbe()) == 0
    capsys.readouterr()
    assert runner.env["agent"] == {"AGENT_FALLBACK_MODEL": "m2", "AGENT_MODEL": "m1"}   # the route replaces the table
    ran = [c for c, _, _ in runner.ran]
    assert ran.index("aihub restart agent") < ran.index("aihub restart relay")
    failing = RelayRunner(["m1"], fail={"aihub restart agent"})
    assert cli_setup.cmd_setup(args("agent", yes=True, set=["services.agent.env.AGENT_MODEL=m1"], from_scratch=True), failing, FakeProbe()) == 1
    assert "restarting agent" in out(capsys)["report"]["failed"][0]["output"]


class LateRelay(RelayRunner):
    """A model that registers on the relay only after a few looks (lcpp's instance loading)."""

    def __init__(self, after: int, **kw: Any) -> None:
        super().__init__([], **kw)
        self.after = after

    def call(self, method: str, path: str, body: Any = None) -> Any:
        if path == "/api/s/relay/v1/models":
            self.after -= 1
            self.models = ["qwen3-8b"] if self.after < 0 else []
        return super().call(method, path, body)


def test_the_relays_models_are_waited_for(agent_root: Path, capsys) -> None:
    runner = LateRelay(after=3)
    assert cli_setup.cmd_setup(args("agent", yes=True, set=["services.agent.env.AGENT_MODEL=qwen3-8b"]), runner, FakeProbe()) == 0
    assert runner.env["agent"] == {"AGENT_MODEL": "qwen3-8b"} and "waiting for the relay" in capsys.readouterr().err
    assert cli_setup.cmd_setup(args("agent", yes=True, from_scratch=True), LateRelay(after=3), FakeProbe()) == 2
    assert out(capsys)["choices"] == ["qwen3-8b"]                     # the question lists it once it's there


def test_the_relay_starts_before_the_models(agent_root: Path, capsys) -> None:
    runner = RelayRunner(["m"])
    assert cli_setup.cmd_setup(args("agent", yes=True, set=["services.agent.env.AGENT_MODEL=m"]), runner, FakeProbe()) == 0
    ran = [c for c, _, _ in runner.ran]
    assert ran.index("aihub install agent") < ran.index("aihub start relay")


def test_rejoin_puts_back_names_with_commas() -> None:
    known = {"Gemma 4 (Q8_0, with vision)", "Qwen3 8B"}
    assert cli_setup.run_mod.rejoin(["Gemma 4 (Q8_0", " with vision)".strip(), "Qwen3 8B"], known) == ["Gemma 4 (Q8_0, with vision)", "Qwen3 8B"]
    assert cli_setup.run_mod.rejoin(["Other", "Qwen3 8B"], known) == ["Other", "Qwen3 8B"]     # another setup's name stays itself


def test_a_skipped_setups_questions_are_not_asked(root: Path, capsys) -> None:
    agent_doc = root / "services" / "agent" / "setup" / "env.md"
    agent_doc.write_text(AGENT.replace('after = ["relay"]', 'after = ["relay", "tts-kokoro"]')
                         .replace('what = "the venv"', 'what = "the venv"\nask = "Accept the agent\'s terms?"'))
    assert cli_setup.cmd_setup(args("relay", "tts", "agent", yes=True, decline=["tts-kokoro/2"]), FakeRunner(), FakeProbe()) == 0
    assert "agent: needs a declined setup" in out(capsys)["skipped"]


def test_a_steps_next_joins_the_report(root: Path, capsys) -> None:
    doc = root / "services" / "relay" / "setup" / "env.md"
    doc.write_text(RELAY.replace('what = "the backend venv"', 'what = "the backend venv"\nnext = "install the packages by hand"'))
    assert cli_setup.cmd_setup(args("relay", yes=True), FakeRunner(), FakeProbe()) == 0
    assert "relay/1: install the packages by hand" in out(capsys)["next"]


# ---- the fourth review (plan 23.14) ---------------------------------------------------------------

def test_a_suggestions_skip_if_registers_without_downloading(root: Path, capsys) -> None:
    doc = root / "services" / "tts" / "setup" / "env.md"
    doc.write_text(TTS.replace('required = true', 'required = true\nskip_if = "test -f weights"'))
    runner = FakeRunner()                                             # every command exits 0: it's there
    assert cli_setup.cmd_setup(args("tts", yes=True, accept=["tts-kokoro/2"], models=["tts-kokoro=Kokoro 82M"]), runner, FakeProbe()) == 0
    capsys.readouterr()
    assert not any("hf download" in c for c, _, _ in runner.ran)
    assert [b["path"] for m, p, b in runner.calls if p == "/api/models"] == ["hf-cache/hub/models--hexgrad--Kokoro-82M"]


class Downloading(FakeRunner):
    """A mod that refuses the download route because an earlier run's job is still going; the
    model is in its catalog (the skip_if passes) once `there_after` looks."""

    def __init__(self, there_after: int = 1, **kw: Any) -> None:
        super().__init__(**kw)
        self.looks = 0
        self.there_after = there_after

    def run(self, cmd: str, cwd: Path, env: dict | None = None, stream: bool = True, echo: bool = False, log: Path | None = None) -> tuple[int, str]:
        if cmd == "grep -q w catalog.json":
            self.ran.append((cmd, cwd.name, env))
            self.looks += 1
            return (0, "") if self.looks > self.there_after else (1, "")
        return super().run(cmd, cwd, env, stream, echo, log)

    def call(self, method: str, path: str, body: Any = None) -> Any:
        if method == "POST" and path == "/api/s/tts/v1/load":
            self.calls.append((method, path, body))
            raise cli.ApiError(409, '"w" is already being downloaded', "lcpp_error")
        return super().call(method, path, body)


def test_a_refused_route_waits_for_the_download_already_running(root: Path, capsys) -> None:
    doc = root / "services" / "tts" / "setup" / "env.md"
    doc.write_text(TTS.replace('body = { preset = "small" }', 'body = { preset = "small" }\nskip_if = "grep -q w catalog.json"'))
    jobs = [[{"id": "j0", "state": "running"}], [{"id": "j0", "state": "running"}], [{"id": "j0", "state": "running", "progress": 0.9}],
            [{"id": "j0", "state": "done"}], [], []]
    a = args("tts", yes=True, accept=["tts-kokoro/2"], models=["tts-kokoro=Whisper"])
    assert cli_setup.cmd_setup(a, Downloading(jobs=jobs), FakeProbe()) == 0
    assert "waiting for the download already running" in capsys.readouterr().err
    b = args("tts", yes=True, accept=["tts-kokoro/2"], models=["tts-kokoro=Whisper"], from_scratch=True)
    assert cli_setup.cmd_setup(b, Downloading(there_after=1), FakeProbe()) == 0    # nothing running, but it finished just before
    capsys.readouterr()
    assert cli_setup.cmd_setup(b, Downloading(there_after=99), FakeProbe()) == 1   # refused, and not there: a failed step
    assert "already being downloaded" in out(capsys)["report"]["failed"][0]["output"]


def test_a_failed_launch_resumes_without_downloading_again(root: Path, capsys) -> None:
    doc = root / "services" / "tts" / "setup" / "env.md"
    doc.write_text(TTS.replace('body = { preset = "small" }', 'body = { preset = "small" }\nstart_op = "POST /api/instances"\nstart_body = { model_id = "w" }'))
    a = args("tts", yes=True, accept=["tts-kokoro/2"], models=["tts-kokoro=Whisper"])
    assert cli_setup.cmd_setup(a, FakeRunner(refuse={"/api/s/tts/api/instances"}), FakeProbe()) == 1
    capsys.readouterr()
    again = FakeRunner()
    assert cli_setup.cmd_setup(args("tts", yes=True), again, FakeProbe()) == 0
    posts = [p for m, p, _ in again.calls if m == "POST"]
    assert "/api/s/tts/v1/load" not in posts and "/api/s/tts/api/instances" in posts


def test_the_command_line_wins_over_the_answers_file(tmp_path: Path) -> None:
    f = tmp_path / "a.json"
    f.write_text(json.dumps({"decline": ["x/1"], "accept": ["y/1"]}))
    a = cli_setup.run_mod.read_answers(args(answers=str(f), accept=["x/1"], decline=["y/1"]))
    assert a.accept == {"x/1"} and a.decline == {"y/1"}


def test_the_relays_models_are_asked_after_folders(agent_root: Path, tmp_path: Path, capsys) -> None:
    doc = agent_root / "services" / "relay" / "setup" / "env.md"
    doc.write_text(RELAY.replace('what = "the backend venv"', 'what = "the backend venv"\n\n[[config]]\nkey = "services.opencode.env.OPENCODE_PROJECT_DIR"\n'
                                 'text = "Which folder?"\nchoices = "folder"\nrequired = true\nrestart = "opencode relay"'))
    (agent_root / "config.toml").write_text('[services]\norder = ["agent", "relay"]\n')        # the agent's setup listed first
    folder = tmp_path.parent / f"{tmp_path.name}-work"
    runner = RelayRunner(["m"])
    a = args("agent", "relay", yes=True, set=[f"services.opencode.env.OPENCODE_PROJECT_DIR={folder}", "services.agent.env.AGENT_MODEL=m"])
    assert cli_setup.cmd_setup(a, runner, FakeProbe()) == 0
    done = out(capsys)["done"]
    assert done.index(f"relay/config:services.opencode.env.OPENCODE_PROJECT_DIR = {folder.resolve()}") < done.index("agent/config:services.agent.env.AGENT_MODEL = m")


def test_a_required_model_left_out_is_reported(root: Path, capsys) -> None:
    assert cli_setup.cmd_setup(args("tts", yes=True, accept=["tts-kokoro/2"], models=["tts-kokoro=Whisper"]), FakeRunner(), FakeProbe()) == 0
    assert any("Kokoro 82M not chosen" in n for n in out(capsys)["next"])


def test_the_plan_shows_a_folder_and_a_mods_setups(root: Path, capsys) -> None:
    doc = root / "services" / "relay" / "setup" / "env.md"
    doc.write_text(RELAY.replace('what = "the backend venv"', 'what = "the backend venv"\n\n[[config]]\nkey = "services.opencode.env.OPENCODE_PROJECT_DIR"\ntext = "Which folder?"\nchoices = "folder"'))
    d = root / "services" / "gen3d" / "setup"
    d.mkdir(parents=True)
    (d.parent / "service.toml").write_text('id = "gen3d"\n')
    (d / "gen3d.md").write_text(block("gen3d", "Base", summary='"3D base"', gpu="true"))
    (d / "cube.md").write_text(block("gen3d-cube", "Cube", summary='"3D engine"', gpu="true", after='["gen3d"]'))
    assert cli_setup.cmd_setup(args("relay", "gen3d", plan=True), FakeRunner(), FakeProbe()) == 0
    p = out(capsys)
    assert [q["choices"] for q in p["questions"] if q["kind"] == "value"] == ["folder"]
    assert p["expanded"] == {"gen3d": ["gen3d", "gen3d-cube"]}             # a mod id that's also a setup id says so


def test_a_hub_that_cant_be_restarted_leaves_a_next_item(agent_root: Path, capsys) -> None:
    runner = RelayRunner(["m"], refuse={"/api/services/agent/config"}, fail={"aihub restart"})   # `aihub serve`: no unit
    assert cli_setup.cmd_setup(args("agent", yes=True, set=["services.agent.env.AGENT_MODEL=m"]), runner, FakeProbe()) == 0
    assert any("restart the hub yourself, then agent" in n for n in out(capsys)["next"])
    assert "aihub restart agent" not in [c for c, _, _ in runner.ran]


def test_a_decide_judge_isnt_checked_against_the_relay(agent_root: Path, capsys) -> None:
    (agent_root / "config.toml").write_text('[agent.judge]\nbackend = "decide"\nmodel = "d3-lite"\n')
    runner = RelayRunner(["m"])
    runner.judge = "d3-lite"
    assert cli_setup.cmd_setup(args("agent", yes=True, set=["services.agent.env.AGENT_MODEL=m"]), runner, FakeProbe()) == 0
    assert out(capsys)["failed"] == []
