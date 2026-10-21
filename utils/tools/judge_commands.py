"""The judge's rules for shell commands (plan 30.2), used by `judge_rules.classify` for `workspace_run`.

`classify_command(command, ctx)` splits the line with `shell.parse` and judges every simple command in it, after
stripping assignments, shell keywords (`if`, `then`, `do`, `{`) and wrappers (`env`, `nohup`, `timeout`, `nice`,
`xargs`, `uv run`, `python -m`, `sudo`) and judging `bash -c` scripts and `$(…)` substitutions as commands of their
own. Each command has a rule: read-only tools and known test runners are allowed only with the options on their
lists (`judge_rules.OPTS`, `RUNNER_OPTS`, `BUILD_OPTS`; any other option, or an operand that could turn into one, is
`unsure`), and test runners only with paths inside the folder; writes are allowed inside the folder at Edit or above
(never to dotfiles or configs that run code), and removing trees, pipes into a shell, history rewriting, killing
processes, disks, remote connections, uploads, root and credentials ask. What the rules don't know is `unsure`.
"""

from __future__ import annotations

import posixpath
import re

from .judge_rules import (ANY_ARGS, BUILD_OPTS, CONFIG_ENV_RE, GENERIC_RUNNER, HIJACK_ENV_RE, LEVELS, MAX_COMMAND, OPTS,
                          RUNNER_OPTS, SECRET_FILE_RE, SECRET_RE, SENSITIVE_WRITE_RE, SUB_OK, Ctx, Verdict, allow, ask,
                          combine, read_target, unsure, write_target)
from .shell import SUB, Command, parse

__all__ = ["classify_command", "LEVELS"]

BUILD_DIRS = {"build", "dist", "node_modules", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache",
              "target", ".tox", ".nox", "htmlcov", ".coverage", "coverage", ".next", ".nuxt", ".turbo", ".parcel-cache",
              ".eggs", "out", ".gradle", ".hypothesis", ".cache"}
READ_ONLY = {"ls", "cat", "head", "tail", "less", "more", "wc", "grep", "egrep", "fgrep", "rg", "ag", "fd", "tree",
             "pwd", "echo", "printf", "which", "type", "file", "stat", "du", "df", "date", "uname", "whoami", "id",
             "sort", "uniq", "cut", "tr", "diff", "cmp", "comm", "jq", "yq", "basename", "dirname", "realpath",
             "readlink", "true", "false", "test", "[", "sleep", "seq", "column", "nl", "xxd", "hexdump", "od",
             "md5sum", "sha1sum", "sha256sum", "sha512sum", "b2sum", "cksum", "strings", "rev", "fold", "fmt",
             "expand", "unexpand", "paste", "join", "tac", "zcat", "bat", "hostname", "nproc", "free", "uptime",
             "lscpu", "ps", "top", "pgrep", "lsof", "tput", "locale", "cal", "expr", "bc",
             "cd", "export", "unset", "set", ":", "exit", "return", "wait", "{", "}", "do", "done",
             "then", "fi", "else", "elif", "if", "for", "while", "until", "in", "case", "esac"}
TEST_RUNNERS = {"pytest", "py.test", "tox", "nox", "jest", "vitest", "mocha", "ava", "tap", "karma", "phpunit",
                "rspec", "ctest", "mypy", "pyright", "pyre", "ruff", "flake8", "pylint", "pyflakes", "pycodestyle",
                "black", "isort", "eslint", "tsc", "prettier", "stylelint", "shellcheck", "hadolint", "golangci-lint",
                "clippy-driver", "rubocop", "biome"}
PY_MODULES_OK = TEST_RUNNERS | {"unittest", "doctest", "compileall", "py_compile", "tabnanny", "pyflakes",
                                "coverage"}     # not timeit (it runs code from its arguments) or pydoc (-w writes)
FORMAT_WRITERS = {"black", "isort", "prettier", "ruff", "biome"}     # rewrite files unless told to check
INTERPRETERS = {"sh", "bash", "zsh", "dash", "ksh", "fish", "csh", "tcsh", "python", "python3", "python2", "perl",
                "ruby", "node", "deno", "bun", "php", "lua", "Rscript", "pwsh", "powershell", "osascript", "source",
                "."}
SHELLS = {"sh", "bash", "zsh", "dash", "ksh", "fish"}
WRAPPERS = {"nohup", "time", "command", "builtin", "exec", "setsid", "unbuffer", "catchsegv", "chronic"}
PRIVILEGE = {"sudo", "doas", "su", "pkexec", "run0", "sudoedit"}
KILLERS = {"kill", "pkill", "killall", "xkill", "skill", "shutdown", "reboot", "halt", "poweroff", "telinit", "init"}
DISK = {"dd", "mkfs", "fdisk", "sfdisk", "cfdisk", "parted", "gparted", "wipefs", "shred", "mount", "umount", "swapon",
        "swapoff", "losetup", "cryptsetup", "mkswap", "blkdiscard", "hdparm", "fsck", "debugfs", "tune2fs"}
PERSISTENCE = {"crontab", "at", "batch", "launchctl", "chsh", "useradd", "usermod", "userdel", "passwd", "visudo",
               "update-alternatives", "ldconfig", "insmod", "rmmod", "modprobe", "sysctl", "iptables", "nft", "ufw",
               "firewall-cmd", "setenforce", "chattr"}
