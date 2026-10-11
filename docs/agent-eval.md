# Agent eval and live smoke test (plan 13.5, 14.12)

Run on 6–7 October 2026. The full account, with every prompt, transcript notes, charts and the live outputs, is the overnight report, `docs/report/report.pdf`. It and its raw data (`docs/report/data/`) and images stay on this machine (gitignored); the tables below come from that data.

## How it was run

- **Harness:** `services/agent/evals/` runs scripted conversations against the agent's HTTP API, answers its questions and parameter cards from each task's script, and grades outcomes: the right tool, the arguments it ran with, outputs exist, it asked when a choice was missing and didn't when everything was given, and it never named an output that doesn't exist.
- **30 tasks in six groups** (32 since plan 17.10): single generations, chains, must ask, must not ask, refusals and safety, and context. Each task runs 3 times; **pass^3** counts a task only when all three runs pass.
- **Dry runs:** generating tools made labelled stand-in outputs (`outputs/eval/`) instead of using the GPU, so 90 conversations per model fit in about 30 minutes. **Live runs** (`evals/live.py`) then made real outputs.
- **Vision check** (`evals/vision.py`): both Gemma 4 31B (skynet) and Gemma 4 26B (local) read a test card correctly (shapes, colours, a number).

## Results

<!-- RESULTS -->
| Run | Tasks × runs | pass@1 | pass^k | Mean time |
|---|---|---|---|---|
| Gemma 4 31B, first run (v1) | 30 × 3 | 86.7% | 21/30 (70%) | 32 s |
| 31B, v2 (leaked-reasoning fix) | 30 × 3 | 94.4% | 25/30 (83%) | 20 s |
| 31B, v3 (+2 tasks re-run) | 30 × 3 | 97.8% | 29/30 (97%) | 23 s |
| 31B, final code | 30 × 3 | 95.6% | 26/30 (87%) | 18 s |
| 31B, 5 weakest tasks re-checked | 5 × 3 | 100.0% | 5/5 (100%) | 22 s |
| 31B, all tools loaded | 30 × 1 | 100.0% | 30/30 (100%) | 33 s |
| Gemma 4 26B, 1 run (local) | 30 × 1 | 90.0% | 27/30 (90%) | 83 s |
| 26B, 3 runs (local) | 30 × 3 | 91.1% | 24/30 (80%) | 78 s |
| 26B, the 4 tasks fixed after its eval, re-checked | 4 × 3 | 91.7% | 3/4 (75%) | 120 s |
| 31B, the same 4 tasks on the fixed code | 4 × 3 | 100.0% | 4/4 (100%) | 18 s |

| Live case | Model (latest run) | Result | Time | Tools |
|---|---|---|---|---|
| L1_fox | 31B | pass | 37 s | comfy_generate_image |
| L2_image_to_3d | 31B | pass | 229 s | read_skill, read_skill, read_skill, comfy_generate_image, view_output, gen3d_make_3d, hub_ |
| L3_image_to_video | 31B, Video work session | pass | 1266 s | comfy_generate_image, comfy_animate_image |
| L4_describe_speak | 31B | pass | 80 s | comfy_generate_image, view_output, tts_speak, tts_speak |
| L7_compact_continue | 31B, re-run after fixes | pass | 556 s | comfy_generate_image, comfy_edit_image |
| L8_fork | 31B, re-run after fixes | pass | 1024 s | comfy_generate_image, comfy_edit_image |
| L10_must_ask | 31B, re-run after fixes | pass | 117 s | read_skill, gen3d_make_3d |
| L5_L6_buttons | 31B, re-run after fixes | pass | 354 s | comfy_generate_image, comfy_remove_background |
| L1_fox | 26B | pass | 62 s | comfy_generate_image |
| L4_describe_speak | 26B | pass | 113 s | comfy_generate_image, view_output, tts_speak |

(Each live case shows its latest run; the report lists every earlier failure and its cause.)

**Other live checks:**
- **Pending card and question survive restarts.** A pending parameter card and a pending question both survived `aihub restart` plus `aihub restart agent`, then finished (`evals/restart_live.py`): pass.
- **Context meter.** It was within 1.1% of the 31B's own prompt-token count (`evals/meter_check.py`).
- **Compaction.** In a thread capped at 6k tokens, 5 clears and a model-written summary still answered a question about the first turn (`evals/compact_live.py`): pass.
- **Sessions.** "LLM work", "3D work" and "Video work" were saved on the real mods, and switching between them peaked at 46 GB of a 118 GB limit; the 26B relaunched with its settings (`evals/sessions_live.py`).
- **MCP.** Claude Code listed 41 AIHub tools and called two. Its `tts_speak` call became a denied approval, and nothing ran.

**Image to 3D (plan 17.10, 2026-10-11).** Two cases joined the set, so it has 32 tasks:
- `picture_object_to_3d`: a vase picture should go to TRELLIS.2.
- `picture_character_to_3d`: a samurai picture should go to Hunyuan3D 2.1.

`img_to_3d` and `one_shot_chain` now expect the generated picture itself to go to `make_3d`, rather than a description of it given to Cube3D.

Dry runs with the 31B, 3 runs each, after the tool text was tightened:
- Both picture cases: 2/3.
- `one_shot_chain`: 2/3.

The misses are the model describing the picture to Cube3D instead of passing it. Two misses are now fixed server-side and no longer fail: gen3d uses TRELLIS.2 when a picture comes without an engine, and accepts a bare output id.
<!-- /RESULTS -->

## Gate

Plan 13.5: Stage D starts when the primary model passes 80% of tasks at pass^3. **The 31B passes.**
