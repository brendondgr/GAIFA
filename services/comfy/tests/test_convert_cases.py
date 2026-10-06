"""11.5: the editor-only constructs the development workflows don't use."""

from comfy.convert import to_api
from comfy.nodes import NodeCatalog

CAT = NodeCatalog({
    "Loader": {"input": {"required": {"name": [["a.safetensors", "b.safetensors"], {}]}}, "output": ["MODEL"]},
    "Lora": {"input": {"required": {"model": ["MODEL"], "lora": [["x.safetensors"], {}], "strength": ["FLOAT", {"default": 1.0}]}},
             "input_order": {"required": ["model", "lora", "strength"]}, "output": ["MODEL"]},
    "Sampler": {"input": {"required": {"model": ["MODEL"], "seed": ["INT", {"default": 0, "control_after_generate": True}],
                                       "steps": ["INT", {"default": 20}]},
                          "optional": {"mode": ["COMFY_DYNAMICCOMBO_V3", {"options": [
                              {"key": "simple", "inputs": {"required": {}}},
                              {"key": "fancy", "inputs": {"required": {"eta": ["FLOAT", {"default": 0.5}]}}}]}]}},
                "input_order": {"required": ["model", "seed", "steps"], "optional": ["mode"]}, "output": ["LATENT"]},
    "Save": {"input": {"required": {"latent": ["LATENT"], "filename_prefix": ["STRING", {"default": "x"}]}},
             "output": [], "output_node": True},
    "Text": {"input": {"required": {"text": ["STRING", {"multiline": True}]}}, "output": ["STRING"]},
    "Dict": {"input": {"required": {"fps": ["INT", {"default": 8}], "fmt": [["mp4", "gif"], {}]}}, "output": []},
})


def node(id, type, inputs=(), outputs=(), values=None, mode=0, **kw):
    return {"id": id, "type": type, "mode": mode, "inputs": [dict(i) for i in inputs], "outputs": [dict(o) for o in outputs],
            "widgets_values": values if values is not None else [], **kw}


def sock(name, type, link=None, widget=None):
    d = {"name": name, "type": type, "link": link}
    if widget:
        d["widget"] = {"name": widget}
    return d


def out(type, links=()):
    return {"type": type, "links": list(links)}


def chain(*middle, links):
    """Loader(1) → … → Sampler(9) → Save(10)."""
    return {"nodes": [node(1, "Loader", outputs=[out("MODEL", [1])], values=["a.safetensors"]), *middle,
                      node(9, "Sampler", [sock("model", "MODEL", 9)], [out("LATENT", [10])], [42, "randomize", 4, "fancy", 0.7]),
                      node(10, "Save", [sock("latent", "LATENT", 10)], values=["out"])],
            "links": links}


def test_widgets_control_values_and_dynamic_combo():
    wf = chain(links=[[1, 1, 0, 9, 0, "MODEL"], [10, 9, 0, 10, 0, "LATENT"]])
    wf["nodes"][1]["inputs"][0]["link"] = 1
    g = to_api(wf, CAT).graph
    assert g["9"]["inputs"] == {"model": ["1", 0], "seed": 42, "steps": 4, "mode": "fancy", "mode.eta": 0.7}
    assert g["10"]["inputs"] == {"latent": ["9", 0], "filename_prefix": "out"}


def test_reroute_bypass_and_muted():
    reroute = node(2, "Reroute", [sock("", "*", 1)], [out("MODEL", [2])])
    bypassed = node(3, "Lora", [sock("model", "MODEL", 2)], [out("MODEL", [3])], ["x.safetensors", 0.5], mode=4)
    wf = chain(reroute, bypassed, links=[[1, 1, 0, 2, 0, "MODEL"], [2, 2, 0, 3, 0, "MODEL"], [3, 3, 0, 9, 0, "MODEL"],
                                         [10, 9, 0, 10, 0, "LATENT"]])
    wf["nodes"][-2]["inputs"][0]["link"] = 3
    g = to_api(wf, CAT).graph
    assert set(g) == {"1", "9", "10"} and g["9"]["inputs"]["model"] == ["1", 0]
    wf["nodes"][2]["mode"] = 2                   # muted instead: its output link is dropped
    assert "model" not in to_api(wf, CAT).graph["9"]["inputs"]


def test_primitive_and_set_get():
    wf = {"nodes": [
        node(1, "Loader", outputs=[out("MODEL", [1])], values=["a.safetensors"]),
        node(2, "SetNode", [sock("MODEL", "MODEL", 1)], [out("*")], ["base"]),
        node(3, "GetNode", outputs=[out("MODEL", [3])], values=["base"]),
        node(4, "PrimitiveNode", outputs=[out("INT", [4])], values=[7, "fixed"]),
        node(9, "Sampler", [sock("model", "MODEL", 3), sock("steps", "INT", 4, widget="steps")], [out("LATENT")], [1, "fixed", 20]),
        node(5, "MarkdownNote", values=["# notes"]),
    ], "links": [[1, 1, 0, 2, 0, "MODEL"], [3, 3, 0, 9, 0, "MODEL"], [4, 4, 0, 9, 1, "INT"]]}
    c = to_api(wf, CAT)
    assert set(c.graph) == {"1", "9"}
    assert c.graph["9"]["inputs"]["model"] == ["1", 0] and c.graph["9"]["inputs"]["steps"] == 7