EXFIL = {"nc", "ncat", "netcat", "socat", "telnet", "ssh", "scp", "sftp", "ftp", "tftp", "rsh", "rcp", "sshpass"}
FETCHERS = {"curl", "wget", "http", "https", "aria2c", "xh", "lynx", "w3m"}
INSTALLERS = {("pip", "install"), ("pip3", "install"), ("pip", "download"), ("npm", "install"), ("npm", "i"),
              ("npm", "ci"), ("npm", "add"), ("yarn", "add"), ("yarn", "install"), ("pnpm", "add"),
              ("pnpm", "install"), ("pnpm", "i"), ("uv", "add"), ("uv", "sync"), ("uv", "lock"), ("cargo", "install"),
              ("cargo", "add"), ("cargo", "fetch"), ("go", "get"), ("go", "install"), ("gem", "install"),
              ("bundle", "install"), ("composer", "install"), ("composer", "require"), ("poetry", "add"),
              ("poetry", "install"), ("conda", "install"), ("mamba", "install"), ("brew", "install"),
              ("apt", "install"), ("apt-get", "install"), ("dnf", "install"), ("yum", "install"), ("pacman", "-S"),
              ("deno", "install"), ("bun", "add"), ("bun", "install")}
GIT_READ = {"status", "log", "diff", "show", "blame", "ls-files", "ls-tree", "rev-parse", "describe", "shortlog",
            "grep", "cat-file", "whatchanged", "count-objects", "rev-list", "name-rev", "merge-base", "help",
            "version", "check-ignore", "for-each-ref", "show-ref", "annotate", "range-diff", "var"}
GIT_HISTORY = {"rebase", "filter-branch", "filter-repo", "replace", "update-ref", "reflog", "gc", "prune",
               "push", "reset", "clean", "commit", "am", "notes", "worktree", "submodule", "lfs", "config",
               "remote", "credential", "send-email", "request-pull", "archive", "bundle", "daemon",
               "instaweb", "svn", "p4", "fast-import", "hook"}
GIT_NETWORK = {"clone", "fetch", "pull", "ls-remote"}
GIT_WRITE_OPTS = ("output", "ext-diff", "open-files-in-pager")    # write a file, or run a program
NPM_SCRIPT_OK = re.compile(r"^(test|tests|lint|build|check|typecheck|type-check|format:check|fmt:check|"
                           r"test:[\w:-]+|lint:[\w:-]+|build:[\w:-]+|check:[\w:-]+)$")
TARGET_RE = re.compile(r"^[A-Za-z0-9_.-]+$")         # a plain make/just target: no assignments, no paths

def _flags(words: list[str]) -> set[str]:
    """Single-letter flags merged (-rf → r, f) plus long ones, up to `--`."""
    out: set[str] = set()
    for w in words:
        if w == "--":
            break
        if w.startswith("--"):
            out.add(w.split("=", 1)[0])
        elif w.startswith("-") and len(w) > 1:
            out.update(w[1:])
    return out


def options(base: str, words: list[str], ctx: Ctx, spec: tuple[str, str, str]
            ) -> tuple[Verdict | None, list[str], list[str]]:
    """Every option in `words` checked against `spec` (see OPTS): (a verdict when one isn't on the list, else None;
    the operands; the options' values). A value that names a secret asks, as a file name does."""
    short, valued, longs = spec
    switch, takes = set(), {}
    for n in longs.split():
        k = n.rstrip("=")
        takes.update({k: len(n) - len(k)}) if k != n else switch.add(k)
    pos: list[str] = []
    vals: list[str] = []
    i = 0
    while i < len(words):
        a = words[i]
        i += 1
        if a == "--":
            pos += words[i:]
            break
        if a.startswith("--"):
            name, eq, val = a[2:].partition("=")
            if name in takes:
                n = takes[name] - (1 if eq else 0)
                vals += ([val] if eq else []) + words[i:i + n]
                i += n
            elif name not in switch:
                return unsure(f"{base} {a.split('=')[0]} isn't an option the rules know is safe", "option"), pos, vals
        elif a.startswith("-") and len(a) > 1:
            for j, c in enumerate(a[1:], 1):
                if c in valued:
                    if a[j + 1:]:
                        vals.append(a[j + 1:])
                    else:
                        vals += words[i:i + 1]
                        i += 1
                    break
                if not (c in short or c.isdigit() and "#" in short):
                    return unsure(f"{base} -{c} isn't an option the rules know is safe", "option"), pos, vals
        else:
            pos.append(a)
    for v in vals:
        if found := read_target(v, ctx):
            return found, pos, vals
    return None, pos, vals


def _opaque(words: list[str]) -> str | None:
    """A word whose value the rules can't see: a substitution or variable (it can split into words, one of them an
    option), or a glob or brace at its start (a file named `--pre=sh` matches `*`)."""
    return next((w for w in words if SUB in w or "$" in w or w[:1] in ("*", "?", "[") or
                 w[:1] == "{" and re.search(r",|\.\.", w)), None)


def _outside(words: list[str], ctx: Ctx) -> str | None:
    """The first word that names a path outside the folder (absolute, `~` or `..`), also after `=`, `:` or `,`
    (--cov-report=html:/tmp/x)."""
    for w in words:
        for piece in re.split(r"[=:,]", w):
            if piece.startswith(("/", "~")) or ".." in piece.split("/"):
                path = ctx.resolve(piece)
                if path is None or not ctx.inside(path):
                    return w
    return None


