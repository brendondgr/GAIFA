"""`python app.py`: start the AIHub hub on 127.0.0.1 and [::1].

Ctrl+C stops only the hub; mods keep running (architecture §5).
"""

from __future__ import annotations

import argparse
import logging
import socket
import sys

import uvicorn

from utils import config
from utils.paths import project_root
from utils.server import Options, create_app

log = logging.getLogger("aihub")

DUAL_STACK = {"127.0.0.1", "localhost", "::1"}


def _listen(host: str, port: int, family: socket.AddressFamily) -> socket.socket:
    s = socket.socket(family, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    if family == socket.AF_INET6:
        s.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 1)
    s.bind((host, port))
    s.listen(2048)
    # Not inheritable (Python's default): uvloop's subprocess spawn doesn't close inheritable fds,
    # so `--dev` mods (child processes) would otherwise keep the hub's port bound after it exits.
    return s


def sockets(host: str, port: int) -> list[socket.socket]:
    """Loopback means both 127.0.0.1 and ::1: `localhost` resolves to ::1 first here,
    and a browser that tries it gets 'connection refused' if only IPv4 listens."""
    if host not in DUAL_STACK:
        family = socket.AF_INET6 if ":" in host else socket.AF_INET
        return [_listen(host.strip("[]"), port, family)]
    socks = [_listen("127.0.0.1", port, socket.AF_INET)]
    try:
        socks.append(_listen("::1", port, socket.AF_INET6))
    except OSError as exc:  # IPv6 disabled: IPv4 alone still works
        log.warning("not listening on [::1]:%s (%s)", port, exc)
    return socks


class Server(uvicorn.Server):
    def handle_exit(self, sig, frame) -> None:
        # End the SSE streams first so the graceful shutdown doesn't wait on them.
        hub = getattr(getattr(self.config.app, "state", None), "hub", None)
        if hub is not None:
            hub.bus.close()
        super().handle_exit(sig, frame)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(prog="app.py", description="Run the AIHub hub.")
    ap.add_argument("--port", type=int, help="port (default: config.toml hub.port, 7000)")
    ap.add_argument("--dev", action="store_true", help="run mods as child processes instead of systemd units")
    ap.add_argument("--no-autostart", action="store_true", help="don't autostart mods")
    ap.add_argument("--demo-mods", action="store_true", help="also load the fake mods in utils/tests/fixtures/mods/")
    return ap.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)  # one line per health check and status poll otherwise
    root = project_root()
    try:
        cfg = config.load(root / "config.toml")
        paths = config.build_paths(cfg, root)
    except config.ConfigError as e:
        print(f"aihub: {e}", file=sys.stderr)
        return 2
    opts = Options(port=args.port, dev=args.dev, autostart=not args.no_autostart, demo_mods=args.demo_mods)
    app = create_app(paths, cfg, backend=None, options=opts)
    port = opts.port or cfg.hub.port
    try:
        socks = sockets(cfg.hub.host, port)
    except OSError as e:
        print(f"aihub: can't listen on {cfg.hub.host}:{port}: {e.strerror}", file=sys.stderr)
        return 1
    server = Server(
        uvicorn.Config(
            app,
            log_level="info",
            # Browsers keep idle connections for minutes; outlive them (LocalTTS / gen3d fix).
            timeout_keep_alive=75,
            # SSE streams never end on their own; don't let them hold a restart hostage.
            timeout_graceful_shutdown=10,
        )
    )
    log.info(
        "listening on %s",
        ", ".join(
            f"[{s.getsockname()[0]}]:{port}" if s.family == socket.AF_INET6 else f"{s.getsockname()[0]}:{port}"
            for s in socks
        ),
    )
    try:
        server.run(sockets=socks)
    except KeyboardInterrupt:  # uvicorn re-raises Ctrl+C after its clean shutdown
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
