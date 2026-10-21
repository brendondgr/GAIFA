# decide: decision models

AIHub mod (port 5107, plan 30.1): questions about an input (yes/no, a choice, a score) answered with a probability
per answer and no generated text. d3-lite (`vllm-sr/d3-lite`, 0.85B, Apache-2.0) first; more models are an adapter
each in `decide/models/<id>.py`. Setup, the pinned revision and what its remote code does: [setup/decide.md](setup/decide.md).

- `POST /v1/decide {input, questions: [{id, type, question, options?, scale?}], images?, videos?, model?}` →
  `{answers: {id: {probs, top, p}}, ms, model, revision}`
- `GET /v1/models`, `POST /v1/load`, `POST /v1/unload`, `GET /v1/status`
- Agent tool: `decide_ask` (risk `read`)

Tests: `.venv/bin/python -m pytest -q` (fake model); `-m gpu -s` for the real one.
