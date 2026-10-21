"""Split a shell command into simple commands, for the judge's rules (plan 30.2). Not a shell: enough of POSIX sh
and bash to see every command a line would run.

`parse(cmd)` returns the simple commands in order (each its words, redirections and how it's joined to the next:
`&&`, `||`, `;`, `|`, `&`), every command substitution (`$(…)`, backticks, `<(…)`, `>(…)`) as text to parse again,
and problems (an unclosed quote or bracket). A word that contains a substitution or a `$variable` holds `SUB` or
keeps its `$`, so the rules can tell a path they can't know. Here-document bodies are skipped, not run.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

SUB = "\x00sub\x00"                  # where a command substitution's output goes in a word
OPS = ("&&", "||", "|&", ";;", "|", "&", ";", "\n")
REDIRECT_RE = re.compile(r"(\d*|&)(>>|>\||>&|&>>|&>|>|<<<|<<-|<<|<&|<>|<)")


@dataclass
class Command:
    words: list[str] = field(default_factory=list)
    redirects: list[tuple[str, str]] = field(default_factory=list)   # (operator, target), e.g. (">", "out.txt")
    joined: str = ""                 # the operator after it: && || ; | & (or "" at the end)
    piped: bool = False              # its stdin comes from the command before it


@dataclass
class Parsed:
    commands: list[Command]
    substitutions: list[str]
    problems: list[str]


def _closing(cmd: str, i: int) -> int:
    """The index of the `)` matching the `(` at `i`, skipping quotes; -1 when there's none."""
    depth, j, n = 0, i, len(cmd)
    while j < n:
        c = cmd[j]
        if c == "\\":
            j += 2
            continue
        if c == "'":
            k = cmd.find("'", j + 1)
            if k < 0:
                return -1
            j = k + 1
            continue
        if c == '"':
            j += 1
            while j < n and cmd[j] != '"':
                j += 2 if cmd[j] == "\\" else 1
            j += 1
            continue
        if c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                return j
        j += 1
    return -1


def parse(cmd: str) -> Parsed:
    commands: list[Command] = []
    subs: list[str] = []
    problems: list[str] = []
    cur = Command()
    word: list[str] | None = None
    pending: str | None = None           # a redirection waiting for its target
    heredocs: list[str] = []             # delimiters whose bodies start after the next newline
    piped = False
    i, n = 0, len(cmd)

    def add(text: str) -> None:
        nonlocal word
        word = (word or []) + [text]

    def end_word() -> None:
        nonlocal word, pending
        if word is None:
            return
        w = "".join(word)
        word = None
        if pending is not None:
            if pending.startswith("<<") and pending != "<<<":
                heredocs.append(w.replace("'", "").replace('"', ""))
            cur.redirects.append((pending, w))
            pending = None
        else:
            cur.words.append(w)

    def end_command(op: str) -> None:
        nonlocal cur, piped
        end_word()
        if cur.words or cur.redirects:
            cur.joined = op
            cur.piped = piped
            commands.append(cur)
        piped = op in ("|", "|&")
        cur = Command()

    def substitution(start: int) -> int:
        """`start` is at the `(` of `$(`, `<(` or `>(`: record the inside, return the index after `)`."""
        k = _closing(cmd, start)
        if k < 0:
            problems.append("an unclosed $( or (")
            subs.append(cmd[start + 1:])
            return n
        subs.append(cmd[start + 1:k])
        return k + 1

    while i < n:
        c = cmd[i]
        if c in " \t":
            end_word()
            i += 1
        elif c == "\\":
            if i + 1 < n and cmd[i + 1] != "\n":
                add(cmd[i + 1])
            i += 2
        elif c == "'":
            k = cmd.find("'", i + 1)
            if k < 0:
                problems.append("an unclosed ' quote")
                add(cmd[i + 1:])
                break
            add(cmd[i + 1:k])
            i = k + 1
        elif c == '"':
            j, buf = i + 1, []
            while j < n and cmd[j] != '"':
                if cmd[j] == "\\" and j + 1 < n:
                    buf.append(cmd[j + 1])
                    j += 2
                elif cmd.startswith("$(", j):
                    j = substitution(j + 1)
                    buf.append(SUB)
                elif cmd[j] == "`":
                    k = cmd.find("`", j + 1)
                    subs.append(cmd[j + 1:k] if k > 0 else cmd[j + 1:])
                    if k < 0:
                        problems.append("an unclosed ` quote")
                    buf.append(SUB)
                    j = k + 1 if k > 0 else n
                else:
                    buf.append(cmd[j])
                    j += 1
            if j >= n:
                problems.append('an unclosed " quote')
            add("".join(buf))
            i = j + 1
        elif cmd.startswith("$(", i) or (word is None and cmd.startswith(("<(", ">("), i)):
            i = substitution(i + 1)
            add(SUB)
        elif c == "`":
            k = cmd.find("`", i + 1)
            if k < 0:
                problems.append("an unclosed ` quote")
            subs.append(cmd[i + 1:k] if k > 0 else cmd[i + 1:])
            add(SUB)
            i = k + 1 if k > 0 else n
        elif c == "#" and word is None:
            k = cmd.find("\n", i)
            i = n if k < 0 else k
        elif (op := next((o for o in OPS if cmd.startswith(o, i)), None)) is not None:
            end_command(op if op != "\n" else ";")
            i += len(op)
            if op == "\n" and heredocs:              # skip the here-document bodies
                for delim in heredocs:
                    while i < n:
                        k = cmd.find("\n", i)
                        line = cmd[i:] if k < 0 else cmd[i:k]
                        i = n if k < 0 else k + 1
                        if line.strip() == delim:
                            break
                heredocs.clear()
        elif c in "()":
            end_command(";")
            i += 1
        elif (m := REDIRECT_RE.match(cmd, i)) and (word is None or "".join(word).isdigit()):
            if word is not None:                       # 2>file: the digits are the fd, not a word
                word = None
            end_word()
            pending = m.group(1) + m.group(2)
            i = m.end()
            if m.group(2) in (">&", "<&") and i < n and (cmd[i].isdigit() or cmd[i] == "-"):
                cur.redirects.append((pending, cmd[i]))     # 2>&1 duplicates a descriptor
                pending = None
                i += 1
        else:
            add(c)
            i += 1
    end_command("")
    if pending is not None:
        problems.append(f"a redirection {pending} without a target")
    depth = 0
    for ch in re.sub(r"'[^']*'|\"(?:\\.|[^\"\\])*\"", "", cmd):
        depth += (ch == "(") - (ch == ")")
        if depth < 0:
            problems.append("an unmatched )")
            break
    return Parsed(commands, subs, problems)
