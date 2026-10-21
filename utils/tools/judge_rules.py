"""The judge's fixed rules (plan 30.2): the first stage of the Auto mode's judge.

`classify(call, folder) -> Verdict(verdict, reason, rule)`, where `verdict` is:
- `allow`: clearly safe (read-only commands, test runners on a known list, edits inside an Edit folder);
- `ask`: clearly needs the user (rm -rf outside build folders, `curl … | sh`, writes to dotfiles, history rewriting,
  killing processes, credentials, anything on the host, sudo);
- `unsure`: the rules can't tell; the judge's model decides (plan 30.3), with `reason` saying why.

`call` is `{tool, args, estimate?}`: `tool` a tool name (`workspace_run`, `workspace_edit`, `web_fetch`, …), `args`
its arguments, `estimate` `{seconds, memory_gb, memory_share}` for a GPU job. `folder` is the workspace folder the
call runs in: `{path, level}` with level read | edit | run | run_net. A shell command is split with `shell.parse`
and every simple command in it is judged (`a && b`, pipes, `$(…)`, `bash -c`, `env`, `xargs` and other wrappers):
one `ask` makes the whole call ask, else one `unsure` makes it unsure. The rules never deny: the hard limits and
the folder's level (Phase 27) refuse; the worst a rule does is ask.
"""

from __future__ import annotations

import ipaddress
import posixpath
import re
from typing import Any, NamedTuple
from urllib.parse import parse_qsl, urlsplit

from .shell import SUB

LEVELS = ("read", "edit", "run", "run_net")
LONG_JOB_S = 300                     # a GPU job longer than this is in the judge's scope ("a few minutes")
LONG_JOB_SHARE = 0.5                 # … or one that needs more than this share of the memory
HUGE_JOB_S = 4 * 3600                # past this the rules ask
HUGE_JOB_GB = 96
MAX_COMMAND = 4000
HIJACK_ENV_RE = re.compile(r"^(LD_PRELOAD|LD_LIBRARY_PATH|LD_AUDIT|PYTHONSTARTUP|PYTHONPATH|BASH_ENV|ENV|PROMPT_COMMAND"
                           r"|GIT_SSH_COMMAND|GIT_SSH|GIT_EXTERNAL_DIFF|GIT_ASKPASS|SSH_ASKPASS|PAGER|GIT_PAGER|EDITOR"
                           r"|VISUAL|NODE_OPTIONS|PERL5OPT|RUBYOPT)=")


class Verdict(NamedTuple):
    verdict: str                     # allow | ask | unsure
    reason: str
    rule: str


def allow(reason: str, rule: str) -> Verdict:
    return Verdict("allow", reason, rule)


def ask(reason: str, rule: str) -> Verdict:
    return Verdict("ask", reason, rule)


def unsure(reason: str, rule: str) -> Verdict:
    return Verdict("unsure", reason, rule)


def combine(verdicts: list[Verdict]) -> Verdict:
    """The strictest: any ask, else any unsure, else allow (the first of each kind gives the reason)."""
    for kind in ("ask", "unsure"):
        for v in verdicts:
            if v.verdict == kind:
                return v
    return verdicts[0] if verdicts else ask("nothing to run", "empty")


SECRET_RE = re.compile(
    r"(gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|sk-(?:ant-|proj-)?[A-Za-z0-9_-]{20,}|AKIA[0-9A-Z]{16}"
    r"|xox[abposr]-[A-Za-z0-9-]{10,}|hf_[A-Za-z0-9]{30,}|AIza[0-9A-Za-z_-]{30,}|glpat-[A-Za-z0-9_-]{20,}"
    r"|-----BEGIN [A-Z ]*PRIVATE KEY-----|authorization:\s*(?:bearer|basic)\s+\S+"
    r"|(?:password|passwd|secret|token|api[_-]?key|access[_-]?key)\s*[=:]\s*['\"]?[^\s'\"$]{6,}"
    r"|--(?:password|token|api-key)[= ]\S+)", re.IGNORECASE)
SECRET_FILE_RE = re.compile(
    r"(^|/)(\.env(\.[\w.-]+)?|\.envrc|\.netrc|\.npmrc|\.pypirc|\.git-credentials|id_(rsa|dsa|ecdsa|ed25519)(\.pub)?"
    r"|[^/]*\.(pem|key|p12|pfx|kdbx)|[^/]*credentials?[^/]*|secrets?(\.[\w]+)?|shadow|gshadow|\.htpasswd)$"
    r"|(^|/)\.(ssh|aws|gnupg|kube|docker|password-store)(/|$)", re.IGNORECASE)
