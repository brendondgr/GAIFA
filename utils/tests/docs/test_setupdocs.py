"""Setup docs generated from the registry (plan 23.2): rendering, hand text, matching, references,
fetch commands, orphans, check mode and the CLI."""

from __future__ import annotations

import json
import subprocess
from argparse import Namespace
from pathlib import Path

import pytest

from utils import cli, setupdocs
from utils.setupdocs import envs, render

ENV_DOC = """<!-- gaifa-setup
id = "img"
title = "Image engine"
models = ["comfyui/**"]
scan = ["workflows/*/workflow.json"]
-->

# Image engine
"""


def entry(path: str, *, files: list[dict] | None = None, source: dict | None = None, **kw) -> dict:
    return {"name": kw.pop("name", path.rsplit("/", 1)[-1]), "kind": kw.pop("kind", "image"), "format": "safetensors",
            "path": path, "files": files if files is not None else [{"path": path, "role": "weights", "size_bytes": 2_500_000_000, "sha256": None}],
            "services": kw.pop("services", []), "source": source, "tags": [], "notes": kw.pop("notes", ""), **kw}


@pytest.fixture
def root(tmp_path: Path) -> Path:
    (tmp_path / "data" / "models").mkdir(parents=True)
    mod = tmp_path / "services" / "img"
    (mod / "setup").mkdir(parents=True)
    (mod / "service.toml").write_text('id = "img"\n[models]\ndirs = ["comfyui"]\n')
    (mod / "setup" / "img.md").write_text(ENV_DOC)
    (mod / "workflows" / "a").mkdir(parents=True)
    (mod / "workflows" / "a" / "workflow.json").write_text(json.dumps({"widgets_values": ["loras\\big.safetensors", "wan_vae.safetensors"]}))
    tpl = tmp_path / "services" / "_template" / "setup"
    tpl.mkdir(parents=True)
    (tpl.parent / "service.toml").write_text('id = "__ID__"\n')
    (tpl / "env.md").write_text(ENV_DOC.replace('"img"', '"__ID__"'))
    readme = tmp_path / "docs" / "setup" / "README.md"
    readme.parent.mkdir(parents=True)
    readme.write_text(f"# Setup\n\nHand text.\n\n{render.START}\nold\n{render.END}\n\nMore hand text.\n")
    write_registry(tmp_path, {
        "big": entry("comfyui/loras/big.safetensors", source={"type": "huggingface", "repo": "org/big", "revision": "main"}),
        "ae": entry("comfyui/vae/ae.safetensors"),
    })
    return tmp_path


def write_registry(root: Path, models: dict) -> None:
    (root / "data" / "models" / "registry.json").write_text(json.dumps({"version": 1, "models": models}))


INV = "data/state/setup/models"


def doc(root: Path, mid: str) -> str:
    return (root / INV / f"{mid}.md").read_text()


def test_writes_the_mods_index_and_the_local_inventory(root: Path) -> None:
    report = setupdocs.sync(root)
    assert sorted(report.written) == ["data/state/setup/models/README.md", "data/state/setup/models/ae.md", "data/state/setup/models/big.md", "docs/setup/README.md"]
    big = doc(root, "big")
    assert big.startswith(render.START + "\n# big.safetensors")
    assert "| Size | 2.5 GB in 1 file |" in big
    assert "| Used by | `img` |" in big
    assert "[Image engine](../../../../services/img/setup/img.md)" in big
    assert "[org/big](https://huggingface.co/org/big)" in big
    assert "[host.md](../../../../docs/setup/host.md#6-accounts-and-licences)" in big
    assert big.endswith(render.END + "\n\n" + render.HAND_WITH_SOURCE)
    assert doc(root, "ae").endswith(render.HAND_NO_SOURCE)            # no source: a "Where to get it" to fill in
    readme = (root / "docs" / "setup" / "README.md").read_text()
    assert readme.startswith("# Setup\n\nHand text.\n\n") and readme.endswith("\n\nMore hand text.\n")
    assert "| `img` | — | — | — | — | [Image engine](../../services/img/setup/img.md) |" in readme
    assert "big" not in readme                                        # the committed index names mods, never models
    inventory = (root / INV / "README.md").read_text()
    assert "[big.safetensors](big.md)" in inventory and "2 models, 5.0 GB in all." in inventory


