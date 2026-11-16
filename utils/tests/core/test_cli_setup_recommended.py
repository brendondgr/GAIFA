"""`gaifa setup` recommends (plan capability-enablement 8.1): the list opens with the set recommended for chat, pre-ticked
(Enter takes them), `--recommended` takes them without the list, the plan's JSON names them, and the report's `next`
lists recommended mods left out that aren't set up, with what a chat loses without each."""

from __future__ import annotations

from pathlib import Path

from utils import cli_setup, cli_setup_recommend as rec
from utils.tests.core.test_cli_setup import AGENT, FakeProbe, FakeRunner, args, block, out, root  # noqa: F401 (fixture)

WEB = block("web", "Web", summary='"Read pages"', gpu="false", disk_gb="0.1", check='"gaifa check web"', recommended="true",
            _tables='[[steps]]\nrun = "gaifa install web"\nwhat = "the venv"')
CAL = block("calendar", "Calendar", summary='"Events"', gpu="false", disk_gb="0.1", check='"gaifa check calendar"', recommended="true",
            _tables='[[steps]]\nrun = "gaifa install calendar"\nwhat = "the venv"')


def add(root: Path, mod: str, doc: str, provides: str, set_up: bool) -> None:
    d = root / "services" / mod / "setup"
    d.mkdir(parents=True)
    (d / "env.md").write_text(doc)
    (d.parent / "service.toml").write_text(f'id = "{mod}"\n[run]\ncommand = [".venv/bin/python", "-m", "{mod}"]\n'
                                           f'[agent]\nprovides = "{provides}"\n')
    if set_up:
        (d.parent / ".venv" / "bin").mkdir(parents=True)
        (d.parent / ".venv" / "bin" / "python").write_text("")


def agent_not_set_up(root: Path) -> None:
    (root / "services" / "agent" / "service.toml").write_text('id = "agent"\n[run]\ncommand = [".venv/bin/python", "-m", "agent"]\n')


def test_the_recommended_set(root: Path) -> None:
    add(root, "web", WEB, "read web pages", set_up=False)
    add(root, "calendar", CAL, "keep your calendar", set_up=True)
    offered, _ = cli_setup.choices(root)
    assert rec.recommended_mods(root, offered) == ["calendar", "web"]
    assert rec.for_chat(root, offered) == ["calendar", "web"]                  # the agent is set up (no command to look for)
    agent_not_set_up(root)
    assert rec.for_chat(root, offered) == ["agent", "calendar", "web"]         # required for a chat: taken too
    assert rec.is_set_up(root, "calendar") and not rec.is_set_up(root, "web")
    assert rec.left_out(root, {"relay"}, offered) == [{"mod": "web", "provides": "read web pages"}]
    assert rec.next_lines(rec.left_out(root, {"relay"}, offered)) == [
        "web: recommended for chat and not set up: without it, a chat can't read web pages (gaifa setup web)"]


def test_the_list_names_them_and_recommended_takes_them(root: Path, capsys) -> None:
    add(root, "web", WEB, "read web pages", set_up=False)
    add(root, "calendar", CAL, "keep your calendar", set_up=True)
    assert cli_setup.cmd_setup(args(), FakeRunner(), FakeProbe()) == 0
    c = out(capsys)
    assert c["stage"] == "choose" and c["recommended"] == ["calendar", "web"]
    assert {x["id"]: x["recommended"] for x in c["choices"]}["web"] is True and "--recommended" in c["answer_with"]
    assert cli_setup.cmd_setup(args(plan=True, recommended=True), FakeRunner(), FakeProbe()) == 0
    p = out(capsys)
    assert p["stage"] == "plan" and sorted(p["mods"]) == ["calendar", "web"] and p["recommended"] == ["calendar", "web"]
    assert p["recommended_left_out"] == []


def test_the_report_names_what_was_left_out(root: Path, capsys) -> None:
    add(root, "web", WEB, "read web pages", set_up=False)
    assert cli_setup.cmd_setup(args("relay", yes=True), FakeRunner(), FakeProbe()) == 0
    r = out(capsys)
    assert "web: recommended for chat and not set up: without it, a chat can't read web pages (gaifa setup web)" in r["next"]


def test_interactive_enter_takes_the_recommended(root: Path, monkeypatch, capsys) -> None:
    add(root, "web", WEB, "read web pages", set_up=False)
    agent_not_set_up(root)
    monkeypatch.setattr("builtins.input", lambda prompt="": "")
    monkeypatch.setattr(cli_setup.run_mod, "interactive", lambda a: True)
    a = args(json=False, plan=True)
    assert cli_setup.cmd_setup(a, FakeRunner(), FakeProbe()) == 0
    text = capsys.readouterr().out
    assert text.index("Recommended for chat (Enter takes them):") < text.index("The rest:")
    assert "[x] agent" in text and "[x] web" in text and "[ ] relay" in text
    assert "web" in text.split("Run it?")[0]


def test_an_agent_without_a_model_is_taken_again(root: Path) -> None:
    """The fresh-clone check: a run that stopped at the agent's model question left it installed; a resumed --recommended
    must take it again, not skip it as set up."""
    add(root, "web", WEB, "read web pages", set_up=False)
    agent_not_set_up(root)
    venv = root / "services" / "agent" / ".venv" / "bin"
    venv.mkdir(parents=True)
    (venv / "python").write_text("")
    offered, _ = cli_setup.choices(root)
    assert rec.is_set_up(root, "agent") and not rec.chat_ready(root) and rec.for_chat(root, offered)[0] == "agent"
    cfg = root / "config.toml"
    cfg.write_text(cfg.read_text() + '\n[services.agent.env]\nAGENT_MODEL = "auto"\n')
    assert rec.chat_ready(root) and "agent" not in rec.for_chat(root, offered)
