from lcpp import settings
from lcpp.catalog import Catalog
from lcpp.cmdline import flag_args, render_preset, router_argv, single_argv


def _pairs(argv):
    """argv → {flag: value-or-True}, for order-independent assertions."""
    out, i = {}, 0
    while i < len(argv):
        a = argv[i]
        if a.startswith("--") and i + 1 < len(argv) and not argv[i + 1].startswith("--"):
            out[a] = argv[i + 1]
            i += 2
        else:
            out[a] = True
            i += 1
    return out


def test_flag_styles():
    assert flag_args({"flash-attn": True}) == ["--flash-attn", "on"]
    assert flag_args({"flash-attn": False}) == ["--flash-attn", "off"]
    assert flag_args({"jinja": False, "no-mmap": False, "metrics": False}) == ["--no-jinja"]
    assert flag_args({"cont_batching": True, "--threads": 8}) == ["--cont-batching", "--threads", "8"]
    assert flag_args({"lora": ["a", "b"], "x": None, "y": ""}) == ["--lora", "a", "--lora", "b"]
    assert flag_args({"port": 1, "host": "0.0.0.0", "alias": "z"}) == []


def test_single_argv_matches_legacy_preset_semantics(home):
    """The gemma-26B golden case: same effective flags the old models.ini produced."""
    s = settings.load(home)
    cat = Catalog.load(home)
    argv = single_argv(home, s, cat, cat.get("gemma-4-26B-it"), 17071)
    assert argv[0] == str(home.root / "runtime/llama.cpp/bin/current/llama-server")
    p = _pairs(argv[1:])
    assert p["--host"] == "127.0.0.1" and p["--port"] == "17071"
    assert p["--model"] == str(home.root / "models/Gemma4-26B/g26.gguf")
    assert p["--alias"] == "gemma-4-26B-it,gemma4-26B"
    assert p["--ctx-size"] == "262144"
    assert p["--cache-type-k"] == "q8_0" and p["--cache-type-v"] == "q8_0"
    assert p["--n-gpu-layers"] == "999" and p["--flash-attn"] == "on"
    assert p["--mmproj"] == str(home.root / "models/Gemma4-26B/mmproj-g26.gguf")
    assert p["--model-draft"] == str(home.root / "models/Gemma4-26B/mtp-g26.gguf")
    assert p["--spec-type"] == "draft-mtp" and p["--gpu-layers-draft"] == "999"
    assert p["--jinja"] is True and p["--reasoning"] == "auto" and p["--reasoning-budget"] == "-1"
    assert "--no-mmap" not in p


def test_single_argv_launch_overrides_win(home):
    s = settings.load(home)
    cat = Catalog.load(home)
    p = _pairs(single_argv(home, s, cat, cat.get("minicpm-5-2B"), 17072,
                           {"ctx-size": 8192, "parallel": 2, "port": 1}))
    assert p["--ctx-size"] == "8192" and p["--parallel"] == "2" and p["--port"] == "17072"


def test_router_preset_and_argv(home):
    s = settings.load(home)
    cat = Catalog.load(home)
    ini = render_preset(home, cat, [cat.get("gemma-4-26B-it"), cat.get("minicpm-5-2B")])
    assert ini.startswith("version = 1")
    assert "[gemma-4-26B-it]" in ini and "[minicpm-5-2B]" in ini
    assert f"model = {home.root / 'models/MiniCPM5-2B/mini.gguf'}" in ini
    assert "flash-attn = on" in ini and "no-mmap = off" in ini
    assert f"mmproj = {home.root / 'models/Gemma4-26B/mmproj-g26.gguf'}" in ini
    mini = ini.split("[minicpm-5-2B]")[1]
    assert "ctx-size = 131072" in mini
    argv = router_argv(home, s, home.generated / "r.ini", 17080, 2)
    p = _pairs(argv[1:])
    assert p["--models-preset"].endswith("r.ini") and p["--models-max"] == "2"