def test_unknown_nodes():
    wf = {"nodes": [
        node(1, "Loader", outputs=[out("MODEL", [1])], values=["a.safetensors"]),
        node(2, "FancyCustom", [sock("model", "MODEL", 1)], [out("MODEL", [2])], ["?"]),
        node(9, "Sampler", [sock("model", "MODEL", 2)], [out("LATENT")], [1, "fixed", 20]),
        node(7, "Bookmark (rgthree)", values=[]),
    ], "links": [[1, 1, 0, 2, 0, "MODEL"], [2, 2, 0, 9, 0, "MODEL"]]}
    c = to_api(wf, CAT)
    assert c.missing == {"2": "FancyCustom"} and c.graph["2"]["inputs"] == {"model": ["1", 0]}
    assert "7" not in c.graph and c.notes[0]["type"] == "Bookmark (rgthree)"


def test_dict_widget_values_and_defaults():
    wf = {"nodes": [node(1, "Dict", values={"fps": 24, "fmt": "gif", "extra": 1}),
                    node(2, "Sampler", [sock("model", "MODEL")], values=[5])], "links": []}
    g = to_api(wf, CAT).graph
    assert g["1"]["inputs"] == {"fps": 24, "fmt": "gif"}
    assert g["2"]["inputs"] == {"seed": 5, "steps": 20, "mode": "simple"}   # missing values: defaults


def test_subgraph_flattened_with_promoted_widget():
    sub = {"id": "sg-1", "name": "Make", "inputs": [{"name": "model", "type": "MODEL"}, {"name": "steps", "type": "INT"}],
           "outputs": [{"name": "LATENT", "type": "LATENT"}],
           "nodes": [node(1, "Lora", [sock("model", "MODEL", 11)], [out("MODEL", [12])], ["x.safetensors", 0.8]),
                     node(2, "Sampler", [sock("model", "MODEL", 12), sock("steps", "INT", 13, widget="steps")],
                          [out("LATENT", [14])], [3, "fixed", 20])],
           "links": [{"id": 11, "origin_id": -10, "origin_slot": 0, "target_id": 1, "target_slot": 0, "type": "MODEL"},
                     {"id": 12, "origin_id": 1, "origin_slot": 0, "target_id": 2, "target_slot": 0, "type": "MODEL"},
                     {"id": 13, "origin_id": -10, "origin_slot": 1, "target_id": 2, "target_slot": 1, "type": "INT"},
                     {"id": 14, "origin_id": 2, "origin_slot": 0, "target_id": -20, "target_slot": 0, "type": "LATENT"}]}
    wf = {"nodes": [node(1, "Loader", outputs=[out("MODEL", [1])], values=["b.safetensors"]),
                    node(5, "sg-1", [sock("model", "MODEL", 1), sock("steps", "INT", None, widget="steps")],
                         [out("LATENT", [2])], [9, 0.3], properties={"proxyWidgets": [["-1", "steps"], ["1", "strength"]]}),
                    node(10, "Save", [sock("latent", "LATENT", 2)], values=["out"])],
          "links": [[1, 1, 0, 5, 0, "MODEL"], [2, 5, 0, 10, 0, "LATENT"]],
          "definitions": {"subgraphs": [sub]}}
    g = to_api(wf, CAT).graph
    assert set(g) == {"1", "5:1", "5:2", "10"}
    assert g["5:1"]["inputs"] == {"model": ["1", 0], "lora": "x.safetensors", "strength": 0.3}
    assert g["5:2"]["inputs"]["model"] == ["5:1", 0] and g["5:2"]["inputs"]["steps"] == 9
    assert g["10"]["inputs"]["latent"] == ["5:2", 0]


def test_subgraph_promoted_input_without_proxies():
    sub = {"id": "sg-2", "inputs": [{"name": "steps", "type": "INT"}], "outputs": [],
           "nodes": [node(2, "Sampler", [sock("model", "MODEL"), sock("steps", "INT", 13, widget="steps")], [], [3, "fixed", 20])],
           "links": [{"id": 13, "origin_id": -10, "origin_slot": 0, "target_id": 2, "target_slot": 1, "type": "INT"}]}
    wf = {"nodes": [node(5, "sg-2", [sock("steps", "INT", None, widget="steps")], [], [11])], "links": [],
          "definitions": {"subgraphs": [sub]}}
    assert to_api(wf, CAT).graph["5:2"]["inputs"]["steps"] == 11
