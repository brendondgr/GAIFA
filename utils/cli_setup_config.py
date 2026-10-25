"""`gaifa setup`'s values (plan 23.12): settings a setup doc asks for once its mods are installed, such
as the agent's model, whose choices only exist then (the relay's models). Hosted providers become
relay endpoints first. Values go into config.toml with a text edit (standard library only), checked
by parsing the result. Asked after install and models, before the checks."""

from __future__ import annotations

import argparse
import getpass
import json
import re
import tomllib
from pathlib import Path
from typing import Any

if __package__:
    from utils.cli_setup_run import Answers, Runner, Stop, doc_of, interactive, say
else:
    from cli_setup_run import Answers, Runner, Stop, doc_of, interactive, say  # type: ignore[no-redef]


NOT_CHAT = {"auto", "agent"}   # the relay's router pseudo-model, and OpenCode's coding agent (it runs shell commands)
WAIT_S = 60          # how long to wait for the relay to list a model…
WAIT_STARTED_S = 900 # …or, when this run launched one (lcpp), for it to load and register


def relay_models(runner: Runner, root: Path) -> list[str]:
    """The model names the relay serves now (starting it first if it isn't running)."""
    for attempt in (0, 1):
        try:
            data = runner.call("GET", "/api/s/relay/v1/models") or {}
            return sorted({str(m.get("id")) for m in data.get("data", []) if m.get("id")})
        except Exception:  # noqa: BLE001: not running yet
            if attempt == 0:
                runner.run("gaifa start relay", root, stream=False)
    return []


def add_provider(runner: Runner, p: dict[str, Any]) -> str:
    """A hosted provider (an OpenAI-compatible API) as a relay endpoint: services/relay/setup/relay.md."""
    if not isinstance(p, dict) or not p.get("name") or not p.get("base_url"):
        raise Stop("failed", output=f"a provider needs a name and a base_url (and a key and model names): {sorted(p) if isinstance(p, dict) else p!r}",
                   doc="services/relay/setup/relay.md")
    body = {"name": p["name"], "base_url": p["base_url"], "protocol": "openai", "available_models": list(p.get("models", []))}
    if p.get("key"):
        body["upstream_key"] = p["key"]
    try:
        runner.call("POST", "/api/s/relay/admin/endpoints", body)
    except Exception as x:  # noqa: BLE001
        raise Stop("failed", output=f"adding the provider {p['name']!r} to the relay: {getattr(x, 'detail', x)}", doc="services/relay/setup/relay.md") from None
    return p["name"]


def _table_and_key(key: str) -> tuple[str, str]:
    if key == "agent.judge.model":
        return "agent.judge", "model"
    if key.startswith("services.") and key.endswith(".accel") and key.count(".") == 2:
        return key.rsplit(".", 1)[0], "accel"
    _, mod, _, var = key.split(".", 3)
    return f"services.{mod}.env", var


def set_value(path: Path, key: str, value: str) -> None:
    """Set one value in config.toml, keeping everything else as it is; the result must parse."""
    table, k = _table_and_key(key)
    text = path.read_text() if path.exists() else ""
    line = f"{k} = {json.dumps(value)}"
    lines = text.splitlines()
    head = next((i for i, x in enumerate(lines) if x.strip() == f"[{table}]"), None)
    if head is None:
        new = text.rstrip("\n") + ("\n\n" if text.strip() else "") + f"[{table}]\n{line}\n"
    else:
        end = next((i for i in range(head + 1, len(lines)) if lines[i].lstrip().startswith("[")), len(lines))
        at = next((i for i in range(head + 1, end) if re.match(rf"^\s*{re.escape(k)}\s*=", lines[i])), None)
        if at is None:
            lines.insert(head + 1, line)
        else:
            lines[at] = line
        new = "\n".join(lines) + "\n"
    try:
        data = tomllib.loads(new)
    except tomllib.TOMLDecodeError as e:
        raise Stop("failed", output=f"config.toml: setting {key} would make it invalid ({e}); set it by hand") from None
    cur: Any = data
    for part in key.split("."):
        cur = cur.get(part) if isinstance(cur, dict) else None
    if cur != value:
        raise Stop("failed", output=f"config.toml: {key} is set another way (an inline table?); set it by hand")
    tmp = path.with_suffix(".toml.tmp")
    tmp.write_text(new)
    tmp.replace(path)


def _override_env(path: Path, mod: str) -> dict[str, str]:
    try:
        env = tomllib.loads(path.read_text()).get("services", {}).get(mod, {}).get("env", {})
    except (OSError, tomllib.TOMLDecodeError):
        return {}
    return {str(k): str(v) for k, v in env.items()} if isinstance(env, dict) else {}


