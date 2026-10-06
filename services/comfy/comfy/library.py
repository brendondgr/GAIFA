"""The packs as the API sees them: each pack converted, checked and described once per change
(of its files, the node catalog or the models list)."""

from __future__ import annotations

import logging
import time
from typing import Any

import httpx

from .check import Issue, check, convert, summary
from .convert import Converted
from .nodes import NodeCatalog
from .packs import Pack, Packs
from .schema import input_schema
from .tasks import Tasks

log = logging.getLogger("comfy")
MODELS_TTL_S = 60


class Library:
    def __init__(self, packs: Packs, catalog: NodeCatalog, tasks: Tasks, hub_url: str = ""):
        self.packs, self.catalog, self.tasks, self.hub_url = packs, catalog, tasks, hub_url
        self.models: dict[str, dict] = {}          # file name → {id, source}, from AIHub's registry
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
        issues = errs if conv is None else check(p, self.catalog, self.tasks, self.models, conv)
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
                "description": m.description if m else "", "tags": m.tags if m else [],
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
            "presets": m.presets if m else {},
            "memory_gb": m.memory_gb if m else None,
            "issues_list": [i.json() for i in issues],
            "files": {"editor": bool(p.source), "api": bool(p.api), "manifest": p.dir is not None and (p.dir / "workflow.toml").exists()},
            "nodes": self.nodes(conv),
        })
        return out

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
