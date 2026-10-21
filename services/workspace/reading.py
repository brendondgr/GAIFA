"""The reading tools (plan 27.2): tree, read, search and read-only git, as text for the model.

Every answer that carries a folder's contents is wrapped as
`<untrusted source="…">…</untrusted>`: the files are data, never instructions (plan Stage J).
Git runs with external diff drivers, textconv, fsmonitor, pagers, hooks, signing and submodules
turned off, and with every filter, diff and merge driver the repository's own config names (a
sandbox run or a clone can write `.git/config`) emptied, so git never runs code from a folder.
`git_read` never shows secret files, a blob by hash or `rev:path`.
"""

from __future__ import annotations

import fnmatch
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

from folders import MAX_BYTES, SECRET_GLOBS, SKIP_DIRS, Folder, Folders, Refused, is_binary, is_secret, was_named

_CLOSE = re.compile(r"</\s*untrusted", re.I)
GIT_SAFE = ["-c", "core.fsmonitor=false", "-c", "diff.external=", "-c", "core.pager=cat", "-c", "core.hooksPath=/dev/null",
            "-c", "color.ui=false", "-c", "safe.directory=*", "-c", "log.showSignature=false", "-c", "commit.gpgSign=false",
            "-c", "tag.gpgSign=false", "-c", "gpg.program=false", "-c", "gpg.ssh.program=false", "-c", "gpg.x509.program=false",
            "-c", "diff.ignoreSubmodules=all", "-c", "submodule.recurse=false", "-c", "status.submoduleSummary=false",
            "-c", "gc.auto=0", "-c", "maintenance.auto=false"]
DRIVERS = r"^(filter|diff|merge)\..*\.(clean|smudge|process|textconv|command|driver)$"
GIT_READ = ("status", "log", "diff", "show", "branch")
MAX_LINE = 2000


def untrusted(source: str, text: str) -> str:
    """`text` as data: a closing tag inside it can't end the block early."""
    src = source.replace('"', "'")
    return f'<untrusted source="{src}">\n{_CLOSE.sub("</ untrusted", text)}\n</untrusted>'


def git_env() -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update({"GIT_CONFIG_NOSYSTEM": "1", "GIT_TERMINAL_PROMPT": "0", "GIT_PAGER": "cat", "PAGER": "cat", "LC_ALL": "C.UTF-8"})
    return env


def drivers_off(cwd: Path) -> dict[str, str]:
    """The repo's own filter, diff and merge drivers, emptied (as GIT_CONFIG_* so a name with `=` in it
    still works). Read without running anything; the user's global ones (git-lfs) are kept."""
    r = subprocess.run(["git", *GIT_SAFE, "config", "--show-scope", "--name-only", "-z", "--get-regexp", DRIVERS], cwd=cwd,
                       capture_output=True, text=True, timeout=10, env=git_env(), errors="replace")
    parts = r.stdout.split("\0")
    keys: list[tuple[str, str]] = []
    for scope, name in zip(parts[0::2], parts[1::2]):
        if scope == "global" or not name:
            continue
        keys.append((name, ""))
        if name.lower().startswith("filter."):
            keys.append((name.rsplit(".", 1)[0] + ".required", "false"))
    env = {"GIT_CONFIG_COUNT": str(len(keys))}
    for i, (k, v) in enumerate(keys):
        env.update({f"GIT_CONFIG_KEY_{i}": k, f"GIT_CONFIG_VALUE_{i}": v})
    return env


def git(cwd: Path, *args: str, timeout: float = 20, check: bool = True) -> subprocess.CompletedProcess[str]:
    r = subprocess.run(["git", *GIT_SAFE, *args], cwd=cwd, capture_output=True, text=True, timeout=timeout,
                       env={**git_env(), **drivers_off(cwd)}, errors="replace")
    if check and r.returncode != 0:
        raise Refused("git_failed", (r.stderr or r.stdout).strip()[:600] or f"git {args[0]} failed", "", 422)
    return r


def is_repo(root: Path) -> bool:
    return (root / ".git").exists() and git(root, "rev-parse", "--is-inside-work-tree", check=False).returncode == 0


