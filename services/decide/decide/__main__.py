"""python -m decide [--port N]  ->  serve the mod on 127.0.0.1."""

import argparse
import logging
import os
from pathlib import Path

import uvicorn

from .server import create_app
from .settings import Settings


class _QuietPolls(logging.Filter):
    """AIHub polls health and status every few seconds; keep them out of the log."""

    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        return not any(f'"GET {p} ' in msg for p in ("/health", "/v1/status"))


def main() -> None:
    ap = argparse.ArgumentParser(prog="decide")
    ap.add_argument("--port", type=int, default=None)
    args = ap.parse_args()
    settings = Settings.from_env(port=args.port)
    for var in ("TMPDIR", "TRITON_CACHE_DIR", "HF_MODULES_CACHE"):   # service.toml points them into data/state
        if os.environ.get(var):
            Path(os.environ[var]).mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    logging.getLogger("uvicorn.access").addFilter(_QuietPolls())
    uvicorn.run(create_app(settings), host="127.0.0.1", port=settings.port, log_level="info")


if __name__ == "__main__":
    main()
