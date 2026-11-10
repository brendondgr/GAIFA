"""Agent workflows (plan agent-workflows): a chat spawns sub-agents, each a chat of its own linked to it.

- `settings.py`: what a sub-agent takes from its parent, and the limits (`[agent.workflows]` through the hub).
- `runner.py`: spawning, the queue and its slots, budgets, results, stopping with the parent.
"""
