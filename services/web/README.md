# Web

An AIHub mod (plan Phase 26): web search through a SearXNG on this machine, and pages fetched into Outputs so the chat agent can read and cite them. Setup: [setup/web.md](setup/web.md). The mod guide is [docs/mods.md](../../docs/mods.md).

| Route | What it does |
|---|---|
| `GET /health` | 200 while this server is up (SearXNG may still be down) |
| `GET /v1/status` | SearXNG up or down (with the reason and where its URL came from), searches, pages fetched, fetches refused |
| `POST /v1/search` | `{query, categories?, time_range?, language?, limit ≤ 20}` → `{results: [{title, url, snippet, engine, published?}], answers, suggestions, unresponsive}` |
| `POST /v1/fetch` | `{url, max_chars?}` → the page saved as an output, its final URL, title and first `max_chars` of markdown |

The agent's tools are `web_search` and `web_fetch`, both risk `network` (plan 25.1). `web_search` runs without asking: AIHub ships an `always` grant for it (hub.db migration 010), listed in Settings → Agent, where revoking it makes searches ask (`grant_key = "const:search"`, so one answer covers every search). `web_fetch` asks; its `grant_key = "url:host"`, so "allow in this chat" covers one site. The skill [skills/researching](skills/researching/SKILL.md) tells the agent how to research and cite.

**Dry runs (the agent eval).** Both tools say `dry_run = true` in `[tools]`, so in a dry run the hub still calls this mod, with `"dry_run": true` in `X-AIHub-Origin`. The mod then answers from its **fake web**, [fakeweb/](fakeweb/) (`fakeweb.py`): canned search results and pages on `.example` hosts, which never resolve, and never the internet or SearXNG. The pages go through the same conversion and are saved as outputs with `"dry_run": true` in their sidecar. The eval task `web_two_sources` uses them.

**Reading a page for the user** (plan 30.8). The mod's page, **Read a page**, and Chat's composer (a pasted link, or "Add a web page" in the attach menu) go through the hub's `POST /api/web/read {url, text?}`, not a tool call: the user asked for the page, so there is no approval card, but every fetch rule below applies. The hub calls `/v1/fetch`, then screens the **whole** saved text for instructions aimed at an AI (patterns, then the `[agent.screen]` model, in pieces; architecture §14.8), keeps the report with the output (`outputs/.text/<id>.screening.json`) and answers `{output, url, final_url, title, kind, chars, screening: {removed, checked, ms, model, covered, findings: [{passage, why, by, excerpt, line}]}}`, plus `markdown` and `screened` with `text: true`. The agent's later reads of that output (`hub_read_document`, an attachment sent whole) reuse the report instead of screening again. The page shows the markdown rendered as the agent reads it (or as it was), what was removed and why, Copy markdown and Open in Outputs.

**Which SearXNG.** The URL the [`searxng` mod](../searxng/README.md) publishes (`GET /api/s/searxng/v1/endpoint` through the hub, asked at most once a minute), else `SEARXNG_URL` (default `http://127.0.0.1:8080`).

## Outputs

- **Pages** become markdown: `outputs/web/<date>/<HHMMSS>-<host>-<slug>.md`, starting with the title, the source URL and the fetch time, then the page's main content. `htmlmd.py` puts back what trafilatura loses: a code block's language (`language-*`, `lang-*`, `highlight-source-*` classes) and blank lines, taken from the page's `<pre>`; layout tables without a header line (GitHub's comments) become paragraphs, wider ones get a header line. Plain text and JSON are kept as they are (JSON in a fenced block).
- **PDFs** are saved as they came: `…/<HHMMSS>-<host>-<slug>.pdf` with `kind = "document"` in the sidecar, so the hub's document tools (plan 24.3–24.4) read them. (`[outputs] kinds` in `service.toml` says only `text`: the manifest doesn't accept `document` there yet.)
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
- When it finds no main content (a page that is all navigation), the page's visible text is kept instead, with its headings, list items, code blocks and table rows (`htmlmd.plain`; `html2txt` gave one line).

## Working on it

```bash
.venv/bin/python -m pytest      # the tests: a fake SearXNG and local web server, no network
aihub check web --start
aihub restart web               # after editing server.py, pages.py or htmlmd.py
./install.sh                    # after changing requirements.txt
```