# Paths whose change runs code later or changes how tools behave: never written without asking.
SENSITIVE_WRITE_RE = re.compile(
    r"(^|/)(\.git(/|$)|\.github/workflows/|\.gitlab-ci\.yml$|\.circleci/|\.husky/|\.pre-commit-config\.yaml$"
    r"|\.vscode/(tasks|settings|launch)\.json$|\.idea/|\.bashrc$|\.bash_profile$|\.profile$|\.zshrc$|\.zprofile$"
    r"|\.bash_logout$|\.inputrc$|\.gitconfig$|\.config/|\.local/|\.cache/|\.ssh/|\.gnupg/|\.aws/|\.kube/|\.docker/"
    r"|\.netrc$|\.npmrc$|\.pypirc$|\.envrc$|\.env(\.[\w.-]+)?$|\.git-credentials$|\.mcp\.json$|\.claude/|\.cursor/)")
DOCS_HOSTS = {"docs.python.org", "developer.mozilla.org", "pypi.org", "en.wikipedia.org", "docs.rs", "crates.io",
              "pkg.go.dev", "www.npmjs.com", "nodejs.org", "docs.github.com", "learn.microsoft.com",
              "docs.pytest.org", "fastapi.tiangolo.com", "docs.pydantic.dev", "huggingface.co", "readthedocs.io",
              "www.rust-lang.org", "doc.rust-lang.org", "go.dev", "man7.org", "www.postgresql.org", "sqlite.org"}
PY_DANGER_RE = re.compile(r"\b(shutil\.rmtree|os\.(remove|unlink|rmdir|removedirs|system|popen|exec\w*|spawn\w*|kill)"
                          r"|subprocess|pty\.spawn|ctypes|socket\.|__import__\(['\"](os|subprocess)|send2trash"
                          r"|\.unlink\(|\.rmdir\(|eval\(|exec\()")
RUN_REMOTE_RE = re.compile(r"\b(curl|wget|fetch)\b[^|\n]*\|\s*(sudo\s+)?(ba|z|da|k)?sh\b|base64\s+(-d|--decode)[^|\n]*\|"
                           r"\s*(ba)?sh\b|\b(eval|exec)\s*\(\s*(requests|urllib|httpx|base64|atob|fetch)", re.I)
PY_NET_RE = re.compile(r"\b(requests|httpx|urllib|aiohttp|http\.client|ftplib|smtplib|paramiko)\b")


class Ctx:
    """Where a command runs: the folder (an absolute path), the current directory inside it, and its level."""

    def __init__(self, folder: dict[str, Any] | None):
        self.root = posixpath.normpath((folder or {}).get("path") or "/nonexistent-folder")
        self.level = (folder or {}).get("level") or "read"
        self.cwd = self.root

    def at_least(self, need: str) -> bool:
        return LEVELS.index(self.level) >= LEVELS.index(need) if self.level in LEVELS else False

    def resolve(self, word: str) -> str | None:
        """The absolute path a word names, or None when it can't be known (a variable, a substitution, ~user)."""
        if SUB in word or "$" in word or word.startswith("~") and not (word == "~" or word.startswith("~/")):
            return None
        if word == "~" or word.startswith("~/"):
            return "/home/~" + word[1:]                    # outside every folder, whatever $HOME is
        return posixpath.normpath(posixpath.join(self.cwd, word))

    def inside(self, path: str) -> bool:
        return path == self.root or path.startswith(self.root.rstrip("/") + "/")

    def rel(self, path: str) -> str:
        return posixpath.relpath(path, self.root)


def write_target(word: str, ctx: Ctx, what: str = "writes") -> Verdict:
    """A path a command writes to: inside the folder and not sensitive, at Edit or above."""
    if word in ("/dev/null", "/dev/stdout", "/dev/stderr", "/dev/tty", "-") or word.isdigit():
        return allow("output to the terminal or nowhere", "write-null")
    path = ctx.resolve(word)
    if path is None:
        return ask(f"{what} to a path the rules can't know ({word.replace(SUB, '$(…)')})", "write-unknown")
    if not ctx.inside(path):
        return ask(f"{what} outside the folder ({word})", "write-outside")
    if SENSITIVE_WRITE_RE.search(ctx.rel(path)) or SECRET_FILE_RE.search(ctx.rel(path)):
        return ask(f"{what} to {ctx.rel(path)}, a dotfile or config that runs code or holds secrets", "write-dotfile")
    if not ctx.at_least("edit"):
        return ask(f"{what} a file in a folder at {ctx.level}", "write-level")
    return allow(f"{what} inside the folder", "write-inside")


def read_target(word: str, ctx: Ctx) -> Verdict | None:
    path = ctx.resolve(word)
    probe = path if path is not None else word
    if SECRET_FILE_RE.search(probe):
        return ask(f"reads {word}, which may hold credentials", "read-secret")
    return None


