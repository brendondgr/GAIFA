"""The packs as the API sees them: each pack converted, checked and described once per change
(of its files, the node catalog or the models list)."""

from __future__ import annotations

import logging
import time
from typing import Any

import httpx

from .check import Issue, check, convert, summary
from .convert import Converted
from .detect import Suggestion, model_sizes, suggest, to_toml
from .nodes import NodeCatalog
from .packs import Pack, Packs
from .schema import input_schema
from .tasks import Tasks

log = logging.getLogger("comfy")
MODELS_TTL_S = 60


def apply_set(conv: Converted, values: dict) -> list[Issue]:
    """workflow.toml's [set]: fixed field values on the converted graph."""
    issues = []
    for target, v in values.items():
        node, _, fld = target.partition(".")
        if node not in conv.graph:
            issues.append(Issue("error", "set_unmapped", f"set: node {node} isn't in the graph ({target})"))
        else:
            conv.graph[node]["inputs"][fld] = v
    return issues


class Library:
    def __init__(self, packs: Packs, catalog: NodeCatalog, tasks: Tasks, hub_url: str = "", models_dir=None):
        self.packs, self.catalog, self.tasks, self.hub_url = packs, catalog, tasks, hub_url
        self.models_dir = models_dir
        self._sizes: tuple[float, dict[str, int]] = (0.0, {})
        self.tools_rev: tuple[Any, str] | None = None   # (inputs, revision): tools.revision's cache (plan 51.2)
        self.models: dict[str, dict] = {}          # file name → {id, source}, from GAIFA's registry
        self._models_at = 0.0
        self._cache: dict[str, tuple[tuple, Converted | None, list[Issue]]] = {}

    def _key(self, p: Pack) -> tuple:
        return (p.sig, p.manifest is None, self.catalog.version, len(self.models))

    def analysed(self, p: Pack) -> tuple[Converted | None, list[Issue]]:
        key = self._key(p)
        hit = self._cache.get(p.id)
        if hit and hit[0] == key:
            return hit[1], hit[2]
        conv, errs = convert(p, self.catalog) if self.catalog else (None, [Issue(
            "warning", "no_catalog", "ComfyUI's node list isn't cached yet: load comfy once to check this workflow")])
        if conv is not None and p.manifest and p.manifest.set:
            errs += apply_set(conv, p.manifest.set)
        issues = errs if conv is None else errs + check(p, self.catalog, self.tasks, self.models, conv)
        self._cache[p.id] = (key, conv, issues)
        return conv, issues

    def state(self, p: Pack, issues: list[Issue]) -> str:
        if p.draft:
            return "draft"
        return "ready" if summary(issues)["ok"] else "broken"

    def brief(self, p: Pack) -> dict[str, Any]:
        _, issues = self.analysed(p)
        m = p.manifest
        return {"id": p.id, "name": p.name, "task": p.task, "state": self.state(p, issues),
                "description": m.description if m else "", "tags": m.tags if m else [], "agent": m.agent if m else False,
                "loose": p.dir is None, "preview": f"/v1/workflows/{p.id}/preview" if p.preview else None,
                "issues": summary(issues)}

    def detail(self, p: Pack) -> dict[str, Any]:
        conv, issues = self.analysed(p)
        out = self.brief(p)
        m = p.manifest
        out.update({
            "schema": input_schema(p, conv, self.catalog, self.tasks),
            "inputs": {k: v.model_dump(exclude_none=True, exclude_defaults=True) for k, v in m.inputs.items()} if m else {},
            "outputs": {k: v.model_dump(exclude_none=True) for k, v in m.outputs.items()} if m else {},
            "presets": {k: m.preset_values(k) for k in m.presets} if m else {},
            "preset_info": {k: {kk: v[kk] for kk in ("label", "quality") if kk in v} for k, v in m.presets.items()} if m else {},
            "edit": m.edit if m else None, "good_for": m.good_for if m else "", "speed": m.speed if m else "",
            "set": m.set if m else {},
            "memory_gb": m.memory_gb if m else None,
            "issues_list": [i.json() for i in issues],
            "files": {"editor": bool(p.source), "api": bool(p.api), "manifest": p.dir is not None and (p.dir / "workflow.toml").exists()},
            "nodes": self.nodes(conv),
        })
        return out

    def sizes(self) -> dict[str, int]:
        if time.monotonic() - self._sizes[0] > 300:
            self._sizes = (time.monotonic(), model_sizes(self.models_dir))
        return self._sizes[1]

    def suggest(self, p: Pack) -> tuple[Suggestion | None, str]:
        """A drafted workflow.toml for the pack (its current one is ignored)."""
        conv, _ = self.analysed(p)
        if conv is None:
            return None, ""
        name = p.manifest.name if p.manifest and p.manifest.name else p.id
        s = suggest(conv, self.catalog, p.editor(), name, self.sizes())
        return s, to_toml(s)

    def nodes(self, conv: Converted | None) -> list[dict]:
        """The graph's nodes, for the review screen: id, type, title and current field values."""
        if conv is None:
            return []
        out = []
        for eid, n in conv.graph.items():
            t = n["class_type"]
            out.append({"id": eid, "type": t, "title": conv.titles.get(eid) or t, "installed": self.catalog.has(t),
                        "output": self.catalog.is_output(t),
                        "fields": {k: v for k, v in n["inputs"].items() if not isinstance(v, list)}})
        return sorted(out, key=lambda n: [int(x) if x.isdigit() else x for x in n["id"].split(":")])

    async def refresh_models(self, client: httpx.AsyncClient | None = None, force: bool = False) -> None:
        """File name → registry entry, so a missing model can name its registry id and source."""
        if not self.hub_url or (not force and time.monotonic() - self._models_at < MODELS_TTL_S):
            return
        self._models_at = time.monotonic()
        try:
            async with httpx.AsyncClient(timeout=5) as c:
                r = await (client or c).get(f"{self.hub_url}/api/models")
                items = r.json() if r.status_code == 200 else []
        except (httpx.HTTPError, ValueError):
            return
        items = items.get("models", []) if isinstance(items, dict) else items
        index: dict[str, dict] = {}
        for m in items or []:
            for f in m.get("files") or []:
                index[f["path"].rsplit("/", 1)[-1]] = {"id": m["id"], "source": m.get("source"), "exists": f.get("exists", True)}
        self.models = index
