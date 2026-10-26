"""The agent's structured memory (plan structured-memory): entities in a tree and the facts about them.

    model.py     kinds, paths, normalized names
    store.py     MemoryStore: entities, aliases, anchors, the log and undo (tables in agent.db)
    facts.py     the facts: added, replaced, retired, approved, searched by keyword
    importer.py  the old memory files and agent preferences, once
"""
