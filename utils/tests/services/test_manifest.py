"""2.1: service.toml schema, discovery, error collection, placeholders, env and overrides."""

from __future__ import annotations

from pathlib import Path

import pytest

from utils import config, manifest
from utils.manifest import ManifestError, discover, effective, launch_spec, start_order

FULL = """
id = "tts"
name = "Speech"
description = "Text to speech"
icon = "wave"
version = "0.4.0"

[run]
command = [".venv/bin/python", "-m", "localtts", "--data", "./data"]
port = 5040
health = "/health"
status = "/v1/status"
env = { LOCALTTS_PORT = "{port}", LOCALTTS_OUTPUTS_DIR = "{outputs}", WORKERS = 2, DEBUG = false }
env_file = ".env"
start_timeout_s = 60
stop_timeout_s = 180
restart = "on-failure"
after = ["relay"]

[memory]
estimate_gb = 9.2
load = "POST /v1/load"
unload = "POST /v1/unload"
triggers = ["POST /v1/speech"]

[models]
dirs = ["tts", "voices"]

[outputs]
kinds = ["audio"]

[ui]
page = "ui/page.js"
native = "/ui/"

[[ui.widgets]]
id = "clips"
title = "Clips per day"
kind = "bar"
source = "GET /v1/hub/widgets/clips"
ranges = ["7d", "30d"]
span = 4

[api]
hide = ["GET /ui/{path}"]
[api.responses]
"POST /v1/speech" = "audio"

[tools]
speak = { op = "POST /v1/speech", description = "Speak text", job = true, job_status = "GET /v1/jobs/{id}", risk = "generate", ask = ["voice"], core = true }
delete_voice = { op = "DELETE /v1/voices/{name}", confirm = true }

[agent]
tools_source = "GET /v1/tools"
"""

MINIMAL = """
id = "{id}"
[run]
command = ["python3", "server.py"]
port = {port}
"""


def write(base: Path, folder: str, text: str) -> Path:
    d = base / folder
    d.mkdir(parents=True, exist_ok=True)
    (d / "service.toml").write_text(text)
    return d


def minimal(base: Path, sid: str, port: int) -> Path:
    return write(base, sid, MINIMAL.replace("{id}", sid).replace("{port}", str(port)))


@pytest.fixture
def svc(tmp_path) -> Path:
    d = tmp_path / "services"
    d.mkdir()
    return d


@pytest.fixture
def cfg_paths(tmp_path):
    def make(text: str = "") -> tuple[config.Config, object]:
        (tmp_path / "config.toml").write_text(text)
        cfg = config.load(tmp_path / "config.toml")
        return cfg, config.build_paths(cfg, tmp_path)

    return make


# --- schema ---------------------------------------------------------------------


def test_full_manifest_parses(svc):
    write(svc, "tts", FULL)
    [mod] = discover([svc])
    assert mod.ok, mod.errors
    m = mod.manifest
    assert (m.name, m.icon, m.version, m.run.port, m.run.restart) == ("Speech", "wave", "0.4.0", 5040, "on-failure")
    assert m.run.env["WORKERS"] == "2" and m.run.env["DEBUG"] == "false"  # TOML scalars become strings
    assert m.memory.estimate_gb == 9.2 and m.memory.triggers == ["POST /v1/speech"]
    assert m.outputs.kinds == ["audio"]
    assert m.ui.widgets[0].span == 4 and m.ui.page == "ui/page.js"
    assert m.api.responses == {"POST /v1/speech": "audio"}
    assert m.tools["delete_voice"].confirm is True
    assert m.tools["speak"].job is True and m.tools["delete_voice"].job is False
    assert m.tools["speak"].risk == "generate" and m.tools["speak"].ask == ["voice"] and m.tools["speak"].core
    assert m.agent.tools_source == "GET /v1/tools"


def test_minimal_manifest_defaults(svc):
    minimal(svc, "hello", 5100)
    [mod] = discover([svc])
    m = mod.manifest
    assert mod.ok
    assert m.name == "hello"  # name defaults to the id
    assert (m.icon, m.version, m.run.kind, m.run.health, m.run.openapi, m.run.status) == ("box", None, "process", "/health", "/openapi.json", None)
    assert m.memory is None and m.outputs is None and m.ui.page is None and m.tools == {}
    assert m.agent.tools_source is None