def apply(runner: Runner, root: Path, key: str, value: str) -> bool:
    """Set a value through the hub, which saves config.toml and applies it at once (a mod restart then
    runs with it). False: the hub didn't take it, and the file was edited directly instead, which
    the hub reads only when it starts."""
    try:
        if key == "agent.judge.model":
            runner.call("PUT", "/api/settings", {"judge": {"model": value}})
        else:
            _, mod, _, var = key.split(".", 3)
            runner.call("PUT", f"/api/services/{mod}/config", {"env": {**_override_env(root / "config.toml", mod), var: value}})
        return True
    except Exception:  # noqa: BLE001: the hub is down, or refused it: the careful text edit
        set_value(root / "config.toml", key, value)
        return False


def record_accel(runner: Runner, root: Path, mod: str, accel: str, env: dict[str, str]) -> bool:
    """Plan 38.2: `[services.<mod>] accel` and the variant's env, through the hub (applied at once) or, when
    it doesn't take them, written into config.toml (read when the hub next starts). True: the hub took them."""
    body: dict[str, Any] = {"accel": accel}
    if env:
        body["env"] = {**_override_env(root / "config.toml", mod), **env}
    try:
        runner.call("PUT", f"/api/services/{mod}/config", body)
        return True
    except Exception:  # noqa: BLE001: the hub is down, or doesn't know the key yet
        set_value(root / "config.toml", f"services.{mod}.accel", accel)
        for k, v in env.items():
            set_value(root / "config.toml", f"services.{mod}.env.{k}", v)
        return False


def applied(runner: Runner, key: str) -> str | None:
    """The value the hub runs with now (None when unknown)."""
    try:
        if key == "agent.judge.model":
            return ((runner.call("GET", "/api/settings") or {}).get("judge") or {}).get("model")
        _, mod, _, var = key.split(".", 3)
        return (((runner.call("GET", f"/api/services/{mod}") or {}).get("config") or {}).get("env") or {}).get(var)
    except Exception:  # noqa: BLE001
        return None


def wait_models(runner: Runner, root: Path, args: argparse.Namespace, want: str | None, timeout: float) -> list[str]:
    """The relay's chat models, waited for while the list is empty or lacks `want`: a model just
    launched (lcpp) or just discovered (OpenCode) registers some seconds to minutes later."""
    waited, said = 0.0, False
    while True:
        models = [m for m in relay_models(runner, root) if m not in NOT_CHAT]
        if (models and (want is None or want in models)) or waited >= timeout:
            return models
        if not said:
            say(args, "    waiting for the relay to list " + (want or "a chat model") + " (a model just started takes a while to load)")
            said = True
        runner.sleep(5)
        waited += 5


def get_value(path: Path, key: str) -> str | None:
    try:
        cur: Any = tomllib.loads(path.read_text())
    except (OSError, tomllib.TOMLDecodeError):
        return None
    for part in key.split("."):
        cur = cur.get(part) if isinstance(cur, dict) else None
    return cur if isinstance(cur, str) else None


def _prompt(e: Any, c: Any, choices: list[str], runner: Runner) -> str | None:
    """None: skipped; "": ask again (a provider added, or a refresh)."""
    print(f"\n{c.text}" + ("" if c.required else " (optional)"))
    for i, m in enumerate(choices, 1):
        print(f"  {i}. {m}")
    if c.choices == "relay-models":
        print("  h. add a hosted provider (an OpenAI-compatible API: its URL, key and model names)")
        print("  r. look again (a model that's still loading appears once it's ready)")
    if c.choices == "folder":
        pick = input("An absolute folder outside GAIFA" + ("" if c.required else " (Enter to skip)") + ": ").strip()
        return pick or None
    while True:
        pick = input("Number" + (", h" if c.choices == "relay-models" else "") + ("" if c.required else ", or Enter to skip") + ": ").strip()
        if not pick and not c.required:
            return None
        if pick == "r" and c.choices == "relay-models":
            return ""
        if pick == "h" and c.choices == "relay-models":
            name = add_provider(runner, {"name": input("  a name for it: ").strip(), "base_url": input("  base URL (e.g. https://api.openai.com/v1): ").strip(),
                                         "key": getpass.getpass("  API key (hidden): ").strip(), "models": [m.strip() for m in input("  model names, comma-separated: ").split(",") if m.strip()]})
            print(f"  added {name}")
            return ""   # ask again with the new models
        if pick.isdigit() and 0 < int(pick) <= len(choices):
            return choices[int(pick) - 1]


