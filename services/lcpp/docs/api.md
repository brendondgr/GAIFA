# lcpp API

lcppd listens on `http://127.0.0.1:7710` (this machine only; `daemon.port` in
`data/lcpp.json`). The web UI and the `lcpp` CLI are both clients of this API.
Interactive schema: `http://127.0.0.1:7710/api/docs`.

**Errors** are always `{"detail": string, "code": string}` with an HTTP status.
Codes: `port_in_use`, `port_reserved`, `name_taken`, `invalid_name`,
`model_not_found`, `model_files_missing`, `model_in_use`, `instance_not_found`,
`alias_conflict`, `relay_unreachable`, `invalid_param`, `daemon_error`,
`hf_not_found`, `hf_gated`, `hf_unreachable`, `not_gguf`, `download_not_found`,
`disk_full`.

`{name}` in instance routes also accepts the instance's **port**.

## Endpoints

| Method | Path | Body | Returns |
| --- | --- | --- | --- |
| GET | `/api/health` | | `{ok, version, instances}` |
| GET | `/api/overview` | | `{instances: Instance[], system: System, relay: RelayStatus}` |
| GET | `/api/system` | | `System` |
| GET | `/api/instances` | | `Instance[]` |
| POST | `/api/instances/preflight` | `LaunchSpec` | `Preflight` |
| POST | `/api/instances` | `LaunchSpec` | `201 {instance, warnings}` |
| POST | `/api/instances/stop-all` | | `202 {stopping: string[]}` |
| GET | `/api/instances/{name}` | | `Instance` |
| DELETE | `/api/instances/{name}` | | `202 Instance` (now `stopping`; a `failed` one is removed) |
| DELETE | `/api/instances/{name}?dismiss=1` | | `204` |
| POST | `/api/instances/{name}/restart` | | `202 Instance` |
| POST | `/api/instances/{name}/models/{id}/load` · `/unload` | | `Instance` (router only) |
| GET | `/api/instances/{name}/logs?lines=N` | | `{lines: LogLine[]}` |
| GET | `/api/instances/{name}/logs/stream` | | SSE, one `LogLine` per `data:` |
| POST | `/api/instances/{name}/relay` | `{alias?}` | `Instance` |
| DELETE | `/api/instances/{name}/relay` | | `Instance` |
| POST | `/api/chat` | `{target, request}` | SSE of OpenAI chunks, then `{"lcpp_metrics": Metrics}` |
| GET | `/api/models` | | `{defaults, models: Model[]}` |
| PUT | `/api/models/defaults` | `Params` | `Params` |
| PUT | `/api/models/{id}` | `ModelInput` | `Model` |
| DELETE | `/api/models/{id}` | | `204` (`409 model_in_use` while running) |
| POST | `/api/models/validate` | `ModelInput` | `{ok, files, errors}` |
| GET | `/api/models/discovered` | | `Discovered[]` |
| POST | `/api/downloads/resolve` | `{input}` | `HfRepo` |
| GET | `/api/downloads` | | `Download[]` (newest first) |
| POST | `/api/downloads` | `DownloadSpec` | `201 Download` |
| POST | `/api/downloads/{id}/cancel` | | `Download` (partial files removed) |
| POST | `/api/downloads/{id}/retry` | | `Download` (resumes `.part` files) |
| DELETE | `/api/downloads/{id}` | | `204` (cancels first if still running) |
| GET | `/api/relay` | | `{status, owned, others, routable_models}` |
| POST | `/api/relay/test` | | `RelayStatus` |
| DELETE | `/api/relay/registrations/{key}` | | `204` |
| POST | `/api/relay/cleanup` | | `{removed: string[]}` |
| GET / PUT | `/api/settings` | `Settings` | `Settings` / `{settings, restart_required}` |
| GET | `/api/recent` | | `LaunchSpec[]` (≤ 5, newest first) |
| GET | `/api/ports/suggest` | | `{port}` |
| GET | `/config.js` | | switches the web UI from its mock API to this one |

## Types

The object shapes are the ones in
[plans/design-brief-lcpp-ui.md §6.4](plans/design-brief-lcpp-ui.md), which the
web UI's mock implements. Notes on the live implementation:

- **LaunchSpec**: `kind` defaults to `single`. `model_id` accepts an id or a
  nickname (`minicpm`). `relay.enabled` defaults to `relay.auto_register`.
  Params named `host`, `port`, `model`, `alias`, or `models-*` are rejected
  (`invalid_param`), because lcpp manages them.
- **Instance.rss_bytes** is the whole process tree's RSS **plus the GPU
  memory (GTT + VRAM) its DRM clients hold**. On unified memory, VmRSS alone
  misses most of a model's footprint.
