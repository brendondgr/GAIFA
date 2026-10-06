"""Editor workflow (what ComfyUI saves) → API graph (what /prompt runs), using the node catalog.

This does what ComfyUI's frontend does in `graphToPrompt`, without a browser:
- **Widget values** are matched to the node's widget inputs in catalog order. The extra values
  the editor stores after some widgets (a seed's "randomize", LoadImage's "image" upload button)
  are recognised and skipped; dynamic combos (`COMFY_DYNAMICCOMBO_V3`) bring the chosen option's
  own widgets, named `parent.child`; inputs the saved file has no value for get their default.
- **Links** are followed through what only exists in the editor: Reroute, PrimitiveNode, Note
  and MarkdownNote, KJNodes' SetNode/GetNode, muted nodes (their links are dropped), bypassed
  nodes (the input of the same type is passed through) and subgraphs (flattened; inner nodes get
  ids "outer:inner", as ComfyUI does).

A node type the catalog doesn't have is kept (links only) and reported, so check() can name it.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any

from .nodes import InputSpec, NodeCatalog, _spec

MUTED, BYPASS = 2, 4
SUBGRAPH_IN, SUBGRAPH_OUT = "-10", "-20"
CONTROL_VALUES = {"fixed", "increment", "decrement", "randomize"}
UPLOAD_VALUES = {"image", "video", "audio", "Upload", "upload"}
UPLOAD_FLAGS = ("image_upload", "video_upload", "audio_upload", "animated_image_upload")
WIDGET_TYPES = {"INT", "FLOAT", "STRING", "BOOLEAN", "COMBO", "COMFY_DYNAMICCOMBO_V3"}
EDITOR_ONLY = {"Note", "MarkdownNote", "Reroute", "PrimitiveNode", "SetNode", "GetNode",
               # rgthree's editor helpers: they switch or group other nodes, and never run
               "Fast Groups Bypasser (rgthree)", "Fast Groups Muter (rgthree)", "Fast Bypasser (rgthree)",
               "Fast Muter (rgthree)", "Mute / Bypass Repeater (rgthree)", "Mute / Bypass Relay (rgthree)",
               "Node Collector (rgthree)", "Bookmark (rgthree)", "Label (rgthree)", "Reroute (rgthree)"}
PASS_THROUGH = {"Reroute", "Reroute (rgthree)"}
# cg-use-everywhere: links that exist only in the editor, made by broadcasting a value to inputs
BROADCAST = ("Anything Everywhere", "Prompts Everywhere", "Seed Everywhere")


class ConvertError(Exception):
    def __init__(self, reason: str, node: str | None = None, type: str | None = None):
        super().__init__(f"node {node} ({type}): {reason}" if node else reason)
        self.reason, self.node, self.type = reason, node, type


@dataclass
class Converted:
    graph: dict[str, dict]
    missing: dict[str, str] = field(default_factory=dict)       # exec id → node type not in the catalog
    notes: list[dict] = field(default_factory=list)             # {node, type, detail}: things worth a look
    titles: dict[str, str] = field(default_factory=dict)        # exec id → the node's title in the editor
    broadcast: list[str] = field(default_factory=list)          # "Anything Everywhere" nodes: links only the editor makes


@dataclass(frozen=True)
class Literal:
    value: Any


def is_api(d: Any) -> bool:
    """An API graph: {"<id>": {"class_type": …, "inputs": {…}}, …}."""
    return isinstance(d, dict) and bool(d) and all(isinstance(v, dict) and "class_type" in v for v in d.values())


def is_editor(d: Any) -> bool:
    return isinstance(d, dict) and isinstance(d.get("nodes"), list)


@dataclass
class _Link:
    id: str
    origin: str
    origin_slot: int
    target: str
    target_slot: int
    type: str


class _Scope:
    """One graph level: the root, or a subgraph definition."""

    def __init__(self, nodes: list[dict], links: list, defs: dict[str, dict], parent: _Scope | None = None,
                 owner: dict | None = None, prefix: str = ""):
        self.nodes = {str(n["id"]): n for n in nodes}       # ids may be ints or strings ("2682:0")
        self.links: dict[str, _Link] = {}
        for raw in links or []:
            ln = _link(raw)
            if ln:
                self.links[ln.id] = ln
        self.defs, self.parent, self.owner, self.prefix = defs, parent, owner, prefix

    def exec_id(self, node_id) -> str:
        return f"{self.prefix}{node_id}"

    def input_link(self, node: dict, slot: int) -> _Link | None:
        ins = node.get("inputs") or []
        if slot >= len(ins):
            return None
        lid = ins[slot].get("link")
        return self.links.get(str(lid)) if lid is not None else None

    def child(self, node: dict) -> _Scope:
        d = self.defs[node["type"]]
        return _Scope(d.get("nodes") or [], d.get("links") or [], self.defs, self, node, f"{self.exec_id(node['id'])}:")


def _link(raw) -> _Link | None:
    try:
        if isinstance(raw, list) and len(raw) >= 5:
            return _Link(str(raw[0]), str(raw[1]), int(raw[2]), str(raw[3]), int(raw[4]), str(raw[5]) if len(raw) > 5 else "*")
        if isinstance(raw, dict) and "id" in raw:
            return _Link(str(raw["id"]), str(raw["origin_id"]), int(raw["origin_slot"]), str(raw["target_id"]),
                         int(raw["target_slot"]), str(raw.get("type", "*")))
    except (TypeError, ValueError):
        return None
    return None


class _Converter:
    def __init__(self, wf: dict, catalog: NodeCatalog):
        self.catalog = catalog
        defs = {d["id"]: d for d in ((wf.get("definitions") or {}).get("subgraphs") or []) if "id" in d}
        self.root = _Scope(wf.get("nodes") or [], wf.get("links") or [], defs)
        self.out = Converted({})
        self._setters: dict[str, tuple[_Scope, dict]] = {}

    # ---- nodes ------------------------------------------------------------------------
    def run(self) -> Converted:
        self._index_setters(self.root)
        self._scope(self.root)
        return self.out

    def _index_setters(self, scope: _Scope) -> None:
        for n in scope.nodes.values():
            if n.get("type") == "SetNode" and n.get("widgets_values"):
                self._setters[str(n["widgets_values"][0])] = (scope, n)
            elif n.get("type") in scope.defs:
                self._index_setters(scope.child(n))

    def _scope(self, scope: _Scope) -> None:
        for nid, node in scope.nodes.items():
            t = node.get("type")
            if node.get("mode") in (MUTED, BYPASS):
                continue
            if t in scope.defs:
                self._scope(scope.child(node))
                continue
            if t in EDITOR_ONLY and not self.catalog.has(t):
                continue
            if str(t).startswith(BROADCAST) and not self.catalog.has(t):
                self.out.broadcast.append(scope.exec_id(nid))
                continue
            eid = scope.exec_id(nid)
            if not self.catalog.has(t):
                if not self._has_links(scope, node):
                    self.out.notes.append({"node": eid, "type": t, "detail": "not installed and not connected: left out"})
                    continue
                self.out.missing[eid] = t
            title = node.get("title") or (self.catalog.node(t) or {}).get("display_name") or t
            self.out.graph[eid] = {"class_type": t, "inputs": self._inputs(scope, node), "_meta": {"title": title}}
            self.out.titles[eid] = title

    def _has_links(self, scope: _Scope, node: dict) -> bool:
        if any(i.get("link") is not None for i in node.get("inputs") or []):
            return True
        return any(o.get("links") for o in node.get("outputs") or [])

    def _inputs(self, scope: _Scope, node: dict) -> dict:
        t = node["type"]
        ui_inputs = node.get("inputs") or []
        inputs: dict[str, Any] = {}
        if self.catalog.has(t):
            inputs.update(self._widgets(node))
        for slot, ui in enumerate(ui_inputs):
            if ui.get("link") is None:
                continue
            ln = scope.links.get(str(ui["link"]))
            if ln is None:
                continue
            src = self._source(scope, ln)
            name = ui.get("name") or (ui.get("widget") or {}).get("name")
            if not name:
                continue
            if src is None:
                continue                           # dropped (muted source): a widget keeps its own value
            if isinstance(src, Literal):
                inputs[name] = src.value
            else:
                inputs[name] = [src[0], src[1]]
        return inputs

    # ---- widget values ----------------------------------------------------------------
    def _widgets(self, node: dict) -> dict:
        t = node["type"]
        values = node.get("widgets_values")
        sockets = {i.get("name") for i in node.get("inputs") or [] if not i.get("widget")}
        specs = [s for s in self.catalog.inputs(t) if self._is_widget(s, sockets)]
        out: dict[str, Any] = {}
        if t in CUSTOM_WIDGETS:
            return CUSTOM_WIDGETS[t](values)
        if isinstance(values, dict):              # some custom nodes (VideoHelperSuite) save by name
            for s in specs:
                out[s.name] = values.get(s.name, _default(s))
            for k, v in values.items():           # widgets their editor adds per format (crf, pix_fmt, …)
                if k not in out and k not in sockets and (v is None or isinstance(v, (str, int, float, bool))):
                    out[k] = v
            return out
        queue = list(values or [])
        self._consume(specs, queue, out, "")
        return out

    @staticmethod
    def _is_widget(spec: InputSpec, sockets: set) -> bool:
        if spec.name in sockets:
            return False                           # a socket in this saved node (forceInput, converted)
        return (spec.type in WIDGET_TYPES or spec.type in DISPLAY_WIDGETS) and not spec.options.get("forceInput")

    def _consume(self, specs: list[InputSpec], queue: list, out: dict, prefix: str) -> None:
        for s in specs:
            name = prefix + s.name
            v = queue.pop(0) if queue else _default(s)
            out[name] = v
            if queue and (s.options.get("control_after_generate") or (s.type == "INT" and s.name in ("seed", "noise_seed"))):
                if isinstance(queue[0], str) and queue[0] in CONTROL_VALUES:
                    queue.pop(0)
            if queue and any(s.options.get(f) for f in UPLOAD_FLAGS) and queue[0] in UPLOAD_VALUES:
                queue.pop(0)
            if s.type == "COMFY_DYNAMICCOMBO_V3":
                opts = s.options.get("options") or []
                chosen = next((o for o in opts if o.get("key") == v), opts[0] if opts else None)
                if chosen is not None and chosen.get("key") != v:
                    out[name] = chosen.get("key")
                sub = []
                for section in ("required", "optional"):
                    for k, raw in ((chosen or {}).get("inputs", {}).get(section) or {}).items():
                        sp = _spec(k, raw, section == "required")
                        if sp.type in WIDGET_TYPES:
                            sub.append(sp)
                self._consume(sub, queue, out, name + ".")

    # ---- links ------------------------------------------------------------------------
    def _source(self, scope: _Scope, ln: _Link, depth: int = 0) -> tuple[str, int] | Literal | None:
        """Where a link's value really comes from: (exec id, slot), a literal, or None (dropped)."""
        if depth > 64:
            raise ConvertError("links loop through editor-only nodes", scope.exec_id(ln.target))
        if ln.origin == SUBGRAPH_IN:
            return self._from_subgraph_input(scope, ln.origin_slot, depth)
        node = scope.nodes.get(ln.origin)
        if node is None:
            return None
        t = node.get("type")
        if node.get("mode") == MUTED:
            return None
        if node.get("mode") == BYPASS:                 # a bypassed subgraph passes through too
            return self._through_bypass(scope, node, ln, depth)
        if t in scope.defs:
            return self._from_subgraph_output(scope.child(node), ln.origin_slot, depth)
        if t in PASS_THROUGH and not self.catalog.has(t):
            up = scope.input_link(node, 0)
            return self._source(scope, up, depth + 1) if up else None
        if t == "PrimitiveNode" and not self.catalog.has(t):
            vals = node.get("widgets_values") or []
            return Literal(vals[0]) if vals else None
        if t == "GetNode" and not self.catalog.has(t):
            name = str((node.get("widgets_values") or [""])[0])
            got = self._setters.get(name)
            if not got:
                raise ConvertError(f"GetNode '{name}' has no matching SetNode", scope.exec_id(ln.origin), t)
            s_scope, setter = got
            up = s_scope.input_link(setter, 0)
            return self._source(s_scope, up, depth + 1) if up else None
        if t == "SetNode" and not self.catalog.has(t):
            up = scope.input_link(node, 0)
            return self._source(scope, up, depth + 1) if up else None
        return scope.exec_id(ln.origin), ln.origin_slot

    def _through_bypass(self, scope: _Scope, node: dict, ln: _Link, depth: int):
        ins = node.get("inputs") or []
        out_type = ((node.get("outputs") or [{}] * (ln.origin_slot + 1))[ln.origin_slot] or {}).get("type") or ln.type
        order = [ln.origin_slot] + [i for i in range(len(ins)) if i != ln.origin_slot] if ln.origin_slot < len(ins) else range(len(ins))
        for i in order:
            if i < len(ins) and ins[i].get("type") == out_type and ins[i].get("link") is not None:
                up = scope.links.get(str(ins[i]["link"]))
                return self._source(scope, up, depth + 1) if up else None
        # No input of that type: ComfyUI's editor falls back to the input at the same slot number
        # (seen on a held-out workflow: a bypassed SAM2Segment's MASK output carried its prompt).
        if ln.origin_slot < len(ins) and ins[ln.origin_slot].get("link") is not None:
            up = scope.links.get(str(ins[ln.origin_slot]["link"]))
            return self._source(scope, up, depth + 1) if up else None
        return None

    def _from_subgraph_input(self, scope: _Scope, slot: int, depth: int):
        owner, parent = scope.owner, scope.parent
        if owner is None or parent is None:
            return None
        ins = owner.get("inputs") or []
        sg_inputs = (scope.defs[owner["type"]].get("inputs") or [])
        name = (sg_inputs[slot].get("name") if slot < len(sg_inputs) else None) or (ins[slot].get("name") if slot < len(ins) else None)
        # The subgraph node lists its inputs in its own order (widgets promoted later go at the end),
        # so the outside link is found by the input's name; the slot number is only a fallback.
        outer = next((i for i, x in enumerate(ins) if x.get("name") == name),
                     slot if len(ins) == len(sg_inputs) else None)
        up = parent.input_link(owner, outer) if outer is not None else None   # no outside socket: the inner value stands
        if up is not None:
            return self._source(parent, up, depth + 1)
        # Not connected outside: a value typed on the subgraph node itself (a promoted widget).
        vals = owner.get("widgets_values")
        if not isinstance(vals, list):
            return None
        proxies = (owner.get("properties") or {}).get("proxyWidgets")
        if proxies:                                # newer editors: values follow proxyWidgets; "-1" = an input
            for (inner_id, wname), v in zip(proxies, vals, strict=False):
                if str(inner_id) == "-1" and wname == name:
                    return Literal(v)
            return None
        widget_names = [i.get("widget", {}).get("name") or i.get("name") for i in ins if i.get("widget")]
        if name in widget_names and widget_names.index(name) < len(vals):
            return Literal(vals[widget_names.index(name)])
        return None

    def _from_subgraph_output(self, inner: _Scope, slot: int, depth: int):
        for ln in inner.links.values():
            if ln.target == SUBGRAPH_OUT and ln.target_slot == slot:
                return self._source(inner, ln, depth + 1)
        return None


