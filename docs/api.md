# lcpp API

lcppd listens on `http://127.0.0.1:7700` (this machine only; `daemon.port` in
`data/lcpp.json`). The web UI and the `lcpp` CLI are both clients of this API.
Interactive schema: `http://127.0.0.1:7700/api/docs`.

**Errors** are always `{"detail": string, "code": string}` with an HTTP status.
Codes: `port_in_use`, `port_reserved`, `name_taken`, `invalid_name`,
`model_not_found`, `model_files_missing`, `model_in_use`, `instance_not_found`,
`alias_conflict`, `relay_unreachable`, `invalid_param`, `daemon_error`.

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
