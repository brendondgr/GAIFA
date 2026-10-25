"""python -m comfy  ->  serve the adapter on 127.0.0.1:$GAIFA_PORT."""

import logging

import uvicorn

from .config import Settings
from .server import create_app


class _QuietPolls(logging.Filter):
    """GAIFA polls health and status every few seconds; keep them out of the log."""

    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        return not any(f'"GET {p} ' in msg for p in ("/health", "/v1/status"))


def main() -> None:
    settings = Settings.from_env()
    logging.getLogger("uvicorn.access").addFilter(_QuietPolls())
    uvicorn.run(create_app(settings), host="127.0.0.1", port=settings.port, log_level="info")


if __name__ == "__main__":
    main()