def read_only_rule(base: str, args: list[str], ctx: Ctx) -> Verdict:
    """A read-only tool: allowed only with options on its list (OPTS) and operands that can't turn into options."""
    if base in ANY_ARGS:
        if base == "printf" and args[:1] and args[0].startswith("-v"):
            return unsure("printf -v sets a shell variable", "option")
        return allow(f"{base} only reads", "read-only")
    if base not in SUB_OK and (w := _opaque(args)):
        return unsure(f"{base} gets an argument the rules can't see ({w.replace(SUB, '$(…)')}); it could be an option",
                      "dynamic")
    found, pos, _ = options(base, args, ctx, OPTS[base])
    if found:
        return found
    if base == "date" and [p for p in pos if not p.startswith("+")] or base == "hostname" and pos:
        return unsure(f"{base} with an operand sets the clock or the host name", "option")
    if base != "date" and (p := next((p for p in pos if p.startswith("+")), None)):
        return unsure(f"{base} {p}: a + operand can be a command", "option")
    if base in ("uniq", "xxd") and len(pos) > 1:
        return unsure(f"{base} writes to its second file name ({pos[1]})", "write-option")
    if base in ("jq", "yq") and re.search(r"\$ENV\b|\benv\b", " ".join(pos)):
        return unsure(f"{base} prints the environment, which may hold secrets", "env-dump")
    return allow(f"{base} only reads", "read-only")


def runner_rule(base: str, args: list[str], ctx: Ctx, spec: tuple[str, str, str]) -> Verdict | None:
    """A test runner's or build tool's options and paths: None when they're on its list and inside the folder."""
    if w := _opaque(args):
        return unsure(f"{base} with arguments from another command ({w.replace(SUB, '$(…)')})", "dynamic")
    found, pos, vals = options(base, args, ctx, spec)
    if found:
        return found
    if w := _outside(pos + vals, ctx):
        return unsure(f"{base} names a path outside the folder ({w})", "runner-outside")
    return None


def make_rule(base: str, args: list[str], ctx: Ctx) -> Verdict:
    """make and just run the folder's recipes (the test-runner policy), with plain targets and a few switches only:
    `make --eval`, `-f`, `-C`, `-I`, `CC=…` and `just --shell` change what runs."""
    if w := _opaque(args):
        return unsure(f"{base} with arguments from another command ({w.replace(SUB, '$(…)')})", "dynamic")
    ok = (r"-[kBsSnqiwrR]+|-j\d*|--(keep-going|silent|quiet|always-make|dry-run|just-print|no-print-directory|"
          r"print-directory|jobs(=\d+)?)") if base == "make" else r"-n|--dry-run|-l|--list|-q|--quiet|--summary"
    for a in args:
        if not (re.fullmatch(ok, a) or TARGET_RE.match(a) and not a.startswith("-")):
            return unsure(f"{base} {a}: not a plain target or a switch the rules know", "build")
    if any(a in ("install", "uninstall", "deploy", "publish", "release", "clean", "distclean") for a in args):
        return unsure(f"{base} {' '.join(args)} may install, publish or delete", "build")
    return allow(f"{base} builds or tests the project", "test-runner")


def tar_rule(args: list[str], ctx: Ctx) -> Verdict:
    """tar lists an archive (-t with -f FILE and -v) and nothing else: --checkpoint-action, -I and --to-command run
    programs, and a `host:file` archive is opened over rsh."""
    w = (["-" + args[0]] if args and not args[0].startswith("-") else args[:1]) + args[1:]
    if re.search(r"^-[a-z]*[xc]", w[0] if w else "") or {"--extract", "--create", "-x", "-c"} & set(w):
        return unsure("tar unpacks or packs files", "tar")
    listing, i = False, 0
    while i < len(w):
        a = w[i]
        i += 1
        if a in ("--list", "--verbose"):
            listing |= a == "--list"
        elif a.startswith("--file=") or a == "--file" or re.fullmatch(r"-[tv]*f", a) or re.fullmatch(r"-[tv]+", a):
            listing |= "t" in a.split("=")[0] and not a.startswith("--file")
            if a.endswith("f") or a == "--file" or a.startswith("--file="):
                name = a.split("=", 1)[1] if "=" in a else (w[i] if i < len(w) else "")
                i += 0 if "=" in a else 1
                if ":" in name:
                    return unsure(f"tar opens {name} over the network (host:file)", "tar")
                if found := read_target(name, ctx):
                    return found
        elif a.startswith("-"):
            return unsure(f"tar {a} isn't an option the rules know is safe", "tar")
    return allow("tar lists an archive", "read-only") if listing else unsure("tar without -t", "tar")


def _env_assign(word: str) -> Verdict | None:
    if HIJACK_ENV_RE.match(word):
        return ask(f"sets {word.split('=')[0]}, which makes other programs run code", "env-hijack")
    if CONFIG_ENV_RE.match(word):
        return unsure(f"sets {word.split('=')[0]}, which changes what programs run or read", "env-config")
    return None


def _args(words: list[str]) -> list[str]:
    out, end = [], False
    for w in words:
        if not end and w == "--":
            end = True
        elif end or not w.startswith("-") or w == "-":
            out.append(w)
    return out


