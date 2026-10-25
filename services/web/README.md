# Web

A GAIFA mod (plan Phase 26): web search through a SearXNG on this machine, and pages fetched and saved as hidden outputs so the chat agent can read and cite them. Setup: [setup/web.md](setup/web.md). The mod guide is [docs/mods.md](../../docs/mods.md).

| Route | What it does |
|---|---|
| `GET /health` | 200 while this server is up (SearXNG may still be down) |
| `GET /v1/status` | SearXNG up or down (with the reason and where its URL came from), searches, pages fetched, fetches refused |
| `POST /v1/search` | `{query, categories?, time_range?, language?, limit ≤ 20}` → `{results: [{title, url, snippet, engine, published?}], answers, suggestions, unresponsive}` |
| `POST /v1/fetch` | `{url, max_chars?, focus?}` → the page saved as an output, its final URL, title, `description` (its meta description, when it has one) and first `max_chars` of markdown. `focus` is for the hub (below); the mod ignores it |
| `GET /v1/favicon?host=<host>` | A site's icon for Chat's Sources (`favicons.py`): ICO, PNG, GIF, JPEG or WebP, with `nosniff` and a week's browser cache; 404 `no_favicon` when there is none, 422 `bad_host` for an IP, a local name or anything that isn't a DNS name |

The agent's tools are `web_search` and `web_fetch`, both risk `network` (plan 25.1). `web_search` runs without asking: GAIFA ships an `always` grant for it (hub.db migration 010), listed in Settings → Agent, where revoking it makes searches ask (`grant_key = "const:search"`, so one answer covers every search). `web_fetch` asks; its `grant_key = "url:host"`, so "allow in this chat" covers one site. It runs without a card, in every mode but Plan, for a URL the chat's own search returned and for a **link the user typed** in the chat (the agent sends the links of the user's own messages as `origin.links`; the hub compares the exact URL and never stores them; `utils/tools/searched.py`).

**What the model reads of a fetched page** (the hub's `utils/tools/webread.py`, after this mod answers). The text carries the saved page's line numbers (`  120| …`, blank lines left out), and the result's `cite` says how to cite it: the page as a link to its URL, a passage as `#n:<line>` (the agent puts in the output's real `#n`), which opens the viewer at that line. A page longer than `max_chars` comes back as its passages most relevant to `focus` (or the user's message this turn), most relevant first, each under `── lines a–b of N · under "<heading>" ──`, with an "About this page" line (the description, else the first paragraph), up to `max_chars`; `relevance` in the result says how many and by what. `[agent.web] relevance` (Settings → Agent → Reading web pages): `auto` (the decide mod when it's up with its model loaded, else `lexical`), `decide` (d3-lite answers "does this passage help answer …?" for lexical's best 24, four at once), `lexical` (BM25 on the words in common), `off` (the page's start). Only what is shown is screened. The whole page stays the output for `hub_read_document` and `hub_search_document`. The skill [skills/researching](skills/researching/SKILL.md) tells the agent how to research and cite.

**Dry runs (the agent eval).** Both tools say `dry_run = true` in `[tools]`, so in a dry run the hub still calls this mod, with `"dry_run": true` in `X-GAIFA-Origin`. The mod then answers from its **fake web**, [fakeweb/](fakeweb/) (`fakeweb.py`): canned search results and pages on `.example` hosts, which never resolve, and never the internet or SearXNG. The pages go through the same conversion and are saved as outputs with `"dry_run": true` in their sidecar. The eval task `web_two_sources` uses them.

**Reading a page for the user** (plan 30.8). The mod's page, **Read a page**, and Chat's composer (a pasted link, or "Add a web page" in the attach menu) go through the hub's `POST /api/web/read {url, text?}`, not a tool call: the user asked for the page, so there is no approval card, but every fetch rule below applies. The hub calls `/v1/fetch`, then screens the **whole** saved text for instructions aimed at an AI (patterns, then the `[agent.screen]` model, in pieces; architecture §14.8), keeps the report with the output (`outputs/.text/<id>.screening.json`) and answers `{output, url, final_url, title, kind, chars, screening: {removed, checked, ms, model, covered, findings: [{passage, why, by, excerpt, line}]}}`, plus `markdown` and `screened` with `text: true`. The agent's later reads of that output (`hub_read_document`, an attachment sent whole) reuse the report instead of screening again. The page shows the markdown rendered as the agent reads it (or as it was), what was removed and why, Copy markdown and Open in Outputs.

**Which SearXNG.** The URL the [`searxng` mod](../searxng/README.md) publishes (`GET /api/s/searxng/v1/endpoint` through the hub, asked at most once a minute), else `SEARXNG_URL` (default `http://127.0.0.1:8080`).

**Site icons** (`favicons.py`, for the Sources pill under a chat reply). The UI asks `/api/s/web/v1/favicon?host=<host>` for each source's host; nothing goes to a third-party icon service. The mod tries `https://<host>/favicon.ico`, then the `<link rel="icon">` (or `shortcut icon`, `apple-touch-icon`, never SVG or `data:`) of the site's home page, which it reads only when that site's `robots.txt` allows it (the `/favicon.ico` request itself skips robots.txt, as browsers do). Every request follows the fetch rules below (public addresses only, checked on every connection and redirect), with an 8 s limit for the whole lookup and 100 KB per icon. An icon is served only when it says it is an image (or `application/octet-stream`, or nothing) **and** its bytes start like an ICO, PNG, GIF, JPEG or WebP; its type comes from those bytes. SVG is refused (it can carry script), and the UI draws the host's first letter instead. Icons are cached in `data/state/web/favicons/<host>.<ext>` (misses as `<host>.miss`): hits for 30 days, misses for a day, at most 2000 files and 20 MB, oldest first. Privacy: showing a reply's sources makes this machine contact each shown site, at most once a month per site: `/favicon.ico`, and when that fails its `robots.txt`, home page and icon. That includes search results the agent didn't open (when the pill shows them, or **Also found** is opened), so those sites learn this machine's address.

## Outputs

Every saved page is a **hidden** output (plan 30.9): its sidecar says `"hidden": true`, so the hub keeps it for `hub_read_document` / `hub_search_document`, the screening report and citations (by id, its file and text all work), but leaves it out of the Outputs page (unless **Saved web pages** is on), the pickers, the Overview, the agent's output search and the embed library: Outputs holds what the user made. `pages.hide_saved(outputs)` marks pages saved before this (a sidecar with no `hidden` key; one that says `false` is left alone), safe to run any number of times. `[outputs] hidden_keep_days` in `config.toml` moves hidden pages older than that to the outputs trash; `0`, the default, keeps them.

- **Pages** become markdown: `outputs/web/<date>/<HHMMSS>-<host>-<slug>.md`, starting with the title, the source URL and the fetch time, then the page's main content. `htmlmd.py` puts back what trafilatura loses: a code block's language (`language-*`, `lang-*`, `highlight-source-*` classes) and blank lines, taken from the page's `<pre>`; layout tables without a header line (GitHub's comments) become paragraphs, wider ones get a header line; heading and definition permalinks (Sphinx's `¶`, and `#`, `§`, `🔗` anchors) are dropped outside code, from the title too. Plain text and JSON are kept as they are (JSON in a fenced block).
- **PDFs** are saved as they came: `…/<HHMMSS>-<host>-<slug>.pdf` with `kind = "document"` in the sidecar, so the hub's document tools (plan 24.3–24.4) read them. (`[outputs] kinds` in `service.toml` says only `text`: the manifest doesn't accept `document` there yet.)
- **Sidecar** `<file>.json`: `title`, `kind`, `url` (as asked), `final_url` (after redirects), `fetched_ts`, `fetched` (ISO time), `content_type`, `chars`, `published`, `site` and `description` when the page says, `source`, `hidden: true`, and `dry_run: true` from the fake web.

