"""Speech to Text: the stt mod (plan Phase 29). AIHub runs `.venv/bin/python server.py`.

Reads AIHUB_PORT, AIHUB_OUTPUTS, AIHUB_MODELS and AIHUB_URL (architecture §4.4), plus STT_DEVICE
(auto | cpu | cuda), STT_BACKEND (faster-whisper | mock) and STT_IDLE_UNLOAD_S. The routes are in
stt/server.py.
"""

from __future__ import annotations

import logging
import os

import uvicorn


def main() -> None:
    from stt.server import create_app

    logging.basicConfig(level=getattr(logging, os.environ.get("LOG_LEVEL", "info").upper(), logging.INFO),
                        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s")
    app = create_app()
    uvicorn.run(app, host="127.0.0.1", port=app.state.settings.port, log_level="info")


if __name__ == "__main__":
    main()
