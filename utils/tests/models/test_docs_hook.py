"""The setup docs follow the registry (plan 23.3): adds, edits, deletes, verifies and hand edits of
registry.json rewrite the model docs, debounced, and `[docs] regenerate = false` stops it."""

from __future__ import annotations

import asyncio
import json

from utils.registry import Patch
from utils.registry.adding import ModelInput, add
from utils.registry.docs_hook import DocsHook

FAST = 0.05


def _doc(models, mid):
    return models.paths.root / "docs" / "setup" / "models" / f"{mid}.md"


async def _settle(hook: DocsHook) -> None:
    for _ in range(100):
        await asyncio.sleep(FAST)
        if hook._task is None or hook._task.done():
            return


async def test_add_update_delete(reg, models):
    hook = DocsHook(reg, models.paths.root, lambda: True, debounce_s=FAST)
    models.put("comfyui/loras/a.safetensors", 100)
    await add(reg, ModelInput(path="comfyui/loras/a.safetensors", name="Model A", kind="lora"))
    await _settle(hook)
    mid = next(iter(reg.entries))
    doc = _doc(models, mid)
    assert "# Model A" in doc.read_text()
    doc.write_text(doc.read_text().replace("## Notes\n", "## Notes\n\nMine.\n"))
    await reg.update(mid, Patch(name="Model B"))
    await _settle(hook)
    text = doc.read_text()
    assert "# Model B" in text and "# Model A" not in text and text.endswith("## Notes\n\nMine.\n")
    await reg.delete(mid)
    await _settle(hook)
    assert "**Not in the registry.**" in doc.read_text()           # hand text: kept and marked
    doc.write_text(doc.read_text().replace("\nMine.\n", "\n"))
    hook.changed(None)
    await _settle(hook)
    assert not doc.exists()                                           # no hand text left: removed


async def test_a_burst_makes_one_write(reg, models):
    hook = DocsHook(reg, models.paths.root, lambda: True, debounce_s=0.2)
    for name in "abc":
        models.put(f"llm/{name}.gguf", 10)
        await add(reg, ModelInput(path=f"llm/{name}.gguf", name=name, kind="llm"))
    await _settle(hook)
    assert hook.runs == 1
    assert len(list((models.paths.root / "docs" / "setup" / "models").glob("*.md"))) == 3


async def test_off_means_no_writes(reg, models):
    hook = DocsHook(reg, models.paths.root, lambda: False, debounce_s=FAST)
    hook.start()
    models.put("llm/x.gguf", 10)
    await add(reg, ModelInput(path="llm/x.gguf", name="x", kind="llm"))
    await asyncio.sleep(FAST * 4)
    assert hook.runs == 0 and not (models.paths.root / "docs" / "setup" / "models").exists()


async def test_a_hand_edit_of_registry_json_is_picked_up(reg, models):
    hook = DocsHook(reg, models.paths.root, lambda: True, debounce_s=FAST)
    models.put("tts/v/model.bin", 10)
    models.write({"v": {"path": "tts/v", "files": [models.file("tts/v/model.bin")], "kind": "tts"}})
    data = json.loads(models.paths.registry.read_text())
    models.paths.registry.write_text(json.dumps(data) + "\n")       # a new stamp
    reg.refresh()
    await _settle(hook)
    assert _doc(models, "v").exists()


async def test_start_does_a_full_pass(reg, models):
    models.put("llm/y.gguf", 10)
    models.write({"y": {"path": "llm/y.gguf", "files": [models.file("llm/y.gguf")], "kind": "llm"}})
    reg.load()
    hook = DocsHook(reg, models.paths.root, lambda: True, debounce_s=FAST)
    hook.start()
    await _settle(hook)
    assert _doc(models, "y").exists()
    await hook.close()


async def test_a_failing_listener_never_breaks_a_write(reg, models):
    reg.subscribe(lambda _mid: 1 / 0)
    seen = []
    reg.subscribe(seen.append)
    models.put("llm/z.gguf", 10)
    await add(reg, ModelInput(path="llm/z.gguf", name="z", kind="llm"))
    assert len(seen) == 1                                             # the second listener still ran
    assert reg.entries
