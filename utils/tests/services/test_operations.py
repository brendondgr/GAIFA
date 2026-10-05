"""2.6: OpenAPI → Operation[]: the four real captures (snapshots) and fake-ok live through the route.

Snapshots live in fixtures/openapi/snapshots/. After an intended change, regenerate them with
    UPDATE_SNAPSHOTS=1 uv run pytest utils/tests/services/test_operations.py
and review the diff.
"""

from __future__ import annotations

import json
import os

import httpx
import pytest

from utils.manifest import Manifest
from utils.operations import OpenAPIError, convert
from utils.tests.conftest import OPENAPI
from utils.tests.services.conftest import ready, until

SNAPSHOTS = OPENAPI / "snapshots"

# Roughly what each app's service.toml will say when it moves in (Phases 7–10).
MANIFESTS = {
    "tts": {
        "id": "tts", "run": {"command": ["x"], "port": 5040},
        "api": {"responses": {"POST /v1/speech": "audio", "POST /v1/audio/speech": "audio", "GET /v1/voices/{name}/audio": "audio", "GET /v1/outputs/{filename}": "file"}},
        "tools": {"speak": {"op": "POST /v1/speech", "description": "Speak text in a saved voice"},
                  "delete_voice": {"op": "DELETE /v1/voices/{name}", "confirm": True}},
    },
    "gen3d": {
        "id": "gen3d", "run": {"command": ["x"], "port": 5050},
        "api": {"hide": ["GET /v1/jobs/{jid}/files/*"],
                "responses": {"GET /v1/events": "stream", "GET /v1/jobs/{jid}/events": "stream", "GET /v1/jobs/{jid}/download": "file"}},
        "tools": {"make_3d": {"op": "POST /v1/jobs"}, "cancel_3d": {"op": "POST /v1/jobs/{jid}/cancel", "confirm": True}},
    },
    "lcpp": {
        "id": "lcpp", "run": {"command": ["x"], "port": 7710, "openapi": "/openapi.json"},
        "api": {"responses": {"GET /api/instances/{name}/logs/stream": "stream"}},
        "tools": {"start_llm": {"op": "POST /api/instances"}, "stop_llm": {"op": "DELETE /api/instances/{name}", "confirm": True}},
    },
    "relay": {
        "id": "relay", "run": {"command": ["x"], "port": 4000},
        "api": {"hide": ["* /admin/endpoints/*/tunnel*"]},
    },
}


@pytest.mark.parametrize("name", sorted(MANIFESTS))
def test_real_openapi_snapshots(name):
    doc = json.loads((OPENAPI / f"{name}.json").read_text())
    ops = convert(doc, Manifest.model_validate(MANIFESTS[name]))
    snap = SNAPSHOTS / f"{name}.operations.json"
    text = json.dumps(ops, indent=1, sort_keys=True) + "\n"
    if os.environ.get("UPDATE_SNAPSHOTS"):
        SNAPSHOTS.mkdir(exist_ok=True)
        snap.write_text(text)
    assert snap.exists(), f"no snapshot; run with UPDATE_SNAPSHOTS=1 to create {snap.name}"
    assert json.loads(text) == json.loads(snap.read_text())


def test_every_operation_has_the_brief_shape():
    keys = {"id", "method", "path", "summary", "description", "tag", "params", "body", "response", "destructive", "tool"}
    for name, m in MANIFESTS.items():
        ops = convert(json.loads((OPENAPI / f"{name}.json").read_text()), Manifest.model_validate(m))
        assert ops, name
        assert len({o["id"] for o in ops}) == len(ops)
        for o in ops:
            assert set(o) == keys
            assert o["method"] in ("GET", "POST", "PUT", "PATCH", "DELETE")
            assert o["response"] in ("json", "audio", "image", "video", "model3d", "file", "stream", "empty")
            assert o["body"] is None or o["body"]["content_type"] in ("application/json", "multipart/form-data")
            assert "$ref" not in json.dumps(o), (name, o["id"])
            for p in o["params"]:
                assert p["in"] in ("path", "query") and (p["required"] or p["in"] == "query")


