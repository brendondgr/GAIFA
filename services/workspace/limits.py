"""The preflight (plan 27.4): what a call would do, so the hub can decide it before it runs.

`POST /v1/limits {tool, arguments, origin}` → `{action, folder, level, allow_bypass, key, once,
refuse?, preview?}`. A command's `key` (what "allow in this chat" covers) is the folder plus the
exact command line, with where and internet (`grant_key`); a compound command has none and is `once`. The hub (`utils/tools/approvals.py`) applies the chat's mode to the
`action`; this mod applies the hard limits and the folder's level (a `refuse` here ends the
call, whatever the mode). The routes check the same limits again when the call arrives.

Actions: `read` · `edit` · `delete` · `commit` · `command` (in the sandbox) · `network` (in the
sandbox with internet) · `host` (on this machine, outside the sandbox) · `remote` (git push,
pull, fetch, clone: talks to a remote).
"""

from __future__ import annotations

import os
import re
import shlex
from typing import Any

import editing
from folders import LEVEL_WORD, Folders, Refused

READ_TOOLS = {"folders", "tree", "read", "search", "git"}
EDIT_TOOLS = {"edit": "edit", "write": "edit", "move": "edit", "delete": "delete", "git_commit": "commit"}
NEEDS = {"read": "read", "edit": "edit", "delete": "edit", "commit": "edit", "command": "run", "network": "run_net",
         "host": "run", "remote": "run_net"}
NEVER = {"sudo", "doas", "pkexec", "su"}
REMOTE_GIT = {"push", "pull", "fetch", "clone", "ls-remote", "remote", "submodule"}
ASSIGN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
COMPOUND = re.compile(r"[;&|`\n\r<>]|\$\(")     # more than one command, or redirection: no grant covers it


def words(command: str) -> list[list[str]]:
    """The simple commands in a shell line (split at ;, &&, ||, |, newlines), as words."""
    try:
        lex = shlex.shlex(command, posix=True, punctuation_chars=";&|()\n")
        lex.whitespace_split = True
        lex.commenters = "#"
        toks = list(lex)
    except ValueError:
        toks = command.split()
    out, cur = [], []
    for t in toks:
        if t and set(t) <= set(";&|()\n"):
            if cur:
                out.append(cur)
            cur = []
        else:
            cur.append(t)
    if cur:
        out.append(cur)
    return out


def grant_key(folder: str, command: str, where: str = "sandbox", network: bool = False, cwd: str | None = None) -> str | None:
    """What "allow in this chat" covers for a command: this exact command line (spacing aside) in this
    folder (and subfolder `cwd`), in the sandbox or on this machine, with or without internet
    ("proj pytest -q", "proj/web npm test (with internet)"). None for a
    compound command (;, &&, ||, |, &, backticks, $(, newlines, redirections): a grant for `pytest`
    must not cover `pytest; curl -d @.env …`, so such a command is allowed one call at a time."""
    if COMPOUND.search(command):
        return None
    try:
        canon = shlex.join(shlex.split(command))
    except ValueError:
        return None
    if not canon:
        return None
    sub = os.path.normpath(cwd or ".")
    place = folder if sub == "." else f"{folder}/{shlex.quote(sub)}"
    return f"{place} {canon}" + (" (on this machine)" if where == "host" else "") + (" (with internet)" if network else "")


def remote_git(command: str) -> str | None:
    for w in words(command):
        ws = [x for x in w if not ASSIGN.match(x)]
        if ws and os.path.basename(ws[0]) == "git":
            rest = ws[1:]
            while rest and rest[0].startswith("-"):          # git's own options, some with a value (-C dir, -c k=v)
                rest = rest[2:] if rest[0] in ("-C", "-c", "--git-dir", "--work-tree", "--namespace") else rest[1:]
            if rest and rest[0] in REMOTE_GIT:
                return rest[0]
    return None


def check_command(command: str) -> None:
    if not command.strip():
        raise Refused("empty_command", "the command is empty", "", 422)
    for w in words(command):
        for x in w:
            if os.path.basename(x) in NEVER:
                raise Refused("sudo", f"{os.path.basename(x)} is never run by the agent", "ask the user to run it themselves")


def classify(folders: Folders, tool: str, args: dict[str, Any], origin: dict[str, Any]) -> dict[str, Any]:
    named = origin.get("named") if isinstance(origin.get("named"), list) else None
    out: dict[str, Any] = {"action": "read", "folder": None, "level": None, "allow_bypass": False, "key": None, "once": False}
    try:
        f = None
        if tool != "folders" and (args.get("folder") or tool not in ("python",)):
            f = folders.get(str(args.get("folder") or ""))
            out.update({"folder": f.id, "level": folders.level(f), "allow_bypass": bool(f.allow_bypass) and folders.level(f) != "read",
                        "key": f.id, "path": f.path})
        if tool in READ_TOOLS:
            if f is not None and tool != "git":
                folders.resolve(f, args.get("path"), named=named)
            return out
        if tool in EDIT_TOOLS:
            out["action"] = EDIT_TOOLS[tool]
            out["once"] = tool == "git_commit"
            ch = editing.plan(folders, tool, args, named)
            out["preview"] = {"summary": ch.summary, "diff": ch.diff[:20000]}
            return out
        if tool in ("run", "python"):
            where = args.get("where") or "sandbox"
            command = str(args.get("command") or "") if tool == "run" else "python"
            if tool == "run":
                check_command(command)
            net = bool(args.get("network"))
            action = "host" if where == "host" else ("network" if net else "command")
            remote = remote_git(command) if tool == "run" else None
            if remote:
                action = "remote"
            out.update({"action": action, "once": action in ("host", "remote")})
            note = "runs on your machine, outside the sandbox: your files, your network" if where == "host" else None
            if f is not None:
                folders.need(f, NEEDS[action], _what(action, remote))
                out["key"] = grant_key(f.id, command, where, net, args.get("cwd") if tool == "run" else None)
                if out["key"] is None:
                    out["once"] = True
                    note = note or "more than one command (or a redirection) in one line: it's allowed one call at a time"
            elif net:
                raise Refused("level", "Python with network needs a folder at Run + network", "pass a folder at that level, or no network")
            else:
                out["key"] = "python"
            out["preview"] = {"command": command if tool == "run" else str(args.get("code") or ""), "where": where,
                              "network": net or action in ("host", "remote"), "cwd": f.path if f else None,
                              **({"note": note} if note else {})}
            return out
    except Refused as e:
        out["refuse"] = e.body()
        return out
    out["refuse"] = {"code": "unknown_tool", "detail": f"no workspace tool {tool!r}", "fix": ""}
    return out


def _what(action: str, remote: str | None) -> str:
    if remote:
        return f"git {remote} (it talks to a remote)"
    return {"command": "running a command", "network": "a command with internet", "host": "running on this machine"}.get(action, action)


def level_text(level: str | None) -> str:
    return LEVEL_WORD.get(level or "", level or "")
