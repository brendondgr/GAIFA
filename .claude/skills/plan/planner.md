# Plan format reference (AIHub)

Plans are explicit, hierarchical and checkable. They name **where** work happens and **how we know it's done**; they never contain implementations.

## 1. Introduction
One or two short paragraphs: the problem, the approach, and which architecture sections and plan phases it touches.

## 2. Gaps & unanswered questions
- **Simple gap** → state the assumption and proceed: `- **Retention of old logs**: unknown. *Assumption:* keep 14 days, matching metrics_1m.`
- **Complex gap** → ask it and flag it: `- **Should comfy auto-start at boot?** *Needs a human answer.*`
- Anything that deletes data, touches the existing apps' running services, or writes outside the project root is always a complex gap unless the plan already approves it.

## 3. Phases and steps
Match `docs/backend-plan.md` exactly.

```markdown
## Phase N — <Title>

- [ ] **N.1 <Short title, often the file: `utils/foo.py`>.**
  - **<Aspect>:** what to build, naming files, classes, functions and routes.
  - **Why:** one line, only when the reason isn't obvious from the architecture.
  *Done when:* <tests or observable checks that prove it>.
- [ ] **N.2 …**

**Wire — Phase N:** which UI areas switch from mock to live, and what that shows.

**Checks & deliverables — Phase N**
- [ ] <end-to-end checks, browser checks>
- [ ] Delivered: <list of files/modules>.
```

Rules for every step:
- **Locations are mandatory:** file paths, classes, functions, routes, config keys, manifest fields.
- **Order matters:** each step only depends on earlier steps. Say so when a step needs something from the user (a running service, an approval).
- **No large code blocks.** Names, signatures and data shapes (a JSON or TOML snippet of a few lines) are fine; implementations aren't.
- **A `Done when` line on every step** that names the tests (in `utils/tests/<area>/test_<behavior>.py`) or the check.
- **Commit line:** each step ends with tests passing and a commit `AIHub (N.k): <sentence>`; the plan doesn't repeat this per step, it's stated once in "How to work this plan".
- **Docs in sync:** if the step changes behavior described in `architecture.md` or the brief's §6 / §11.7, say which section to update.
- **Sizes:** keep files under ~500 lines (hard limit 800); split a step if it would produce a larger file.

## 4. Deliverables table
End a standalone plan (not an amendment) with:

| Deliverable | Description | Location |
| --- | --- | --- |
| `<module>` | what it does | `utils/<module>.py` |
| Tests | small, fast tests over a subset of data (fake mods, fixtures) | `utils/tests/<area>/test_<behavior>.py` |

Tests are always a deliverable.

## Review checklist (when asked to evaluate a plan)
- Does every step name locations and a `Done when`?
- Is anything planned that contradicts architecture §2 decisions or the mod contract (§4)?
- Does any step write outside the project root, delete data, or stop a running app without an approval point?
- Are the UI areas that go live listed, and does the contract test still cover them?
- Are docs updates named for every behavior change?
