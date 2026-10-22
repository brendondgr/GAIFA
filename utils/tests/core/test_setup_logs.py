"""40.1: the setup keeps what it saw: every step's, check's and smoke's full log, where each failure comes
from (its setup doc's line), its command, folder, exit code and environment, and the last run's outcome."""

from __future__ import annotations

import json
from pathlib import Path

from utils import cli_setup, cli_setup_run
from utils.tests.core.test_cli_setup import FakeProbe, FakeRunner, args, out, root  # noqa: F401 (root is a fixture)


def test_a_failed_step_names_its_log_and_doc_line(root: Path, capsys) -> None:  # noqa: F811
    assert cli_setup.cmd_setup(args("agent", yes=True), FakeRunner(fail={"aihub install agent"}), FakeProbe()) == 1
    f = out(capsys)["report"]["failed"][0]
    doc = (root / "services" / "agent" / "setup" / "env.md").read_text().splitlines()
    line = int(f["source"].rsplit(":", 1)[1])
    assert f["source"].startswith("services/agent/setup/env.md:") and "aihub install agent" in doc[line - 1]
    assert (f["cwd"], f["exit"], f["run"]) == ("services/agent", 1, "aihub install agent")
    assert f["log"] == "data/state/setup/logs/agent_1.log" and "boom" in (root / f["log"]).read_text()
    assert (root / "data/state/setup/logs/relay_1.log").exists()            # the step before it, which worked


def test_a_failed_check_too(root: Path, capsys) -> None:  # noqa: F811
    assert cli_setup.cmd_setup(args("relay", yes=True), FakeRunner(fail={"aihub check relay"}), FakeProbe()) == 1
    f = out(capsys)["failed"][0]
    assert f["step"] == "check" and f["source"].endswith(":" + str(next(i for i, l in enumerate(
        (root / "services/relay/setup/env.md").read_text().splitlines(), 1) if "aihub check relay" in l)))
    assert f["log"] == "data/state/setup/logs/relay_check.log"


def test_the_last_run_is_saved(root: Path, capsys) -> None:  # noqa: F811
    assert cli_setup.cmd_setup(args("relay", yes=True), FakeRunner(fail={"aihub check relay"}), FakeProbe()) == 1
    capsys.readouterr()
    last = json.loads((root / "data/state/setup/last-run.json").read_text())
    assert last["machine"]["gpus"][0]["arch"] == "gfx1151" and last["targets"] == ["relay"]
    assert last["plan"]["setups"] == ["relay"] and last["result"]["stage"] == "report" and last["result"]["failed"]
    assert cli_setup.cmd_setup(args("relay", plan=True), FakeRunner(), FakeProbe()) == 0       # a plan isn't a run
    assert json.loads((root / "data/state/setup/last-run.json").read_text())["ts"] == last["ts"]


def test_the_real_runner_writes_the_whole_log(tmp_path: Path, monkeypatch) -> None:
    from utils import cli
    cli_setup_run.cli = cli
    log = tmp_path / "logs" / "x.log"
    rc, tail = cli_setup_run.Runner().run("echo one; echo two >&2; exit 3", tmp_path, stream=False, log=log)
    text = log.read_text()
    assert rc == 3 and "two" in tail and text.startswith("$ echo one") and "one\ntwo\n" in text and text.endswith("# exit 3\n")
    monkeypatch.setattr(cli_setup_run, "LOG_CAP", 10)
    cli_setup_run.Runner().run("yes | head -1000", tmp_path, stream=False, log=log)
    assert log.read_text().count("y\n") < 20 and "[the log stops here: 2 MB]" in log.read_text()