def unwrap(words: list[str], ctx: Ctx, depth: int) -> tuple[list[str], list[Verdict]]:
    """Strip assignments and wrappers (env, nohup, timeout, nice, xargs, uv run, python -m) to the command that runs;
    `bash -c` scripts and xargs targets are judged on the way."""
    seen: list[Verdict] = []
    w = list(words)
    while w:
        head = posixpath.basename(w[0]) if "/" in w[0] and not w[0].startswith(".") else w[0]
        if re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", w[0]):
            if v := _env_assign(w[0]):
                seen.append(v)
            w = w[1:]
        elif head in ("{", "then", "do", "else", "elif", "if", "while", "until", "!", "(", "time"):
            w = w[1:]                       # a keyword before a command: the command after it runs
        elif head in ("for", "select", "case", "function"):
            return [], seen                 # `for x in …`: words, not a command (substitutions are judged apart)
        elif head in PRIVILEGE:
            seen.append(ask(f"{head} runs it as another user (root)", "sudo"))
            w = w[1:]
            while w and w[0].startswith("-"):
                w = w[1:]
        elif head == "env":
            w = w[1:]
            while w and (w[0].startswith("-") or "=" in w[0]):
                if not w[0].startswith("-") and (v := _env_assign(w[0])):
                    seen.append(v)
                if w[0] in ("-u", "-C", "-S", "--chdir", "--unset", "--split-string"):
                    if w[0] in ("-S", "--split-string") and len(w) > 1:
                        w = w[1].split() + w[2:]
                        break
                    w = w[2:]
                else:
                    w = w[1:]
            if not w:
                return ["printenv"], seen
        elif head in WRAPPERS:
            w = w[1:]
            while w and w[0].startswith("-"):
                w = w[1:]
        elif head in ("nice", "ionice", "chrt", "taskset", "stdbuf", "timeout", "flock", "prlimit"):
            w = w[1:]
            while w and (w[0].startswith("-") or (head in ("timeout", "chrt", "taskset", "flock") and
                                                   re.match(r"^[\d.]+[smhd]?$|^0x[0-9a-f]+$", w[0]))):
                w = w[2:] if w[0] in ("-n", "-c", "-p", "-s", "-k", "-o", "-e", "-i") else w[1:]
        elif head == "xargs":
            w, holder = w[1:], None
            while w and w[0].startswith("-"):
                if w[0].startswith("-I") or w[0].startswith("--replace"):
                    holder = (w[0][2:] or (w[1] if len(w) > 1 else "{}")) if w[0].startswith("-I") else "{}"
                    w = w[1:] if w[0] != "-I" else w[2:]
                    continue
                w = w[2:] if w[0] in ("-n", "-P", "-d", "-L", "-s", "-a", "-E", "-l") else w[1:]
            if not w:
                return ["echo"], seen
            # it runs with arguments the rules can't see (in place of -I's placeholder, or at the end)
            w = [x.replace(holder, SUB) for x in w] if holder else w + [SUB]
        elif head in ("uv", "poetry", "pipenv", "pdm", "hatch", "rye") and len(w) > 1 and w[1] == "run":
            w = w[2:]
            while w and w[0].startswith("-"):
                w = w[2:] if w[0] in ("--with", "--python", "-p", "--project", "--directory", "--package",
                                      "--extra", "--group", "--env-file") else w[1:]
        elif head in ("python", "python3") and len(w) > 2 and w[1] == "-m":
            mod = w[2]
            if mod == "pip":
                w = ["pip"] + w[3:]
            elif mod in PY_MODULES_OK or mod.split(".")[0] in PY_MODULES_OK:
                w = [mod.split(".")[0]] + w[3:]
            else:
                return w, seen
        elif head in SHELLS and len(w) > 1:
            rest = [x for x in w[1:] if x not in ("-e", "-x", "-u", "-o", "pipefail", "-l", "--login", "-i",
                                                   "--norc", "--noprofile", "-eu", "-euo", "-ex", "-eux")]
            if rest and re.fullmatch(r"-[a-z]*c[a-z]*", rest[0]):      # -c, and merged flags such as -lc, -ec
                if len(rest) < 2:
                    return w, seen
                if SUB in rest[1] or "$" in rest[1].split("'")[0] and re.search(r"\$\{?\w", rest[1]):
                    seen.append(ask(f"{head} -c runs a script built from another command's output or a variable",
                                    "run-substitution"))
                    return [], seen
                seen.append(classify_command(rest[1], ctx, depth + 1))
                return [], seen
            return w, seen
        else:
            return w, seen
    return w, seen


def simple(cmd: Command, ctx: Ctx, depth: int) -> Verdict:
    """One simple command, after its wrappers: its own rule, its redirections, and what feeds it."""
    found: list[Verdict] = []
    for op, target in cmd.redirects:
        if ">" in op and not (target.isdigit() or target == "-"):
            found.append(write_target(target, ctx, "redirects output"))
        elif op in ("<",) and (v := read_target(target, ctx)):
            found.append(v)
    words, seen = unwrap(cmd.words, ctx, depth)
    found += seen
    if words:
        v = command_rule(words, cmd, ctx, depth)
        found.append(ctx.user.apply(ctx, cmd.words, words, v) if ctx.user else v)   # your rules (judge_user.py)
    if ctx.user and (v := ctx.user.asks(cmd.words, words)):
        found.append(v)
    return combine(found) if found else allow("nothing runs", "noop")


