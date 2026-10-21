"""The aihub-setup block, version 2 (plan 23.7): summary, gpu, disk, needs, after, check, steps and
suggested models; and the mods index that shows them."""

from __future__ import annotations

from pathlib import Path

import pytest

from utils import setupdocs
from utils.setupdocs import block, envs, render

FULL = '''<!-- aihub-setup
id = "tts-kokoro"
title = "Kokoro"
models = ["hf-cache/hub/models--hexgrad--Kokoro-82M"]
summary = "Speech: fast English voices"
gpu = true
disk_gb = 14
needs = ["podman", "espeak-ng"]
after = ["tts"]
check = "aihub check tts"

[[steps]]
run = "aihub install tts"
what = "the server venv"

[[steps]]
run = "scripts/install-runtime.sh --accept-breeze-license"
what = "the engine venvs"
ask = "Breeze TTS 2 is non-commercial. Accept its licence?"

[[suggest]]
name = "Kokoro 82M"
repo = "hexgrad/Kokoro-82M"
revision = "f3ff357"
dest = "hf-cache"
size_gb = 0.34
good_for = "fast English voices"
licence = "Apache-2.0"
required = true

[[suggest]]
name = "Whisper small"
op = "POST /v1/load"
body = { preset = "balanced" }
size_gb = 0.46
good_for = "transcribing references"
-->

# Kokoro
'''


def doc(tmp_path: Path, text: str, mod: str = "tts") -> Path:
    d = tmp_path / "services" / mod / "setup"
    d.mkdir(parents=True, exist_ok=True)
    (d.parent / "service.toml").write_text(f'id = "{mod}"\n')
    p = d / "env.md"
    p.write_text(text)
    return p


def test_every_key(tmp_path: Path) -> None:
    env, problem = envs.parse(doc(tmp_path, FULL), "tts")
    assert problem is None and env is not None
    s = env.setup
    assert (s.summary, s.gpu, s.disk_gb, s.needs, s.after, s.check) == ("Speech: fast English voices", True, 14.0, ["podman", "espeak-ng"], ["tts"], "aihub check tts")
    assert [st.run for st in s.steps] == ["aihub install tts", "scripts/install-runtime.sh --accept-breeze-license"]
    assert s.steps[0].ask == "" and s.steps[1].ask.startswith("Breeze TTS 2")
    k, w = s.suggest
    assert (k.repo, k.revision, k.dest, k.size_gb, k.required, k.gated, k.op, k.kind) == ("hexgrad/Kokoro-82M", "f3ff357", "hf-cache", 0.34, True, False, "", "other")
    assert (w.op, w.body, w.repo, w.required) == ("POST /v1/load", {"preset": "balanced"}, "", False)


def test_the_new_keys_are_optional(tmp_path: Path) -> None:
    env, problem = envs.parse(doc(tmp_path, '<!-- aihub-setup\nid = "x"\ntitle = "X"\n-->\n'), "tts")
    assert problem is None and env.setup == block.Setup()


@pytest.mark.parametrize("extra,problem", [
    ('summary = ""', "`summary` must be a non-empty string"),
    ('gpu = "yes"', "`gpu` must be true or false"),
    ("disk_gb = -1", "`disk_gb` must be a number"),
    ('needs = "podman"', "`needs` must be a list of strings"),
    ('check = ""', "`check` must be a non-empty command"),
    ('[[steps]]\nrun = "x"', "steps[0]: `what` must be a non-empty string"),
    ('[[steps]]\nrun = "x"\nwhat = "y"\nwhen = "now"', "steps[0]: unknown key(s) when"),
    ('[[suggest]]\nname = "A"\nsize_gb = 1\ngood_for = "b"', "give either `repo`"),
    ('[[suggest]]\nname = "A"\nsize_gb = 1\ngood_for = "b"\nrepo = "o/r"\nop = "POST /v1/x"\ndest = "x"', "not both or neither"),
    ('[[suggest]]\nname = "A"\nsize_gb = 1\ngood_for = "b"\nrepo = "o/r"', "a `repo` needs `dest`"),
    ('[[suggest]]\nname = "A"\nsize_gb = 1\ngood_for = "b"\nrepo = "o/r"\ndest = "../out"', "`dest` must be a folder inside data/models/"),
    ('[[suggest]]\nname = "A"\nsize_gb = 1\ngood_for = "b"\nrepo = "nope"\ndest = "x"', "`repo` must look like org/name"),
    ('[[suggest]]\nname = "A"\nsize_gb = 1\ngood_for = "b"\nop = "load it"', '`op` must look like "POST /v1/load"'),
    ('[[suggest]]\nname = "A"\nsize_gb = 1\ngood_for = "b"\nop = "POST /v1/load"\ndest = "x"', "go with `repo`, not `op`"),
    ('[[suggest]]\nname = "A"\nsize_gb = 1\ngood_for = "b"\nop = "POST /v1/load"\nkind = "tts"', "go with `repo`, not `op`"),
    ('[[suggest]]\nname = "A"\nsize_gb = 1\ngood_for = "b"\nrepo = "o/r"\ndest = "x"\nkind = ""', "`kind` must be a registry kind"),
    ('[[suggest]]\nname = "A"\ngood_for = "b"\nrepo = "o/r"\ndest = "x"', "`size_gb` must be a number"),
    ('[[suggest]]\nname = "A"\nsize_gb = 1\ngood_for = "b"\nrepo = "o/r"\ndest = "x"\nrequired = "yes"', "`required` must be true or false"),
    ('[[suggest]]\nname = "A"\nsize_gb = 1\ngood_for = "b"\nrepo = "o/r"\ndest = "x"\nmirror = "y"', "suggest[0]: unknown key(s) mirror"),
])
def test_bad_values(tmp_path: Path, extra: str, problem: str) -> None:
    env, got = envs.parse(doc(tmp_path, f'<!-- aihub-setup\nid = "x"\ntitle = "X"\n{extra}\n-->\n'), "tts")
    assert env is None and problem in got


def test_the_mods_index_shows_the_block(tmp_path: Path) -> None:
    doc(tmp_path, FULL)
    doc(tmp_path, '<!-- aihub-setup\nid = "web"\ntitle = "Web"\nsummary = "Search"\ngpu = false\ndisk_gb = 0.05\n-->\n', mod="web")
    readme = tmp_path / "docs" / "setup" / "README.md"
    readme.parent.mkdir(parents=True)
    readme.write_text(f"# Setup\n\n{render.START}\n{render.END}\n")
    setupdocs.sync(tmp_path)
    text = readme.read_text()
    assert "| `tts` | Speech: fast English voices | yes | 14.0 GB | [Kokoro](../../services/tts/setup/env.md) |" in text
    assert "| `web` | Search | no | 50 MB | [Web](../../services/web/setup/env.md) |" in text


def test_the_template_parses_once_filled_in(tmp_path: Path) -> None:
    tpl = (Path(__file__).resolve().parents[3] / "services" / "_template" / "setup" / "env.md").read_text()
    env, problem = envs.parse(doc(tmp_path, tpl.replace("__ID__", "my-mod").replace("__NAME__", "My Mod"), mod="my-mod"), "my-mod")
    assert problem is None
    assert env.setup.summary.startswith("My Mod") and env.setup.check == "aihub check my-mod --start" and env.setup.steps[0].run == "aihub install my-mod"