def tree(folders: Folders, f: Folder, path: str | None, depth: int, limit: int, named: list[str] | None) -> str:
    base, rel = folders.resolve(f, path, named=named)
    if not base.is_dir():
        raise Refused("not_a_folder", f"{rel} is a file", "read it with workspace_read", 422)
    root = Path(os.path.realpath(f.path))
    lines: list[str] = []
    more = 0

    def walk(d: Path, level: int) -> None:
        nonlocal more
        try:
            entries = sorted(d.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
        except OSError:
            return
        for p in entries:
            if len(lines) >= limit:
                more += 1
                continue
            r = str(p.relative_to(root))
            is_dir = p.is_dir() and not p.is_symlink()
            pad = "  " * level
            if is_dir and p.name in SKIP_DIRS:
                lines.append(f"{pad}{p.name}/  (skipped)")
            elif is_dir:
                lines.append(f"{pad}{p.name}/")
                if level + 1 < depth:
                    walk(p, level + 1)
            elif p.is_symlink():
                lines.append(f"{pad}{p.name} -> {os.readlink(p)}")
            else:
                try:
                    size = p.stat().st_size
                except OSError:
                    size = 0
                note = "  (secret: not read)" if is_secret(r) else "  (over 2 MB)" if size > MAX_BYTES else ""
                lines.append(f"{pad}{p.name}  {_size(size)}{note}")

    walk(base, 0)
    head = f"{f.id}:{rel} ({f.path}{'' if rel == '.' else '/' + rel})"
    tail = f"\n… {more} more entries (raise limit, or list a subfolder)" if more else ""
    return untrusted(f"workspace {f.id} tree", head + "\n" + "\n".join(lines) + tail)


def _size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024  # type: ignore[assignment]
    return str(n)


def read(folders: Folders, f: Folder, path: str, offset: int, limit: int, named: list[str] | None) -> str:
    p, rel = folders.resolve(f, path, named=named, read_file=True)
    if p.is_dir():
        raise Refused("is_a_folder", f"{rel} is a folder", "list it with workspace_tree", 422)
    if not p.exists():
        raise Refused("not_found", f"{rel} doesn't exist in {f.id}", "find it with workspace_tree or workspace_search", 404)
    text = p.read_text(errors="replace")
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    total = len(lines)
    start = max(1, offset)
    chunk = lines[start - 1:start - 1 + limit]
    width = len(str(start + len(chunk)))
    body = "\n".join(f"{start + i:>{width}}| {ln[:MAX_LINE]}{' …' if len(ln) > MAX_LINE else ''}" for i, ln in enumerate(chunk))
    end = start + len(chunk) - 1
    head = f"{f.id}:{rel} lines {start}–{end} of {total}" if chunk else f"{f.id}:{rel} has {total} lines; none from {start}"
    more = f"\nMore: workspace_read(folder={f.id!r}, path={rel!r}, offset={end + 1})" if end < total else ""
    return head + "\n" + untrusted(f"{f.id}:{rel}", body) + more + f"\nCite lines as {rel}:<line>."


def search(folders: Folders, f: Folder, query: str, regex: bool, glob: str | None, path: str | None,
           limit: int, named: list[str] | None) -> str:
    base, rel = folders.resolve(f, path, named=named)
    root = Path(os.path.realpath(f.path))
    hits: list[str] = []
    if shutil.which("rg"):
        hits = _rg(root, base, query, regex, glob, limit + 1)
    else:
        hits = _py_search(root, base, query, regex, glob, limit + 1)
    hits = [h for h in hits if not is_secret(h.split(":", 1)[0]) or was_named(h.split(":", 1)[0], named)]
    more = len(hits) > limit
    hits = hits[:limit]
    where = f"{f.id}:{rel}" if rel != "." else f.id
    if not hits:
        return f"No matches for {query!r} in {where}."
    head = f"{len(hits)}{'+' if more else ''} matches for {query!r} in {where} (path:line: text)"
    tail = "\n… more matches: narrow the query, glob or path" if more else ""
    return head + "\n" + untrusted(f"workspace {f.id} search", "\n".join(hits)) + tail


def _rg(root: Path, base: Path, query: str, regex: bool, glob: str | None, limit: int) -> list[str]:
    args = ["rg", "--line-number", "--no-heading", "--color=never", "--max-columns=300", "--max-columns-preview",
            "--max-filesize=2M", "--hidden", "--no-config", "-g", "!.git"]
    for d in SKIP_DIRS - {".git"}:
        args += ["-g", f"!{d}/"]
    if glob:
        args += ["-g", glob]
    if not regex:
        args.append("--fixed-strings")
    args += ["--smart-case", "-e", query, "--", str(base.relative_to(root)) if base != root else "."]
    try:
        r = subprocess.run(args, cwd=root, capture_output=True, text=True, timeout=30, errors="replace")
    except subprocess.TimeoutExpired:
        raise Refused("search_timeout", "the search took over 30 s", "narrow it with path or glob", 422) from None
    if r.returncode == 2 and not r.stdout:
        raise Refused("bad_query", (r.stderr or "rg failed").strip()[:300], "check the pattern (or pass regex=false)", 422)
    out = []
    for line in r.stdout.splitlines():
        out.append(line[2:] if line.startswith("./") else line)
        if len(out) >= limit:
            break
    return out


def _py_search(root: Path, base: Path, query: str, regex: bool, glob: str | None, limit: int) -> list[str]:
    try:
        pat = re.compile(query if regex else re.escape(query), 0 if any(c.isupper() for c in query) else re.I)
    except re.error as e:
        raise Refused("bad_query", f"not a valid pattern: {e}", "check the pattern (or pass regex=false)", 422) from None
    out: list[str] = []
    for d, dirs, files in os.walk(base):
        dirs[:] = sorted(x for x in dirs if x not in SKIP_DIRS)
        for name in sorted(files):
            p = Path(d) / name
            r = str(p.relative_to(root))
            if glob and not fnmatch.fnmatch(name, glob) and not fnmatch.fnmatch(r, glob):
                continue
            try:
                if p.stat().st_size > MAX_BYTES or is_binary(p):
                    continue
                for i, line in enumerate(p.read_text(errors="replace").split("\n"), 1):
                    if pat.search(line):
                        out.append(f"{r}:{i}:{line[:300]}")
                        if len(out) >= limit:
                            return out
            except OSError:
                continue
    return out


def git_read(f: Folder, root: Path, command: str, rev: str | None, relp: str | None, limit: int) -> str:
    """`relp`: a path the caller resolved inside the folder (folders.resolve), matched literally."""
    if command not in GIT_READ:
        raise Refused("not_read_only", f"git {command} isn't one of the read-only commands ({', '.join(GIT_READ)})",
                      "commit with workspace_git_commit; other git commands run with workspace_run", 422)
    if not is_repo(root):
        raise Refused("not_a_repo", f"{f.id} isn't a git repository", "", 422)
    if rev:
        _check_rev(root, rev)
    tail = ["--", *_pathspecs(relp, secrets=command != "log")]
    if command == "status":
        args = ["status", "--short", "--branch", "--ignore-submodules=all", *tail]
    elif command == "log":
        args = ["log", f"-n{limit}", "--date=short", "--format=%h %ad %an  %s", *([rev] if rev else []), *tail]
    elif command == "diff":
        args = ["diff", "--no-ext-diff", "--no-textconv", "--stat", "--patch", *([rev] if rev else []), *tail]
    elif command == "show":
        args = ["show", "--no-ext-diff", "--no-textconv", "--stat", "--patch", rev or "HEAD", *tail]
    else:
        args = ["branch", "-vv", "--no-color"]
    out = git(root, *args).stdout
    lines = out.split("\n")
    cut = len(lines) > 1500
    text = "\n".join(lines[:1500]) + ("\n… (cut at 1500 lines: pass a path or a narrower revision)" if cut else "")
    return f"git {command} in {f.id}\n" + untrusted(f"workspace {f.id} git {command}", text or "(nothing)")


def _check_rev(root: Path, rev: str) -> None:
    """Commits and ranges of commits only: no `rev:path`, no blob or tree by hash."""
    bad = Refused("bad_rev", f"{rev!r} isn't a commit or a range of commits",
                  "pass a commit, branch or range such as HEAD~3..HEAD (read files with workspace_read)", 422)
    if rev.startswith("-") or ":" in rev or not re.match(r"^[\w./~^@{}+-]{1,200}$", rev):
        raise bad
    for side in re.split(r"\.\.\.?", rev):
        side = re.sub(r"\^(@|-\d*)$", "", side)
        if side and git(root, "rev-parse", "--verify", "--quiet", "--end-of-options", side + "^{commit}", check=False).returncode:
            raise bad


def _pathspecs(relp: str | None, secrets: bool = True) -> list[str]:
    """The caller's path, literally (no globs or pathspec magic), and secret files left out (unless the
    path is one: the user named it)."""
    out = [f":(literal){relp}"] if relp and relp != "." else []
    if secrets and not (relp and is_secret(relp)):
        out += [x for g in SECRET_GLOBS for x in (f":(exclude,glob,icase)**/{g}", f":(exclude,glob,icase)**/{g}/**")]
    return out


def dirty(root: Path) -> list[str]:
    """Changed or untracked files in the working tree ([] when clean or not a repo)."""
    if not (root / ".git").exists():
        return []
    r = git(root, "status", "--porcelain", check=False)
    return [ln for ln in r.stdout.splitlines() if ln.strip()][:50] if r.returncode == 0 else []


def origin_of(header: str | None) -> dict:
    """X-AIHub-Origin: who called (thread, turn, the files the user named)."""
    if not header:
        return {}
    try:
        v = json.loads(header)
    except ValueError:
        return {}
    return v if isinstance(v, dict) else {}
