"""The judge's rules for shell commands (plan 30.2), used by `judge_rules.classify` for `workspace_run`.

`classify_command(command, ctx)` splits the line with `shell.parse` and judges every simple command in it, after
stripping assignments and wrappers (`env`, `nohup`, `timeout`, `nice`, `xargs`, `uv run`, `python -m`, `sudo`) and
judging `bash -c` scripts and `$(…)` substitutions as commands of their own. Each command has a rule: read-only
tools and known test runners are allowed, writes are allowed inside the folder at Edit or above (never to dotfiles
or configs that run code), and removing trees, pipes into a shell, history rewriting, killing processes, disks,
remote connections, uploads, root and credentials ask. What the rules don't know is `unsure`.
"""

from __future__ import annotations

import posixpath
import re

from .judge_rules import (HIJACK_ENV_RE, LEVELS, MAX_COMMAND, SECRET_FILE_RE, SECRET_RE, SENSITIVE_WRITE_RE, Ctx,
                          Verdict, allow, ask, combine, read_target, unsure, write_target)
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
             "lscpu", "ps", "top", "htop", "pgrep", "lsof", "tput", "locale", "cal", "expr", "bc",
             "cd", "export", "unset", "set", ":", "exit", "return", "wait", "{", "}", "do", "done",
             "then", "fi", "else", "elif", "if", "for", "while", "until", "in", "case", "esac"}
TEST_RUNNERS = {"pytest", "py.test", "tox", "nox", "jest", "vitest", "mocha", "ava", "tap", "karma", "phpunit",
                "rspec", "ctest", "mypy", "pyright", "pyre", "ruff", "flake8", "pylint", "pyflakes", "pycodestyle",
                "black", "isort", "eslint", "tsc", "prettier", "stylelint", "shellcheck", "hadolint", "golangci-lint",
                "clippy-driver", "rubocop", "biome"}
PY_MODULES_OK = TEST_RUNNERS | {"unittest", "doctest", "compileall", "py_compile", "json.tool", "timeit", "pydoc",
                                "tabnanny", "pyflakes", "coverage"}
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
NPM_SCRIPT_OK = re.compile(r"^(test|tests|lint|build|check|typecheck|type-check|format:check|fmt:check|"
                           r"test:[\w:-]+|lint:[\w:-]+|build:[\w:-]+|check:[\w:-]+)$")

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
            if HIJACK_ENV_RE.match(w[0]):
                seen.append(ask(f"sets {w[0].split('=')[0]}, which makes other programs run code", "env-hijack"))
            w = w[1:]
        elif head in PRIVILEGE:
            seen.append(ask(f"{head} runs it as another user (root)", "sudo"))
            w = w[1:]
            while w and w[0].startswith("-"):
                w = w[1:]
        elif head == "env":
            w = w[1:]
            while w and (w[0].startswith("-") or "=" in w[0]):
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
        found.append(command_rule(words, cmd, ctx, depth))
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
    if base in ("export", "declare", "alias") and (hit := next((a for a in args if HIJACK_ENV_RE.match(a)), None)):
        return ask(f"sets {hit.split('=')[0]}, which makes other programs run code", "env-hijack")
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
    if base == "awk" or base == "gawk":
        if re.search(r"system\s*\(|\|\s*getline|print\s*>|\bfflush|\"\s*\|", " ".join(args)):
            return ask("awk runs commands or writes files from its program", "awk-system")
        return allow("awk reads and prints", "read-only")
    if base == "tar":
        if re.search(r"^-?[a-z]*[xc]", args[0] if args else "") or {"--extract", "--create", "-x", "-c"} & set(args):
            return unsure("tar unpacks or packs files", "tar")
        return allow("tar lists an archive", "read-only")
    if base in ("unzip", "gunzip", "bunzip2", "unxz", "7z", "zip", "gzip"):
        return unsure(f"{base} writes files", "archive")
    if base in READ_ONLY:
        if base == "cd":
            target = ctx.resolve(args[0]) if args else None
            if target is None or not ctx.inside(target):
                return unsure(f"cd leaves the folder ({' '.join(args) or '~'})", "cd-outside")
            ctx.cwd = target
        return allow(f"{base} only reads", "read-only")
    if base == "npm" or base == "yarn" or base == "pnpm" or base == "bun":
        verb = args[0] if args else ""
        script = args[1] if verb in ("run", "run-script") and len(args) > 1 else verb
        if verb in ("test", "t") or NPM_SCRIPT_OK.match(script or ""):
            return allow(f"{base} {verb} {script if script != verb else ''}".strip() + " runs the project's tests or "
                         "build", "test-runner")
        if verb in ("ls", "list", "outdated", "view", "info", "why", "explain", "config" if "get" in args else "-"):
            return allow(f"{base} {verb} only reads", "read-only")
        return unsure(f"{base} {verb} runs a project script", "script")
    if base in ("cargo", "go", "make", "gradle", "mvn", "dotnet", "swift", "zig", "cmake", "meson", "ninja", "just"):
        verb = args[0] if args else ""
        okay = {"cargo": {"test", "build", "check", "clippy", "fmt", "doc", "bench", "tree", "metadata"},
                "go": {"test", "build", "vet", "fmt", "list", "doc", "version", "env"},
                "make": None, "just": None, "ninja": None, "cmake": None, "meson": {"test", "compile", "setup"},
                "gradle": {"test", "build", "check"}, "mvn": {"test", "verify", "compile", "package"},
                "dotnet": {"test", "build"}, "swift": {"test", "build"}, "zig": {"build", "test"}}[base]
        if okay is None:
            if any(a in ("install", "uninstall", "deploy", "publish", "release", "clean", "distclean") for a in args):
                return unsure(f"{base} {' '.join(args)} may install, publish or delete", "build")
            return allow(f"{base} builds or tests the project", "test-runner")
        if verb in okay:
            if base == "cargo" and verb == "fmt" and "--check" not in args:
                return allow("cargo fmt rewrites the project's files", "formatter")
            return allow(f"{base} {verb} builds or tests the project", "test-runner")
        return unsure(f"{base} {verb} isn't a build or test the rules know", "build")
    if base in TEST_RUNNERS or base in PY_MODULES_OK:
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
            return allow(f"pip {verb} only reads", "read-only")
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
        if verb == "diff" and ("--output" in flags or "--ext-diff" in flags):
            return unsure("git diff writes to a file or runs a diff program", "git-write")
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