def test_hand_text_is_kept_and_a_second_run_changes_nothing(root: Path) -> None:
    setupdocs.sync(root)
    path = root / INV / "big.md"
    path.write_text(path.read_text().replace("## What to look for\n", "## What to look for\n\nNeeds the fp8 fix.  \n"))
    write_registry(root, {"big": entry("comfyui/loras/big.safetensors", name="Big", source={"type": "huggingface", "repo": "org/big"})})
    setupdocs.sync(root)
    text = path.read_text()
    assert "# Big\n" in text and "Needs the fp8 fix.  \n" in text
    again = setupdocs.sync(root)
    assert again.written == [] and setupdocs.sync(root, check=True).problems() == []


def test_check_mode_compares_only_the_committed_index(root: Path) -> None:
    report = setupdocs.sync(root, check=True)
    assert report.stale == ["docs/setup/README.md"] and report.missing == []
    assert not (root / INV).exists()                                 # nothing written, the inventory untouched
    setupdocs.sync(root)
    write_registry(root, {"big": entry("comfyui/loras/big.safetensors", kind="lora", source={"type": "huggingface", "repo": "org/big"})})
    assert setupdocs.sync(root, check=True).problems() == []         # a model change is the inventory's business
    (root / "services" / "img" / "setup" / "more.md").write_text(ENV_DOC.replace('"img"', '"img-more"'))
    report = setupdocs.sync(root, check=True)
    assert report.stale == ["docs/setup/README.md"] and report.problems() == ["stale: docs/setup/README.md"]


def test_orphans(root: Path) -> None:
    setupdocs.sync(root)
    ae = root / INV / "ae.md"
    big = root / INV / "big.md"
    big.write_text(big.read_text() + "\nKeep this.\n")
    write_registry(root, {})
    assert setupdocs.sync(root, check=True).orphans == []            # the inventory isn't checked
    report = setupdocs.sync(root)
    assert report.removed == [f"{INV}/ae.md"] and not ae.exists()    # nothing hand-written: deleted
    assert report.orphans == [f"{INV}/big.md"]                       # hand-written: kept, marked
    assert "**Not in the registry.**" in big.read_text() and big.read_text().endswith("Keep this.\n")
    assert report.problems() == []


def test_coverage_is_about_mods(root: Path) -> None:
    write_registry(root, {
        "big": entry("comfyui/loras/big.safetensors", source={"type": "huggingface", "repo": "org/big"}),
        "llm": entry("llm/x/x.gguf", kind="llm", services=["lcpp"]),
    })
    lcpp = root / "services" / "lcpp"
    lcpp.mkdir()
    (lcpp / "service.toml").write_text('id = "lcpp"\n[models]\ndirs = ["llm"]\n')
    report = setupdocs.sync(root)
    assert report.uncovered == ["llm"] and report.unsourced == ["llm"]  # notes for the inventory
    assert report.uncovered_mods == ["lcpp"]
    assert report.problems() == [] and report.problems(strict=True) == ["mod lcpp has no setup doc (services/lcpp/setup/)"]
    path = root / INV / "llm.md"
    path.write_text(path.read_text().replace("## Where to get it\n", "## Where to get it\n\nAsk on the forum.\n"))
    assert setupdocs.sync(root).unsourced == []


def test_glob_rules() -> None:
    assert envs.matches("comfyui/vae/x.safetensors", "comfyui/**")
    assert envs.matches("tts/breeze-tts-2", "tts/breeze-tts-2") and envs.matches("tts/breeze-tts-2/a/b", "tts")
    assert not envs.matches("tts-old/x", "tts")
    assert envs.matches("hf-cache/hub/models--a--b", "hf-cache/hub/models--a--*")


def test_references_match_whole_names_only(root: Path) -> None:
    setupdocs.sync(root)
    assert "Referenced by" in doc(root, "big")                     # "loras\\big.safetensors" names it
    assert "Referenced by" not in doc(root, "ae")                  # "wan_vae.safetensors" doesn't name ae.safetensors


