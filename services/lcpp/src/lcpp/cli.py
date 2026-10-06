"""``lcpp`` — the command line for lcppd.

    lcpp status                         what is running
    lcpp start minicpm --port 7072      start a model (waits until ready)
    lcpp start --router --port 7070     a router over the whole catalog
    lcpp stop 7072 | lcpp stop all      stop by name, port, or everything
    lcpp logs 7072 -f                   follow an instance's log
    lcpp relay add 7072 --alias mini    publish to Relay
    lcpp service start                  the daemon itself (systemd user unit)

Every command except ``service`` talks to the daemon over HTTP; this module
and what it imports are stdlib-only so the CLI answers in milliseconds.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from typing import Any

from lcpp import __version__
from lcpp.client import ApiError, Client, DaemonDown, q

GB = 1024**3


# ---- formatting ----------------------------------------------------------
def fmt_gb(b: int | None) -> str:
    return "—" if not b else f"{b / GB:.1f} GB"


def fmt_dur(seconds: float) -> str:
    s = int(max(0, seconds))
    if s < 60:
        return f"{s}s"
    m, h, d = s // 60, s // 3600, s // 86400
    if h < 1:
        return f"{m}m {s % 60}s"
    if d < 1:
        return f"{h}h {m % 60}m"
    return f"{d}d {h % 24}h"


def table(rows: list[list[str]], header: list[str]) -> str:
    widths = [max(len(str(r[i])) for r in [header, *rows]) for i in range(len(header))]
    line = lambda r: "  ".join(str(c).ljust(w) for c, w in zip(r, widths)).rstrip()  # noqa: E731
    return "\n".join([line(header), *map(line, rows)])


def parse_value(v: str) -> Any:
    low = v.lower()
    if low in ("true", "on", "yes"):
        return True
    if low in ("false", "off", "no"):
        return False
    if low in ("null", "none"):
        return None
    for cast in (int, float):
        try:
            return cast(v)
        except ValueError:
            pass
    return v


def out_json(data: Any) -> None:
    print(json.dumps(data, indent=2))


def instance_line(i: dict[str, Any]) -> list[str]:
    loaded = [m["id"] for m in i["models"] if m["loaded"]]
    model = i["model_id"] or (f"router ({len(i['models'])} models; loaded: "
                              f"{', '.join(loaded) if loaded else 'none'})")
    up = fmt_dur(time.time() - (i["ready_ts"] or i["started_ts"])) if i["state"] == "ready" else i["state"]
    relay = i["relay"]
    rel = "—" if relay["state"] == "off" else f"{relay['state']} ({relay['alias']})"
    return [i["name"], str(i["port"]), model, up, fmt_gb(i["rss_bytes"]), rel]


# ---- commands ---------------------------------------------------------------
def cmd_status(c: Client, a: argparse.Namespace) -> int:
    ov = c.get("/api/overview")
    if a.json:
        out_json(ov)
        return 0
    sysv, relay = ov["system"], ov["relay"]
    mem = sysv["memory"]
    print(f"lcppd {sysv['daemon']['version']} on {c.base} · up {fmt_dur(sysv['daemon']['uptime_s'])}"
          f" · llama.cpp {sysv['llama']['build']}")
    print(f"memory {fmt_gb(mem['used_bytes'])} / {fmt_gb(mem['total_bytes'])} used · "
          f"relay {relay['url']} {'reachable' if relay['reachable'] else 'UNREACHABLE'}")
    if not ov["instances"]:
        print("\nno instances running — start one with: lcpp start <model> [--port N]")
        return 0
    print()
    print(table([instance_line(i) for i in ov["instances"]],
                ["NAME", "PORT", "MODEL", "STATE/UP", "MEMORY", "RELAY"]))
    for i in ov["instances"]:
        if i["state"] == "failed":
            print(f"\n{i['name']} failed: {i['last_error']}")
    return 0


def cmd_models(c: Client, a: argparse.Namespace) -> int:
    if a.discovered:
        found = c.get("/api/models/discovered")
        if a.json:
            out_json(found)
        elif not found:
            print("no unconfigured GGUF files in the scan directories")
        else:
            print(table([[d["suggested_id"], fmt_gb(d["size_bytes"]), d["path"]] for d in found],
                        ["SUGGESTED ID", "SIZE", "PATH"]))
        return 0
    data = c.get("/api/models")
    if a.json:
        out_json(data)
        return 0
    rows = []
    for m in data["models"]:
        caps = [k for k in ("vision", "speculative", "split") if m["capabilities"][k]]
        rows.append([m["id"], ", ".join(m["nicknames"]), fmt_gb(m["size_bytes"]),
                     str(m["effective"].get("ctx-size", "")), ",".join(caps),
                     "ok" if m["ok"] else "MISSING", ", ".join(m["running"])])
    print(table(rows, ["ID", "NICKNAMES", "SIZE", "CTX", "FEATURES", "FILES", "RUNNING"]))
    return 0


def build_spec(a: argparse.Namespace) -> dict[str, Any]:
    params: dict[str, Any] = {}
    for kv in a.set or []:
        key, sep, val = kv.partition("=")
        if not sep:
            raise SystemExit(f"--set expects key=value, got {kv!r}")
        params[key.strip().removeprefix("--")] = parse_value(val.strip())
    if a.ctx:
        params["ctx-size"] = a.ctx
    spec: dict[str, Any] = {"kind": "router" if a.router else "single", "params": params}
    if a.router:
        if a.models:
            spec["model_ids"] = [m.strip() for m in a.models.split(",") if m.strip()]
        spec["models_max"] = a.models_max
    else:
        if not a.model:
            raise SystemExit("lcpp start: name a model (see `lcpp models`), or pass --router")
        spec["model_id"] = a.model
    if a.port:
        spec["port"] = a.port
    if a.name:
        spec["name"] = a.name
    if a.relay is not None or a.alias:
        spec["relay"] = {"enabled": a.relay if a.relay is not None else True, "alias": a.alias}
    return spec


def wait_ready(c: Client, name: str, timeout: float) -> dict[str, Any]:
    t0 = time.monotonic()
    last = ""
    tty = sys.stderr.isatty()
    while True:
        inst = c.get(f"/api/instances/{q(name)}")
        if inst["state"] != "starting":
            if tty:
                sys.stderr.write("\r\033[K")
            return inst
        if tty:
            tail = (inst["last_log_lines"] or [""])[-1][-70:]
            msg = f"\r\033[K  starting {name} … {time.monotonic() - t0:.0f}s  {tail}"
            if msg != last:
                sys.stderr.write(msg)
                sys.stderr.flush()
                last = msg
        if time.monotonic() - t0 > timeout:
            if tty:
                sys.stderr.write("\n")
            print(f"{name} is still starting after {timeout:.0f}s; check `lcpp logs {name}`")
            return inst
        time.sleep(0.5)


def cmd_start(c: Client, a: argparse.Namespace) -> int:
    spec = build_spec(a)
    if a.dry_run:
        pf = c.post("/api/instances/preflight", spec)
        if a.json:
            out_json(pf)
            return 0 if not pf["errors"] else 1
        print(f"name {pf['name']} · port {pf['port']} · estimated {fmt_gb(pf['estimated_bytes'])}"
              f" of {fmt_gb(pf['available_bytes'])} available")
        for w in pf["warnings"]:
            print(f"warning: {w}")
        for e in pf["errors"]:
            print(f"error: {e['detail']}")
        print(" ".join(pf["argv"]))
        return 0 if not pf["errors"] else 1
    res = c.post("/api/instances", spec)
    inst = res["instance"]
    for w in res["warnings"]:
        print(f"warning: {w}", file=sys.stderr)
    if not a.wait:
        print(f"starting {inst['name']} on {inst['url']}")
        return 0
    inst = wait_ready(c, inst["name"], a.timeout)
    if inst["state"] == "ready":
        up = fmt_dur((inst["ready_ts"] or time.time()) - inst["started_ts"])
        print(f"{inst['name']} ready on {inst['url']} ({up})")
        if inst["relay"]["state"] != "off":
            print(f"relay: {inst['relay']['state']} as {inst['relay']['alias']!r}")
        return 0
    if inst["state"] == "failed":
        print(f"{inst['name']} failed: {inst['last_error']}", file=sys.stderr)
        for line in inst["last_log_lines"]:
            print(f"  {line}", file=sys.stderr)
        return 1
    return 0 if inst["state"] == "starting" else 1


def cmd_stop(c: Client, a: argparse.Namespace) -> int:
    if a.target == "all":
        names = c.post("/api/instances/stop-all")["stopping"]
        print("stopping: " + (", ".join(names) if names else "nothing was running"))
    else:
        inst = c.delete(f"/api/instances/{q(a.target)}")
        names = [inst["name"]]
        print(f"stopping {inst['name']}")
    if a.wait and names:
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            running = {i["name"] for i in c.get("/api/instances")}
            if not running & set(names):
                print("stopped")
                return 0
            time.sleep(0.3)
        print("still stopping after 60s", file=sys.stderr)
        return 1
    return 0


def cmd_restart(c: Client, a: argparse.Namespace) -> int:
    inst = c.post(f"/api/instances/{q(a.target)}/restart")
    print(f"restarting {inst['name']}")
    if not a.wait:
        return 0
    time.sleep(0.3)
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        try:
            cur = c.get(f"/api/instances/{q(inst['name'])}")
        except ApiError:
            time.sleep(0.3)
            continue
        if cur["state"] == "starting":
            cur = wait_ready(c, inst["name"], a.timeout)
        if cur["state"] in ("ready", "failed"):
            print(f"{cur['name']} {cur['state']}" + (f": {cur['last_error']}" if cur["state"] == "failed" else ""))
            return 0 if cur["state"] == "ready" else 1
        time.sleep(0.3)
    return 1


def cmd_logs(c: Client, a: argparse.Namespace) -> int:
    for line in c.get(f"/api/instances/{q(a.target)}/logs?lines={a.lines}")["lines"]:
        print(line["text"])
    if a.follow:
        try:
            for line in c.sse("GET", f"/api/instances/{q(a.target)}/logs/stream"):
                print(line["text"], flush=True)
        except KeyboardInterrupt:
            pass
    return 0


def cmd_relay(c: Client, a: argparse.Namespace) -> int:
    if a.relay_cmd == "add":
        inst = c.post(f"/api/instances/{q(a.target)}/relay", {"alias": a.alias})
        r = inst["relay"]
        print(f"{inst['name']}: relay {r['state']} as {r['alias']!r}" + (f" ({r['error']})" if r["error"] else ""))
        return 0
    if a.relay_cmd == "remove":
        inst = c.delete(f"/api/instances/{q(a.target)}/relay")
        print(f"{inst['name']}: removed from relay")
        return 0
    if a.relay_cmd == "cleanup":
        removed = c.post("/api/relay/cleanup")["removed"]
        print("removed: " + (", ".join(removed) if removed else "no orphaned registrations"))
        return 0
    data = c.get("/api/relay")
    if a.json:
        out_json(data)
        return 0
    s = data["status"]
    print(f"relay {s['url']}: " + (f"reachable ({s['latency_ms']} ms)" if s["reachable"] else f"UNREACHABLE — {s['error']}"))
    if data["owned"]:
        print()
        print(table([[r["key"], r["instance"] or "—", r["alias"] or "—", ",".join(r["models"]),
                      r["health"] + (" (orphan)" if r["orphan"] else "")] for r in data["owned"]],
                    ["KEY", "INSTANCE", "ALIAS", "MODELS", "HEALTH"]))
    else:
        print("no registrations managed by lcpp")
    return 0


def cmd_chat(c: Client, a: argparse.Namespace) -> int:
    target = ({"type": "relay", "model": a.target} if a.via_relay else {"type": "instance", "name": a.target})
    req: dict[str, Any] = {"messages": [{"role": "user", "content": " ".join(a.prompt)}],
                           "max_tokens": a.max_tokens}
    if a.no_think:
        req["chat_template_kwargs"] = {"enable_thinking": False}
    metrics = None
    thinking = False
    for ev in c.sse("POST", "/api/chat", {"target": target, "request": req}):
        if "lcpp_metrics" in ev:
            metrics = ev["lcpp_metrics"]
            continue
        if "error" in ev:
            print(f"\nerror: {ev['error'].get('message')}", file=sys.stderr)
            return 1
        for ch in ev.get("choices") or []:
            d = ch.get("delta") or {}
            if d.get("reasoning_content"):
                if not thinking:
                    sys.stdout.write("\033[2m" if sys.stdout.isatty() else "")
                    thinking = True
                sys.stdout.write(d["reasoning_content"])
            if d.get("content"):
                if thinking:
                    sys.stdout.write("\033[0m\n\n" if sys.stdout.isatty() else "\n\n")
                    thinking = False
                sys.stdout.write(d["content"])
            sys.stdout.flush()
    print()
    if metrics:
        print(f"— ttft {metrics['ttft_ms']} ms · {metrics['tokens_per_s']} tok/s · "
              f"{metrics['prompt_tokens']} in / {metrics['completion_tokens']} out · {metrics['total_ms']} ms",
              file=sys.stderr)
    return 0


def cmd_ui(c: Client, a: argparse.Namespace) -> int:
    import webbrowser

    print(c.base + "/")
    webbrowser.open(c.base + "/")
    return 0


def cmd_service(_: Client | None, a: argparse.Namespace) -> int:
    from lcpp import service

    return service.run(a.service_cmd)


def cmd_doctor(c: Client, a: argparse.Namespace) -> int:
    from lcpp import doctor

    return doctor.run(c)


# ---- parser ------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="lcpp", description="Launch and manage llama.cpp servers on this machine.",
                                formatter_class=argparse.RawDescriptionHelpFormatter,
                                epilog="Targets are instance names or ports. Web UI: lcpp ui")
    p.add_argument("--daemon", metavar="URL", help="lcppd URL (default: from data/lcpp.json, or $LCPP_URL)")
    p.add_argument("--version", action="version", version=f"lcpp {__version__}")
    sub = p.add_subparsers(dest="cmd", metavar="COMMAND")

    s = sub.add_parser("status", aliases=["ps"], help="daemon and instance status")
    s.add_argument("--json", action="store_true")
    s.set_defaults(func=cmd_status)

    s = sub.add_parser("models", aliases=["ls"], help="the model catalog")
    s.add_argument("--discovered", action="store_true", help="GGUF files not yet in the catalog")
    s.add_argument("--json", action="store_true")
    s.set_defaults(func=cmd_models)

    s = sub.add_parser("start", help="start a model server")
    s.add_argument("model", nargs="?", help="model id or nickname (see `lcpp models`)")
    s.add_argument("-p", "--port", type=int, help="port (default: first free in the configured range)")
    s.add_argument("-n", "--name", help="instance name (default: <nickname>-<port>)")
    s.add_argument("-c", "--ctx", type=int, help="context size (ctx-size)")
    s.add_argument("-s", "--set", action="append", metavar="KEY=VALUE", help="extra llama-server param (repeatable)")
    s.add_argument("--relay", dest="relay", action="store_true", default=None, help="publish to Relay")
    s.add_argument("--no-relay", dest="relay", action="store_false", help="do not publish to Relay")
    s.add_argument("--alias", help="Relay alias (default: the model's first nickname)")
    s.add_argument("--router", action="store_true", help="router mode: many models, loaded on demand")
    s.add_argument("--models", help="router: comma-separated models (default: all)")
    s.add_argument("--models-max", type=int, default=1, help="router: models loaded at once")
    s.add_argument("--dry-run", action="store_true", help="show the preflight check and command only")
    s.add_argument("--no-wait", dest="wait", action="store_false", help="return once the process starts")
    s.add_argument("--timeout", type=float, default=900, help="seconds to wait for ready")
    s.add_argument("--json", action="store_true")
    s.set_defaults(func=cmd_start)

    s = sub.add_parser("stop", help="stop an instance, or `all`")
    s.add_argument("target", help="name, port, or `all`")
    s.add_argument("--wait", action="store_true", help="wait until stopped")
    s.set_defaults(func=cmd_stop)

    s = sub.add_parser("restart", help="restart an instance")
    s.add_argument("target")
    s.add_argument("--no-wait", dest="wait", action="store_false")
    s.add_argument("--timeout", type=float, default=900)
    s.set_defaults(func=cmd_restart)

    s = sub.add_parser("logs", help="show (or follow) an instance's log")
    s.add_argument("target")
    s.add_argument("-f", "--follow", action="store_true")
    s.add_argument("-n", "--lines", type=int, default=50)
    s.set_defaults(func=cmd_logs)

    s = sub.add_parser("relay", help="Relay registrations")
    rs = s.add_subparsers(dest="relay_cmd", metavar="ACTION")
    rs.add_parser("status", help="reachability and lcpp-managed registrations")
    r = rs.add_parser("add", help="publish an instance")
    r.add_argument("target")
    r.add_argument("--alias")
    r = rs.add_parser("remove", help="unpublish an instance")
    r.add_argument("target")
    rs.add_parser("cleanup", help="remove orphaned registrations")
    s.add_argument("--json", action="store_true")
    s.set_defaults(func=cmd_relay, relay_cmd="status")

    s = sub.add_parser("chat", help="send one prompt to an instance (or a Relay model)")
    s.add_argument("target", help="instance name/port, or a Relay model with --via-relay")
    s.add_argument("prompt", nargs="+")
    s.add_argument("--via-relay", action="store_true")
    s.add_argument("--max-tokens", type=int, default=512)
    s.add_argument("--no-think", action="store_true", help="disable reasoning for this prompt")
    s.set_defaults(func=cmd_chat)

    s = sub.add_parser("service", help="the lcppd background service")
    s.add_argument("service_cmd", choices=["install", "uninstall", "start", "stop", "restart", "status", "logs"])
    s.set_defaults(func=cmd_service)

    s = sub.add_parser("ui", help="open the web UI")
    s.set_defaults(func=cmd_ui)

    s = sub.add_parser("doctor", help="check binary, models, ports and Relay")
    s.set_defaults(func=cmd_doctor)
    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    a = parser.parse_args(argv)
    if not getattr(a, "func", None):  # bare `lcpp` means `lcpp status`
        a.func, a.json = cmd_status, False
    client = Client(a.daemon)
    try:
        return a.func(client, a)
    except DaemonDown as e:
        print(f"{e}\nstart it with: lcpp service start", file=sys.stderr)
        return 1
    except ApiError as e:
        print(f"error: {e.detail}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
