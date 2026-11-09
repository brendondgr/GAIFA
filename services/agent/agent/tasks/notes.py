"""A scheduled run's prompt part and its `task_note` tool (plan scheduled-tasks 2.4).

The *Scheduled task* part says what the run is (its task, whether anyone is watching), how to behave with no one there
(a refused call is worked around and reported; `ask_user` gets no answer), how to end (a short summary: done, refused,
left open), and the task's notes on how to do it, which earlier runs kept with `task_note`.

`task_note {action: add | replace | remove, id?, text?}` is a local tool a task's runs have, never a plain chat, and
never offered at /mcp. Notes are about how to do the task (where things are, what worked, what to skip), never facts
about the user or results of one run: those would carry one run into the next.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .store import NOTE_CHARS, NOTES_MAX, TaskError

if TYPE_CHECKING:
    from ..tools import ToolSet

TOOLS: list[dict[str, Any]] = [
    {"name": "task_note", "description": "Keep a short note on how to do this scheduled task, for its later runs: where things "
     "are, which way worked, what to skip, so the next run is quicker. Not results of this run, and nothing about the user. "
     f"At most {NOTES_MAX} notes of {NOTE_CHARS} characters; replace one that's out of date rather than adding another.",
     "parameters": {"type": "object", "properties": {
         "action": {"type": "string", "enum": ["add", "replace", "remove"]},
         "id": {"type": "string", "description": "replace, remove: the note's id (n_…)"},
         "text": {"type": "string", "description": "add, replace: the note, one or two sentences"}},
         "required": ["action"]}},
]
NAMES = {t["name"] for t in TOOLS}
UNATTENDED = ("This is a scheduled run and no one is watching. Do the task from its instructions without asking anything "
              "(ask_user gets no answer: decide, and say what you assumed). A tool call that would have needed someone's "
              "approval is refused (error `unattended`): don't retry it; do what you can without it. End with a short "
              "summary for the person who reads this later: what you did, what was refused and why, and what's left open.")
TEST = ("This is a test run of a scheduled task: the person is watching, and calls that need approval show them a card as "
        "usual. Work as the scheduled runs will, and end with the same short summary: what you did and what's left open.")


def task_text(task: dict[str, Any], notes: list[dict[str, Any]], settings: dict[str, Any]) -> str:
    out = [f"This chat is a run of the scheduled task **{task['name']}** ({task['when']}). Its first message is the task's "
           "instructions, written by the user ahead of time.",
           UNATTENDED if settings.get("unattended") else TEST]
    if notes:
        out.append("How to do this task (notes from earlier runs; task_note keeps them up to date):\n"
                   + "\n".join(f"- {n['id']}: {n['text']}" for n in notes))
    else:
        out.append("There are no notes on how to do this task yet: when you find something a later run should know (where "
                   "things are, which way worked), keep it with task_note.")
    return "\n\n".join(out)


class TaskTools:
    """Mixed into the agent's Local tools (local.py)."""

    a: Any

    async def t_task_note(self, tid: str, cid: str, args: dict[str, Any], tools: ToolSet, thread: dict[str, Any]) -> str:
        kid = (thread.get("settings") or {}).get("task")
        k = self.a.scheduled
        if not kid or k.get(str(kid)) is None:
            return self.err(tid, cid, "task_note", "not_a_task_run", "this chat isn't a run of a scheduled task",  # type: ignore[attr-defined]
                            "keep what you learned with remember instead, if the user wants it kept")
        action, nid, text = args.get("action"), str(args.get("id") or "").strip(), str(args.get("text") or "")
        try:
            if action == "add":
                note = k.add_note(kid, text, thread_id=tid)
            elif action in ("replace", "remove"):
                have = k.note(nid)
                if have is None or have["task_id"] != kid:
                    known = ", ".join(n["id"] for n in k.notes(kid)) or "none"
                    return self.err(tid, cid, "task_note", "unknown_note", f"{nid or '(no id)'} isn't one of this task's notes",  # type: ignore[attr-defined]
                                    f"use one of: {known}")
                if action == "remove":
                    k.remove_note(nid)
                    note = None
                else:
                    note = k.update_note(nid, text, thread_id=tid)
            else:
                return self.err(tid, cid, "task_note", "invalid_arguments", "action is add, replace or remove")  # type: ignore[attr-defined]
        except TaskError as e:
            fix = "replace or remove an old note first" if e.code == "too_many_notes" else "send one or two sentences"
            return self.err(tid, cid, "task_note", e.code, e.detail, fix)  # type: ignore[attr-defined]
        return self.ok(tid, cid, "task_note", {"saved": note, "notes": [{"id": n["id"], "text": n["text"]}  # type: ignore[attr-defined]
                                                                        for n in k.notes(kid)]})
