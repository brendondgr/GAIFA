"""Voice: the speech-to-speech mod (plan voice-speech-model). GAIFA runs `.venv/bin/python server.py`.

Reads GAIFA_PORT, GAIFA_MODELS and GAIFA_URL (architecture §4.4), plus VOICE_MODELS_DIR, VOICE_LLAMA_BIN,
VOICE_QUANT, VOICE_GPU_LAYERS and VOICE_IDLE_UNLOAD_S. The routes are in voice/server.py.
"""

from __future__ import annotations

import logging
import os

import uvicorn


class _QuietPolls(logging.Filter):
    """GAIFA polls health and status every few seconds; keep them out of the log."""

    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        return not any(f'"GET {p} ' in msg for p in ("/health", "/v1/status"))


def main() -> None:
    from voice.server import create_app

    logging.basicConfig(level=getattr(logging, os.environ.get("LOG_LEVEL", "info").upper(), logging.INFO),
                        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s")
    logging.getLogger("uvicorn.access").addFilter(_QuietPolls())
    app = create_app()
    uvicorn.run(app, host="127.0.0.1", port=app.state.settings.port, log_level="info")


if __name__ == "__main__":
    main()