def command_rule(w: list[str], cmd: Command, ctx: Ctx, depth: int) -> Verdict:
    name = w[0]
    base = posixpath.basename(name)
    args, flags = w[1:], _flags(w[1:])
    dynamic = any(SUB in x for x in w)
    for a in args if base not in ("tee", "touch", "mkdir", "truncate") else []:   # reading a secret is never routine
        if not a.startswith("-") and (v := read_target(a, ctx)):
            return v
    if base in INTERPRETERS and cmd.piped and not [a for a in args if not a.startswith("-")]:
        return ask(f"pipes text into {base}, which runs it as code", "pipe-to-shell")
    if base in INTERPRETERS and any(SUB in a for a in args) or base == "eval" and dynamic:
        return ask(f"{base} runs the output of another command as code", "run-substitution")
    if base in PRIVILEGE:
        return ask(f"{base} runs as root", "sudo")
    if base in KILLERS or (base == "fuser" and "k" in flags):
        return ask(f"{base} stops processes or the machine", "kill")
    if base == "systemctl" or base == "service":
        if any(re.match(r"-[HM]|--host|--machine", a) for a in args):
            return ask(f"{base} --host reaches another machine", "remote")
        verb = next((a for a in args if not a.startswith("-")), "")
        if verb in ("status", "show", "list-units", "list-unit-files", "is-active", "is-enabled", "cat", ""):
            return allow("reads service state", "systemctl-read")
        return ask(f"systemctl {verb} changes a running service", "kill")
    if base in DISK or base.startswith("mkfs"):
        return ask(f"{base} works on disks or raw devices", "disk")
    if base in PERSISTENCE:
        return ask(f"{base} changes the system or schedules something to run later", "persistence")
    if base in EXFIL:
        return ask(f"{base} connects to another machine", "remote")
    if base == "printenv" or (base in ("env", "set", "export", "declare") and not args):
        return unsure("prints the environment, which may hold secrets", "env-dump")
    if base in ("export", "declare", "alias") and (hit := next((v for a in args if (v := _env_assign(a))), None)):
        return hit
    if base == "rm" or base == "rmdir" or base == "unlink":
        return rm_rule(base, args, flags, ctx)
    if base == "find":
        return find_rule(args, ctx, depth)
    if base == "git":
        return git_rule(args, ctx)
    if base in FETCHERS:
        return fetch_command(base, args, flags, ctx)
    if any((base, a) == pair for pair in INSTALLERS for a in args[:1]) or (base == "uv" and args[:2] == ["pip", "install"]):
        if args[:1] and base in ("apt", "apt-get", "dnf", "yum", "pacman", "brew"):
            return ask(f"{base} installs system packages", "system-install")
        if "-g" in args or "--global" in args or "--user" in args or "--break-system-packages" in args:
            return ask(f"{base} installs outside the folder", "global-install")
        if not ctx.at_least("run_net"):
            return ask(f"{base} {args[0]} downloads packages, and the folder isn't at Run + network", "net-level")
        return unsure(f"{base} {args[0]} downloads and installs packages (their install scripts run)", "install")
    if base in ("chmod", "chown", "chgrp"):
        mode = next((a for a in args if not a.startswith("-")), "")
        if base != "chmod" or "R" in flags or "--recursive" in flags or re.search(r"[+=][rwxXt]*s|^[0-7]?[4-7][0-7]{3}$",
                                                                                   mode):
            return ask(f"{base} changes owners, setuid bits or whole trees", "chmod")
        return combine([write_target(a, ctx, "changes permissions of") for a in _args(args)[1:]] or
                       [allow("chmod", "chmod")])
    if base in ("mv", "cp", "ln", "install", "rsync"):
        targets = _args(args)
        if base == "rsync" and any(re.match(r"^[\w.-]+@?[\w.-]*:", t) for t in targets):
            return ask("rsync to or from another machine", "remote")
        found = [write_target(t, ctx, f"{base} writes") for t in targets[-1:]]
        if base == "mv":
            found += [write_target(t, ctx, "moves") for t in targets[:-1]]
        found += [v for t in targets[:-1] if (v := read_target(t, ctx))]
        v = combine(found) if found else allow("nothing to copy", base)
        return v if v.verdict != "allow" or base == "cp" else unsure(f"{base} moves or links files; nothing undoes it",
                                                                     base)
    if base in ("mkdir", "touch", "tee", "truncate"):
        targets = [a for a in _args(args) if not re.match(r"^\d+[KMG]?$", a)]
        found = [write_target(t, ctx, f"{base} writes") for t in targets]
        if base == "truncate":
            found.append(unsure("truncate empties files", "truncate"))
        return combine(found) if found else allow(f"{base} with nothing to write", base)
    if base == "sed" and ("i" in flags or "--in-place" in flags):
        files = _args(args)[1:]
        return combine([write_target(f, ctx, "edits in place") for f in files] or [unsure("sed -i", "sed")])
    if base in ("awk", "gawk", "mawk", "nawk"):
        prog = " ".join(args)
        if re.search(r"system\s*\(|\|\s*getline|\bprintf?\b[^;}\n]*\||\bfflush|\"\s*\|", prog):
            return ask("awk runs commands from its program", "awk-system")
        found, pos, _ = options(base, args, ctx, ("", "Fv", "field-separator= assign="))   # not -f, -e, -i, -l
        if found or dynamic or re.fullmatch(r"\$\{?[A-Za-z_]\w*\}?", pos[0] if pos else ""):
            return found or unsure(f"{base} with arguments from another command", "dynamic")
        if re.search(r"\bprintf?\b[^;}\n]*>|getline\s*(\w+\s*)?<|ENVIRON|PROCINFO|@load|@include", prog):
            return unsure("awk writes or reads a file named in its program, or reads the environment", "awk-write")
        return allow("awk reads and prints", "read-only")
    if base == "tar":
        return tar_rule(args, ctx)
    if base in ("unzip", "gunzip", "bunzip2", "unxz", "7z", "zip", "gzip"):
        return unsure(f"{base} writes files", "archive")
    if base in READ_ONLY:
        if base == "cd":
            target = ctx.resolve(args[0]) if args else None
            if target is None or not ctx.inside(target):
                return unsure(f"cd leaves the folder ({' '.join(args) or '~'})", "cd-outside")
            ctx.cwd = target
            return allow("cd only reads", "read-only")
        return read_only_rule(base, args, ctx)
    if base == "npm" or base == "yarn" or base == "pnpm" or base == "bun":
        verb = args[0] if args else ""
        script = args[1] if verb in ("run", "run-script") and len(args) > 1 else verb
        extra = args[2:] if verb in ("run", "run-script") else args[1:]
        if verb in ("test", "t") or NPM_SCRIPT_OK.match(script or ""):
            if [a for a in extra if a not in ("--silent", "-s", "--if-present")]:
                return unsure(f"{base} {verb} with more arguments (they reach the script or set {base}'s config)",
                              "script")
            return allow(f"{base} {verb} {script if script != verb else ''}".strip() + " runs the project's tests or "
                         "build", "test-runner")
        if verb in ("ls", "list", "outdated", "view", "info", "why", "explain", "config" if "get" in args else "-"):
            if (w := _opaque(extra)) or [a for a in extra if a.startswith("-") and a.split("=")[0] not in
                                         ("--all", "-a", "--json", "--long", "-l", "--parseable", "-p", "--depth",
                                          "--omit", "--prod", "--dev", "--global", "-g")]:
                return unsure(f"{base} {verb} with options the rules don't know", "option")
            return allow(f"{base} {verb} only reads", "read-only")
        return unsure(f"{base} {verb} runs a project script", "script")
    if base in ("cargo", "go", "make", "gradle", "mvn", "dotnet", "swift", "zig", "cmake", "meson", "ninja", "just"):
        verb = args[0] if args else ""
        okay = {"cargo": {"test", "build", "check", "clippy", "fmt", "doc", "bench", "tree", "metadata"},
                "go": {"test", "build", "vet", "fmt", "list", "doc", "version", "env"},
                "make": None, "just": None, "ninja": None, "cmake": None, "meson": {"test", "compile", "setup"},
                "gradle": {"test", "build", "check"}, "mvn": {"test", "verify", "compile", "package"},
                "dotnet": {"test", "build"}, "swift": {"test", "build"}, "zig": {"build", "test"}}[base]
        if base in ("make", "just"):
            return make_rule(base, args, ctx)
        rest = args if okay is None else args[1:]
        if base == "go":                    # go's flags take one dash: -run, -count=1
            rest = ["-" + a if re.match(r"-[a-z]", a) else a for a in rest]
        if (okay is None or verb in okay) and (found := runner_rule(base, rest, ctx, BUILD_OPTS[base])):
            return found
        if okay is None:
            if any(a in ("install", "uninstall", "deploy", "publish", "release", "clean", "distclean") for a in args):
                return unsure(f"{base} {' '.join(args)} may install, publish or delete", "build")
            return allow(f"{base} builds or tests the project", "test-runner")
        if verb in okay:
            if base == "cargo" and verb == "fmt" and "--check" not in args:
                return allow("cargo fmt rewrites the project's files", "formatter")
            return allow(f"{base} {verb} builds or tests the project", "test-runner")
        return unsure(f"{base} {verb} isn't a build or test the rules know", "build")
    if base == "coverage":
        sub, m = (args[0] if args else ""), (args.index("-m") if "-m" in args else 0)
        if sub == "run" and 0 < m < len(args) - 1 and args[m + 1] in TEST_RUNNERS | {"unittest"} and \
                all(re.fullmatch(r"--(branch|parallel-mode|source=[\w.,/-]+)|-p", a) for a in args[1:m]):
            return command_rule(args[m + 1:], cmd, ctx, depth)          # coverage run -m pytest …: pytest's rule
        if sub not in ("report", "html", "xml", "json", "lcov", "combine", "erase", "debug"):
            return unsure(f"coverage {sub} runs code the rules can't see", "interpreter")
    if base in TEST_RUNNERS or base in PY_MODULES_OK:
        if found := runner_rule(base, args, ctx, RUNNER_OPTS.get(base, GENERIC_RUNNER)):
            return found
        if base in FORMAT_WRITERS and not ({"--check", "--diff", "check", "--dry-run", "-c"} & set(args)) \
                and not (base == "ruff" and args[:1] == ["check"] and "--fix" not in args):
            return combine([allow(f"{base} rewrites files", "formatter")] +
                           [write_target(a, ctx, f"{base} rewrites") for a in _args(args) if a not in ("format", "check")])
        if dynamic:
            return unsure(f"{base} with arguments from another command", "dynamic")
        return allow(f"{base} runs the project's tests or checks", "test-runner")
    if base == "pip" or base == "pip3":
        verb = args[0] if args else ""
        if verb in ("list", "show", "freeze", "check", "--version", "help", "index", "inspect"):
            found, _, _ = options(base, args[1:], ctx, ("oulevfq", "", "format= outdated uptodate local editable "
                                                        "exclude-editable not-required verbose files all quiet path="))
            return found or allow(f"pip {verb} only reads", "read-only")    # not --log FILE: it writes
        if verb == "uninstall":
            return unsure("pip uninstall removes packages", "install")
        return unsure(f"pip {verb}", "install")
    if base in INTERPRETERS or base == "eval":
        if args in (["--version"], ["-V"], ["-v"]) and base not in ("source", ".", "eval"):
            return allow("prints the version", "read-only")
        if not args or all(a.startswith("-") for a in args):
            return unsure(f"{base} reads code from its input", "interpreter")
        return unsure(f"{base} runs code the rules can't see", "interpreter")
    if name.startswith(("./", "/", "../")) or "/" in name:
        path = ctx.resolve(name)
        if path is None or not ctx.inside(path):
            return unsure(f"runs {name}, outside the folder", "program-outside")
        return unsure(f"runs {ctx.rel(path)}, a program in the folder", "program")
    return unsure(f"{base} isn't a command the rules know", "unknown")