def _power_lora(values) -> dict:
    """rgthree's Power Lora Loader saves [{}, {type: header}, {on, lora, strength}…, {}, ""]; its
    editor sends them as PowerLoraLoaderHeaderWidget, lora_1…lora_n and "➕ Add Lora"."""
    out: dict[str, Any] = {}
    n = 0
    for v in values or []:
        if isinstance(v, dict) and v.get("type"):
            out[str(v["type"])] = v
        elif isinstance(v, dict) and "lora" in v:
            n += 1
            out[f"lora_{n}"] = {k: x for k, x in v.items() if x is not None}   # the editor leaves out unset strengthTwo
    if values and values[-1] == "":
        out["➕ Add Lora"] = ""
    return out


CUSTOM_WIDGETS = {"Power Lora Loader (rgthree)": _power_lora}
# Widgets that only show something (no value of their own in the saved file): what the editor sends.
DISPLAY_WIDGETS = {"IMAGECOMPARE": {"__value__": ["", ""]}}


def _default(s: InputSpec) -> Any:
    if s.type in DISPLAY_WIDGETS:
        return DISPLAY_WIDGETS[s.type]
    if "default" in s.options:
        return s.options["default"]
    if s.type == "COMFY_DYNAMICCOMBO_V3":
        opts = s.options.get("options") or []
        return opts[0].get("key") if opts else None
    if s.choices:
        return s.choices[0]
    return {"INT": 0, "FLOAT": 0.0, "STRING": "", "BOOLEAN": False}.get(s.type)


