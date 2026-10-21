"""The editing tools (plan 27.3): edit, write, move, delete and commit, each checkpointed first.

Every change returns a unified diff and where to undo it. `plan()` works out the same change
without writing anything, so the approval card can show the diff before the user allows it
(Manual mode). A chat's first change in a folder reports a dirty working tree, so the user knows
which changes were theirs.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from checkpoints import Checkpoints, diff, key, text_of, unlink_in, write_atomic
from folders import Folder, Folders, Refused
from reading import dirty, git, is_repo, untrusted

MAX_WRITE = 4 * 1024 * 1024


@dataclass
class Change:
    """One planned change: what the files become, before anything is written."""
    tool: str
    folder: Folder
    diff: str
    writes: list[tuple[Path, str, bytes | None]] = field(default_factory=list)   # (path, rel, new bytes | None = delete)
    summary: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


def _text(p: Path, rel: str) -> str:
    if not p.is_file():
        raise Refused("not_found", f"{rel} doesn't exist", "create it with workspace_write", 404)
    data = p.read_bytes()
    if b"\0" in data[:8192]:
        raise Refused("binary", f"{rel} is a binary file", "only text files are edited", 415)
    return data.decode("utf-8", errors="surrogateescape")


def _near(text: str, old: str, source: str = "file") -> str:
    """A hint for an `old` that wasn't found: the line most like its first line (the file's own words,
    so inside `<untrusted source=…>`)."""
    import difflib

    first = old.strip().split("\n")[0].strip()
    lines = text.split("\n")
    best = difflib.get_close_matches(first, [ln.strip() for ln in lines], n=1, cutoff=0.6)
    if not best:
        return "read the file again and copy the text exactly, whitespace included"
    n = next(i for i, ln in enumerate(lines, 1) if ln.strip() == best[0])
    return (f"the closest line is {n}: {untrusted(source, best[0][:120])}\n"
            "read the file again and copy the text exactly, whitespace included")


def plan(folders: Folders, tool: str, args: dict[str, Any], named: list[str] | None = None) -> Change:
    """The change a call would make (no writes). Raises Refused for anything a hard limit or the level stops."""
    f = folders.get(str(args.get("folder") or ""))
    folders.need(f, "edit", {"edit": "editing a file", "write": "writing a file", "move": "moving a file",
                              "delete": "deleting a file", "git_commit": "committing"}.get(tool, "changing files"))
    if tool == "edit":
        p, rel = folders.resolve(f, args.get("path"), write=True, named=named)
        old, new = str(args.get("old") or ""), str(args.get("new") if args.get("new") is not None else "")
        if not old:
            raise Refused("empty_old", "old is empty", "pass the exact text to replace (or use workspace_write for a new file)", 422)
        if old == new:
            raise Refused("no_change", "old and new are the same", "", 422)
        text = _text(p, rel)
        count = text.count(old)
        if count == 0:
            raise Refused("old_not_found", f"the text to replace isn't in {rel}", _near(text, old, f"{f.id}:{rel}"), 422)
        if count > 1 and not args.get("replace_all"):
            raise Refused("old_not_unique", f"the text to replace appears {count} times in {rel}",
                          "include more of the surrounding lines so it's unique, or pass replace_all=true", 422)
        after = text.replace(old, new) if args.get("replace_all") else text.replace(old, new, 1)
        return Change(tool, f, diff(text, after, rel), [(p, rel, after.encode("utf-8", errors="surrogateescape"))],
                      f"edited {rel} ({count if args.get('replace_all') else 1} replacement{'s' if count > 1 and args.get('replace_all') else ''})")
    if tool == "write":
        p, rel = folders.resolve(f, args.get("path"), write=True, named=named)
        content = str(args.get("content") if args.get("content") is not None else "")
        data = content.encode("utf-8")
        if len(data) > MAX_WRITE:
            raise Refused("too_large", f"the content is {len(data) // 1024} KB (the limit is 4 MB)", "", 413)
        if p.is_dir():
            raise Refused("is_a_folder", f"{rel} is a folder", "", 422)
        before = _text(p, rel) if p.exists() else ""
        if p.exists() and before == content:
            raise Refused("no_change", f"{rel} already has this content", "", 422)
        d = diff(before, content, rel) if p.exists() else diff("", content, rel).replace(f"--- a/{rel}", "--- /dev/null", 1)
        return Change(tool, f, d, [(p, rel, data)], f"{'wrote' if p.exists() else 'created'} {rel} ({len(data)} bytes)")
    if tool == "move":
        src, rs = folders.resolve(f, args.get("source"), write=True, named=named)
        dst, rd = folders.resolve(f, args.get("destination"), write=True, named=named)
        if not src.is_file():
            raise Refused("not_found", f"{rs} isn't a file", "only files are moved, one at a time", 404)
        if dst.exists():
            raise Refused("exists", f"{rd} already exists", "pick another name, or delete it first", 409)
        data = src.read_bytes()
        return Change(tool, f, f"rename from {rs}\nrename to {rd}\n", [(dst, rd, data), (src, rs, None)], f"moved {rs} → {rd}")
    if tool == "delete":
        p, rel = folders.resolve(f, args.get("path"), write=True, named=named)
        if p.is_dir():
            raise Refused("is_a_folder", f"{rel} is a folder", "delete its files one by one", 422)
        if not p.exists():
            raise Refused("not_found", f"{rel} doesn't exist", "", 404)
        before = text_of(p) if b"\0" not in p.read_bytes()[:8192] else "(binary)\n"
        return Change(tool, f, diff(before, "", rel).replace(f"+++ b/{rel}", "+++ /dev/null", 1), [(p, rel, None)], f"deleted {rel}")
    if tool == "git_commit":
        root, _ = folders.resolve(f, ".")
        if not is_repo(root):
            raise Refused("not_a_repo", f"{f.id} isn't a git repository", "", 422)
        msg = str(args.get("message") or "").strip()
        if not msg:
            raise Refused("no_message", "a commit needs a message", "", 422)
        paths = [":(literal)" + folders.resolve(f, x, named=named)[1] for x in (args.get("paths") or [])]
        status = git(root, "status", "--porcelain", "--", *paths).stdout if paths else git(root, "status", "--porcelain").stdout
        if not status.strip():
            raise Refused("nothing_to_commit", "there are no changes to commit", "", 422)
        stat = git(root, "diff", "HEAD", "--stat", "--no-ext-diff", "--no-textconv", "--", *paths, check=False).stdout
        return Change(tool, f, stat, [], f"commit in {f.id}: {msg.splitlines()[0][:72]}",
                      {"message": msg, "paths": paths, "status": status})
    raise Refused("unknown_tool", f"no editing tool {tool!r}", "", 404)


def apply(folders: Folders, cps: Checkpoints, ch: Change, origin: dict[str, Any]) -> dict[str, Any]:
    """Write the change, checkpointing each file first."""
    thread, turn = key(origin.get("thread"), origin.get("turn"), origin.get("tool_call"))
    root = Path(os.path.realpath(ch.folder.path))
    first = not cps.touched(thread, ch.folder.id)
    was_dirty = dirty(root) if first and ch.tool != "git_commit" else []
    out: dict[str, Any] = {"folder": ch.folder.id, "summary": ch.summary}
    if ch.tool == "git_commit":
        args = ["commit", "-q", "-m", ch.extra["message"]]
        if ch.extra["paths"]:
            git(root, "add", "--", *ch.extra["paths"])
            args += ["--", *ch.extra["paths"]]
        else:
            git(root, "add", "-A")
        git(root, "-c", "user.useConfigOnly=false", *args)
        head = git(root, "log", "-1", "--format=%h %s").stdout.strip()
        out.update({"commit": head.split(" ", 1)[0], "subject": head.split(" ", 1)[-1],
                    "stat": git(root, "show", "--no-ext-diff", "--no-textconv", "--stat", "--format=", "HEAD").stdout[-3000:],
                    "note": "undo it with workspace_run `git reset --soft HEAD~1` if the user asks"})
        return out
    done = []
    try:
        for p, rel, data in ch.writes:
            n = cps.before(thread, turn, ch.folder.id, p, rel, ch.tool)
            done.append(n)
            try:
                if data is None:
                    unlink_in(root, p)
                else:
                    mode = p.stat().st_mode & 0o7777 if p.exists() else None
                    write_atomic(p, data, mode, root=root)
            except (OSError, Refused):
                cps.drop(thread, turn, n)
                done.pop()
                raise
            cps.after(thread, turn, n, p)
    except OSError as e:
        raise Refused("write_failed", f"{type(e).__name__}: {e}"[:300], "", 500) from None
    # the diff quotes the file (a write over one quotes all it had): data for the model, never instructions
    d = ch.diff[:20000] + ("\n… (diff cut at 20000 characters)" if len(ch.diff) > 20000 else "")
    out.update({"diff": untrusted(f"workspace {ch.folder.id} diff", d),
                "checkpoint": {"thread": thread, "turn": turn},
                "undo": f"/api/s/workspace/v1/checkpoints/{thread}/{turn}/undo"})
    if was_dirty:
        out["dirty_before"] = was_dirty
        out["note"] = ("the working tree already had uncommitted changes before this chat's first edit (dirty_before); "
                       "they are the user's, not yours")
    return out