def rm_rule(base: str, args: list[str], flags: set[str], ctx: Ctx) -> Verdict:
    targets = _args(args)
    recursive = bool({"r", "R", "--recursive", "d", "--dir"} & flags) or base == "rmdir"
    if not targets:
        return allow(f"{base} with nothing to remove", "rm-noop")
    found = []
    for t in targets:
        if t in ("/", "/*", "~", "~/", "~/*", "*", ".", "./", "./*", "..", "../", "../*") or "*" in posixpath.dirname(t):
            found.append(ask(f"{base} {t} removes a whole tree", "rm-tree"))
            continue
        path = ctx.resolve(t)
        if path is None:
            found.append(ask(f"{base} of a path the rules can't know ({t.replace(SUB, '$(…)')})", "rm-unknown"))
        elif not ctx.inside(path) or path == ctx.root:
            found.append(ask(f"{base} {t} outside the folder", "rm-outside"))
        elif SENSITIVE_WRITE_RE.search(ctx.rel(path)) or SECRET_FILE_RE.search(ctx.rel(path)):
            found.append(ask(f"{base} {t}: a dotfile, config or .git", "rm-dotfile"))
        elif not ctx.at_least("edit"):
            found.append(ask(f"{base} in a folder at {ctx.level}", "write-level"))
        elif posixpath.basename(path) in BUILD_DIRS or posixpath.basename(path).endswith((".egg-info", ".pyc")):
            found.append(allow(f"{base} {t}: a build or cache folder", "rm-build"))
        elif "*" in t:
            found.append(unsure(f"{base} {t} removes every file that matches", "rm-glob"))
        elif recursive:
            found.append(ask(f"{base} -r {t} removes a folder that isn't a build or cache folder", "rm-tree"))
        else:
            found.append(unsure(f"{base} {t} deletes a file; nothing undoes it", "rm-file"))
    return combine(found)