def _ops(name: str) -> dict[str, dict]:
    doc = json.loads((OPENAPI / f"{name}.json").read_text())
    return {o["id"]: o for o in convert(doc, Manifest.model_validate(MANIFESTS[name]))}


def test_tts_details():
    ops = _ops("tts")
    speak = ops["post_v1_speech"]
    assert speak["response"] == "audio" and speak["tool"] == {"name": "speak", "confirm": False} and not speak["destructive"]
    assert speak["body"]["content_type"] == "application/json"
    assert speak["body"]["schema"]["properties"]["engine"]["enum"] == ["auto", "breeze", "kokoro"]
    assert speak["body"]["schema"]["properties"]["name"] == {"type": "string", "title": "Name", "description": "custom voice name, a Kokoro voice (af_heart...), or omit", "nullable": True}
    add = ops["post_v1_voices"]
    assert add["body"]["content_type"] == "multipart/form-data"
    assert add["body"]["schema"]["properties"]["audio"]["format"] == "binary"
    assert ops["delete_v1_voices_name"]["destructive"] and ops["delete_v1_voices_name"]["tool"]["confirm"]
    assert ops["delete_v1_voices_name"]["params"] == [{"name": "name", "in": "path", "required": True, "schema": {"type": "string", "title": "Name"}}]
    assert ops["get_v1_outputs_filename"]["response"] == "file"
    assert "get_openapi_json" not in ops and "get_docs" not in ops


def test_gen3d_hide_glob_confirm_and_query_params():
    ops = _ops("gen3d")
    assert "get_v1_jobs_jid_files_path" not in ops
    cancel = ops["post_v1_jobs_jid_cancel"]
    assert cancel["destructive"] and cancel["tool"] == {"name": "cancel_3d", "confirm": True}
    limit = next(p for p in ops["get_v1_jobs"]["params"] if p["name"] == "limit")
    assert limit == {"name": "limit", "in": "query", "required": False, "schema": {"type": "integer", "maximum": 1000, "minimum": 1, "default": 100, "title": "Limit"}}
    assert ops["get_v1_events"]["response"] == "stream" and ops["get_v1_events"]["tag"] == "events"


def test_lcpp_tags_and_204():
    ops = _ops("lcpp")
    assert ops["get_api_instances"]["tag"] == "instances"
    assert ops["delete_api_models_model_id"]["response"] == "empty"
    assert ops["get_api_instances_name_logs_stream"]["response"] == "stream"


def test_relay_hides_by_glob_and_skips_head():
    ops = _ops("relay")
    import fnmatch

    assert not [o for o in ops.values() if fnmatch.fnmatchcase(f"{o['method']} {o['path']}", "* /admin/endpoints/*/tunnel*")]
    assert "get_admin_endpoints_tunnel_sessions" in ops  # doesn't match the glob: kept
    assert [o["method"] for o in ops.values() if o["path"] == "/v1/{path}"] == ["GET", "POST", "PUT", "PATCH", "DELETE"]


def test_response_kinds_from_content_types():
    m = Manifest.model_validate({"id": "kinds", "run": {"command": ["x"], "port": 5100}})

    def op(ctype, code="200"):
        return {"responses": {code: {"content": {ctype: {}}} if ctype else {"description": "x"}}}

    doc = {"paths": {
        "/a": {"get": op("audio/mpeg")}, "/i": {"get": op("image/png")}, "/v": {"get": op("video/mp4")},
        "/m": {"get": op("model/gltf-binary")}, "/s": {"get": op("text/event-stream")}, "/f": {"get": op("application/zip")},
        "/o": {"get": op("application/octet-stream")}, "/j": {"get": op("application/json")}, "/e": {"delete": op(None, "204")},
        "/t": {"get": op("text/plain")}, "/n": {"get": {"responses": {"400": {}}}},
    }}
    kinds = {o["path"]: o["response"] for o in convert(doc, m)}
    assert kinds == {"/a": "audio", "/i": "image", "/v": "video", "/m": "model3d", "/s": "stream", "/f": "file",
                     "/o": "file", "/j": "json", "/e": "empty", "/t": "json", "/n": "json"}


