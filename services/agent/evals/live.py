"""`python -m evals.live [--model skynet] [--only a,b] [--out file.json]`: the live smoke test (plan
14.12). Real conversations that make real outputs, one at a time (the GPU runs one job at a time):
an image, image → 3D, image → video (once), describe → speak, a quick-action button, a result-card
button, a compacted thread, a fork, and the same on the local Gemma 4 26B.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from typing import Any

import httpx

from .harness import Harness, Run, Task, dump, first_option, grade
from .tasks import aspect_is, engine_is, final_mentions, got_picture, kinds, no_picture, not_called, preset_in, ran, seed_picture, typed, uses_output_of

IMG, I2V, M3D, SPEAK, EDIT, BG = "comfy_generate_image", "comfy_animate_image", "gen3d_make_3d", "tts_speak", "comfy_edit_image", "comfy_remove_background"


def fast3d(a: dict[str, Any]) -> tuple[bool, dict[str, Any] | None]:
    """Approve every card; gen3d runs with the fast preset (about a minute)."""
    if a["tool"] == M3D:
        return True, {"preset": "fast", "stages": ["shape", "preview"]}
    return True, None


def real(*ks: str):
    """The outputs are real files (not eval stand-ins)."""
    def c(r: Run):
        outs = [o for o in r.outputs() if o["kind"] in ks]
        bad = [o["title"] for o in outs if "DRY RUN" in (o.get("title") or "")]
        return bool(outs) and not bad, f"{[(o['kind'], o['title'][:40]) for o in outs]}"
    return (f"real {', '.join(ks)}", c)


def offers_next():
    return final_mentions("animate", "3d", "edit", "next", "would you like", "want me to")


LIVE: list[Task] = [
    Task("L1_fox", "live", ["Make me an image of a fox."], [ran(IMG), kinds("image"), real("image"), offers_next()],
         answer=first_option, timeout=900),
    Task("L2_image_to_3d", "live", ["Make an image of a cute robot toy, then turn it into a 3D model."],
         [ran(IMG), ran(M3D), kinds("image", "model3d"), real("image", "model3d"), uses_output_of(M3D, "image", IMG),
          engine_is("trellis2", "hunyuan21", "sam3d_objects")],
         card=fast3d, answer=first_option, timeout=1500),
    Task("L3_image_to_video", "live", ["Make a 16:9 image of a sailboat on a calm lake at sunset.",
                                       "Now animate it: the boat drifts slowly and the water ripples."],
         [ran(IMG), aspect_is(IMG, "16:9"), ran(I2V), uses_output_of(I2V, "image", IMG), real("image", "video")],
         answer=first_option, timeout=3600),
    Task("L4_describe_speak", "live", ["Make an image of an owl reading in a library.",
                                       "Describe the image in two sentences, then read your description aloud with the af_heart voice."],
         [ran(IMG), ("looked at the image", lambda r: (bool(r.calls("view_output", by=None)), "")), ran(SPEAK), real("image", "audio")],
         answer=first_option, timeout=1200),
    Task("L7_compact_continue", "live", ["Make an image of an old stone bridge over a stream.", "/compact",
                                         "Edit the image you made earlier: make it night, with a full moon."],
         [ran(IMG), ran(EDIT), uses_output_of(EDIT, "image", IMG), real("image")], answer=first_option, timeout=1500),
    Task("L8_fork", "live", ["Make an image of a fox in a meadow.", "Edit it: make the fox a wolf."],
         [ran(EDIT), ("fork edits the first image", lambda r: uses_output_of(EDIT, "image", IMG, "fork_events")[1](r)),
          ("original unchanged", lambda r: (r.original_before == r.events[: len(r.original_before)], ""))],
         fork_after_turn=1, fork_turn="Edit it: make the fox an owl.", answer=first_option, timeout=1800),
    # capabilities with real outputs (plan 20.5): a local edit, one image → 3D per engine family, text → 3D both ways
    Task("L11_local_edit", "live", ["Remove the red headband from my picture titled 'Samurai figure (eval seed)'."],
         [ran(EDIT), not_called(IMG), preset_in(EDIT, None), real("image")], setup=seed_picture("eval-samurai-2", "services/gen3d/runtime/lab/input/samurai_front_rgba.png", "Samurai figure (eval seed)"), answer=first_option, timeout=1200),
    Task("L12_object_to_3d", "live", ["Make a 3D model of my picture titled 'Glass vase (eval seed)'."],
         [ran(M3D), engine_is("trellis2"), got_picture(), real("model3d")], setup=seed_picture("eval-vase-2", "services/gen3d/runtime/lab/input/vase_rgba.png", "Glass vase (eval seed)"), card=fast3d, answer=first_option, timeout=1500),
    Task("L13_character_to_3d", "live", ["Turn the character in my picture titled 'Samurai figure (eval seed)' into a 3D model."],
         [ran(M3D), engine_is("hunyuan21"), got_picture(), real("model3d")], setup=seed_picture("eval-samurai-2", "services/gen3d/runtime/lab/input/samurai_front_rgba.png", "Samurai figure (eval seed)"), card=fast3d, answer=first_option, timeout=1500),
    Task("L14_body_to_3d", "live", ["Make a rigged 3D body mesh of the person in my picture titled 'Samurai figure (eval seed)'."],
         [ran(M3D), engine_is("sam3d_body"), got_picture(), real("model3d")], setup=seed_picture("eval-samurai-2", "services/gen3d/runtime/lab/input/samurai_front_rgba.png", "Samurai figure (eval seed)"), card=fast3d, answer=first_option, timeout=1500),
    Task("L15_quick_objects_3d", "live", ["Give me a quick, rough 3D shape of my picture titled 'Glass vase (eval seed)' using SAM 3D Objects."],
         [ran(M3D), engine_is("sam3d_objects"), got_picture(), real("model3d")], setup=seed_picture("eval-vase-2", "services/gen3d/runtime/lab/input/vase_rgba.png", "Glass vase (eval seed)"), card=fast3d, answer=first_option, timeout=1500),
    Task("L16_text_to_3d_cube", "live", ["Make a quick 3D model of a fox straight from the text, no picture."],
         [ran(M3D), engine_is("cube3d"), no_picture(), real("model3d")], card=fast3d, answer=first_option, timeout=1500),
    Task("L17_text_to_3d_picture_first", "live", ["Make a 3D model of a ceramic teapot: make a picture of it first, then turn that picture into 3D."],
         [ran(IMG), ran(M3D), uses_output_of(M3D, "image", IMG), engine_is("trellis2", "hunyuan21", "sam3d_objects"), real("image", "model3d")],
         card=fast3d, answer=first_option, timeout=2400),
    Task("L10_must_ask", "live", ["Make a 3D model and split it into parts."],
         [("asked before making it", lambda r: (r.asked() or "?" in r.final(), ""))], answer=typed("A wooden chair"),
         card=fast3d, timeout=1200),
]


async def buttons(h: Harness, model: str) -> Run:
    """L5/L6: a quick action (no model call) makes an image; a result-card button removes its
    background; then the model is asked about it and sees both."""
    run = Run("L5_L6_buttons", model)
    t0 = time.monotonic()
    c = h.c
    tid = (await c.post("/v1/threads", json={"title": "live buttons", "model": model, "mode": "ask"})).json()["id"]
    run.extra["thread"] = tid

    async def settle() -> None:
        await h._settle(tid, time.monotonic() + 900)

    await c.post(f"/v1/threads/{tid}/action", json={"tool": IMG, "arguments": {"prompt": "a red apple on a white table, studio photo",
                                                                               "aspect": "1:1"}})
    await settle()
    evs = await h._events(tid)
    img = [o for e in evs if e["type"] == "tool_result" for o in e["payload"].get("outputs") or []]
    if img:
        await c.post(f"/v1/threads/{tid}/action", json={"tool": BG, "arguments": {"image": f"output:{img[0]['output_id']}"}})
        await settle()
    await h._drive(Task("x", "live", [], []), tid, "What did my two buttons make? Answer in one sentence.", time.monotonic() + 600)
    run.events = await h._events(tid)
    run.seconds = round(time.monotonic() - t0, 1)
    return run


BUTTON_CHECKS = Task("L5_L6_buttons", "live", [], [
    ("quick action ran with no model call", lambda r: (bool([c for c in r.calls(IMG, by="user")]) and
                                                       all(e["type"] != "usage" for e in r.events[: next((i for i, e in enumerate(r.events) if e["type"] == "user"), len(r.events))]), "")),
    ("button removed the background of #1", lambda r: (bool(r.done(BG)) and uses_output_of(BG, "image", IMG)[1](r)[0], "")),
    real("image"), final_mentions("apple", "background")])


async def main(a: argparse.Namespace) -> int:
    h = Harness(a.base, a.model, dry_run=False)
    rows = []
    tasks = [t for t in LIVE if not a.only or t.id in a.only.split(",")]
    try:
        for t in tasks:
            run = await h.run(t)
            row = grade(t, run)
            rows.append(row)
            print(f"{t.id:22} {'PASS' if row['ok'] else 'FAIL'} {row['seconds']:7.1f}s tools={row['tools']}"
                  + ("" if row["ok"] else f" failed={[c['check'] for c in row['checks'] if not c['ok']]}"), flush=True)
            if a.out:
                dump(a.out, {"model": a.model, "rows": rows})
        if not a.only or "L5_L6_buttons" in a.only:
            run = await buttons(h, a.model)
            row = grade(BUTTON_CHECKS, run)
            rows.append(row)
            print(f"L5_L6_buttons          {'PASS' if row['ok'] else 'FAIL'} {row['seconds']:7.1f}s tools={row['tools']}", flush=True)
    finally:
        await h.close()
    if a.out:
        dump(a.out, {"model": a.model, "rows": rows, "passed": sum(r["ok"] for r in rows), "total": len(rows)})
    print(json.dumps({"passed": sum(r["ok"] for r in rows), "total": len(rows)}))
    return 0


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--base", default="http://127.0.0.1:7000/api/s/agent")
    p.add_argument("--model", default="skynet")
    p.add_argument("--only")
    p.add_argument("--out")
    raise SystemExit(asyncio.run(main(p.parse_args())))
