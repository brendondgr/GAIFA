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

### Capabilities (plan 20.5, 2026-10-19)

On 2026-10-19 `skynet` served **MiniCPM-V 4.7 35B** (vLLM, on the remote machine), not the Gemma 4 31B above, so these numbers aren't comparable with the earlier rows. The set is now **41 tasks in seven groups**: nine `capability` tasks join the 32. They cover:
- a local edit;
- an edit with a reference picture;
- a body to 3D;
- text to 3D three ways (asks, Cube3D, picture first);
- full quality by default, and a quick preset when asked;
- an edit that must not regenerate.

Dry runs, 3 each, at concurrency 16 (the local GPU stayed free for the user's TTS tests):

| Run | Tasks × runs | pass@1 | pass^k | Mean time |
|---|---|---|---|---|
| MiniCPM-V 4.7, first run | 41 × 3 | 80.5% | 29/41 (71%) | 19 s |
| after fixing the seeds and the rules below | 41 × 3 | 90.2% | 35/41 (85%) | 17 s |
| final (turned-off mods' skills hidden) | 41 × 3 | 92.7% | 35/41 (85%) | 17 s |

**What the first run found:**
- **Duplicate seed pictures** from earlier days (two "Eval samurai, front view"), so the agent rightly asked which one. Seeds are now made once, across days, with new titles.
- **A task that asked for something the picture doesn't have** (a helmet).
- **"Make it winter" made a new picture.** The text-to-image tool now says to use edit_image for changes, and the prompt says to edit an existing picture rather than generate one.
- **`run_workflow` was used for an edit.** comfy now refuses a pack that a task tool covers, naming that tool.
- **The rule to ask about the 3D method was always on,** so it fired with gen3d turned off. It moved into gen3d's `make_3d` description, and a turned-off mod's skills are hidden and refused.

**Still failing at 3/3:**
- `three_steps` 0/3: no `update_todos`.
- `read_my_paragraph` 1/3: the model asks for the text in plain words, as the prompt says, but the check wants a question card.
Both predate Phase 20.

**The 2/3 cases:**
- picking `sam3d_body` and `intorealism` from the words;
- passing `references`;
- asking once for text to 3D.

**Live runs with real outputs (2026-10-20, `evals/live.py` L11–L17):** 7 cases, 6 passed on the first run. L13 passed when re-run.

| Case | Result | Time |
|---|---|---|
| L11 local edit ("remove the red headband") | pass: `comfy_edit_image` at full quality; headband gone, face, hair and clothes kept | 129 s |
| L12 object → 3D | pass: TRELLIS.2 with the picture | 285 s |
| L13 character → 3D | first run asked which engine in words (it named Hunyuan3D as best); re-run pass | 126 s |
| L14 body → 3D | pass: SAM 3D Body | 19 s |
| L15 quick shape | pass: SAM 3D Objects | 88 s |
| L16 text → 3D | pass: Cube3D, no picture | 98 s |
| L17 text → 3D, picture first | pass: a picture, then an image engine on it | 227 s |

One flaw seen: the edit of a transparent-background picture came back 1024 × 1024 on white, with black bars at the sides. That comes from the edit pack's output, not from engine choice.

### Preferences (plan 21.6, 2026-10-20)

Five `preference` tasks (46 in all). A task's preferences are seeded for its own chat only (`scope: thread`), because tasks run at once, and they're removed afterwards:
- `pref_prefilled`: a seeded workflow preference fills the card;
- `pref_stated`: "from now on…" calls `hub_set_preference`;
- `carry_in_chat`: a card edit carries to the next card in the chat;
- `explicit_beats_pref`: the user's words win over a preference;
- `answer_learned`: a seeded answer stops the 3D question.

| Run | Tasks × runs | pass@1 | pass^k | Mean time |
|---|---|---|---|---|
| MiniCPM-V 4.7, full set | 46 × 3 | 88.4% | 39/46 (85%) | 17 s |
| the 5 preference tasks, after two check fixes | 5 × 3 | 100% | 5/5 | 13 s |

The two fixes were in the checks, not the agent:
- `pref_prefilled` read the event list wrongly;
- `carry_in_chat`'s card script kept state across runs that ran at once. It now edits only the card whose prompt names the cat.

`text_to_3d_asks` fell to 0/3 in this run: the model went straight to Cube3D without asking. The rule lives in `make_3d`'s description, which the model reads only once the tool is loaded.

### The learner's first runs (plan 22.8, 2026-10-20)

**Run 1** (comfy, gen3d; stopped by hand):
- **comfy** adopted version 3, a note that the tool is `comfy_remove_background`. The model had called `comfy:remove_background` four times.
- **gen3d** adopted version 5, with notes saying `gen3d_make_3d` needs an image and `comfy_generate_image` takes `workflow_id`. Both are wrong for today's tools: its evidence predated Phase 20, and the editor never saw the current schemas. The gate passed it at 89.5% against 89.5%.
- It was rolled back to version 3 and marked rejected. The fix: tool notes are now checked against today's schemas, and the editors see those schemas.

**Run 2** (gen3d, tts, hub; 621 s, 18 model calls):
- **gen3d:** the gate failed (84% against 89%), so it kept version 3.
- **tts:** adopted version 11, a note that `tts_speak` takes `name`, not `voice`. A real error in a chat. The schema check refused a PREF proposal that used `voice` twice.
- **hub:** the gate failed (90% against 100%).

**Afterwards,** the full set on harness version 11, with every write a stand-in in dry runs:

| Run | Tasks × runs | pass@1 | pass^k | Mean time |
|---|---|---|---|---|
| MiniCPM-V 4.7, harness v11 | 46 × 3 | 89.9% | 39/46 (85%) | 16 s |

**At 0/3:**
- `three_steps` and `text_to_3d_asks`, as before.
- `picture_character_to_3d`: one run hit the fallback model `gemma4-26B`, which isn't loaded while the GPU is kept free; the others picked TRELLIS.2 or stopped after the search.
<!-- /RESULTS -->

## Gate

Plan 13.5: Stage D starts when the primary model passes 80% of tasks at pass^3. **The 31B passes.** Plan 20.5 keeps the gate for every change to the agent's tools or prompt: MiniCPM-V 4.7 passes at 85%.
