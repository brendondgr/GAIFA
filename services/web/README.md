# Web

An AIHub mod (plan Phase 26): web search through a SearXNG on this machine, and pages fetched into Outputs so the chat agent can read and cite them. Setup: [setup/web.md](setup/web.md). The mod guide is [docs/mods.md](../../docs/mods.md).

| Route | What it does |
|---|---|
| `GET /health` | 200 while this server is up (SearXNG may still be down) |
| `GET /v1/status` | SearXNG up or down (with the reason), searches, pages fetched, fetches refused |
| `POST /v1/search` | `{query, categories?, time_range?, language?, limit ≤ 20}` → `{results: [{title, url, snippet, engine, published?}], answers, suggestions, unresponsive}` |
| `POST /v1/fetch` | `{url, max_chars?}` → the page saved as an output, its final URL, title and first `max_chars` of markdown |

The agent's tools are `web_search` and `web_fetch`, both risk `network` (plan 25.1): `web_search` has `grant_key = "const:search"`, so one "allow in this chat" covers every search; `web_fetch` has `grant_key = "url:host"`, so it covers one site. The skill [skills/researching](skills/researching/SKILL.md) tells the agent how to research and cite.

## Outputs

- **Pages** become markdown: `outputs/web/<date>/<HHMMSS>-<host>-<slug>.md`, starting with the title, the source URL and the fetch time, then the page's main content. Plain text and JSON are kept as they are (JSON in a fenced block).
- **PDFs** are saved as they came: `…/<HHMMSS>-<host>-<slug>.pdf` with `kind = "document"` in the sidecar, so the hub's document tools (plan 24.3–24.4) read them. Until plan 24.1 adds the `document` kind, the index shows them as `other`.
- **Sidecar** `<file>.json`: `title`, `kind`, `url` (as asked), `final_url` (after redirects), `fetched_ts`, `fetched` (ISO time), `content_type`, `chars`, `published` and `site` when the page says, `source`.

## Fetch rules (`safety.py`)

- `http` and `https` only.
- No loopback, private, link-local, carrier-grade NAT, multicast or reserved addresses, and no `localhost`, `.local`, `.localhost`, `.internal`, `.lan` or `.home.arpa` names. The check runs where the connection is made: the name is resolved once, **every** address it resolves to must be public, and the socket connects to the address that was checked. Redirects are followed by hand (at most 5), so every hop goes through the same check; so does `robots.txt`.
- 10 MB per response (by `Content-Length`, and counted while reading) and 20 s for the whole fetch, redirects included.
- `robots.txt` is honoured for the user agent `AIHub-web`, cached per site for an hour. A missing one (4xx) allows everything; one that fails (5xx, no answer) allows nothing (RFC 9309).
- No proxies from the environment; the user agent is `AIHub-web/0.1 (…)`.

## Why trafilatura

Pages become markdown with [trafilatura](https://trafilatura.readthedocs.io/) rather than `readability-lxml` + `markdownify`:
- **One step.** It finds the main content and writes markdown itself (headings, lists, links, tables), so there is no second library and no HTML-to-markdown pass to tune.
- **Metadata.** The title, the publication date and the site name come from the same parse, for the sidecar and the citation.
- **Quality and upkeep.** It is the most accurate of the open extractors in the published benchmarks (its own and ScrapingHub's article-extraction benchmark), is actively maintained, and is Apache-2.0. `readability-lxml` is a port of an old Readability and needs `lxml_html_clean` split out.
- When it finds no main content (a page that is all navigation), the page's visible text is kept instead.

## Working on it

```bash
.venv/bin/python -m pytest      # the tests: a fake SearXNG and local web server, no network
aihub check web --start
aihub restart web               # after editing server.py
./install.sh                    # after changing requirements.txt
```
