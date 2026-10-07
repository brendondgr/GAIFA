# Agent eval and live smoke test (plan 13.5, 14.12)

Run on 6–7 October 2026. The full account, with every prompt, transcript notes, charts and the live outputs, is the overnight report: [report/report.pdf](report/report.pdf). The raw data is in [report/data/](report/data/).

## How it was run

- **Harness:** `services/agent/evals/` runs scripted conversations against the agent's HTTP API, answers its questions and parameter cards from each task's script, and grades outcomes: the right tool, the arguments it ran with, outputs exist, it asked when a choice was missing and didn't when everything was given, and it never named an output that doesn't exist.
- **30 tasks in six groups:** single generations, chains, must ask, must not ask, refusals and safety, and context. Each task runs 3 times; **pass^3** counts a task only when all three runs pass.
- **Dry runs:** generating tools made labelled stand-in outputs (`outputs/eval/`) instead of using the GPU, so 90 conversations per model fit in about 30 minutes. **Live runs** (`evals/live.py`) then made real outputs.
- **Vision check** (`evals/vision.py`): both Gemma 4 31B (skynet) and Gemma 4 26B (local) read a test card correctly (shapes, colours, a number).

## Results

<!-- RESULTS -->

## Gate

Plan 13.5: Stage D starts when the primary model passes 80% of tasks at pass^3. **The 31B passes.**