**Where the time goes** (measured 2026-10-21): fetching takes 55–150 ms and turning HTML into markdown 25–90 ms (about 270 ms for the first page after a start, trafilatura warming up); screening is the rest (gemma4-26B: 2.9 s for 8.5k characters, 13.9 s for 29k). So screening reads less: code and table rows without a sentence in them are left to the patterns, a long page's `web_fetch` screens only the passages shown, and `[agent.screen] parallel` sets the calls at once.

## Fetch rules (`safety.py`)

- `http` and `https` only.
- No loopback, private, link-local, carrier-grade NAT, multicast or reserved addresses, and no `localhost`, `.local`, `.localhost`, `.internal`, `.lan` or `.home.arpa` names. The check runs where the connection is made: the name is resolved once, **every** address it resolves to must be public, and the socket connects to the address that was checked. Redirects are followed by hand (at most 5), so every hop goes through the same check; so does `robots.txt`.
- 10 MB per response (by `Content-Length`, and counted while reading) and 20 s for the whole fetch, redirects included.
- `robots.txt` is honoured for the user agent `GAIFA-web`, cached per site for an hour. A missing one (4xx) allows everything; one that fails (5xx, no answer) allows nothing (RFC 9309).
- No proxies from the environment; the user agent is `GAIFA-web/0.1 (…)`.

## Why trafilatura

Pages become markdown with [trafilatura](https://trafilatura.readthedocs.io/) rather than `readability-lxml` + `markdownify`:
- **One step.** It finds the main content and writes markdown itself (headings, lists, links, tables), so there is no second library and no HTML-to-markdown pass to tune.
- **Metadata.** The title, the publication date and the site name come from the same parse, for the sidecar and the citation.
- **Quality and upkeep.** It is the most accurate of the open extractors in the published benchmarks (its own and ScrapingHub's article-extraction benchmark), is actively maintained, and is Apache-2.0. `readability-lxml` is a port of an old Readability and needs `lxml_html_clean` split out.
- When it finds no main content (a page that is all navigation), the page's visible text is kept instead, with its headings, list items, code blocks and table rows (`htmlmd.plain`; `html2txt` gave one line).

## Working on it

```bash
.venv/bin/python -m pytest      # the tests: a fake SearXNG and local web server, no network
gaifa check web --start
gaifa restart web               # after editing server.py, pages.py or htmlmd.py
./install.sh                    # after changing requirements.txt
```