def find_rule(args: list[str], ctx: Ctx, depth: int) -> Verdict:
    pattern = ("-name", "-iname", "-path", "-ipath", "-wholename", "-iwholename", "-regex", "-iregex", "-lname",
               "-ilname")
    for i, a in enumerate(args):            # `find . $X` could expand to -exec …; `-name '*.py'` is a pattern
        if (w := _opaque([a])) and not (i and args[i - 1] in pattern and SUB not in a and "$" not in a and
                                        re.search(r"[\w.]", a)):
            return unsure(f"find gets an argument the rules can't see ({w.replace(SUB, '$(…)')})", "dynamic")
    if "-delete" in args:
        return ask("find -delete removes every file it matches", "rm-tree")
    found = []
    for flag in ("-exec", "-execdir", "-ok", "-okdir"):
        while flag in args:
            i = args.index(flag)
            end = next((j for j in range(i + 1, len(args)) if args[j] in (";", "+", "\\;")), len(args))
            inner = [a if a != "{}" else SUB for a in args[i + 1:end]]
            if inner:
                found.append(simple(Command(words=inner), ctx, depth + 1))
            args = args[:i] + args[end + 1:]
    if {"-fprint", "-fprint0", "-fprintf", "-fls"} & set(args):
        found.append(unsure("find writes its list to a file", "find-write"))
    found.append(allow("find lists files", "read-only"))
    return combine(found)