def test_recursive_refs_and_duplicate_ids():
    m = Manifest.model_validate({"id": "rec", "run": {"command": ["x"], "port": 5100}})
    doc = {
        "paths": {
            "/tree": {"post": {"requestBody": {"content": {"application/json": {"schema": {"$ref": "#/components/schemas/Node"}}}}, "responses": {}}},
            "/a-b": {"get": {"responses": {}}}, "/a_b": {"get": {"responses": {}}},
            "/x": {"parameters": [{"$ref": "#/components/parameters/Q"}], "get": {"responses": {}}},
        },
        "components": {
            "schemas": {"Node": {"type": "object", "properties": {"kids": {"type": "array", "items": {"$ref": "#/components/schemas/Node"}}}}},
            "parameters": {"Q": {"name": "q", "in": "query", "schema": {"type": "string"}}},
        },
    }
    ops = {o["path"]: o for o in convert(doc, m)}
    kids = ops["/tree"]["body"]["schema"]["properties"]["kids"]["items"]
    assert kids["description"] == "(recursive: Node)"
    assert {ops["/a-b"]["id"], ops["/a_b"]["id"]} == {"get_a_b", "get_a_b_2"}
    assert ops["/x"]["params"] == [{"name": "q", "in": "query", "required": False, "schema": {"type": "string"}}]


def test_not_openapi():
    m = Manifest.model_validate({"id": "bad", "run": {"command": ["x"], "port": 5100}})
    with pytest.raises(OpenAPIError):
        convert({"swagger": "2.0"}, m)


# --- live, through the route ------------------------------------------------------------------


@pytest.fixture
async def hub(rig, serve):
    rig.add("fake-ok")
    served = await serve()
    await ready(served, "fake-ok")
    return served


async def test_route_converts_fake_ok(hub):
    async with httpx.AsyncClient(base_url=hub.url) as c:
        r = await c.get("/api/services/fake-ok/operations")
    assert r.status_code == 200
    ops = {o["id"]: o for o in r.json()}
    assert set(ops) == {
        "get_health", "get_v1_status", "post_v1_echo", "post_v1_speech", "get_v1_events", "post_v1_outputs", "post_v1_upload", "post_v1_jobs",
        "post_v1_fail", "delete_v1_jobs_jid", "get_v1_widgets_requests",
    }
    assert ops["delete_v1_jobs_jid"]["destructive"] and ops["delete_v1_jobs_jid"]["params"][0]["in"] == "path"
    assert ops["post_v1_speech"]["response"] == "audio"  # declared audio/wav (and [api.responses])
    assert ops["get_v1_events"]["response"] == "stream"
    assert ops["post_v1_upload"]["body"]["content_type"] == "multipart/form-data"
    assert ops["post_v1_upload"]["body"]["schema"]["properties"]["file"]["format"] == "binary"
    assert "get_openapi_json" not in ops


async def test_cached_per_process_start(hub):
    svc = hub.services.get("fake-ok")
    await until(lambda: svc.operations)  # fetched in the background once ready
    first_key = svc.operations_key
    assert svc.operations and first_key == (svc.pid, svc.started_ts)  # fetched on ready
    await hub.services.restart("fake-ok", wait=True)
    async with httpx.AsyncClient(base_url=hub.url) as c:
        r = await c.get("/api/services/fake-ok/operations")
    assert r.status_code == 200 and svc.operations_key != first_key
    await hub.services.stop("fake-ok", wait=True)
    async with httpx.AsyncClient(base_url=hub.url) as c:
        r = await c.get("/api/services/fake-ok/operations")
    assert r.status_code == 200 and len(r.json()) == 11  # the last list is kept while stopped


async def test_never_started_is_503(rig, serve):
    rig.add("fake-ok")
    rig.config("[services.fake-ok]\nautostart = false")
    served = await serve()
    async with httpx.AsyncClient(base_url=served.url) as c:
        r = await c.get("/api/services/fake-ok/operations")
        assert r.status_code == 503 and r.json()["code"] == "service_not_running"
        r = await c.get("/api/services/nope/operations")
    assert r.status_code == 404 and r.json()["code"] == "service_not_found"
