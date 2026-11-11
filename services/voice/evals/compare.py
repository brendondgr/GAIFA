"""Q4_K_M against Q8_0 (plan voice-speech-model 4.1): the same spoken prompts through both sizes of the model.

    cd services/voice
    .venv/bin/python -m evals.compare --hub http://127.0.0.1:7000 --out ../../docs/voice-eval.md

For each size it loads the model (POST /v1/load), holds the conversations in evals/prompts.json through the mod's
own WebSocket, and records: the time from the end of your speech to the first audio, how fast speech is made, the
memory, how well it wrote your words down (against the prompt's text), how intelligible its own speech is (the stt
mod's Whisper transcript of the reply against the reply's text; skipped when --stt doesn't answer), and whether
the answer holds the expected fact. The prompts are spoken once by the model's own male voice (POST /v1/speech) and
kept; the replies are saved in pairs (<n>-<id>-q4_k_m.wav, …-q8_0.wav) for listening. One size at a time; nothing
else should use the GPU during a run.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from pathlib import Path
from typing import Any

import httpx

from . import score
from .client import Talk, read_wav, write_wav

HERE = Path(__file__).parent
LABELS = {"q4_k_m": "Q4_K_M", "q8_0": "Q8_0"}


def conversations(prompts: list[dict[str, Any]], tools: bool) -> list[list[dict[str, Any]]]:
    """The prompts as conversations: each alone, a follow-up in the conversation of the turn it needs."""
    by_id = {p["id"]: [p] for p in prompts if p["kind"] != "followup" and (tools or p["kind"] != "tool")}
    for p in prompts:
        if p["kind"] == "followup" and p["after"] in by_id:
            by_id[p["after"]].append(p)
    return list(by_id.values())


async def make_prompts(c: httpx.AsyncClient, prompts: list[dict[str, Any]], folder: Path) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    for p in prompts:
        path = folder / f"{p['id']}.wav"
        if path.is_file():
            continue
        body = {"text": p["text"], "voice": "male", **({"language": p["language"]} if p.get("language") else {})}
        r = await c.post("/v1/speech", json=body)
        r.raise_for_status()
        path.write_bytes(r.content)


async def whisper(stt: str | None, wav: Path, language: str | None) -> str | None:
    """The stt mod's transcript of a WAV (not saved as an output); None when the mod doesn't answer."""
    if not stt:
        return None
    try:
        async with httpx.AsyncClient(base_url=stt, timeout=httpx.Timeout(10, read=120)) as c:
            params = {"filename": wav.name, "save": "false", "preset": "balanced", **({"language": language} if language else {})}
            r = await c.post("/v1/transcribe/upload", params=params, content=wav.read_bytes(),
                             headers={"content-type": "application/octet-stream"})
            if r.status_code >= 400:
                return None
            jid = r.json()["id"]
            for _ in range(600):
                job = (await c.get(f"/v1/jobs/{jid}")).json()
                if job["state"] in ("done", "failed", "cancelled"):
                    text = job.get("transcript") or (job.get("result") or {}).get("text") or ""
                    return " ".join(line.split("]", 1)[-1].strip() for line in text.splitlines() if line.strip()) if job["state"] == "done" else None
                await asyncio.sleep(0.2)
    except (httpx.HTTPError, KeyError, ValueError):
        return None
    return None


async def run_size(args: argparse.Namespace, quant: str, prompts: list[dict[str, Any]], audio: Path) -> dict[str, Any]:
    http = args.hub.rstrip("/") + "/api/s/voice"
    ws = http.replace("http", "ws", 1) + "/v1/realtime"
    rows: list[dict[str, Any]] = []
    async with httpx.AsyncClient(base_url=http, timeout=httpx.Timeout(10, read=180)) as c:
        await c.post("/v1/unload")
        t0 = time.monotonic()
        r = await c.post("/v1/load", json={"quant": quant}, headers={"X-GAIFA-Make-Room": "1"})
        r.raise_for_status()
        load_s = time.monotonic() - t0
        n = 0
        for conv in conversations(prompts, args.tools):
            lang = conv[0].get("language")
            try:
                async with Talk(ws, sample_rate=24000, pause_ms=args.pause_ms, voice="female", quant=quant,
                                **({"language": lang} if lang else {})) as talk:
                    for p in conv:
                        n += 1
                        row = {"n": n, "id": p["id"], "kind": p["kind"], "text": p["text"], "language": lang}
                        try:
                            res = await talk.turn(wav=audio / "prompts" / f"{p['id']}.wav")
                            turn = res["turn"]
                            out = audio / f"{n:02d}-{p['id']}-{quant}.wav"
                            if res["audio"]:
                                write_wav(out, res["audio"], talk.ready["sample_rate_out"])
                            row.update(heard=turn["user"], said=turn["assistant"], first_audio_ms=turn["first_audio_ms"],
                                       audio_ms=res.get("audio_ms"), reply_s=res.get("reply_s"), tools=res.get("tools"),
                                       heard_wer=score.wer(p["text"], turn["user"]),
                                       right=score.has_all(turn["assistant"], p["expect"]) if p.get("expect") else None)
                            if p["kind"] == "tool":
                                row["right"] = any(t.get("name") == p.get("tool") for t in res.get("tools") or [])
                            if res["errors"]:
                                row["error"] = res["errors"][0].get("detail")
                            if res["audio"] and turn["assistant"]:
                                heard = await whisper(args.stt, out, lang)
                                if heard is not None:
                                    row.update(whisper=heard, spoken_wer=score.wer(turn["assistant"], heard))
                        except (TimeoutError, RuntimeError, OSError) as e:
                            row["error"] = str(e) or type(e).__name__
                        rows.append(row)
                        print(f"  {quant} {row['id']}: {row.get('first_audio_ms')} ms · {str(row.get('said'))[:70]!r}"
                              + (f" · ERROR {row['error']}" if row.get("error") else ""), flush=True)
            except (RuntimeError, OSError) as e:
                for p in conv:
                    n += 1
                    rows.append({"n": n, "id": p["id"], "kind": p["kind"], "text": p["text"], "error": str(e)})
        st = (await c.get("/v1/status")).json()["engine"]
    return {"label": LABELS[quant], **score.summary(rows), "load_s": load_s,
            "memory_bytes": (st.get("rss_bytes") or 0) + (st.get("gpu_bytes") or 0), "rows": rows}


def report(sizes: dict[str, dict[str, Any]], args: argparse.Namespace, when: str) -> str:
    out = ["# Voice mode's speech model: Q4_K_M against Q8_0", "",
           f"Run on {when} with `services/voice/evals/compare.py` (plan voice-speech-model 4.1): {next(iter(sizes.values()))['turns']} spoken "
           "prompts through each size of LFM3-Omni-2B, one size at a time, in real time through the voice mod's WebSocket. "
           "The prompts were spoken by the model's own male voice and the replies by its female voice, so \"written down wrong\" "
           "is the model hearing its own kind of speech: a person's voice in a room will do worse. \"Heard wrong by Whisper\" is "
           "the stt mod's transcript of each reply against the reply's text, a measure of how clearly it speaks."
           + ("" if any(s.get("spoken_wer") is not None for s in sizes.values()) else " (The stt mod didn't answer in this run, so it is empty.)"),
           "", score.table(sizes), "",
           "*First audio* is measured in the mod, from the end of the pause that ends your turn to the reply's first audio. "
           "*Speech made* is how much faster than real time the reply's audio is generated. The reply WAVs are in "
           f"`{args.audio}` (local, not tracked), as `<n>-<id>-q4_k_m.wav` and `-q8_0.wav`, for listening.", ""]
    kinds = [("short", "Short questions"), ("long", "Long questions"), ("numbers", "Numbers and names"),
             ("followup", "Follow-ups"), ("language", "Other languages"), ("tool", "Tools")]
    out += ["## By kind of prompt", "", "| Kind | " + " | ".join(f"{s['label']}: right · heard wrong · first audio" for s in sizes.values()) + " |",
            "| --- |" + " --- |" * len(sizes)]
    for kind, label in kinds:
        cells = []
        for s in sizes.values():
            sub = score.summary([r for r in s["rows"] if r["kind"] == kind])
            if not sub["turns"]:
                cells.append("—")
                continue
            cells.append(f"{score.fmt(sub['right'], 'of')} · {score.fmt(sub['heard_wer'], 'pct')} · {score.fmt(sub['first_audio_ms'], 'ms')}")
        if any(c != "—" for c in cells):
            out.append(f"| {label} | " + " | ".join(cells) + " |")
    out += ["", "## Every turn", ""]
    names = list(sizes)
    for i, row in enumerate(sizes[names[0]]["rows"]):
        out.append(f"**{row['n']}. {row['id']}** ({row['kind']}): {row['text']}")
        for name in names:
            r = sizes[name]["rows"][i] if i < len(sizes[name]["rows"]) else {}
            if r.get("error") and not r.get("said"):
                out.append(f"- {sizes[name]['label']}: failed: {r['error']}")
                continue
            mark = "" if r.get("right") is None else (" ✓" if r["right"] else " ✗")
            tools = "".join(f" [called {t.get('name')}]" for t in r.get("tools") or [] if t.get("state") in ("done", "refused", "failed"))
            out.append(f"- {sizes[name]['label']} ({r.get('first_audio_ms')} ms){mark}{tools}: {r.get('said') or '(nothing)'}"
                       + (f" *(heard as: {r.get('heard')})*" if r.get("heard_wer") else ""))
        out.append("")
    return "\n".join(out).rstrip() + "\n"


async def main(args: argparse.Namespace) -> None:
    prompts = json.loads(Path(args.prompts).read_text())["prompts"]
    if args.only:
        prompts = [p for p in prompts if p["id"] in args.only or p.get("after") in args.only]
    audio = Path(args.audio)
    async with httpx.AsyncClient(base_url=args.hub.rstrip("/") + "/api/s/voice", timeout=httpx.Timeout(10, read=180)) as c:
        await c.post("/v1/load", headers={"X-GAIFA-Make-Room": "1"})
        await make_prompts(c, [p for p in prompts if args.tools or p["kind"] != "tool"], audio / "prompts")
    for p in prompts:                                       # every prompt WAV is 24 kHz mono PCM16
        if (audio / "prompts" / f"{p['id']}.wav").is_file():
            assert read_wav(audio / "prompts" / f"{p['id']}.wav")[1] == 24000
    sizes = {}
    for quant in args.quants:
        print(f"== {quant}", flush=True)
        sizes[quant] = await run_size(args, quant, prompts, audio)
    (audio / "results.json").write_text(json.dumps(sizes, indent=1))
    text = report(sizes, args, time.strftime("%Y-%m-%d"))
    if args.out:
        out = Path(args.out)
        keep = ""
        if out.is_file() and "\n## The choice" in out.read_text():      # what was decided stays across runs
            keep = "\n## The choice" + out.read_text().split("\n## The choice", 1)[1]
        out.write_text(text + keep)
        print(f"wrote {out}")
    print(score.table(sizes))


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--hub", default="http://127.0.0.1:7000", help="the hub the voice mod runs under")
    p.add_argument("--stt", default="http://127.0.0.1:7000/api/s/stt", help="the stt mod, for the replies' intelligibility ('' skips it)")
    p.add_argument("--quants", nargs="+", default=["q4_k_m", "q8_0"], choices=list(LABELS))
    p.add_argument("--prompts", default=str(HERE / "prompts.json"))
    p.add_argument("--audio", default=str(HERE.parent.parent.parent / "outputs" / "voice" / "eval"), help="where the prompt and reply WAVs go")
    p.add_argument("--out", help="write the report here (docs/voice-eval.md)")
    p.add_argument("--pause-ms", type=int, default=800)
    p.add_argument("--tools", action="store_true", help="include the tool prompts (Phase 5: [voice_mode] tools must be set)")
    p.add_argument("--only", nargs="*", help="prompt ids, for a short run")
    asyncio.run(main(p.parse_args()))
