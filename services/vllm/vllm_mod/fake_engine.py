"""A stand-in for `vllm serve` (VLLM_FAKE=1): the same arguments, the same log milestones, and the routes
the adapter and the relay use: /health, /v1/models, /metrics and /v1/chat/completions (plain and SSE).

FAKE_VLLM_STARTUP_S   seconds before it listens (default 0.3)
FAKE_VLLM_FAIL        exit 1 during startup, with a traceback-like line
FAKE_VLLM_CRASH_S     exit 1 this many seconds after becoming ready
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time

STATE = {"running": 0, "gen_tokens": 0, "prompt_tokens": 0, "requests": 0}


def log(msg: str) -> None:
    print(f"(EngineCore pid={os.getpid()}) INFO {time.strftime('%m-%d %H:%M:%S')} {msg}", flush=True)


def build_app(args: argparse.Namespace):
    from fastapi import FastAPI, Request
    from fastapi.responses import JSONResponse, PlainTextResponse, StreamingResponse

    app = FastAPI()
    served = args.served_model_name or args.model

    @app.get("/health")
    def health():
        return PlainTextResponse("")

    @app.get("/v1/models")
    def models():
        return {"object": "list", "data": [{"id": served, "object": "model", "owned_by": "vllm", "root": args.model,
                                            "max_model_len": args.max_model_len}]}

    @app.get("/metrics")
    def metrics():
        m = (f'vllm:num_requests_running{{model_name="{served}"}} {STATE["running"]}\n'
             f'vllm:num_requests_waiting{{model_name="{served}"}} 0.0\n'
             f'vllm:kv_cache_usage_perc{{model_name="{served}"}} {0.05 * STATE["running"]}\n'
             f'vllm:generation_tokens_total{{model_name="{served}"}} {STATE["gen_tokens"]}\n'
             f'vllm:prompt_tokens_total{{model_name="{served}"}} {STATE["prompt_tokens"]}\n'
             f'vllm:request_success_total{{finished_reason="stop",model_name="{served}"}} {STATE["requests"]}\n')
        return PlainTextResponse(m)

    @app.post("/v1/chat/completions")
    async def chat(request: Request):
        body = await request.json()
        if body.get("model") != served:
            return JSONResponse({"error": {"message": f"The model `{body.get('model')}` does not exist."}}, 404)
        words = ["Hello", " from", " the", " fake", " vLLM", "."]
        delay = float(os.environ.get("FAKE_VLLM_TOKEN_S", "0.01"))
        STATE["running"] += 1
        STATE["prompt_tokens"] += 5
        if not body.get("stream"):
            try:
                await asyncio.sleep(delay * len(words))
            finally:
                STATE["running"] -= 1
            STATE["gen_tokens"] += len(words)
            STATE["requests"] += 1
            return {"id": "fake", "object": "chat.completion", "model": served,
                    "choices": [{"index": 0, "message": {"role": "assistant", "content": "".join(words)},
                                 "finish_reason": "stop"}],
                    "usage": {"prompt_tokens": 5, "completion_tokens": len(words), "total_tokens": 5 + len(words)}}

        async def gen():
            try:
                for w in words:
                    await asyncio.sleep(delay)
                    STATE["gen_tokens"] += 1
                    chunk = {"id": "fake", "object": "chat.completion.chunk", "model": served,
                             "choices": [{"index": 0, "delta": {"content": w}, "finish_reason": None}]}
                    yield f"data: {json.dumps(chunk)}\n\n"
                yield "data: [DONE]\n\n"
                STATE["requests"] += 1
            finally:
                STATE["running"] -= 1
        return StreamingResponse(gen(), media_type="text/event-stream")

    return app


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="fake-vllm")
    ap.add_argument("cmd", choices=["serve"])
    ap.add_argument("model")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--served-model-name", default=None)
    ap.add_argument("--max-model-len", type=int, default=4096)
    args, _ = ap.parse_known_args(argv)
    startup = float(os.environ.get("FAKE_VLLM_STARTUP_S", "0.3"))
    print(f"(APIServer pid={os.getpid()}) INFO version 0.31.0+fake", flush=True)
    log(f"Starting to load model {args.model}...")
    time.sleep(startup / 3)
    if os.environ.get("FAKE_VLLM_FAIL"):
        print("RuntimeError: No HIP GPUs are available", flush=True)
        sys.exit(1)
    log("Loading weights took 0.11 seconds")
    log("Compiling a graph for compile range (1, 8192) takes 0.1 s")
    time.sleep(startup / 3)
    print("Capturing CUDA graphs (PIECEWISE):  50%|█████     | 2/4\rCapturing CUDA graphs (PIECEWISE): 100%|██████████| 4/4",
          flush=True)
    log("Available KV cache memory: 10.81 GiB")
    time.sleep(startup / 3)

    import uvicorn

    crash = os.environ.get("FAKE_VLLM_CRASH_S")
    if crash:
        async def _crash():
            await asyncio.sleep(float(crash))
            print("RuntimeError: HIP error: an illegal memory access was encountered", flush=True)
            os._exit(1)

        config = uvicorn.Config(build_app(args), host=args.host, port=args.port, log_level="warning")
        server = uvicorn.Server(config)

        async def _run():
            asyncio.get_running_loop().create_task(_crash())
            await server.serve()
        asyncio.run(_run())
        return
    print("INFO:     Application startup complete.", flush=True)
    uvicorn.run(build_app(args), host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