def test_command_as_a_string_is_split(svc):
    write(svc, "hello", 'id = "hello"\n[run]\ncommand = "python3 server.py --flag \'a b\'"\nport = 5100\n')
    [mod] = discover([svc])
    assert mod.manifest.run.command == ["python3", "server.py", "--flag", "a b"]


def test_tcp_health_and_external_kind(svc):
    write(svc, "llama", 'id = "llama"\n[run]\ncommand = ["/usr/bin/llama-server"]\nport = 5101\nhealth = "tcp"\n')
    write(svc, "ext", 'id = "ext"\n[run]\nkind = "external"\nport = 5102\n')
    mods = {m.id: m for m in discover([svc])}
    assert mods["llama"].ok and mods["llama"].manifest.run.health == "tcp"
    assert mods["ext"].ok and mods["ext"].manifest.run.kind == "external" and mods["ext"].manifest.run.command == []


# --- errors are collected, never raised ----------------------------------------------------


@pytest.mark.parametrize(
    "text, expect",
    [
        ('id = "x1"\n[run\n', "not valid TOML"),
        ('id = "bad"\n[run]\ncommand = ["a"]\n', "[run].port: required"),
        ('id = "bad"\n', "run: required"),
        ('id = "bad"\n[run]\ncommand = ["a"]\nport = 70000\n', "[run].port: Input should be less than or equal to 65535"),
        ('id = "bad"\n[run]\nport = 5100\n', "[run].command is required"),
        ('id = "bad"\n[run]\ncommand = ["a"]\nport = 5100\nhealth = "health"\n', "[run].health: must be a path"),
        ('id = "bad"\n[run]\ncommand = ["a"]\nport = 5100\nrestart = "always"\n', "[run].restart"),
        ('id = "bad"\n[run]\ncommand = ["a"]\nport = 5100\nprot = 1\n', "[run].prot: unknown key"),
        ('id = "bad"\nnmae = "x"\n[run]\ncommand = ["a"]\nport = 5100\n', "nmae: unknown key"),
        ('id = "bad"\n[run]\ncommand = ["a"]\nport = 5100\nenv = { "BAD-NAME" = "1" }\n', "not a valid environment variable name"),
        ('id = "bad"\n[run]\ncommand = ["a"]\nport = 5100\n[memory]\nload = "/v1/load"\n', "is not an operation"),
        ('id = "bad"\n[run]\ncommand = ["a"]\nport = 5100\n[ui]\npage = "../x.js"\n', "inside the mod's ui/ folder"),
        ('id = "bad"\n[run]\ncommand = ["a"]\nport = 5100\n[ui]\npage = "ui/page.css"\n', ".js page module"),
        ('id = "bad"\n[run]\ncommand = ["a"]\nport = 5100\n[[ui.widgets]]\nid="a"\ntitle="A"\nkind="pie"\nsource="GET /a"\n', "[ui].widgets.0.kind"),
        ('id = "bad"\n[run]\ncommand = ["a"]\nport = 5100\n[[ui.widgets]]\nid="a"\ntitle="A"\nkind="bar"\nsource="GET /a"\n[[ui.widgets]]\nid="a"\ntitle="B"\nkind="bar"\nsource="GET /b"\n', "duplicate widget id"),
        ('id = "bad"\n[run]\ncommand = ["a"]\nport = 5100\n[models]\ndirs = ["../etc"]\n', "inside data/models"),
        ('id = "bad"\n[run]\ncommand = ["a"]\nport = 5100\n[tools]\nSpeak = { op = "POST /a" }\n', "tool name 'Speak'"),
        ('id = "bad"\n[run]\ncommand = ["a"]\nport = 5100\n[api.responses]\n"POST /a" = "pdf"\n', "[api].responses"),
        ('id = "bad"\n[run]\ncommand = ["a"]\nport = 5100\n[outputs]\nkinds = ["pictures"]\n', "[outputs].kinds.0"),
    ],
)
def test_each_error_kind_is_collected(svc, text, expect):
    folder = "x1" if "x1" in text else "bad"
    write(svc, folder, text)
    [mod] = discover([svc])
    assert not mod.ok
    joined = "\n".join(mod.errors)
    assert expect in joined, joined
    assert all(e.startswith("service.toml") for e in mod.errors)


