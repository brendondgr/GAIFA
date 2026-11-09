"""The environments a chat's workspace calls carry (plan projects 2.2).

A plain chat carries its own `settings.environment`, as before. A project chat carries every environment of its
project (primary first) and then the project's hidden one with its own folders (`own_env`), as `environments`; the
workspace mod uses the union of their folders (services/workspace/folders.py). A project that lists no environments
lends the chat's own (else Default) as its primary.
"""

from __future__ import annotations

from typing import Any


def project_of(settings: dict[str, Any] | None, projects: Any) -> dict[str, Any] | None:
    """The chat's project (None for a plain chat, or one whose project was deleted)."""
    pid = (settings or {}).get("project")
    if not pid or projects is None:
        return None
    try:
        return projects.get(str(pid))
    except Exception:  # noqa: BLE001: a chat never fails over its project
        return None


def chat_envs(settings: dict[str, Any] | None, projects: Any) -> dict[str, Any]:
    """`{environment}` for a plain chat (empty without one), `{environment, environments}` for a project chat with more
    than one; `environment` is always the primary."""
    s = settings or {}
    env = s.get("environment") if isinstance(s.get("environment"), str) and s.get("environment") else None
    p = project_of(s, projects)
    if p is None:
        return {"environment": env} if env else {}
    envs = list(p.get("environments") or []) or [env or "default"]
    if p.get("own_env"):
        envs.append(p["own_env"])
    envs = list(dict.fromkeys(envs))
    return {"environment": envs[0], **({"environments": envs} if len(envs) > 1 else {})}