def _apply_proxy_widgets(wf: dict) -> dict:
    """Subgraph nodes may show some inner widgets on the outside (`properties.proxyWidgets`:
    [[inner id, widget name], …]); the value typed outside wins, so copy it in."""
    defs = {d["id"]: d for d in ((wf.get("definitions") or {}).get("subgraphs") or []) if "id" in d}
    if not defs:
        return wf
    wf = copy.deepcopy(wf)
    defs = {d["id"]: d for d in ((wf.get("definitions") or {}).get("subgraphs") or []) if "id" in d}
    for node in wf.get("nodes") or []:
        proxies = (node.get("properties") or {}).get("proxyWidgets") or []
        vals = node.get("widgets_values")
        d = defs.get(node.get("type"))
        if not d or not proxies or not isinstance(vals, list):
            continue
        inner = {str(n["id"]): n for n in d.get("nodes") or []}
        for (inner_id, wname), v in zip(proxies, vals, strict=False):
            n = inner.get(str(inner_id))           # "-1" (a subgraph input) is handled in _from_subgraph_input
            if n is not None:
                n.setdefault("properties", {}).setdefault("_aihub_overrides", {})[wname] = v
    return wf


def _renumber(wf: dict) -> dict:
    """Give subgraph nodes whose ids collide with an id used before them a new id after the
    workflow's last one, in definition order, as ComfyUI's editor does when it loads a file (so a
    pack's node ids are the ones ComfyUI shows, and keeps once it saves the workflow again)."""
    defs = (wf.get("definitions") or {}).get("subgraphs") or []
    if not defs:
        return wf
    used = {str(n.get("id")) for n in wf.get("nodes") or []}
    last = int((wf.get("state") or {}).get("lastNodeId") or wf.get("last_node_id") or 0)
    plan: list[dict[str, str]] = []
    for sg in defs:
        m: dict[str, str] = {}
        for n in sg.get("nodes") or []:
            i = str(n.get("id"))
            if i in used:
                last += 1
                m[i] = str(last)
                used.add(m[i])
            else:
                used.add(i)
        plan.append(m)
    if not any(plan):
        return wf
    wf = copy.deepcopy(wf)
    for sg, m in zip((wf.get("definitions") or {}).get("subgraphs") or [], plan, strict=False):
        if not m:
            continue
        for n in sg.get("nodes") or []:
            if str(n.get("id")) in m:
                n["id"] = int(m[str(n["id"])]) if m[str(n["id"])].isdigit() else m[str(n["id"])]
        for ln in sg.get("links") or []:
            for k in ("origin_id", "target_id"):
                if isinstance(ln, dict) and str(ln.get(k)) in m:
                    ln[k] = int(m[str(ln[k])])
            if isinstance(ln, list):
                for k in (1, 3):
                    if str(ln[k]) in m:
                        ln[k] = int(m[str(ln[k])])
        for owner in [n for n in wf.get("nodes") or []] + [n for d in (wf.get("definitions") or {}).get("subgraphs") or [] for n in d.get("nodes") or []]:
            if owner.get("type") == sg.get("id"):
                pw = (owner.get("properties") or {}).get("proxyWidgets")
                if pw:
                    owner["properties"]["proxyWidgets"] = [[m.get(str(a), a), b] for a, b in pw]
    return wf