def test_broken_mod_keeps_folder_id_name_and_port(svc):
    write(svc, "broken", 'id = "broken"\nname = "Broken"\n[run]\nport = 5150\n')
    [mod] = discover([svc])
    assert (mod.id, mod.name, mod.manifest_port, mod.manifest) == ("broken", "Broken", 5150, None)


def test_id_must_match_folder(svc):
    write(svc, "speech", 'id = "tts"\n[run]\ncommand = ["a"]\nport = 5100\n')
    [mod] = discover([svc])
    assert mod.id == "speech" and not mod.ok
    assert "must equal the folder name 'speech'" in mod.errors[0]


def test_bad_folder_and_id_names(svc):
    write(svc, "My_Mod", 'id = "My_Mod"\n[run]\ncommand = ["a"]\nport = 5100\n')
    [mod] = discover([svc])
    assert any("folder name 'My_Mod'" in e for e in mod.errors)
    assert any("[a-z][a-z0-9-]" in e for e in mod.errors)


def test_port_clashes(svc):
    minimal(svc, "aaa", 5100)
    minimal(svc, "bbb", 5100)
    minimal(svc, "hubby", 7000)
    mods = {m.id: m for m in discover([svc], hub_port=7000)}
    assert mods["aaa"].ok
    assert mods["bbb"].errors == ["service.toml: [run].port 5100 is already used by aaa"]
    assert mods["hubby"].errors == ["service.toml: [run].port 7000 is the hub's own port"]


def test_one_bad_mod_does_not_hide_the_others(svc):
    minimal(svc, "good", 5100)
    write(svc, "bad", "not toml at all [[[")
    mods = {m.id: m for m in discover([svc])}
    assert mods["good"].ok and not mods["bad"].ok


def test_unreadable_manifest(svc):
    d = write(svc, "bin", "")
    (d / "service.toml").write_bytes(b"\xff\xfe\x00bad")
    [mod] = discover([svc])
    assert not mod.ok and "service.toml" in mod.errors[0]


# --- discovery ---------------------------------------------------------------------------


def test_template_hidden_and_plain_folders_are_skipped(svc):
    minimal(svc, "_template", 5100)
    minimal(svc, ".hidden", 5101)
    (svc / "notamod").mkdir()
    (svc / "loose.toml").write_text("x = 1")
    minimal(svc, "real", 5102)
    assert [m.id for m in discover([svc])] == ["real"]


def test_missing_dir_is_fine(tmp_path):
    assert discover([tmp_path / "nope"]) == []


def test_extra_dirs_cannot_redefine_an_id(svc, tmp_path):
    other = tmp_path / "demo"
    minimal(svc, "dup", 5100)
    minimal(other, "dup", 5101)
    mods = discover([svc, other])
    assert len(mods) == 2
    assert sum(1 for m in mods if m.ok) == 1
    assert any("already used by" in e for m in mods for e in m.errors)


def test_fake_mod_fixtures_are_valid():
    from utils.tests.conftest import FAKE_MODS

    mods = discover([FAKE_MODS])
    assert [m.id for m in mods] == ["fake-crash", "fake-mem", "fake-ok", "fake-perms", "fake-slow", "fake-tools"]
    assert all(m.ok for m in mods), [m.errors for m in mods]


# --- overrides ------------------------------------------------------------------------------


def test_effective_defaults_and_overrides(svc, cfg_paths):
    minimal(svc, "tts", 5040)
    minimal(svc, "plain", 5100)
    cfg, _ = cfg_paths(
        '[memory]\npriority = ["comfy", "tts"]\n'
        '[services.tts]\nport = 5041\nautostart = false\nidle_unload_s = 180\nenv = { A = "1" }\n'
    )
    mods = {m.id: m for m in discover([svc])}
    tts = effective(mods["tts"], cfg)
    assert (tts.port, tts.enabled, tts.autostart, tts.idle_unload_s, tts.priority, tts.env) == (5041, True, False, 180, 1, {"A": "1"})
    plain = effective(mods["plain"], cfg)
    assert (plain.port, plain.enabled, plain.autostart, plain.idle_unload_s, plain.auto_unload) == (5100, True, True, None, True)
    assert plain.priority == manifest.DEFAULT_PRIORITY


