# Plan: GAIFA from other devices on your network

**Asked for:** 2026-11-11 · **Status:** In progress

## 1. Introduction

GAIFA listens on `127.0.0.1:7000` only and has no login: architecture §2 ("only reachable from this machine"), §5 (who may call the hub, `utils/origin.py`) and `HubCfg._loopback` in `utils/config.py`, which refuses any other `hub.host` at startup. The user wants to open it from any device on their home network (a phone, a laptop).

That reverses a founding decision, and the hub can do a lot: edit files in workspace folders, run commands in the sandbox, read memory and chats, hold provider keys. So this plan doesn't simply bind to `0.0.0.0`. It adds a second way in, off by default: the hub also listens on the machine's network address, a device from the network must sign in with a password before anything answers, addresses outside the local network are refused, and the mods stay on loopback (other devices reach them only through the hub's proxy, `/api/s/<id>/*`). On this machine nothing changes: `127.0.0.1:7000` stays as it is, without a login, and mods keep calling the hub there.

Touches architecture §2, §5, §6 (new routes), §9 (`[hub.lan]`), §12 (risks); the brief §6 (types) and the Settings page; `docs/setup/README.md`; the `gaifa` skill's "Loopback only" invariant and `CLAUDE.md`.

## 2. Gaps & unanswered questions

- **A password for other devices?** *Answered (2026-11-11): the user said to build everything, so the recommended answer stands:* yes, one password, set on this machine, asked once per device (a cookie for 30 days). Without one, anyone on the Wi-Fi (guests, a compromised smart device) could run commands and read every chat.
- **The microphone on other devices.** *Answered (2026-11-11): Phase 3 is built (the recommendation).* Browsers allow the microphone (voice mode, dictation) only on `localhost` or over HTTPS. Over plain `http://192.168.x.x:7000` everything works except those. *Recommended and planned (Phase 3):* HTTPS on a second port with a certificate GAIFA makes itself; each device shows a warning once, or you install GAIFA's certificate on it. The alternative is to leave voice out on other devices and skip Phase 3.
- **What other devices may do.** *Answered (2026-11-11): the recommendation:* everything the page does here, except three things that stay on this machine: changing the network settings and password, the Bypass chat mode, and raising a workspace folder's level. Say if other devices should be equal, or more limited (for example chat only).
- **The firewall.** Fedora's firewalld blocks the port. Opening it needs `sudo`, which GAIFA never runs: `gaifa lan on` prints the command (`sudo firewall-cmd --add-port=…/tcp --permanent && sudo firewall-cmd --reload`) and checks afterwards whether the port answers.
- **Which addresses count as your network**: *Assumption:* private and link-local ranges only (10/8, 172.16/12, 192.168/16, 169.254/16, fc00::/7, fe80::/10), and by default only the subnets of this machine's own interfaces. A request from any other address is refused before the sign-in page. GAIFA is never meant for the internet; a VPN (Tailscale's 100.64/10) is opt-in: `[hub.lan] allow = ["100.64.0.0/10"]`.
- **Names**: *Assumption:* devices use the address (`http://192.168.1.20:7000`) or the machine's mDNS name (`http://<hostname>.local:7000`) when the system's Avahi publishes one; GAIFA starts no name service. Extra names: `[hub.lan] names`.
- **`/mcp`, and the mods' own ports**: *Assumption:* loopback only, as today. Claude Code on another machine is not part of this plan.
- **Links that name `127.0.0.1`** (ComfyUI's own page, SearXNG, a mod's direct port, `web/api.js`, `settings/llm-view.js`, `chat/chat-sources.js`, `chat/chat-judge.js`): found in 1.4; each becomes a hub-relative address or is marked "on the GAIFA machine only".
- **The toolbox**: the hub runs on the host as `gaifa.service`; nothing here depends on the toolbox.

## 3. Phases and steps

The three questions above were answered with the recommendations on 2026-11-11.

## Phase 1 — A second way in, with a sign-in (L)

