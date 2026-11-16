"""The CLI drives the gaifa systemd service only when it is this folder's (capability-enablement fresh-clone check,
2026-11-16: `gaifa stop all` in a clone beside the installed GAIFA stopped the installed hub)."""

from __future__ import annotations

from pathlib import Path

from utils import cli


def unit(d: Path, root: Path) -> None:
    d.mkdir(parents=True, exist_ok=True)
    (d / cli.UNIT).write_text(f"[Service]\nWorkingDirectory={root}\nExecStart={root}/.venv/bin/python {root}/app.py\n")


def test_only_this_folders_service_is_driven(tmp_path, monkeypatch, capsys):
    calls: list[tuple] = []
    monkeypatch.setattr(cli, "UNIT_DIR", tmp_path / "units")
    monkeypatch.setattr(cli, "systemctl", lambda *a, **k: calls.append(a) or 0)
    monkeypatch.setattr(cli, "services_or_none", lambda: [])
    here = tmp_path / "clone"
    monkeypatch.setattr(cli, "CODE", here)
    unit(tmp_path / "units", tmp_path / "installed")
    assert cli.unit_installed() and not cli.unit_is_ours() and cli.unit_root() == str(tmp_path / "installed")
    assert cli._lifecycle("stop", None) == 1 and calls == []
    assert "the gaifa service is the GAIFA in" in capsys.readouterr().err
    assert cli._lifecycle("stop", "all") == 0 and calls == []               # its mods only; the other hub is left running
    unit(tmp_path / "units", here)
    assert cli.unit_is_ours()
    cli._lifecycle("stop", "all")
    assert calls == [("stop", cli.UNIT)]