def test_effective_port_clash_after_override(svc, cfg_paths):
    minimal(svc, "aaa", 5100)
    minimal(svc, "bbb", 5101)
    cfg, _ = cfg_paths("[services.bbb]\nport = 5100\n")
    clashes = manifest.check_effective_ports(discover([svc]), cfg, 7000)
    assert clashes == {"bbb": "port 5100 is already used by aaa"}


# --- placeholders and env -------------------------------------------------------------------------


def test_launch_spec_expands_placeholders_and_layers_env(svc, cfg_paths, tmp_path):
    d = write(svc, "tts", FULL)
    (d / ".env").write_text(
        "# secrets\nexport SECRET='s3cret'\nLOCALTTS_PORT=1\nPLAIN=a b # comment\nHF_HOME=/elsewhere\nBRACES={not_expanded}\n"
    )
    cfg, paths = cfg_paths('[services.tts]\nport = 5041\nenv = { LOCALTTS_OUTPUTS_DIR = "{databases}/x", EXTRA = "{hub_url}" }\n')
    [mod] = discover([svc])
    spec = launch_spec(mod, cfg, paths, hub_port=7001)

    assert spec.argv == [str(d / ".venv/bin/python"), "-m", "localtts", "--data", str(d / "data")]
    assert spec.cwd == d and spec.port == 5041 and spec.stop_timeout_s == 180
    assert spec.outputs == tmp_path / "outputs" / "tts"
    env = spec.env
    # hub vars
    assert env["AIHUB_URL"] == "http://127.0.0.1:7001" and env["AIHUB_SERVICE_ID"] == "tts"
    assert env["AIHUB_PORT"] == "5041" and env["AIHUB_ROOT"] == str(tmp_path)
    assert env["AIHUB_OUTPUTS"] == str(tmp_path / "outputs" / "tts") and env["PYTHONUNBUFFERED"] == "1"
    # env_file over hub vars (HF_HOME "unless the mod sets its own"), values not expanded
    assert env["HF_HOME"] == "/elsewhere" and env["SECRET"] == "s3cret" and env["PLAIN"] == "a b"
    assert env["BRACES"] == "{not_expanded}"
    # manifest env over env_file, with placeholders (port is the effective one)
    assert env["LOCALTTS_PORT"] == "5041"
    # config override env over everything
    assert env["LOCALTTS_OUTPUTS_DIR"] == str(tmp_path / "data" / "databases" / "x")
    assert env["EXTRA"] == "http://127.0.0.1:7001"
    assert env["WORKERS"] == "2"


def test_every_placeholder(svc, cfg_paths, tmp_path):
    keys = manifest.PLACEHOLDERS
    env = ", ".join(f'P_{k.upper()} = "{{{k}}}"' for k in keys)
    write(svc, "all", f'id = "all"\n[run]\ncommand = ["{{service_dir}}/run", "{{port}}"]\ncwd = "{{root}}"\nport = 5100\nenv = {{ {env} }}\n')
    cfg, paths = cfg_paths()
    spec = launch_spec(discover([svc])[0], cfg, paths, 7000)
    assert spec.argv == [str(svc / "all" / "run"), "5100"] and spec.cwd == tmp_path
    assert {k: spec.env[f"P_{k.upper()}"] for k in keys} == {
        "root": str(tmp_path),
        "service_dir": str(svc / "all"),
        "port": "5100",
        "models": str(tmp_path / "data" / "models"),
        "outputs": str(tmp_path / "outputs" / "all"),
        "databases": str(tmp_path / "data" / "databases"),
        "hf_home": str(tmp_path / "data" / "models" / "hf-cache"),
        "hub_url": "http://127.0.0.1:7000",
    }


