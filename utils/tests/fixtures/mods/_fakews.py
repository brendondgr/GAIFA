"""fake-ws (plan 27.4): a workspace mod in miniature, for the mode × level tests.

Folder names carry their level: `read`, `edit`, `run`, `run_net`, and a `-bypass` suffix allows
Bypass (`run_net-bypass`). `POST /v1/limits` answers what the real workspace mod's preflight does:
the action, the level, Bypass, the grant key (folder + the command's first word), `once` for host
runs, commits and git remotes, a preview, and a refusal when the level is too low or the command
uses sudo. The tool routes echo what they were sent.
"""

from __future__ import annotations

LEVELS = ("read", "edit", "run", "run_net")
NEEDS = {"read": "read", "edit": "edit", "delete": "edit", "commit": "edit", "command": "run", "network": "run_net",
         "host": "run", "remote": "run_net"}
TOOLS = {"read": "read", "edit": "edit", "delete": "delete", "commit": "commit", "run": None}


def _s(desc: str = "") -> dict:
    return {"type": "string", **({"description": desc} if desc else {})}


def paths() -> dict:
    def body(props: dict, required: list[str]) -> dict:
        return {"post": {"summary": "", "requestBody": {"required": True, "content": {"application/json": {"schema": {
            "type": "object", "properties": props, "required": required}}}}, "responses": {"200": {"content": {"application/json": {"schema": {}}}}}}}
    f = {"folder": _s("the folder")}
    return {
        "/v1/read": body({**f, "path": _s()}, ["folder", "path"]),
        "/v1/edit": body({**f, "path": _s(), "old": _s(), "new": _s()}, ["folder", "path"]),
        "/v1/delete": body({**f, "path": _s()}, ["folder", "path"]),
        "/v1/commit": body({**f, "message": _s()}, ["folder", "message"]),
        "/v1/run": body({**f, "command": _s("a shell command"), "where": {"type": "string", "enum": ["sandbox", "host"], "default": "sandbox"},
                         "network": {"type": "boolean", "default": False}}, ["folder", "command"]),
        "/v1/limits": body({"tool": _s(), "arguments": {"type": "object"}, "origin": {"type": "object"}}, ["tool"]),
    }


def limits(b: dict) -> dict:
    tool, args = b.get("tool"), b.get("arguments") or {}
    folder = str(args.get("folder") or "")
    level = folder.split("-")[0]
    out = {"action": "read", "folder": folder, "level": level, "allow_bypass": folder.endswith("-bypass"), "key": folder, "once": False}
    if level not in LEVELS:
        return {**out, "refuse": {"code": "unknown_folder", "detail": f"no folder {folder!r}", "fix": "workspace_folders"}}
    if tool == "run":
        cmd = str(args.get("command") or "")
        words = cmd.split()
        action = "host" if args.get("where") == "host" else ("network" if args.get("network") else "command")
        if len(words) > 1 and words[0] == "git" and words[1] in ("push", "pull", "fetch", "clone"):
            action = "remote"
        if "sudo" in words:
            return {**out, "action": action, "refuse": {"code": "sudo", "detail": "sudo is never run by the agent", "fix": "ask the user"}}
        out.update({"action": action, "key": f"{folder} {words[0] if words else ''}".strip(),
                    "once": action in ("host", "remote"), "preview": {"command": cmd, "where": args.get("where") or "sandbox"}})
    else:
        out["action"] = TOOLS.get(tool or "", "read") or "read"
        out["once"] = out["action"] == "commit"
        if out["action"] in ("edit", "delete"):
            out["preview"] = {"summary": f"{tool} {args.get('path')}", "diff": f"--- a/{args.get('path')}\n+++ b/{args.get('path')}\n"}
    need = NEEDS[out["action"]]
    if LEVELS.index(level) < LEVELS.index(need):
        out["refuse"] = {"code": "level", "detail": f"needs the folder at {need}; {folder} is at {level}",
                         "fix": f"ask the user to raise {folder} on the Workspace page"}
    return out


def handle(path: str, body: dict) -> dict | None:
    if path == "/v1/limits":
        return limits(body)
    if path in ("/v1/read", "/v1/edit", "/v1/delete", "/v1/commit", "/v1/run"):
        return {"ran": path.rsplit("/", 1)[1], "arguments": body}
    return None
