"""capability-enablement 3.2: the prompt for your own coding agent, the same from `gaifa setup --prompt` and the route:
it names this clone's path, the mods, the skill and their setup docs, and nothing from config.toml."""

from __future__ import annotations

import os
import subprocess

import httpx

from utils.setup_prompt import coding_agent_prompt
from utils.tests.conftest import REPO


def test_the_text_names_the_path_the_mods_the_skill_and_the_docs(tmp_path):
    t = coding_agent_prompt(tmp_path, ["web", "searxng"])
    assert str(tmp_path) in t and "web, searxng" in t
    assert ".agents/skills/gaifa-setup/SKILL.md" in t and "services/web/setup/*.md" in t and "services/searxng/setup/*.md" in t
    assert "bin/gaifa setup --plan --json web searxng" in t and "bin/gaifa doctor" in t and "bin/gaifa report" in t
    assert "sudo" in t and "--done" in t


def test_nothing_from_config_toml(tmp_path):
    (tmp_path / "config.toml").write_text('[services.agent.env]\nAGENT_LLM_KEY = "sk-secret-123"\n')
    assert "sk-secret" not in coding_agent_prompt(tmp_path, ["agent"])


def test_the_cli_prints_it():
    r = subprocess.run([str(REPO / "bin" / "gaifa"), "setup", "--prompt", "web"], capture_output=True, text=True, timeout=30,
                       env={**os.environ})
    root = os.environ.get("GAIFA_ROOT") or str(REPO)          # the tests point GAIFA_ROOT at a throwaway root
    assert r.returncode == 0 and r.stdout == coding_agent_prompt(root, ["web"])


async def test_the_route_returns_the_same_text(client, root):
    r = await client.get("/api/setup/prompt", params={"ids": "web,embed"})
    assert r.status_code == 200 and r.json()["text"] == coding_agent_prompt(root, ["web", "embed"])
    assert (await client.get("/api/setup/prompt", params={"ids": "../etc"})).status_code == 422
