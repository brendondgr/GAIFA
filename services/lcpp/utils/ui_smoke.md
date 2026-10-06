# UI smoke checklist

Against the live daemon at http://127.0.0.1:7710 (badge in the sidebar footer
reads LIVE). The same page over a plain static server (`lcpp-ui` preview on
:7711) runs against the mock; `Shift+D` opens its scenario panel.

1. **Launch**: `+ Launch`, pick MiniCPM5-2B, port shows ✓ free, preflight
   estimate ≈ 5.8 GB, command preview matches `lcpp start minicpm --dry-run`.
   Launch → card goes starting → ready within seconds.
2. **Port conflict**: in Launch, type 7070 (the router) → ✗ in use by lcpp
   instance; type 4000 → ✗ reserved (Relay). Launch stays disabled.
3. **Logs**: card → Logs; lines stream; scroll up stops Follow; filter works.
4. **Playground**: Try it → send a prompt; reply streams; ttft and tok/s shown.
   Target "… — via Relay" goes through :4000 and appears in Relay's Requests.
5. **Relay**: card toggle unpublishes/publishes; Relay view lists `lcpp:<port>`;
   the Relay dashboard shows the endpoint with a "managed · lcpp" badge.
6. **Router**: a router card lists its models; Load/Unload changes the dot.
7. **Stop / Stop all**: confirmation names the instance and mentions Relay;
   card disappears; `lcpp status` agrees.
8. **Models**: sizes and file counts match `lcpp models`; Nemotron shows
   `split` with 3 parts; "Discovered" lists `~/Models/Qwen3.6-27B-Q4KM.gguf`.
9. **Settings**: change the port range, Save, `GET /api/ports/suggest` follows.
10. **Phone width** (375 px): no horizontal scroll; dialogs are full-screen.
11. **Idle**: close the tab; `utils/measure_idle.sh` shows ~0% CPU.
