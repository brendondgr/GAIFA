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
  model that long once it has the slot (the Auto judge, page screening): past it, 504 `answer_timeout`, while the
  work finishes and keeps the slot until then.

Tests: `.venv/bin/python -m pytest -q` (fake model); `-m gpu -s` for the real one.