def git_rule(args: list[str], ctx: Ctx) -> Verdict:
    while args and args[0].startswith("-"):
        if args[0] == "-c" or args[0].startswith("--config") or args[0] in ("--exec-path",):
            return ask("git -c sets config for this run (it can make git run programs)", "git-config")
        if args[0] in ("-C", "--git-dir", "--work-tree", "--namespace"):
            path = ctx.resolve(args[1]) if len(args) > 1 else None
            if path is None or not ctx.inside(path):
                return ask(f"git {args[0]} points outside the folder", "git-outside")
            args = args[2:]
        else:
            args = args[1:]
    if not args:
        return allow("git's help", "read-only")
    verb, rest = args[0], args[1:]
    flags = _flags(rest)
    if verb in GIT_READ:
        if w := _opaque(rest):
            return unsure(f"git {verb} gets an argument the rules can't see ({w.replace(SUB, '$(…)')})", "dynamic")
        for a in rest[:rest.index("--") if "--" in rest else len(rest)]:
            name = a[2:].split("=", 1)[0]
            # git takes any unambiguous prefix of a long option: --outp is --output
            if a.startswith("--") and len(name) >= 1 and any(d.startswith(name) for d in GIT_WRITE_OPTS) or \
                    verb == "grep" and re.match(r"-[^-]*O", a) or verb == "help" and a.startswith("-") and \
                    a not in ("-a", "--all", "-g", "--guides"):
                return unsure(f"git {verb} {a.split('=')[0]} writes a file or runs a program", "git-write")
        for a in rest:                      # git show HEAD:.env prints the file
            if ":" in a and not a.startswith("-") and (found := read_target(a.split(":", 1)[1], ctx)):
                return found
        return allow(f"git {verb} only reads", "git-read")
    if verb == "branch":
        if {"d", "D", "--delete", "m", "M", "--move", "f", "--force", "c", "C", "--set-upstream-to", "u"} & flags:
            return ask("git branch deletes, renames or moves a branch", "git-history")
        return allow("git branch lists or makes a branch", "git-read") if len(_args(rest)) <= 1 else \
            unsure("git branch from a start point", "git")
    if verb == "tag":
        if {"d", "--delete", "f", "--force"} & flags:
            return ask("git tag deletes or moves a tag", "git-history")
        return allow("git tag lists tags", "git-read") if not _args(rest) or "l" in flags else unsure("git tag", "git")
    if verb == "stash":
        sub = rest[0] if rest else "push"
        if sub in ("list", "show"):
            return allow("git stash list only reads", "git-read")
        if sub in ("drop", "clear"):
            return ask(f"git stash {sub} throws away stashed work", "git-history")
        return unsure(f"git stash {sub} moves uncommitted work", "git")
    if verb in ("checkout", "restore", "switch"):
        if "--" in rest or "." in rest or verb == "restore" or {"f", "--force", "--discard-changes"} & flags:
            return ask(f"git {verb} can throw away uncommitted changes", "git-history")
        return unsure(f"git {verb} changes the working tree", "git")
    if verb == "add":
        return allow("git add stages changes", "git-add") if ctx.at_least("edit") else ask("git add in a folder at "
                                                                                             f"{ctx.level}", "write-level")
    if verb == "push":
        return ask("git push sends commits to another machine", "git-push")
    if verb == "commit":
        if "--amend" in flags:
            return ask("git commit --amend rewrites the last commit", "git-history")
        return ask("commits ask every time (plan 27.3)", "git-commit")
    if verb == "reset":
        if {"--hard", "--merge", "--keep"} & flags:
            return ask("git reset --hard throws away work", "git-history")
        return unsure("git reset moves the branch or unstages", "git")
    if verb in GIT_HISTORY:
        if verb in ("config", "remote") and (not rest or rest[0] in ("--get", "--list", "-l", "-v", "--get-all",
                                                                    "get-url", "show")):
            return allow(f"git {verb} only reads", "git-read")
        if verb == "reflog" and (not rest or rest[0] in ("show", "list")):
            return allow("git reflog only reads", "git-read")
        if verb == "worktree" and rest[:1] == ["list"]:
            return allow("git worktree list only reads", "git-read")
        return ask(f"git {verb} rewrites history, changes config or reaches a remote", "git-history")
    if verb in GIT_NETWORK:
        if not ctx.at_least("run_net"):
            return ask(f"git {verb} reaches a remote, and the folder isn't at Run + network", "net-level")
        return unsure(f"git {verb} downloads from a remote", "git-network")
    return unsure(f"git {verb} isn't one the rules know", "git")


def fetch_command(base: str, args: list[str], flags: set[str], ctx: Ctx) -> Verdict:
    upload = {"d", "F", "T", "--data", "--data-binary", "--data-raw", "--data-urlencode", "--form", "--upload-file",
              "--post-data", "--post-file", "--body-data", "--body-file", "--json"}
    if upload & flags or re.search(r"(^|\s)-X\s*(POST|PUT|PATCH|DELETE)|--method[= ](POST|PUT|DELETE)", " ".join(args),
                                   re.I) or (base in ("http", "https", "xh") and any("=" in a for a in args[1:])):
        return ask(f"{base} sends data to a server", "upload")
    if not ctx.at_least("run_net"):
        return ask(f"{base} reaches the internet, and the folder isn't at Run + network", "net-level")
    outs = [args[i + 1] for i, a in enumerate(args[:-1]) if a in ("-o", "--output", "-O", "--output-document")]
    found = [write_target(o, ctx, f"{base} saves") for o in outs if o != "-"]
    found.append(unsure(f"{base} downloads from the internet", "download"))
    return combine(found)


def classify_command(command: str, ctx: Ctx, depth: int = 0) -> Verdict:
    if depth > 4:
        return ask("commands nested more than four deep", "nested")
    if not command.strip():
        return ask("an empty command", "empty")
    if len(command) > MAX_COMMAND:
        return unsure(f"a {len(command)}-character command", "long")
    if SECRET_RE.search(command):
        return ask("the command contains what looks like a password, token or key", "credentials")
    if re.search(r":\s*\(\s*\)\s*\{.*:\s*\|\s*:", command):
        return ask("a fork bomb", "fork-bomb")
    p = parse(command)
    if p.problems:
        return ask(f"the command can't be read safely ({p.problems[0]})", "parse")
    found = []
    for c in p.commands:
        found.append(simple(c, ctx, depth))
        if c.joined == "&" and found[-1].verdict == "allow":
            found[-1] = allow(found[-1].reason + " (in the background)", found[-1].rule)
    found += [classify_command(s, ctx, depth + 1) for s in p.substitutions]
    return combine(found)
