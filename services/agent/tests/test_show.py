"""Plan 47.1: the `show` tool: each view, each source, errors that name the field and the fix, the limits."""

from __future__ import annotations

import asyncio

import pytest

from agent import show

CSV = b"day,images,videos\nMon,4,1\nTue,6,2\nWed,3,0\n"


def resolve(ref: str) -> str | None:
    return {"#1": "aaaaaaaaaaaa", "#2": "bbbbbbbbbbbb", "output:cccccccccccc": "cccccccccccc"}.get(ref)


async def read(oid: str):
    if oid == "aaaaaaaaaaaa":
        return CSV, {"name": "stats.csv"}
    if oid == "bbbbbbbbbbbb":
        return b'[{"name": "fox", "size": 3}, {"name": "owl", "size": 5}]', {"name": "x.json"}
    return b'{"oops": 1}', {"name": "notes.json"}


def run(args):
    return asyncio.run(show.check(args, resolve, read))


def err(args) -> show.ShowError:
    with pytest.raises(show.ShowError) as e:
        run(args)
    return e.value


def test_inline_views():
    s = run({"view": "bar", "title": "Made per day", "x": ["Mon", "Tue"], "series": [{"name": "Images", "values": [4, 6]}]})
    assert s == {"view": "bar", "title": "Made per day", "data": {"x": ["Mon", "Tue"], "series": [{"name": "Images", "values": [4, 6]}]}}
    assert show.summary(s) == "Shown: a bar chart of 1 series, 2 points."
    t = run({"view": "table", "columns": ["a", "b"], "rows": [[1, 2], {"a": 3, "b": 4}]})
    assert t["data"]["rows"] == [[1, 2], [3, 4]]
    assert run({"view": "donut", "items": [{"label": "x", "value": 1}]})["data"]["items"][0]["value"] == 1
    hm = run({"view": "heatmap", "rows": ["a"], "columns": ["1", "2"], "values": [[1, 2]]})
    assert hm["data"]["values"] == [[1, 2]]


def test_a_list_sent_as_json_text_is_read():
    s = run({"view": "bar", "x": '["Mon", "Tue"]', "series": '[{"name": "n", "values": [1, 2]}]'})
    assert s["data"]["x"] == ["Mon", "Tue"]


def test_errors_name_the_field_and_the_fix():
    e = err({"view": "line", "x": ["a", "b"], "series": [{"name": "s", "values": [1]}]})
    assert e.field == "series[0].values" and "one value per x" in e.fix
    e = err({"view": "line", "x": ["a"], "series": [{"name": "s", "values": ["5 GB"]}]})
    assert "numbers" in e.detail and "unit" in e.fix
    assert err({"view": "pie"}).field == "view"
    assert err({"view": "line", "x": list(range(501)), "series": [{"values": [1] * 501}]}).field == "x"
    assert err({"view": "table", "columns": ["a"], "rows": [[1]] * 201}).field == "rows"
    assert err({"view": "gallery", "outputs": ["#9"]}).field == "outputs[0]"
    assert err({"view": "image", "outputs": ["#1", "#2"]}).field == "outputs"


def test_a_file_source_is_read_and_checked():
    s = run({"view": "line", "source": "#1", "x": "day", "y": ["images", "videos"]})
    assert s["file"] == {"output_id": "aaaaaaaaaaaa", "rows": 3, "columns": ["day", "images", "videos"], "x": "day", "y": ["images", "videos"]}
    assert "3 rows" in show.summary(s)
    e = err({"view": "line", "source": "#1", "x": "day", "y": ["audio"]})
    assert e.field == "y" and "day, images, videos" in e.fix
    assert err({"view": "line", "source": "#1", "x": "day", "y": ["day"]}).detail.startswith("column 'day' isn't numbers")
    t = run({"view": "table", "source": "#2"})
    assert t["file"]["columns"] == ["name", "size"] and t["file"]["show"] == ["name", "size"]
    assert err({"view": "table", "source": "output:cccccccccccc"}).field in ("source", "columns")


def test_hub_sources_and_outputs():
    s = run({"view": "area", "source": "hub:memory", "range": "7d"})
    assert s["hub"] == {"name": "memory", "range": "7d"} and "kept current" in show.summary(s)
    assert err({"view": "line", "source": "hub:secrets"}).field == "source"
    assert err({"view": "line", "source": "hub:mod_stat"}).field == "mod"
    assert run({"view": "gallery", "outputs": ["#1", "#2"]})["outputs"] == ["aaaaaaaaaaaa", "bbbbbbbbbbbb"]


async def test_show_through_the_loop(env):
    env.model.queue({"tool_calls": [{"name": "show", "arguments": {"view": "bar", "x": ["a", "b"], "series": [{"name": "n", "values": [1, 2]}]}}]},
                    {"text": "There it is."})
    tid = await env.thread(mode="auto")
    await env.send(tid, "chart it")
    res = env.payloads(tid, "tool_result")[-1]
    assert res["name"] == "show" and res["status"] == "done" and res["data"]["show"]["view"] == "bar"
    assert res["content"].startswith("Shown: a bar chart")