def test_references_skip_files_git_doesnt_track(root: Path) -> None:
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    mod = root / "services" / "img"
    (mod / "workflows" / "b").mkdir()
    (mod / "workflows" / "b" / "workflow.json").write_text(json.dumps({"widgets_values": ["ae.safetensors"]}))
    subprocess.run(["git", "-C", str(root), "add", "services/img/workflows/a/workflow.json"], check=True)
    setupdocs.sync(root)
    assert "Referenced by" in doc(root, "big")                     # a/ is tracked
    assert "Referenced by" not in doc(root, "ae")                  # b/ names ae, but git doesn't track it


@pytest.mark.parametrize("source,files,path,expect", [
    ({"type": "url", "url": "https://x.test/m.bin"}, None, "comfyui/m/m.bin", ['curl -L --fail -o "data/models/comfyui/m/m.bin.part" "https://x.test/m.bin"']),
    ({"type": "huggingface", "repo": "o/r", "revision": "abc"}, None, "comfyui/vae/v.safetensors", ['--include "*v.safetensors" --revision abc --local-dir data/state/downloads/m', 'find data/state/downloads/m -name "v.safetensors"']),
    ({"type": "huggingface", "repo": "o/r"}, [{"path": "3d/r/a.ckpt"}, {"path": "3d/r/sub/b.yaml"}], "3d/r", ["hf download o/r a.ckpt sub/b.yaml --local-dir data/models/3d/r"]),
    ({"type": "huggingface", "repo": "o/r", "revision": "c0ffee"}, [{"path": "hf-cache/hub/models--o--r/snapshots/c0ffee/config.json"}, {"path": "hf-cache/hub/models--o--r/refs/main"}], "hf-cache/hub/models--o--r", ["HF_HOME=data/models/hf-cache uvx --from huggingface_hub hf download o/r config.json --revision c0ffee"]),
    ({"type": "created", "note": "a clip"}, None, "voices/v", []),
    ({"type": "local"}, None, "llm/x.gguf", []),
    (None, None, "llm/x.gguf", []),
])
def test_fetch_commands(source, files, path, expect) -> None:
    e = entry(path, source=source, files=files if files is not None else [{"path": path}])
    cmds = render.fetch(e, "m")
    assert len(cmds) == (len(expect) if expect else 0)
    for c, want in zip(cmds, expect):
        assert want in c


@pytest.mark.parametrize("text,problem", [
    ("# no block\n", "no <!-- gaifa-setup"),
    ('<!-- gaifa-setup\nid = "x"\n-->\n', "`title` must be"),
    ('<!-- gaifa-setup\nid = "x"\ntitle = "X"\nmodel = ["a"]\n-->\n', "unknown key(s) model"),
    ('<!-- gaifa-setup\nid = "x"\ntitle = "X"\nmodels = "a"\n-->\n', "`models` must be a list"),
    ("<!-- gaifa-setup\nid = \n-->\n", "isn't TOML"),
])
def test_bad_environment_docs(root: Path, text: str, problem: str) -> None:
    (root / "services" / "img" / "setup" / "bad.md").write_text(text)
    report = setupdocs.sync(root, check=True)
    assert problem in report.env_problems["services/img/setup/bad.md"]
    assert any(p.startswith("setup doc services/img/setup/bad.md") for p in report.problems())


def test_duplicate_ids_and_the_template_is_skipped(root: Path) -> None:
    (root / "services" / "img" / "setup" / "again.md").write_text(ENV_DOC)
    found, problems = envs.load_envs(root)
    assert [e.id for e in found] == ["img"]                         # _template's env.md isn't a mod's
    assert "also used by" in problems["services/img/setup/img.md"] or "also used by" in problems["services/img/setup/again.md"]