def to_api(workflow: dict, catalog: NodeCatalog) -> Converted:
    """Convert an editor workflow; an API graph is returned as it is."""
    if is_api(workflow):
        return Converted(copy.deepcopy(workflow), titles={k: (v.get("_meta") or {}).get("title", "") for k, v in workflow.items()})
    if not is_editor(workflow):
        raise ConvertError("not a ComfyUI workflow (neither an editor file nor an API graph)")
    if not catalog:
        raise ConvertError("the node catalog is empty: load ComfyUI once so its node list is cached")
    wf = _apply_proxy_widgets(_renumber(workflow))
    conv = _Converter(wf, catalog)
    out = conv.run()
    _overrides(conv.root, out)
    return out


def _overrides(scope: _Scope, out: Converted) -> None:
    """Apply proxied widget values (see _apply_proxy_widgets) to the flattened nodes."""
    for nid, node in scope.nodes.items():
        if node.get("type") in scope.defs:
            _overrides(scope.child(node), out)
            continue
        ov = (node.get("properties") or {}).get("_aihub_overrides")
        eid = scope.exec_id(nid)
        if ov and eid in out.graph:
            for k, v in ov.items():
                if not isinstance(out.graph[eid]["inputs"].get(k), list):
                    out.graph[eid]["inputs"][k] = v
