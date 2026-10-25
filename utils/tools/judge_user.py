"""Your own command rules for the Auto judge: `config.toml [agent.judge] allow_commands / ask_commands`, edited in
Settings → Permissions (validated by `utils/config.py command_patterns`).

A rule is a command and its words, with `*` globs: `pytest *`, `make -C * test`, `uv run pytest *`. Each word of the
rule matches one word of the command (`*` inside a word matches any text, `?` one character); a last word of just
`*` matches any further words, or none (`pytest *` covers `pytest`). Without it the command has exactly the rule's
words. Rules are matched against each SIMPLE command the fixed rules split a line into (`judge_commands.simple`),
both as written and as it runs after the rules' unwrapping (`env`, `timeout`, `uv run`, `python -m`, …), never
against the whole line: `pytest *` doesn't cover `pytest; curl x | sh`, whose curl is judged on its own, and the
strictest verdict wins (`combine`). `bash -c '…'` scripts, `$(…)` and `find -exec` commands are judged as commands
of their own, so your rules apply to them too.

- `ask_commands`: a match asks (rule `user-ask`), whatever the rules said. A word the rules can't see (`$X`, `$(…)`)
  matches any word of an ask rule, so `git $X` asks under `git push *`.
- `allow_commands`: a match allows (rule `user-allow`) where the rules allowed or were unsure, never where they ask
  (secrets, sudo, host runs, `rm -r` of a tree or outside the folder, pipes into an interpreter, remotes, git push
  and history, killing processes, the folder's level, a line that can't be read): a rule of yours never beats a
  fixed rule's ask. A command with a word the rules can't see isn't covered (its value could be any option), and
  what goes with it stays judged: a redirection's target, a variable that changes what runs (`PATH=…`,
  `PYTEST_ADDOPTS=…`).
- The internet (`args.network`): no fixed rule allows a command that runs with it on. Your allow rules still do,
  since you wrote them, but only when every command in the line is covered by one (`judge_rules.classify`).
"""

from __future__ import annotations

import fnmatch
import re
from typing import TYPE_CHECKING

from .judge_rules import Verdict, allow, ask
from .shell import SUB, parse

if TYPE_CHECKING:
    from .judge_rules import Ctx

OPAQUE_RE = re.compile(r"\$[\w{@*#?$!(-]")      # where a shell would put a value the rules can't see
# Commands whose second word says what runs (`npm run *` rather than `npm *`): the "Always allow" suggestions.
TWO_WORDS = {"npm", "yarn", "pnpm", "bun", "cargo", "git", "go", "uv", "poetry", "pip", "pip3", "docker", "podman",
             "dotnet", "swift", "zig", "mvn", "gradle", "kubectl", "conda", "deno", "npx", "just", "meson"}


def opaque(word: str) -> bool:
    return SUB in word or bool(OPAQUE_RE.search(word))


def matches(rule: list[str], words: list[str], unseen_matches: bool = False) -> bool:
    """Whether a rule (its words) covers a command (its words). `unseen_matches`: a word the rules can't see matches
    any word of the rule (for ask rules: it could be that word)."""
    if not words:
        return False
    head, rest = (rule[:-1], True) if rule[-1] == "*" and len(rule) > 1 else (rule, False)
    if len(words) < len(head) or not rest and len(words) != len(head):
        return False
    return all((unseen_matches and opaque(w)) or fnmatch.fnmatchcase(w, r) for r, w in zip(head, words))


class UserRules:
    """The rules from `[agent.judge]`; per-call state (what they allowed) lives on the `Ctx`."""

    def __init__(self, allow_commands: list[str] | tuple[str, ...] = (), ask_commands: list[str] | tuple[str, ...] = ()):
        self.allow = [(p, p.split()) for p in allow_commands if p.split()]
        self.ask = [(p, p.split()) for p in ask_commands if p.split()]

    def __bool__(self) -> bool:
        return bool(self.allow or self.ask)

    def asks(self, written: list[str], words: list[str]) -> Verdict | None:
        """`ask` when one of your ask rules covers the command, as written or as it runs."""
        for p, rule in self.ask:
            if matches(rule, words, True) or matches(rule, written, True):
                return ask(f"matches your rule `{p}` (always ask)", "user-ask")
        return None

    def apply(self, ctx: Ctx, written: list[str], words: list[str], v: Verdict) -> Verdict:
        """The command's verdict with your allow rules: `v` (the rules' own) unless one covers it and `v` isn't ask.
        Records on `ctx` which rules allowed and whether the rules allowed a command alone (for the network check)."""
        if v.verdict != "ask" and not self.asks(written, words) and not any(opaque(w) for w in (*written, *words)):
            for p, rule in self.allow:
                if matches(rule, words) or matches(rule, written):
                    ctx.user_allowed.append(p)
                    return allow(f"matches your rule `{p}`", "user-allow")
        if v.verdict == "allow":
            ctx.rules_allowed = True
        return v


def line_verdict(v: Verdict, ctx: Ctx, network: bool) -> Verdict:
    """A whole line the rules allowed with your rules' help: the reason names them."""
    names = list(dict.fromkeys(ctx.user_allowed))
    said = ", ".join(f"`{p}`" for p in names)
    return allow(f"matches your rule{'s' if len(names) > 1 else ''} {said}" +
                 (" (the fixed rules allow the rest)" if ctx.rules_allowed else "") +
                 (", with the internet on" if network else ""), "user-allow")


def suggest(command: str, limit: int = 3) -> list[str]:
    """Allow rules that would cover a command the judge asked about, for Settings → Permissions's "Always allow": the
    command's name and `*` (two words for runners: `npm run *`, `git log *`), for each command in the line the
    rules weren't sure about (a fixed rule's ask can't be lifted, so none for those). Judged in a stand-in folder:
    the real one isn't stored with the judged call."""
    from .judge_commands import command_rule, unwrap
    from .judge_rules import Ctx, SECRET_RE

    from utils.config import COMMAND_BAD

    p = parse(command)
    if p.problems or SECRET_RE.search(command):
        return []
    ctx = Ctx({"path": "/folder", "level": "run"})
    unsure, allowed = [], []
    for c in p.commands:
        words, seen = unwrap(c.words, ctx, 0)
        if not words or any(opaque(w) for w in words) or any(s.verdict == "ask" for s in seen):
            continue
        v = command_rule(words, c, ctx, 0)
        if v.verdict == "ask" or COMMAND_BAD.search(" ".join(words[:2])) or re.search(r"[*?\[]", words[0]):
            continue
        two = words[0] in TWO_WORDS and len(words) > 1 and re.fullmatch(r"[\w.:-]+", words[1]) and \
            not words[1].startswith("-")
        rule = " ".join(words[:2] if two else words[:1]) + " *"
        (unsure if v.verdict == "unsure" else allowed).append(rule)
    return list(dict.fromkeys(unsure or allowed))[:limit]