- **Instance.models** (router only) carries `loading` besides `loaded`.
- **Preflight.estimated_bytes** is model files + a KV-cache estimate from the
  GGUF header (sliding-window, hybrid and shared-KV layers accounted for) +
  512 MB overhead.
- **Chat**: for an `instance` target, the daemon picks the upstream `model`
  itself (a single-model server's id, or a router's own model if the one sent
  isn't served). `stream_options.include_usage` is always requested.
- **Recent**: a launch with `save_preset` is stored with `name` set to the
  preset name.

### Hugging Face downloads

These shapes are not in the design brief; `web/assets/mock.js` implements them
too.

- **resolve `input`** is a repo id (`openbmb/MiniCPM5-1B`), a repo URL
  (optionally `/tree/<rev>`), or a file link
  (`https://huggingface.co/<repo>/resolve/<rev>/<file>.gguf?download=true`,
  or `/blob/`). The daemon reads the Hub API with the token from `HF_TOKEN` or
  `~/.cache/huggingface/token` (`hf auth login`). The token is sent to
  huggingface.co only, never to the CDN it redirects to.
- **HfRepo**: `{repo, revision, sha, gated, kind, message, search_url,
  choices, mmproj, drafts, selected, suggested_id, suggested_dir, free_bytes}`.
  - `choices` is one entry per model GGUF, sorted by size: `{id, label, quant,
    files: [{path, size_bytes, sha256}], size_bytes, complete, suggested_id}`.
    Split parts are grouped into one choice, whose `id` is part 1.
  - `mmproj` and `drafts` are the repo's `mmproj-*` and `mtp-*` sidecars.
  - `selected` is set for a file link, or when the repo has one choice.
    Otherwise the user picks.
  - A repo without GGUFs comes back with `choices: []`. `kind` says what it
    holds (`safetensors`, `awq`, `gptq`, …, from
    `config.quantization_config.quant_method`), and `message` and
    `search_url` point to a GGUF conversion.
- **DownloadSpec**: `{repo, revision?, choice, mmproj?, draft?, dir?,
  model_id?, nicknames?, add_to_catalog? = true}`.
  - The daemon re-reads the repo and ignores client-sent sizes.
  - `dir` is one folder name under `models/`.
  - `model_id` must not be in the catalog yet. With a `draft`, the entry gets
    `spec_type: draft-mtp`.
- **Download**: `{id, repo, revision, label, dir, state, error, warning,
  model_id, bytes_total, bytes_done, speed_bps, eta_s, created_ts,
  finished_ts, files: [{path, name, size_bytes, done_bytes, state}]}`.
  - `state` is `queued`, `downloading`, `done`, `failed` or `cancelled`.
  - Downloads run one at a time inside the daemon. Each file streams to
  `<name>.part`, is checked against its LFS sha256, then is renamed into
  place.
  - A daemon restart stops a download. Retry, or start it again, and it
  resumes from the `.part` file.
  - Finished jobs stay listed until dismissed or the daemon restarts.

## Under AIHub

When lcpp runs as AIHub's `lcpp` mod (`services/lcpp`, AIHub plan Phase 10), the daemon has `AIHUB_URL` and these apply. Without it, nothing below changes lcpp's behavior.

- **`GET /api/status`** → `{loaded, busy, stats, jobs}` (AIHub's status shape): `loaded` = an instance is ready, `busy` = one is starting or a download is running; stats Running, Catalog, On disk (GB); jobs = starting instances and downloads with progress (finished downloads stay for 2 min).
- **Memory acquire.** `POST /api/instances` asks AIHub for the preflight's `estimated_bytes` first (`POST {AIHUB_URL}/api/memory/acquire`). When other mods would have to be unloaded, the launch fails with **409 `needs_room`** and AIHub's plan in `data.plan`. Sending the launch again with **`X-AIHub-Make-Room: 1`** lets AIHub unload them. If AIHub can't be reached, the launch goes ahead (and is logged).
- **Errors** may carry a `data` object: `{detail, code, data?}`.
- **Downloads** are registered in AIHub's models registry when they finish (`POST {AIHUB_URL}/api/models`: the folder, kind `llm`, the Hugging Face repo and revision, each file's sha256). A failure becomes the job's `warning`.
- **Models folder.** `LCPP_MODELS_DIR` (AIHub: `data/models/llm`). Catalog paths are relative to it (`Gemma4-26B/x.gguf`); paths outside it are stored absolute or `~/`-relative. The old repo-relative form (`models/Gemma4-26B/x.gguf`) still resolves, and `data/models.json` is rewritten once when it is loaded. A `scan_dirs` entry `"models"` means this folder.
- **Relay metadata.** Registrations link `manager_url` to the Launcher page in AIHub (`{AIHUB_URL}/#/s/lcpp`).
