import asyncio
import io

from comfy import logtail


def test_follow_prints_new_whole_lines_and_rereads_after_truncation(tmp_path):
    log = tmp_path / "comfyui.log"
    log.write_text("old line\n")
    out = io.StringIO()

    async def go():
        t = asyncio.create_task(logtail.follow(log, out, interval=0.01))
        await asyncio.sleep(0.05)
        with log.open("a") as f:
            f.write("one\ntw")
        await asyncio.sleep(0.05)
        with log.open("a") as f:
            f.write("o\n")
        await asyncio.sleep(0.05)
        log.write_text("fresh\n")                 # a new start empties the log
        await asyncio.sleep(0.05)
        t.cancel()

    asyncio.run(go())
    assert out.getvalue().splitlines() == ["[comfyui] one", "[comfyui] two", "[comfyui] fresh"]