def edit_rule(tool: str, args: dict[str, Any], ctx: Ctx) -> Verdict:
    paths = [args.get(k) for k in ("path", "from", "to", "source", "destination") if args.get(k)]
    found = []
    for p in paths:
        p = str(p)
        if p.startswith(("/", "~")) or ".." in p.split("/"):
            found.append(ask(f"{tool} names a path outside the folder ({p})", "write-outside"))
            continue
        found.append(write_target(p, ctx, "edits" if tool != "workspace_delete" else "deletes"))
    text = "\n".join(str(args.get(k) or "") for k in ("new", "content", "message"))
    if SECRET_RE.search(text):
        found.append(ask("the change contains what looks like a password, token or key", "credentials"))
    if RUN_REMOTE_RE.search(text):
        found.append(unsure("the change adds code that downloads and runs something", "edit-run-remote"))
    if tool == "workspace_delete":
        found.append(unsure("deletes a file (undo restores it)", "delete"))
    if not found:
        return ask(f"{tool} without a path", "empty")
    v = combine(found)
    return v if v.verdict != "allow" else allow("an edit inside an Edit folder (undo restores it)", "edit-inside")


def fetch_rule(args: dict[str, Any]) -> Verdict:
    url = str(args.get("url") or "")
    try:
        u = urlsplit(url)
        host = (u.hostname or "").lower()
    except ValueError:
        return ask(f"a URL that can't be read ({url[:80]})", "url")
    if u.scheme not in ("http", "https") or not host:
        return ask(f"fetches a {u.scheme or 'schemeless'} URL", "url")
    if u.username or u.password or SECRET_RE.search(url) or any(
            re.search(r"(token|key|secret|password|passwd|auth|session|sig)", k, re.I) for k, _ in parse_qsl(u.query)):
        return ask("the URL carries credentials", "credentials")
    try:
        ip = ipaddress.ip_address(host.strip("[]"))
        if not ip.is_global:
            return ask(f"fetches a private address ({host})", "private")
    except ValueError:
        if host == "localhost" or host.endswith((".local", ".internal", ".lan", ".localhost", ".home.arpa")):
            return ask(f"fetches a local name ({host})", "private")
    if len(url) > 2000 or any(len(v) >= 64 and re.fullmatch(r"[A-Za-z0-9+/=_-]+", v) for _, v in parse_qsl(u.query)):
        return ask("the URL carries a long encoded value (it could send data out)", "exfil-url")
    if not u.query and (host in DOCS_HOSTS or any(host.endswith("." + d) for d in DOCS_HOSTS)):
        return allow(f"reads documentation on {host}", "docs")
    return unsure(f"fetches {host}", "fetch")


def gpu_rule(tool: str, est: dict[str, Any]) -> Verdict:
    secs = float(est.get("seconds") or 0)
    gb = float(est.get("memory_gb") or 0)
    share = float(est.get("memory_share") or 0)
    if secs > HUGE_JOB_S or gb > HUGE_JOB_GB:
        return ask(f"{tool} would run about {secs / 60:.0f} min or need {gb:.0f} GB", "huge-job")
    if secs <= LONG_JOB_S and share <= LONG_JOB_SHARE:
        return allow(f"{tool} is a short GPU job (about {secs:.0f} s)", "short-job")
    return unsure(f"{tool} is a long GPU job (about {secs / 60:.0f} min, {gb:.0f} GB)", "long-job")


def classify(call: dict[str, Any], folder: dict[str, Any] | None = None) -> Verdict:
    """The rules' verdict on one tool call (see the module docstring)."""
    tool = str(call.get("tool") or "")
    args = call.get("args") or call.get("arguments") or {}
    ctx = Ctx(folder)
    from .judge_commands import classify_command     # it imports this module's helpers

    if tool in ("workspace_run", "workspace_shell"):
        if (args.get("where") or "sandbox") != "sandbox":
            return ask("runs on your machine, outside the sandbox: always asks", "host")
        if not ctx.at_least("run"):
            return ask(f"commands need Run; the folder is at {ctx.level}", "run-level")
        return classify_command(str(args.get("command") or ""), ctx)
    if tool == "workspace_python":
        code = str(args.get("code") or "")
        if SECRET_RE.search(code):
            return ask("the code contains what looks like a password, token or key", "credentials")
        if m := PY_DANGER_RE.search(code):
            return ask(f"the code deletes files or runs commands ({m.group(0)})", "python-danger")
        if PY_NET_RE.search(code):
            return unsure("the code uses the network", "python-net")
        return unsure("runs Python in the sandbox", "python")
    if tool == "workspace_git_commit":
        return ask("commits ask every time (plan 27.3)", "git-commit")
    if tool in ("workspace_edit", "workspace_write", "workspace_move", "workspace_delete"):
        if not ctx.at_least("edit"):
            return ask(f"edits need Edit; the folder is at {ctx.level}", "write-level")
        return edit_rule(tool, args, ctx)
    if tool in ("web_fetch",):
        return fetch_rule(args)
    if tool in ("web_search", "workspace_folders", "workspace_tree", "workspace_read", "workspace_search",
                "workspace_git"):
        return allow("only reads", "read-tool")
    if call.get("estimate"):
        return gpu_rule(tool, call["estimate"])
    return unsure(f"{tool or 'this tool'} isn't one the rules know", "unknown-tool")