- [x] **1.1 Settings: `utils/config.py`, `config.example.toml`.**
  - **`[hub.lan]`** (`LanCfg`): `enabled = false`, `bind = "auto"` (the address of the default route's interface; or an address, never a public one), `port = 7000`, `allow = []` (extra CIDRs), `names = []`, `session_days = 30`. `hub.host` stays loopback and its check stays.
  - **`utils/lan/addresses.py`:** `local_addresses()` (the interfaces' addresses and subnets, standard library plus `/proc/net` or `psutil`, which the hub already has), `is_local(ip, cfg)`, `urls(cfg)` for what to show the user.
  *Done when:* `utils/tests/lan/test_addresses.py` (ranges, a public `bind` refused with a fix, `allow`), `utils/tests/settings/test_lan.py` (defaults, a save, a bad value 422).
- [x] **1.2 The password and sessions: `utils/lan/auth.py`.**
  - **Password:** set with `gaifa lan password` (prompted, never an argument) or in Settings on this machine; stored as scrypt (`hashlib.scrypt`, a salt per password) in `data/state/lan/auth.json` (0600; in `gaifa backup`). At least 12 characters. No password → the network listener doesn't start.
  - **Sessions:** a random token per device in an `HttpOnly`, `SameSite=Strict` cookie (`gaifa_session`; `Secure` over HTTPS), kept hashed in `data/state/lan/sessions.json` with the device's label (from its User-Agent), address, first and last use; `session_days` to expire.
  - **Attempts:** five wrong passwords from an address → 30 s, doubling to 15 min; a toast on this machine (`POST /api/notify`) for a new device and for a lockout.
  *Done when:* `utils/tests/lan/test_auth.py` (hashing, a session's life, expiry, revoke, lockout with a fake clock).
- [x] **1.3 The guard: `utils/origin.py`, `utils/lan/guard.py`.**
  - **Who is asking:** from the connection's address, never a header (`X-Forwarded-For` is ignored). Loopback → today's rules, unchanged. Not local (`is_local` false) → 403 `not_local`, no body. Local → `Host` must be the bind address or one of `names` (421 `bad_host` otherwise, so DNS rebinding stays closed), `same_origin` accepts that origin with `http` or `https`, and everything except the sign-in routes and its page needs a valid session: 401 `sign_in` for the API, a redirect to `/signin` for a page, close code 4401 for a WebSocket.
  - **Pure ASGI**, as `RequestGuard` is, so streams, SSE and WebSockets pass through; `request.state.remote = True` for a signed-in network device (1.5 reads it).
  - **Routes** (`utils/routes/lan.py`): `GET /signin` (a small page of its own, no app code before sign-in), `POST /api/lan/signin`, `POST /api/lan/signout`, `GET /api/lan/status` (loopback: enabled, URLs, devices; a network device: its own session only), `DELETE /api/lan/sessions/{id}` and `PUT /api/lan/password` (loopback only).
  *Done when:* `utils/tests/lan/test_guard.py` over the ASGI app with fake client addresses: loopback unchanged (the existing origin tests pass untouched), a public address refused, a local one without a cookie gets only `/signin`, a foreign `Host` 421, a cross-site POST 403, SSE and a WebSocket with and without a session, `/mcp` and `/api/lan/password` refused from the network.
- [x] **1.4 Listening: `app.py`, and the page's addresses.**
  - **Sockets:** `sockets()` already returns a list; with `lan.enabled` and a password it adds the network address. A bind that fails (the address is gone, the port is taken) is a warning and an alert, not a failed start. An address that changes (DHCP, another Wi-Fi) is followed: `utils/lan/watch.py` rebinds when the interface's address changes.
  - **Mods:** untouched; `GAIFA_URL` stays `http://127.0.0.1:7000`. `gaifa doctor` gains a check that no mod listens on anything but loopback.
  - **The page:** audit `web/` for `127.0.0.1` / `localhost` (the files in §2): API and stream addresses come from `location`; links to a mod's own port go through the proxy or show "on the GAIFA machine only" when `config.js` says `remote`.
  *Done when:* `utils/tests/lan/test_listen.py` (the socket list per config; a failed bind doesn't stop the hub); a scratch hub bound to this machine's address, opened from the toolbox's or a container's address: sign in, Overview, a chat turn with its stream, a mod page through the proxy; `gaifa doctor` passes.
- [x] **1.5 What a network device may not do: `utils/lan/limits.py`.**
  - A short list checked in one place (a dependency on the routes it names): `PUT /api/settings` for `[hub.lan]`, the `/api/lan` admin routes, a chat's mode set to Bypass (the agent is told through the origin: `origin.remote`), raising a workspace folder's level. Refused with 403 `this_machine_only` and a sentence saying where to do it. The page hides or disables those controls when `remote`.
  - The list follows the answer to §2's third question.
  *Done when:* `utils/tests/lan/test_limits.py` (each refused from the network, allowed from loopback); the contract test with the new error code; brief §6 and §11.7.

*As built (2026-11-12):* the hub listens on every address (`bind = "all"`: 0.0.0.0 and ::) rather than one, so a new Wi-Fi address needs no rebinding (`watch.py` isn't needed: `Lan` finds the interfaces again every 30 s); `bind` can still name one address. Only real network interfaces count as local: container bridges (docker, br-, veth, podman) and VPNs (tailscale, wg) don't unless `allow` names them. The WebSocket proxy trusts the guard for a signed-in device. Checked on a scratch hub reached at this machine's Wi-Fi address (192.168.1.19:7079, so the requests came from the network, not loopback) with curl and a WebSocket client: no cookie 401 and the page redirected to `/signin`, a wrong password 401, signed in the API, the page, Overview, the event stream, the agent through the proxy and voice mode's WebSocket worked; a foreign Host 421, `/mcp` 403, Bypass 403, another site's Origin 403; this machine still needed nothing; `gaifa doctor` said it is open. The sign-in page seen at phone width. The sign-in in a browser is the user's to try (a password typed on a non-localhost address).

**Wire — Phase 1:** nothing visible yet beyond the sign-in page; the switch is Phase 2.

**Checks & deliverables — Phase 1**
- [ ] The whole suite passes with `lan.enabled = false` and nothing behaves differently (the default).
- [ ] From a second device on the network against a scratch hub (the user's phone, with the firewall command run by the user): sign-in, a chat, a generated image opening, the stream surviving a screen lock.
- [ ] A wrong `Host`, a cross-site form and an address outside the subnet are refused (curl with `--resolve` and a container on another bridge network).
- [ ] Delivered: `[hub.lan]`, `utils/lan/`, the guard's network rules, `/signin` and `/api/lan/*`, the second socket.

## Phase 2 — Turning it on, and seeing who is in (M)

- [x] **2.1 The command: `utils/cli.py` (`gaifa lan`).**
  - `gaifa lan status` (on or off, the URLs, devices signed in, whether the port answers from the network address), `gaifa lan on` (asks for a password when none is set, saves `enabled`, restarts the hub, prints the URL, a QR code of it as text, and the firewall command with what it does), `gaifa lan off`, `gaifa lan password`, `gaifa lan devices`, `gaifa lan signout <id> | --all`. Standard library only.
  *Done when:* `utils/tests/cli/test_lan.py` against a fake hub; `gaifa lan on` and `off` on a scratch root.
  *As built:* no QR code in the terminal (a QR encoder isn't worth a dependency in the standard-library CLI); the address is printed. The tests are `utils/tests/lan/test_cli.py`; `status` and `devices` ran against the scratch hub, `on` and `off` (which restart the installed hub's service) only against the fake one.
- [x] **2.2 Settings → General → Network: `web/settings/schema.js`, `web/settings/blocks-lan.js`.**
  - Rows: Open to my network (off by default; turning it on shows what it means in two sentences and needs a password), the address to open and a QR code, the firewall command with Copy, Password (change), Devices (label, address, last used, Sign out; Sign out everyone), Also allow (CIDRs), Names. On a network device the section is read-only and says so. A banner in the header on this machine while it is on ("Open to your network"), linking here.
  - Saving `enabled` restarts only the listener (`POST /api/lan/apply`), not the hub.
  *Done when:* `settings-schema.test.mjs` and a new `settings-lan.test.mjs`; `utils/tests/lan/test_apply.py` (on, off, a new address, without dropping loopback connections); browser check on a scratch hub.
- [x] **2.3 The page on a phone.**
  - Check the Chat page, Overview and Settings at 390 px wide through the network address and fix what blocks use (the sidebar as a drawer, the composer above the keyboard, panes stacked): only what is broken; a full mobile layout is a plan of its own.
  *Done when:* a list of what was found and fixed in `web/PATCHES.md`; screenshots in `docs/reference/lan-2026-11/`.
  *As built (2026-11-12):* no new route to apply without a restart: turning it on or off says so and offers **Restart GAIFA now** (`POST /api/system/restart`, which works only when the hub is its own systemd unit, found from its cgroup, and is refused from the network); no header banner (the Network group, `gaifa lan status` and `gaifa doctor` say it is open); no QR code. At 390 px (Chat, Overview, Settings, Calendar) nothing is cut off and nothing scrolls sideways; the pages are zoomed out a little (Settings 13 %, Overview 10 %, Chat 4 %) by their fixed side columns, left as found: a phone layout is a plan of its own. The screenshots were not kept: they show this machine's name and address.
- [x] **2.4 Docs and rules.**
  - architecture §2 (the hub address row: loopback, plus the network when the user turns it on, behind a sign-in), §5, §6, §9, §12 (the risks: the password is the only thing between the Wi-Fi and the sandbox; plain HTTP shows it and the chats to anyone who can read the network's traffic, which Phase 3 closes); `docs/setup/README.md` (opening GAIFA to your network); `docs/structure.md`; `CLAUDE.md` and the `gaifa` skill's invariant, reworded: the hub's default is loopback only, the network is opt-in through `[hub.lan]`, mods are always loopback (the skill in `.claude/skills/` and its copy in `.agents/skills/`).
  *Done when:* the docs tests pass; `gaifa docs --check --strict`.

**Wire — Phase 2:** Settings → General → Network and `gaifa lan` are live.

**Checks & deliverables — Phase 2**
- [ ] On the installed hub: `gaifa lan on`, the user runs the firewall command, a phone signs in and chats; `gaifa lan devices` shows it; Sign out ends its stream within a few seconds; `gaifa lan off` closes the port (checked from the phone).
- [ ] Delivered: `gaifa lan`, the Network section, the phone fixes, the docs.

## Phase 3 — HTTPS, so the microphone works on other devices (M)

Only if §2's second question is answered yes.

- [ ] **3.1 A certificate of its own: `utils/lan/cert.py`.**
  - `gaifa lan cert`: a small certificate authority and a server certificate for the bind address, the hostname and `names`, made with the `openssl` command when present (else the `cryptography` package as an optional dependency), in `data/state/lan/tls/` (keys 0600, never in `gaifa backup`'s default set without a flag). Renewed when the address changes or 30 days before it expires.
  *Done when:* `utils/tests/lan/test_cert.py` (the names in the certificate, renewal on a new address), skipped where `openssl` is missing.
- [ ] **3.2 The HTTPS listener: `app.py`.**
  - A second `uvicorn.Server` on the same app (`lifespan="off"`, one event loop) with TLS on `[hub.lan] https_port = 7443`; loopback stays plain HTTP so mods and the CLI are untouched. `[hub.lan] https = "also" | "only" | "off"`: `only` turns the network's plain-HTTP port into a redirect.
  *Done when:* `utils/tests/lan/test_https.py` (both listeners serve one app, the redirect, the `Secure` cookie); voice mode from a scratch hub over HTTPS in a browser on another address, with the fake microphone.
- [ ] **3.3 Trusting it on a device.**
  - `GET /lan/ca.crt` (the authority's public certificate only) with a page at `/lan/trust` of steps per system (iOS, Android, Windows, macOS, Linux), linked from the sign-in page and Settings → Network. Without it the device's browser warns once and goes on.
  *Done when:* the user's phone uses voice mode over the network; the steps are in `docs/setup/README.md`.

**Checks & deliverables — Phase 3**
- [ ] A phone on the network: sign in over HTTPS, dictate a message, hold a voice conversation.
- [ ] Delivered: the certificate, the HTTPS listener, the trust page.

## 4. Deliverables

| Deliverable | Description | Location |
| --- | --- | --- |
| `[hub.lan]` | the network listener's settings | `utils/config.py`, `config.example.toml` |
| Addresses | this machine's network addresses and what counts as local | `utils/lan/addresses.py`, `watch.py` |
| Sign-in | the password, sessions per device, lockout | `utils/lan/auth.py`, `utils/routes/lan.py` |
| Guard | the rules for a network device, beside the loopback ones | `utils/lan/guard.py`, `utils/origin.py` |
| Limits | what stays on this machine | `utils/lan/limits.py` |
| Listeners | the network socket, and HTTPS | `app.py`, `utils/lan/cert.py` |
| `gaifa lan` | on, off, status, password, devices, cert | `utils/cli.py` |
| Settings → General → Network | the switch, address, QR code, devices | `web/settings/schema.js`, `web/settings/blocks-lan.js` |
| Docs | architecture §2, §5, §6, §9, §12; setup guide; the reworded invariant | `docs/`, `CLAUDE.md`, `.claude/skills/gaifa/`, `.agents/skills/gaifa/` |
| Tests | fast tests with fake client addresses and a fake clock; Node tests for the page | `utils/tests/lan/`, `utils/tests/cli/test_lan.py`, `utils/tests/settings/test_lan.py`, `utils/tests/web/settings-lan.test.mjs` |
