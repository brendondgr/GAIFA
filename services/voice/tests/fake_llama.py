#!/usr/bin/env python3
"""A stand-in for llama-server in tests: /health, /tts, and a scripted /v1/realtime.

FAKE_LLAMA_MODE: "ok" (default), "die" (exit 3 at once), "slow" (ready after 1 s).
"""
import asyncio, base64, json, os, struct, sys, time

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, Response

MODE = os.environ.get("FAKE_LLAMA_MODE", "ok")
REPLY = os.environ.get("FAKE_LLAMA_REPLY", "Paris is the capital of France.")
CHUNKS = int(os.environ.get("FAKE_LLAMA_CHUNKS", "10"))          # 100 ms of audio each
DELAY = float(os.environ.get("FAKE_LLAMA_DELAY", "0.01"))
RATE = 24000
T0 = time.monotonic()
app = FastAPI()


def wav(seconds=0.2):
    n = int(RATE * seconds)
    data = b"\x00\x01" * n
    return b"RIFF" + struct.pack("<I", 36 + len(data)) + b"WAVEfmt " + struct.pack("<IHHIIHH", 16, 1, 1, RATE, RATE * 2, 2, 16) + \
        b"data" + struct.pack("<I", len(data)) + data


@app.get("/health")
def health():
    ready = MODE != "slow" or time.monotonic() - T0 > 1.0
    return JSONResponse({"status": "ok" if ready else "loading"}, 200 if ready else 503)


@app.post("/tts")
def tts():
    return Response(wav(), media_type="audio/wav")


class Sock:
    """The few calls the script below makes, over FastAPI's WebSocket."""

    def __init__(self, ws):
        self.ws = ws

    async def send(self, text):
        await self.ws.send_text(text)

    async def close(self):
        await self.ws.close()

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            return await self.ws.receive_text()
        except (WebSocketDisconnect, RuntimeError):
            raise StopAsyncIteration from None


@app.websocket("/v1/realtime")
async def realtime_route(ws: WebSocket):
    await ws.accept()
    try:
        await realtime(Sock(ws), ws.query_params.get("intent") == "transcription")
    except (WebSocketDisconnect, RuntimeError):
        pass


async def realtime(ws, transcription=False):
    session = {"type": "realtime", "instructions": "", "output_modalities": None, "tools": [],
               "audio": {"input": {"format": {"type": "audio/pcm", "rate": 16000}, "turn_detection": None},
                         "output": {"format": {"type": "audio/pcm", "rate": RATE}, "voice": None, "language": None}}}
    await ws.send(json.dumps({"type": "session.created", "session": session}))
    heard = 0
    answered = False
    outputs = []
    cancel = asyncio.Event()
    task = None

    async def respond():
        nonlocal answered
        await ws.send(json.dumps({"type": "response.created"}))
        if session.get("tools") and not answered and MODE != "notool":       # a tool first, then the answer
            await ws.send(json.dumps({"type": "response.output_text.delta", "delta": "Let me check. "}))
            call = {"type": "function_call", "name": os.environ.get("FAKE_LLAMA_TOOL") or session["tools"][0]["name"],
                    "arguments": os.environ.get("FAKE_LLAMA_ARGS", '{"day": "tomorrow"}'), "call_id": "call_1"}
            await ws.send(json.dumps({"type": "response.done", "response": {"status": "completed", "output": [
                {"type": "message", "content": [{"type": "output_text", "text": "Let me check. "}]}, call], "usage": {"output_tokens": 5}}}))
            return
        answered = False
        words = REPLY.split(" ")
        said = ""
        for i in range(CHUNKS):
            if cancel.is_set():
                await ws.send(json.dumps({"type": "response.done", "response": {"status": "cancelled", "output": [
                    {"type": "message", "content": [{"type": "output_text", "text": said}]}], "usage": {"output_tokens": i}}}))
                return
            if i < len(words):
                d = words[i] + (" " if i < len(words) - 1 else "")
                said += d
                await ws.send(json.dumps({"type": "response.output_text.delta", "delta": d}))
            await ws.send(json.dumps({"type": "response.output_audio.delta",
                                      "delta": base64.b64encode(b"\x00\x01" * (RATE // 10)).decode()}))
            await asyncio.sleep(DELAY)
        if len(words) > CHUNKS:
            rest = " ".join(words[CHUNKS:])
            said += rest
            await ws.send(json.dumps({"type": "response.output_text.delta", "delta": rest}))
        await ws.send(json.dumps({"type": "response.done", "response": {"status": "completed", "output": [
            {"type": "message", "content": [{"type": "output_text", "text": said}]}], "usage": {"output_tokens": CHUNKS}}}))

    async for raw in ws:
        ev = json.loads(raw)
        t = ev["type"]
        if t == "session.update":
            s = ev["session"]
            session.update({k: v for k, v in s.items() if k != "audio"})
            for side in ("input", "output"):
                session["audio"][side].update((s.get("audio") or {}).get(side) or {})
            if MODE == "log":
                print("SESSION " + json.dumps(session), flush=True)
            await ws.send(json.dumps({"type": "session.updated", "session": session}))
        elif t == "input_audio_buffer.append":
            heard += len(base64.b64decode(ev["audio"])) // 2
        elif t == "input_audio_buffer.commit":
            await ws.send(json.dumps({"type": "input_audio_buffer.committed", "item_id": "i1"}))
            if session["type"] == "transcription":
                await ws.send(json.dumps({"type": "conversation.item.input_audio_transcription.completed", "item_id": "i1",
                                          "transcript": f"heard {heard} samples" if heard else ""}))
                heard = 0
        elif t == "response.create":
            heard = 0
            cancel.clear()
            task = asyncio.create_task(respond())
        elif t == "response.cancel":
            if task and not task.done():
                cancel.set()
            else:
                await ws.send(json.dumps({"type": "error", "error": {"message": "no response to cancel"}}))
        elif t == "conversation.item.create":
            if ev["item"].get("type") == "function_call_output":
                answered = True
                print("TOOL_OUTPUT " + ev["item"]["output"], flush=True)
            await ws.send(json.dumps({"type": "conversation.item.added"}))
        if MODE == "drop" and t == "response.create":
            await asyncio.sleep(0.05)
            await ws.close()


if __name__ == "__main__":
    if MODE == "die":
        print("fake llama: cannot load model", flush=True)
        sys.exit(3)
    uvicorn.run(app, host="127.0.0.1", port=int(sys.argv[sys.argv.index("--port") + 1]), log_level="warning")
