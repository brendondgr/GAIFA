"""``python -m lcpp.daemon`` — run lcppd in the foreground (systemd runs this).

One worker, no reload, warnings-only logging and no access log: at idle the
process should be doing nothing at all.
"""

from __future__ import annotations

import argparse
import logging
import os

import uvicorn

from lcpp import settings
from lcpp.paths import Paths


def main() -> None:
    ap = argparse.ArgumentParser(prog="lcppd")
    ap.add_argument("--port", type=int, help="override data/lcpp.json daemon.port")
    ap.add_argument("--dev", action="store_true",
                    help="run instances as child processes instead of systemd units")
    args = ap.parse_args()
    if args.dev:
        os.environ["LCPP_BACKEND"] = "subprocess"
    paths = Paths.default()
    port = args.port or settings.load(paths)["daemon"]["port"]
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")

    from lcpp.daemon.app import create_app

    uvicorn.run(create_app(paths), host=settings.HOST, port=port, log_level="warning",
                access_log=False, lifespan="on", server_header=False)


if __name__ == "__main__":
    main()