def test_cli(root: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(cli, "ROOT", root)
    assert cli.cmd_docs(Namespace(check=True, strict=False)) == 1
    assert cli.cmd_docs(Namespace(check=False, strict=False)) == 0
    assert "wrote data/state/setup/models/big.md" in capsys.readouterr().out
    assert cli.cmd_docs(Namespace(check=True, strict=False)) == 0
    assert cli.cmd_docs(Namespace(check=True, strict=True)) == 0      # ae has no source: a note, not a failure
    (root / "services" / "bare").mkdir()
    (root / "services" / "bare" / "service.toml").write_text('id = "bare"\n')
    assert cli.cmd_docs(Namespace(check=True, strict=True)) == 1      # a mod without a setup doc
    assert "mod bare has no setup doc" in capsys.readouterr().err


def test_a_recommended_mods_doc_has_check_and_when_it_fails(root: Path) -> None:
    """capability-enablement 8.2: `--strict` fails a recommended mod's own doc without `## Check` and a `## When it fails`
    table (what you see | what to check | the fix); a mod that isn't recommended needn't have them."""
    d = root / "services" / "rec" / "setup"
    d.mkdir(parents=True)
    (d.parent / "service.toml").write_text('id = "rec"\n')
    head = '<!-- gaifa-setup\nid = "rec"\ntitle = "Rec"\nsummary = "x"\nrecommended = true\n-->\n\n# Rec\n\n'
    (d / "rec.md").write_text(head + "## Check it works\n\nrun it\n")
    problems = setupdocs.sync(root, check=True).problems(strict=True)
    assert any("services/rec/setup/rec.md" in p and "`## Check` section" in p and "`## When it fails` section" in p for p in problems)
    assert not any("rec.md" in p for p in setupdocs.sync(root, check=True).problems())          # only under --strict
    (d / "rec.md").write_text(head + "## Check\n\n`gaifa check rec`\n\n## When it fails\n\nask someone\n")
    assert any("needs a table" in p for p in setupdocs.sync(root, check=True).problems(strict=True))
    (d / "rec.md").write_text(head + "## Check\n\n`gaifa check rec`\n\n## When it fails\n\n| What you see | What to check | The fix |\n"
                              "|---|---|---|\n| failed | `gaifa logs rec` | `gaifa start rec` |\n")
    assert not any("rec.md" in p for p in setupdocs.sync(root, check=True).problems(strict=True))
    (d / "rec.md").write_text(head.replace("recommended = true\n", "") + "## Check it works\n\nrun it\n")
    assert not any("rec.md" in p for p in setupdocs.sync(root, check=True).problems(strict=True))


def test_every_recommended_mod_here_has_them() -> None:
    root = Path(__file__).resolve().parents[3]
    assert setupdocs.sync(root, check=True).unguided == {}


def test_the_turning_on_table(root: Path) -> None:
    """capability-enablement 8.3: docs/turning-things-on.md's table, made by gaifa docs: each mod, what it gives,
    recommended first, the size with default models, what a chat can't do without it, the command."""
    d = root / "services" / "rec" / "setup"
    d.mkdir(parents=True)
    (d.parent / "service.toml").write_text('id = "rec"\n[agent]\nprovides = "do the rec thing"\n')
    (d / "rec.md").write_text('<!-- gaifa-setup\nid = "rec"\ntitle = "Rec"\nsummary = "Rec: things"\nrecommended = true\ndisk_gb = 1.0\n'
                              '[[suggest]]\nname = "M"\nrepo = "a/b"\ndest = "rec/m"\nsize_gb = 0.5\ngood_for = "x"\ndefault = true\n-->\n\n# Rec\n')
    page = root / "docs" / "turning-things-on.md"
    page.parent.mkdir(parents=True, exist_ok=True)
    page.write_text(f"# Turning things on\n\n{render.START}\n{render.END}\n\nhand text\n")
    report = setupdocs.sync(root, check=True)
    assert "docs/turning-things-on.md" in report.stale
    setupdocs.sync(root)
    text = page.read_text()
    assert "| [`rec`](../services/rec/setup/rec.md) | Rec: things | yes | 1.5 GB | do the rec thing | `gaifa setup rec` | — |" in text
    assert text.endswith("hand text\n") and setupdocs.sync(root, check=True).stale == []
