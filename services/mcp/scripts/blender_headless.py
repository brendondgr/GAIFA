"""Blender without a window, as the target of the MCP for Blender server (plan mcp-client 5.1).

    blender -b [scene.blend] --python services/mcp/scripts/blender_headless.py -- [--port 9876]

The MCP for Blender add-on (ahujasid/mcp-for-blender, installed in Blender's add-ons) listens on a socket and runs the
commands it gets on Blender's main thread through a timer, which never fires in background mode, so the add-on won't
start there. This starts the add-on's own socket server and runs its queued commands here, in a loop on the main
thread. The add-on isn't enabled (no update check, no preferences); its tools that need a window (viewport
screenshots) answer with an error, everything else (scene, objects, materials, Python, renders, saving) works.
"""

import argparse
import socket
import sys
import threading
import time

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
p = argparse.ArgumentParser()
p.add_argument("--host", default="localhost")
p.add_argument("--port", type=int, default=9876)
a = p.parse_args(argv)

import blender_mcp  # noqa: E402: the add-on, from Blender's scripts/addons

srv = blender_mcp.BlenderMCPServer(host=a.host, port=a.port)
srv.running = True
srv.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
srv.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
srv.socket.bind((a.host, a.port))
srv.socket.listen(5)
srv.server_thread = threading.Thread(target=srv._server_loop, daemon=True)
srv.server_thread.start()
print(f"blender_headless: MCP for Blender listening on {a.host}:{a.port}", flush=True)
try:
    while True:
        srv._drain_command_queue()
        time.sleep(0.05)
except KeyboardInterrupt:
    srv.running = False
