# decide: decision models

GAIFA mod (port 5107, plan 30.1): questions about an input (yes/no, a choice, a score) answered with a probability
per answer and no generated text. d3-lite (`vllm-sr/d3-lite`, 0.85B, Apache-2.0) first; more models are an adapter
each in `decide/models/<id>.py`. Setup, the pinned revision and what its remote code does: [setup/decide.md](setup/decide.md).

- `POST /v1/decide {input, questions: [{id, type, question, options?, scale?}], images?, videos?, model?}` →
  `{answers: {id: {probs, top, p}}, ms, model, revision}`
- `GET /v1/models`, `POST /v1/load`, `POST /v1/unload`, `GET /v1/status`
- Agent tool: `decide_ask` (risk `read`)
- Each ask takes an `interactive` lease from GAIFA's GPU queue around the model call (plan 31.3; `decide/gpu_slot.py`
  is an identical copy of `services/_template/gpu_slot.py`), then asks for memory if it switches models. On the CPU it
  takes none. A lease cancelled from the queue answers 409 `gpu_cancelled`. `X-GAIFA-Answer-Within: <s>` gives the
  model that long once it has the slot and the model is loaded (the Auto judge, page screening; a load after an idle
  unload doesn't count, plan web-approvals 1.3): past it, 504 `answer_timeout`, while the work finishes and keeps the
  slot until then.

Tests: `.venv/bin/python -m pytest -q` (fake model); `-m gpu -s` for the real one.

## Adding a decision model

Any decision model can be set up here and made the Auto judge (plan capability-enablement, section 2): the machine
test and the judge's eval advise, they never block. What a model needs depends on whether its **family** already
has an adapter.

**A model of a family that has one (d3 today): a card, no code.** Put the model in `data/models/decide/<id>/`
(`hf download <repo> --revision <commit> --local-dir data/models/decide/<id>`) with a `gaifa-decide.toml` beside it
(or ship it as `decide/models/cards/<id>.toml`):

```toml
family = "d3"                       # the adapter that reads it (decide/models/__init__.py FAMILIES)
id = "d3-something"                 # the folder's name, what Settings and `model` call it
name = "d3-something (Decision 3.0)"
repo = "org/d3-something"
revision = "<the 40-character commit whose code you read>"
license = "apache-2.0"
params = "2B"
weights = "model-00001-of-00001.safetensors"
threshold = 0.35                    # the Auto judge's cutoff for this model (see below)
tuned = false                       # true once the judge's eval measured that cutoff
# inputs = ["text", "image", "video"]
[pinned]                            # every code file at that revision, and the manifest, by sha256
"modeling_d3.py" = "<sha256>"
"MODEL_MANIFEST.json" = "<sha256>"
```

The family's `check` refuses the model while any pinned file differs or a code file isn't listed, exactly as for
d3-lite: **read the code at that revision first** (what it imports, opens, downloads, runs; setup/decide.md, "The
remote code", is the example), then pin it. `GET /v1/models` lists it; once its files match, it is usable.

**A model of a new family: an adapter.** `decide/models/<family>.py`, a class with the members listed in
`decide/models/__init__.py` (`ID`, `NAME`, `REPO`, `REVISION`, `FOLDER`, `LICENSE`, `PARAMS`, `INPUTS`, `WEIGHTS`,
`FAMILY`, `THRESHOLD`, `TUNED`; `check`, `load`, `unload`, `ask`), added to `ADAPTERS` and `FAMILIES`. Answers are
the mod's shape (`{probs, top, p}` per question). Copy `tests/test_pinned.py` for its pins and `tests/test_adapters.py`
for the listing, and record what its code does in `setup/decide.md`. A folder no adapter reads is listed by
`GET /v1/models` as not usable, with this as the fix; `gaifa setup --prompt decide` hands the task to a coding agent.

**The threshold.** The judge allows a call when the lowest "safe" probability reaches it. Measure it with the judge's
eval (from the repo root: `uv run python -m services.agent.evals.judge.run --name <id> --backend decide --model <id>
--threshold <t>`, for a few values of `t`; `--summary` compares the runs): pick the cutoff that keeps unsafe calls
asked at the rate d3-lite's 0.35 does, then set `threshold` and `tuned = true`. Until then the
model is selectable as the judge and Settings says "not tuned for this model".

**How fast it is here.** `POST /v1/selftest {"model": "<id>"}` (or Settings → Services → Test): load, one answer, ten
more, the device and memory in one sentence; the last result per model is kept (`data/state/decide/selftest.json`)
and shown beside the model under Settings → Permissions → Auto judge.
