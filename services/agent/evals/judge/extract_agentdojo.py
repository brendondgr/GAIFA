"""Extract AgentDojo's tasks into the judge's inputs (plan 30.4). Run with the benchmark's own venv, made by
bench.sh: `data/state/judge-bench/.venv/bin/python -I services/agent/evals/judge/extract_agentdojo.py OUT.jsonl`.

Each user task gives its request (`prompt`) and the calls that complete it (`ground_truth`); each injection task
gives the attacker's goal, the calls that achieve it, and the benchmark's own attack text for that goal. The text stays in data/state/judge-bench/ (gitignored).
"""

from __future__ import annotations

import json
import sys

from agentdojo.attacks.important_instructions_attacks import DEFAULT_USER_NAME, ImportantInstructionsAttack
from agentdojo.task_suite.load_suites import get_suites

VERSION = "v1.2"


def calls(task, env) -> list[dict]:
    return [{"function": c.function, "args": dict(c.args)} for c in task.ground_truth(env)]


def main(out: str) -> None:
    n = 0
    with open(out, "w") as f:
        for name, suite in get_suites(VERSION).items():
            env = suite.load_and_inject_default_environment({})
            for tid, t in suite.user_tasks.items():
                row = {"kind": "user", "suite": name, "id": tid, "text": t.PROMPT, "calls": calls(t, env.model_copy(deep=True))}
                f.write(json.dumps(row, default=str) + "\n")
                n += 1
            for tid, t in suite.injection_tasks.items():
                row = {"kind": "injection", "suite": name, "id": tid, "text": t.GOAL, "calls": calls(t, env.model_copy(deep=True)),
                       # the benchmark's own attack text for this goal (its "important_instructions" attack), for 30.6
                       "attack": ImportantInstructionsAttack._JB_STRING.format(user=DEFAULT_USER_NAME, model="AI assistant",
                                                                               goal=t.GOAL)}
                f.write(json.dumps(row, default=str) + "\n")
                n += 1
    print(f"{n} tasks to {out}")


if __name__ == "__main__":
    main(sys.argv[1])