def phase(live: list[Any], args: argparse.Namespace, answers: Answers, root: Path, runner: Runner, report: dict[str, Any], state: dict[str, Any], started: bool = False) -> None:
    """Providers first, then every [[config]] value of the chosen setups."""
    state.setdefault("config", {})
    state.setdefault("providers", [])
    if answers.providers:
        relay_models(runner, root)        # starts the relay: providers are its endpoints
    for p in answers.providers:
        if p.get("name") not in state["providers"]:
            say(args, f"\n==> relay: adding the provider {p.get('name')}")
            state["providers"].append(add_provider(runner, p))
            report["done"].append(f"relay: provider {p.get('name')}")
    # Folders and lists first: setting one can bring the relay new models (OpenCode's folder starts
    # it, then the relay finds Zen's), so the questions about the relay's models come last.
    todo = [(e, c) for e in live for c in e.setup.config]
    for e, c in sorted(todo, key=lambda ec: ec[1].choices == "relay-models"):
        qid = f"{e.id}/config:{c.key}"
        value = answers.values.get(qid, answers.values.get(c.key))
        while True:
            if c.choices == "relay-models":
                choices = wait_models(runner, root, args, value, WAIT_STARTED_S if started else WAIT_S)
            elif c.choices == "folder":
                choices = []
            else:
                choices = list(c.choices)
            if value is None and interactive(args):
                value = _prompt(e, c, choices, runner)
                if value == "":
                    value = None
                    continue
            break
        if value is None:
            if c.required:
                hint = ""
                if c.choices == "relay-models":
                    hint = ("; to add a hosted provider first: \"providers\" in --answers (services/relay/setup/relay.md)"
                            + ("" if choices else "; the relay serves no chat model yet: set up lcpp with a model (setup launches it), add a hosted provider, or set up opencode"))
                elif c.choices == "folder":
                    hint = " (an absolute folder outside GAIFA; created if missing)"
                raise Stop("question", id=qid, kind="value", text=c.text, choices=choices if c.choices != "folder" else "folder",
                           answer_with=f'--set "{qid}=<value>"' + hint)
            report["next"].append(f"{qid}: not set ({c.text}); later: --set \"{qid}=<value>\", or Settings")
            continue
        if c.choices == "folder":
            folder = Path(value).expanduser()
            if not folder.is_absolute() or folder.resolve().is_relative_to(root.resolve()):
                raise Stop("unknown-value", id=qid, value=value, choices="an absolute folder outside GAIFA", doc=doc_of(e, root))
            folder.mkdir(parents=True, exist_ok=True)
            value = str(folder.resolve())
        elif choices and value not in choices:
            raise Stop("unknown-value", id=qid, value=value, choices=choices, doc=doc_of(e, root))
        if state["config"].get(qid) == value and applied(runner, c.key) == value:
            report["skipped"].append(f"{qid}: already {value}")
            continue
        targets = c.restart.split()
        if not apply(runner, root, c.key, value):
            # In the file only: the hub reads it when it starts, so restart the hub before the mods
            # (a mod restarted now would run with the hub's old value).
            if not runner.hub_up():
                report["next"].append(f"{qid}: written to config.toml while the hub is down; it applies when the hub starts"
                                      + (f", then restart {' and '.join(t for t in targets if t != 'hub')}" if any(t != "hub" for t in targets) else ""))
                targets = []
            elif "hub" not in targets:
                targets.insert(0, "hub")
        for target in targets:
            rc, out = runner.run("gaifa restart" if target == "hub" else f"gaifa restart {target}", root, stream=False)
            if rc and target == "hub":
                # A hub without its systemd unit (`gaifa serve`, a test port) can't be restarted from here.
                report["next"].append(f"{qid}: written to config.toml; restart the hub yourself"
                                      + (f", then {' and '.join(t for t in targets if t != 'hub')}" if any(t != "hub" for t in targets) else "") + f" ({out.strip()[:200]})")
                break
            if rc:
                raise Stop("failed", setup=e.id, step=f"config:{c.key}", output=f"restarting {target} after setting {c.key}: {out}", doc=doc_of(e, root))
        started = started or "relay" in targets      # a restarted relay looks for its endpoints' models again
        state["config"][qid] = value
        report["done"].append(f"{qid} = {value}")


def verify(live: list[Any], root: Path, runner: Runner, report: dict[str, Any]) -> None:
    """After the checks: a value chosen from the relay's models (one in config.toml: set by this run
    or before; a skipped optional one is the code's default and isn't checked) must be what the hub
    runs with, and still on the relay."""
    models: list[str] | None = None
    for e in live:
        for c in e.setup.config:
            value = get_value(root / "config.toml", c.key)
            if c.choices != "relay-models" or value is None:
                continue
            if c.key == "agent.judge.model" and get_value(root / "config.toml", "agent.judge.backend") == "decide":
                continue                  # a decide model id, not one of the relay's
            models = relay_models(runner, root) if models is None else models
            running = applied(runner, c.key)
            ok = value in models and running in (None, value)
            report["checks"].append({"setup": e.id, "run": f"{c.key} on the relay", "ok": ok})
            if running not in (None, value):
                why = f"config.toml says {value!r}, but the hub runs with {running!r}: gaifa restart, then restart {c.restart or 'the mod'}"
            else:
                why = f"{value!r} isn't a model the relay serves ({', '.join(models) or 'none'})"
            if not ok:
                report["failed"].append({"setup": e.id, "step": f"config:{c.key}", "output": why, "doc": doc_of(e, root)})
