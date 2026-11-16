# Embed models, measured

Plan [capability-enablement](plans/capability-enablement.md) 7.3. The `embed` mod runs EmbeddingGemma 2 by default, or a smaller text-only encoder (how to choose and switch: [services/embed/setup/embed.md](../services/embed/setup/embed.md#choosing-models)). These are the numbers the choice rests on, measured on this machine on 2026-11-15 with `services/embed/evals/measure.py`.

**How.** Each model in-process, alone: load time, then 40 short texts in one batch (texts a second), the process's memory as the hub counts it (PSS plus GPU memory), and a small retrieval score on GAIFA's own fixture set (`services/embed/evals/fixture.json`): 24 short documents like those the library, chats and memory hold, and 24 questions worded differently from the document each should find (recall@1: the right one first; MRR: the mean of 1/its rank). The fixture is small and in English: it tells a model that works from one that doesn't, not two good models apart; the MTEB leaderboard (linked from the setup's model question) compares them properly.

**The machine.** Radeon 8060S (gfx1151, ROCm torch from `locks/embed.txt`); the CPU rows use a CPU-only torch (what the `cpu` variant installs), on the same Ryzen AI Max+ 395 (32 threads). This machine's ROCm torch is about 50–100 times slower on the CPU (no MKL), which is why the `cpu` variant installs its own.

| Model | Size | Reads | Dim | Device | Load | Texts a second | Memory | Recall@1 | MRR |
|---|---|---|---|---|---|---|---|---|---|
| EmbeddingGemma 2 | 1.5 GB | text, images, audio, video | 768 | GPU (bf16) | 4.7 s | 367 | 2.8 GB | 0.96 | 0.98 |
| BGE base (English) | 0.44 GB | text | 768 | GPU (fp32) | 3.3 s | 977 | 2.3 GB | 1.00 | 1.00 |
| BGE small (English) | 0.13 GB | text | 384 | GPU (fp32) | 3.1 s | 1291 | 1.9 GB | 0.96 | 0.98 |
| EmbeddingGemma 2 | 1.5 GB | text, images, audio, video | 768 | CPU (fp32) | 7.6 s | 129 | 2.0 GB | 0.96 | 0.98 |
| BGE base (English) | 0.44 GB | text | 768 | CPU (fp32) | 6.1 s | 383 | 0.9 GB | 1.00 | 1.00 |
| BGE small (English) | 0.13 GB | text | 384 | CPU (fp32) | 6.3 s | 831 | 0.6 GB | 0.96 | 0.98 |

GPU memory includes the ROCm runtime (about 1.7 GB whatever the model). On the GPU, the switch from EmbeddingGemma 2 to BGE small re-indexed this machine's library (436 outputs, 5,566 chunks, 94 chat summaries, the agent's memory) in under two minutes while search kept answering.

**What they give up.** Both BGE models read English text only, up to 512 tokens a chunk (the library's chunks are about 800 tokens, so a chunk's end is cut); pictures, audio and video are found by their titles and prompts only, and a search for them by kind answers `needs_full_model`. EmbeddingGemma 2 reads many languages and every kind in one space.

**Choosing.** With a GPU, EmbeddingGemma 2: it is fast enough and finds pictures, audio and video too. Without one, or with little memory, BGE small: 0.6 GB on the CPU and still quick. BGE base sits between them for English text.

To measure again, or another model (from `services/embed`, with the mod's venv; `--cpu` for the CPU):

```bash
.venv/bin/python -m evals.measure ../../data/models/embed embeddinggemma-2 bge-base-en-v1.5 bge-small-en-v1.5
```