def test_unknown_placeholder_is_an_error(svc, cfg_paths):
    write(svc, "typo", 'id = "typo"\n[run]\ncommand = ["a"]\nport = 5100\nenv = { X = "{output}" }\n')
    cfg, paths = cfg_paths()
    with pytest.raises(ManifestError, match=r"\[run\].env.X: unknown placeholder \{output\}"):
        launch_spec(discover([svc])[0], cfg, paths, 7000)


def test_json_like_env_values_are_left_alone(svc, cfg_paths):
    write(svc, "js", 'id = "js"\n[run]\ncommand = ["a"]\nport = 5100\nenv = { J = \'{"a": 1}\', U = "{UPPER}" }\n')
    cfg, paths = cfg_paths()
    spec = launch_spec(discover([svc])[0], cfg, paths, 7000)
    assert spec.env["J"] == '{"a": 1}' and spec.env["U"] == "{UPPER}"


def test_missing_env_file_is_optional_and_bad_one_errors(svc, cfg_paths):
    d = write(svc, "envy", 'id = "envy"\n[run]\ncommand = ["a"]\nport = 5100\nenv_file = ".env"\n')
    cfg, paths = cfg_paths()
    [mod] = discover([svc])
    assert "AIHUB_PORT" in launch_spec(mod, cfg, paths, 7000).env
    (d / ".env").write_text("OK=1\nthis line is wrong\n")
    with pytest.raises(ManifestError, match=r"\.env:2: expected KEY=value"):
        launch_spec(mod, cfg, paths, 7000)


def test_command_path_resolution(tmp_path):
    base = tmp_path / "mod"
    r = manifest.resolve_arg
    assert r("python3", base, True) == "python3"  # PATH lookup
    assert r(".venv/bin/python", base, True) == str(base / ".venv/bin/python")
    assert r("/usr/bin/x", base, True) == "/usr/bin/x"
    assert r("server.py", base, False) == "server.py"  # relative to cwd at run time
    assert r("../shared.py", base, False) == str(tmp_path / "shared.py")
    assert r("-m", base, False) == "-m"


def test_venv_python_symlink_is_not_followed(tmp_path):
    # Following .venv/bin/python to the base interpreter would start the mod outside its venv.
    base = tmp_path / "mod"
    (base / ".venv" / "bin").mkdir(parents=True)
    (base / ".venv" / "bin" / "python").symlink_to("/usr/bin/python3")
    assert manifest.resolve_arg(".venv/bin/python", base, True) == str(base / ".venv" / "bin" / "python")


def test_launch_spec_refuses_a_broken_mod(svc, cfg_paths):
    write(svc, "bad", 'id = "bad"\n[run]\nport = 5100\n')
    cfg, paths = cfg_paths()
    with pytest.raises(ManifestError, match="command is required"):
        launch_spec(discover([svc])[0], cfg, paths, 7000)


# --- ordering ------------------------------------------------------------------------------------


def test_order_and_after(svc):
    for i, sid in enumerate(["relay", "tts", "zzz", "aaa", "loop-a", "loop-b"]):
        minimal(svc, sid, 5100 + i)
    (svc / "relay" / "service.toml").write_text(MINIMAL.replace("{id}", "relay").replace("{port}", "5100") + 'after = ["tts", "ghost"]\n')
    (svc / "loop-a" / "service.toml").write_text(MINIMAL.replace("{id}", "loop-a").replace("{port}", "5104") + 'after = ["loop-b"]\n')
    (svc / "loop-b" / "service.toml").write_text(MINIMAL.replace("{id}", "loop-b").replace("{port}", "5105") + 'after = ["loop-a"]\n')
    mods = discover([svc])
    order = ["relay", "tts"]
    assert [m.id for m in manifest.ordered(mods, order)] == ["relay", "tts", "aaa", "loop-a", "loop-b", "zzz"]
    # relay waits for tts; the unknown "ghost" is ignored; the a↔b cycle doesn't hang
    assert [m.id for m in start_order(mods, order)] == ["tts", "relay", "aaa", "loop-b", "loop-a", "zzz"]


def test_empty_openapi_means_none(svc):
    write(svc, "bin", 'id = "bin"\n[run]\ncommand = ["/usr/bin/x"]\nport = 5100\nopenapi = ""\nhealth = "tcp"\n')
    [mod] = discover([svc])
    assert mod.ok and mod.manifest.run.openapi is None
