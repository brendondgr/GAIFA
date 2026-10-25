"""`python -m agent`: serve on 127.0.0.1:$GAIFA_PORT."""

import logging
import os

import uvicorn

from .server import create_app

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    uvicorn.run(create_app(), host="127.0.0.1", port=int(os.environ.get("GAIFA_PORT", "5100")), log_level="warning")
